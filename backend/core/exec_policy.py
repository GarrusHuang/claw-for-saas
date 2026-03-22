"""
命令执行安全策略。

提供结构化的命令安全检查:
- 危险命令正则黑名单 (可扩展)
- 安全命令前缀白名单 (白名单命令跳过黑名单检查)
- 敏感文件名检测

Usage:
    policy = ExecPolicy()
    safe, reason = policy.check_command("rm -rf /")
    # safe=False, reason="安全检查: 命令包含危险操作 — rm -rf /"
"""

from __future__ import annotations

import re


class ExecPolicy:
    """命令执行安全策略。"""

    # 危险命令正则
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+~",
        r"\bsudo\b",
        r"\bcurl\b.*\|\s*sh",
        r"\bwget\b.*\|\s*sh",
        r"\bmkfs\b",
        r":\(\)\s*\{",        # fork bomb
        r"\bdd\s+if=",
        r"\bchmod\s+777\s+/",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\binit\s+0\b",
        # 新增
        r"\bkill\s+-9\s+-1\b",     # kill all processes
        r"\bpkill\s+-9\b",         # force kill by name
        r"\bchown\s+root\b",       # change owner to root
        r"\biptables\b",           # firewall manipulation
        r"\bnc\s+-l\b",            # netcat listener
    ]

    # 安全命令前缀 (匹配这些前缀的命令跳过黑名单检查)
    SAFE_PREFIXES = [
        "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
        "echo", "pwd", "whoami", "date", "env", "which", "type",
        "python", "python3", "pip", "pip3",
        "node", "npm", "npx", "yarn",
        "git status", "git log", "git diff", "git branch", "git show",
        "cd", "mkdir", "touch", "cp", "mv",
        "sort", "uniq", "cut", "tr", "sed", "awk",
        "file", "stat", "du", "df",
    ]

    # 敏感文件名 (禁止写入)
    SENSITIVE_FILES = [
        ".env", ".env.local", ".env.production",
        "credentials", "credentials.json",
        "id_rsa", "id_ed25519", "id_ecdsa",
        ".pem", ".key", ".p12", ".pfx",
        "shadow", "passwd",
    ]

    def __init__(
        self,
        extra_dangerous: list[str] | None = None,
        extra_safe: list[str] | None = None,
    ) -> None:
        patterns = list(self.DANGEROUS_PATTERNS)
        if extra_dangerous:
            patterns.extend(extra_dangerous)
        self._dangerous_re = [re.compile(p, re.IGNORECASE) for p in patterns]

        self._safe_prefixes = list(self.SAFE_PREFIXES)
        if extra_safe:
            self._safe_prefixes.extend(extra_safe)

    def check_command(self, command: str) -> tuple[bool, str]:
        """
        检查命令安全性。

        Returns:
            (is_safe, reason) — is_safe=True 允许执行, False 拒绝并返回原因
        """
        cmd = command.strip()
        if not cmd:
            return True, ""

        # 提取首个 token (处理管道/分号前的命令)
        first_token = cmd.split()[0] if cmd.split() else ""

        # 白名单检查: 安全命令前缀跳过黑名单
        for prefix in self._safe_prefixes:
            if " " in prefix:
                # 多 token 前缀 (如 "git status")
                if cmd.startswith(prefix):
                    return True, ""
            else:
                if first_token == prefix:
                    return True, ""

        # 黑名单检查
        for pattern in self._dangerous_re:
            if pattern.search(cmd):
                return False, f"安全检查: 命令包含危险操作 — {cmd[:100]}"

        # 默认放行
        return True, ""

    def is_sensitive_file(self, path: str) -> bool:
        """检查文件名是否为敏感文件。"""
        basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        for sensitive in self.SENSITIVE_FILES:
            if basename == sensitive or basename.endswith(sensitive):
                return True
        return False
