"""
A6 安全沙箱 — SandboxManager。

运行时围栏替代用户确认。Agent 在沙箱内自由操作，安全由环境保证。

能力:
- 6a. 文件操作沙箱: 每个会话分配独立 workspace, 路径验证
- 6b. 命令执行沙箱: Docker 容器内执行 + 资源限制 (CPU/内存/timeout/output)
- 6c. 网络访问白名单: 默认拒绝, 白名单放行
- 磁盘配额: 单用户最大存储限制
- 速率限制: 单会话工具调用频率限制
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """沙箱配置。"""
    # 文件沙箱
    workspace_base_dir: str = "data/workspace"
    max_disk_quota_mb: int = 500  # 单用户最大磁盘配额 (MB)
    temp_file_ttl_s: int = 86400  # 临时文件 TTL (默认 24 小时)

    # 网络白名单
    network_whitelist: list[str] = field(default_factory=list)  # 允许的域名/URL 前缀
    block_private_networks: bool = True  # 阻止内网地址

    # 速率限制
    rate_limit_per_minute: int = 100  # 单会话每分钟最大工具调用次数

    # 命令沙箱 (6b)
    command_timeout_s: int = 30  # 默认命令超时
    command_max_timeout_s: int = 120  # 最大命令超时
    command_max_output_bytes: int = 10240  # 命令最大输出 (10KB)
    docker_enabled: bool = False  # 是否启用 Docker 沙箱 (需要 Docker 运行时)
    docker_image: str = "python:3.11-slim"  # Docker 沙箱镜像
    docker_cpu_limit: str = "1"  # CPU 核心限制
    docker_memory_limit: str = "512m"  # 内存限制
    docker_network_mode: str = "none"  # 网络模式 (none=无网络)


# 内网 IP 段 — 硬禁止
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

# 元数据端点 — 硬禁止
_METADATA_HOSTS = {
    "169.254.169.254",  # AWS/GCP metadata
    "metadata.google.internal",
    "metadata.internal",
}


class SandboxManager:
    """
    运行时安全沙箱管理器。

    提供:
    - workspace 分配和路径验证
    - 网络访问白名单
    - 磁盘配额追踪
    - 速率限制
    """

    _RATE_CLEANUP_INTERVAL = 300  # 5 minutes

    def __init__(self, config: SandboxConfig | None = None, backend_root: str = "") -> None:
        self.config = config or SandboxConfig()
        self._backend_root = backend_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._rate_counters: dict[str, list[float]] = {}  # session_id -> [timestamp, ...]
        self._last_rate_cleanup: float = 0.0

    # ── 6a. 文件操作沙箱 ──

    def get_workspace(self, tenant_id: str, user_id: str, session_id: str = "") -> str:
        """
        获取会话 workspace 目录。

        目录结构: {workspace_base}/{tenant_id}/{user_id}/{session_id}/
        如果 session_id 为空，返回用户级目录。
        """
        parts = [self._backend_root, self.config.workspace_base_dir, tenant_id, user_id]
        if session_id:
            parts.append(session_id)
        workspace = os.path.join(*parts)
        os.makedirs(workspace, exist_ok=True)
        return os.path.realpath(workspace)

    def validate_path(self, path: str, workspace: str) -> str:
        """
        验证路径是否在 workspace 内。

        Returns:
            解析后的安全路径

        Raises:
            PermissionError: 路径不在 workspace 内
        """
        resolved = os.path.realpath(os.path.expanduser(path))
        ws_real = os.path.realpath(workspace)

        if resolved == ws_real or resolved.startswith(ws_real + os.sep):
            return resolved

        raise PermissionError(
            f"路径 {path} 不在工作空间内。"
            f"允许的目录: {workspace}"
        )

    def check_disk_quota(self, tenant_id: str, user_id: str) -> dict:
        """
        检查用户磁盘配额。

        Returns:
            {"used_mb": float, "quota_mb": int, "available_mb": float, "exceeded": bool}
        """
        user_dir = os.path.join(
            self._backend_root, self.config.workspace_base_dir, tenant_id, user_id
        )
        if not os.path.isdir(user_dir):
            return {
                "used_mb": 0.0,
                "quota_mb": self.config.max_disk_quota_mb,
                "available_mb": float(self.config.max_disk_quota_mb),
                "exceeded": False,
            }

        total_bytes = 0
        for dirpath, _dirnames, filenames in os.walk(user_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total_bytes += os.path.getsize(fp)
                except OSError:
                    pass

        used_mb = round(total_bytes / (1024 * 1024), 2)
        quota_mb = self.config.max_disk_quota_mb
        return {
            "used_mb": used_mb,
            "quota_mb": quota_mb,
            "available_mb": round(quota_mb - used_mb, 2),
            "exceeded": used_mb > quota_mb,
        }

    def cleanup_expired(self, tenant_id: str, user_id: str) -> int:
        """清理过期的临时文件，返回清理数量。"""
        user_dir = os.path.join(
            self._backend_root, self.config.workspace_base_dir, tenant_id, user_id
        )
        if not os.path.isdir(user_dir):
            return 0

        now = time.time()
        ttl = self.config.temp_file_ttl_s
        cleaned = 0

        for entry in os.listdir(user_dir):
            session_dir = os.path.join(user_dir, entry)
            if not os.path.isdir(session_dir):
                continue
            # 检查目录修改时间
            try:
                mtime = os.path.getmtime(session_dir)
                if now - mtime > ttl:
                    shutil.rmtree(session_dir, ignore_errors=True)
                    cleaned += 1
            except OSError:
                pass

        if cleaned:
            logger.info(f"Cleaned {cleaned} expired workspace(s) for {tenant_id}/{user_id}")
        return cleaned

    # ── 6c. 网络访问白名单 ──

    def validate_url(self, url: str) -> str | None:
        """
        验证 URL 是否允许访问。

        Returns:
            None 如果允许, 否则返回拒绝原因字符串。
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return f"无效 URL: {url}"

        host = parsed.hostname or ""
        if not host:
            return f"URL 缺少主机名: {url}"

        # 检查元数据端点
        if host.lower() in _METADATA_HOSTS:
            return f"禁止访问元数据端点: {host}"

        # 检查内网地址
        if self.config.block_private_networks:
            try:
                ip = ipaddress.ip_address(host)
                for net in _PRIVATE_NETWORKS:
                    if ip in net:
                        return f"禁止访问内网地址: {host}"
            except ValueError:
                # 不是 IP 地址，是域名 — 检查常见内网域名
                if host in ("localhost", "0.0.0.0", "[::]"):
                    return f"禁止访问本地地址: {host}"

                # DNS 解析检查 — 防止 SSRF 通过域名指向内网 IP
                import socket
                try:
                    addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                    for family, _, _, _, sockaddr in addrs:
                        resolved_ip = ipaddress.ip_address(sockaddr[0])
                        for net in _PRIVATE_NETWORKS:
                            if resolved_ip in net:
                                return f"域名 {host} 解析到内网地址 {sockaddr[0]}, 禁止访问"
                except socket.gaierror:
                    # DNS 解析失败不阻止 — 可能是合法的外部域名暂时不可达
                    pass

        # 如果配置了白名单，只允许白名单内的 URL
        whitelist = self.config.network_whitelist
        if whitelist:
            for pattern in whitelist:
                if host == pattern or host.endswith("." + pattern) or url.startswith(pattern):
                    return None  # 允许
            return f"URL 不在白名单中: {host}"

        # 无白名单配置 = 允许所有非内网 URL
        return None

    # ── 6b. 命令执行沙箱 ──

    # 沙箱内不设命令黑名单 — workspace 隔离 + 磁盘配额 + 网络白名单已提供足够保护。
    # 业务层安全检查由 hooks.py code_safety_hook 负责（精确正则匹配）。

    def run_command(
        self,
        command: str,
        workspace: str,
        timeout: int | None = None,
    ) -> dict:
        """
        在沙箱中执行命令。

        Docker 模式: 命令在容器内执行，workspace 只读挂载 + /tmp 可写。
        本地模式: 命令在 subprocess 中执行，限制工作目录为 workspace。

        Returns:
            {"exit_code": int, "stdout": str, "stderr": str, "duration_ms": float, ...}
        """
        timeout = min(
            max(1, timeout or self.config.command_timeout_s),
            self.config.command_max_timeout_s,
        )
        max_output = self.config.command_max_output_bytes

        if self.config.docker_enabled:
            return self._run_in_docker(command, workspace, timeout, max_output)
        else:
            return self._run_local(command, workspace, timeout, max_output)

    def _run_local(
        self, command: str, workspace: str, timeout: int, max_output: int,
    ) -> dict:
        """本地 subprocess 执行 (工作目录限制为 workspace)。"""
        start = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workspace,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            duration_ms = round((time.monotonic() - start) * 1000, 1)

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            stdout_truncated = False
            stderr_truncated = False

            if len(stdout.encode("utf-8")) > max_output:
                stdout = stdout.encode("utf-8")[:max_output].decode("utf-8", errors="ignore")
                stdout_truncated = True
            if len(stderr.encode("utf-8")) > max_output:
                stderr = stderr.encode("utf-8")[:max_output].decode("utf-8", errors="ignore")
                stderr_truncated = True

            return {
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": duration_ms,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "sandbox": "local",
            }
        except subprocess.TimeoutExpired:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"命令超时 (>{timeout}s)",
                "duration_ms": duration_ms,
                "timed_out": True,
                "sandbox": "local",
            }
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e), "sandbox": "local"}

    def _run_in_docker(
        self, command: str, workspace: str, timeout: int, max_output: int,
    ) -> dict:
        """
        Docker 容器内执行命令。

        - workspace 只读挂载到 /workspace
        - /tmp 可写 (容器内临时文件)
        - 资源限制: CPU + 内存
        - 网络隔离: 默认无网络
        - 自动清理容器 (--rm)
        """
        docker_cmd = [
            "docker", "run", "--rm",
            "--cpus", self.config.docker_cpu_limit,
            "--memory", self.config.docker_memory_limit,
            "--network", self.config.docker_network_mode,
            "--read-only",
            "--tmpfs", "/tmp:size=64m",
            "-v", f"{workspace}:/workspace:ro",
            "-w", "/workspace",
            "--user", "nobody",
            self.config.docker_image,
            "sh", "-c", command,
        ]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5,  # 额外 5s 给 Docker 启动
            )
            duration_ms = round((time.monotonic() - start) * 1000, 1)

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            stdout_truncated = False
            stderr_truncated = False

            if len(stdout.encode("utf-8")) > max_output:
                stdout = stdout.encode("utf-8")[:max_output].decode("utf-8", errors="ignore")
                stdout_truncated = True
            if len(stderr.encode("utf-8")) > max_output:
                stderr = stderr.encode("utf-8")[:max_output].decode("utf-8", errors="ignore")
                stderr_truncated = True

            return {
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": duration_ms,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "sandbox": "docker",
            }
        except subprocess.TimeoutExpired:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Docker 命令超时 (>{timeout}s)",
                "duration_ms": duration_ms,
                "timed_out": True,
                "sandbox": "docker",
            }
        except FileNotFoundError:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "Docker 未安装或不在 PATH 中",
                "sandbox": "docker",
            }
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e), "sandbox": "docker"}

    # ── 速率限制 ──

    def cleanup_stale_counters(self) -> int:
        """清理过期的速率限制计数器，返回清理数量。"""
        now = time.time()
        window = 60.0
        stale_keys = [
            key for key, timestamps in self._rate_counters.items()
            if not any(t > now - window for t in timestamps)
        ]
        for key in stale_keys:
            del self._rate_counters[key]
        return len(stale_keys)

    def check_rate_limit(self, session_id: str, tenant_id: str = "") -> bool:
        """
        检查单会话速率限制。

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID (用于隔离不同租户的计数器)

        Returns:
            True 如果允许, False 如果超限。
        """
        now = time.time()

        # 定期清理过期计数器
        if now - self._last_rate_cleanup > self._RATE_CLEANUP_INTERVAL:
            self.cleanup_stale_counters()
            self._last_rate_cleanup = now
        window = 60.0  # 1 分钟窗口
        key = f"{tenant_id}:{session_id}" if tenant_id else session_id

        if key not in self._rate_counters:
            self._rate_counters[key] = []

        # 清理过期记录
        timestamps = self._rate_counters[key]
        cutoff = now - window
        self._rate_counters[key] = [t for t in timestamps if t > cutoff]

        if len(self._rate_counters[key]) >= self.config.rate_limit_per_minute:
            return False

        self._rate_counters[key].append(now)
        return True

    def get_rate_limit_info(self, session_id: str, tenant_id: str = "") -> dict:
        """获取速率限制信息。"""
        now = time.time()
        window = 60.0
        key = f"{tenant_id}:{session_id}" if tenant_id else session_id
        timestamps = self._rate_counters.get(key, [])
        recent = [t for t in timestamps if t > now - window]
        return {
            "calls_in_window": len(recent),
            "limit": self.config.rate_limit_per_minute,
            "remaining": max(0, self.config.rate_limit_per_minute - len(recent)),
        }
