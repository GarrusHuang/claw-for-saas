"""
Tests for core/sandbox.py — SandboxManager.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.sandbox import SandboxManager, SandboxConfig


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def sandbox(tmp_path):
    """Create a SandboxManager with tmp workspace."""
    config = SandboxConfig(
        workspace_base_dir="workspace",
        max_disk_quota_mb=10,
        network_whitelist=[],
        block_private_networks=True,
        rate_limit_per_minute=5,
    )
    return SandboxManager(config=config, backend_root=str(tmp_path))


@pytest.fixture
def sandbox_with_whitelist(tmp_path):
    """SandboxManager with network whitelist configured."""
    config = SandboxConfig(
        workspace_base_dir="workspace",
        network_whitelist=["example.com", "api.github.com"],
        block_private_networks=True,
        rate_limit_per_minute=100,
    )
    return SandboxManager(config=config, backend_root=str(tmp_path))


# ──────────────────────────────────────────────
# 6a: 文件操作沙箱
# ──────────────────────────────────────────────

class TestWorkspace:
    """Tests for workspace allocation and path validation."""

    def test_get_workspace_creates_dir(self, sandbox, tmp_path):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        assert os.path.isdir(ws)
        assert "T1" in ws
        assert "U1" in ws
        assert "sess1" in ws

    def test_get_workspace_without_session(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1")
        assert os.path.isdir(ws)
        assert "T1" in ws
        assert "U1" in ws

    def test_validate_path_inside_workspace(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        inner = os.path.join(ws, "subdir", "file.txt")
        os.makedirs(os.path.dirname(inner), exist_ok=True)
        with open(inner, "w") as f:
            f.write("test")
        result = sandbox.validate_path(inner, ws)
        assert result == os.path.realpath(inner)

    def test_validate_path_outside_workspace_raises(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        with pytest.raises(PermissionError, match="不在工作空间内"):
            sandbox.validate_path("/etc/passwd", ws)

    def test_validate_path_traversal_raises(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        traversal = os.path.join(ws, "..", "..", "..", "etc", "passwd")
        with pytest.raises(PermissionError):
            sandbox.validate_path(traversal, ws)

    def test_validate_path_workspace_root_is_ok(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        result = sandbox.validate_path(ws, ws)
        assert result == os.path.realpath(ws)


# ──────────────────────────────────────────────
# Disk quota
# ──────────────────────────────────────────────

class TestDiskQuota:
    """Tests for disk quota checking."""

    def test_empty_workspace_quota(self, sandbox):
        quota = sandbox.check_disk_quota("T1", "U1")
        assert quota["used_mb"] == 0.0
        assert quota["exceeded"] is False

    def test_quota_tracks_file_size(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        # Write a 100KB file (large enough to register as > 0.0 MB after rounding)
        with open(os.path.join(ws, "data.bin"), "wb") as f:
            f.write(b"x" * (100 * 1024))
        quota = sandbox.check_disk_quota("T1", "U1")
        assert quota["used_mb"] > 0
        assert quota["exceeded"] is False

    def test_quota_exceeded(self, sandbox, tmp_path):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        # Write a file larger than quota (10 MB)
        with open(os.path.join(ws, "big.bin"), "wb") as f:
            f.write(b"x" * (11 * 1024 * 1024))
        quota = sandbox.check_disk_quota("T1", "U1")
        assert quota["exceeded"] is True


# ──────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────

class TestCleanup:
    """Tests for expired workspace cleanup."""

    def test_cleanup_expired_removes_old_dirs(self, sandbox, tmp_path):
        # Create workspace and make it look old
        ws = sandbox.get_workspace("T1", "U1", "old-session")
        old_time = time.time() - 200000  # way past TTL
        os.utime(ws, (old_time, old_time))
        cleaned = sandbox.cleanup_expired("T1", "U1")
        assert cleaned >= 1

    def test_cleanup_no_expired(self, sandbox):
        sandbox.get_workspace("T1", "U1", "fresh-session")
        cleaned = sandbox.cleanup_expired("T1", "U1")
        assert cleaned == 0


# ──────────────────────────────────────────────
# 6c: 网络访问白名单
# ──────────────────────────────────────────────

class TestNetworkValidation:
    """Tests for URL validation and network whitelist."""

    def test_allow_public_url_no_whitelist(self, sandbox):
        result = sandbox.validate_url("https://www.google.com/search")
        assert result is None  # allowed

    def test_block_private_ip_10(self, sandbox):
        result = sandbox.validate_url("http://10.0.0.1/api")
        assert result is not None
        assert "内网" in result

    def test_block_private_ip_192(self, sandbox):
        result = sandbox.validate_url("http://192.168.1.1/admin")
        assert result is not None

    def test_block_private_ip_172(self, sandbox):
        result = sandbox.validate_url("http://172.16.0.1/api")
        assert result is not None

    def test_block_localhost(self, sandbox):
        result = sandbox.validate_url("http://localhost:8080/api")
        assert result is not None
        assert "本地" in result

    def test_block_loopback_127(self, sandbox):
        result = sandbox.validate_url("http://127.0.0.1:3000/")
        assert result is not None

    def test_block_metadata_endpoint(self, sandbox):
        result = sandbox.validate_url("http://169.254.169.254/latest/meta-data/")
        assert result is not None
        assert "元数据" in result

    def test_block_gcp_metadata(self, sandbox):
        result = sandbox.validate_url("http://metadata.google.internal/computeMetadata/v1/")
        assert result is not None

    def test_whitelist_allows_listed_domain(self, sandbox_with_whitelist):
        result = sandbox_with_whitelist.validate_url("https://example.com/data")
        assert result is None

    def test_whitelist_allows_subdomain(self, sandbox_with_whitelist):
        result = sandbox_with_whitelist.validate_url("https://sub.example.com/data")
        assert result is None

    def test_whitelist_blocks_unlisted_domain(self, sandbox_with_whitelist):
        result = sandbox_with_whitelist.validate_url("https://evil.com/data")
        assert result is not None
        assert "白名单" in result

    def test_invalid_url(self, sandbox):
        result = sandbox.validate_url("not-a-url")
        assert result is not None

    def test_empty_host(self, sandbox):
        result = sandbox.validate_url("http:///path")
        assert result is not None


# ──────────────────────────────────────────────
# Rate limiting
# ──────────────────────────────────────────────

class TestRateLimit:
    """Tests for per-session rate limiting."""

    def test_within_limit(self, sandbox):
        for _ in range(5):
            assert sandbox.check_rate_limit("sess1") is True

    def test_exceeds_limit(self, sandbox):
        for _ in range(5):
            sandbox.check_rate_limit("sess1")
        assert sandbox.check_rate_limit("sess1") is False

    def test_different_sessions_independent(self, sandbox):
        for _ in range(5):
            sandbox.check_rate_limit("sess1")
        # sess2 should still be allowed
        assert sandbox.check_rate_limit("sess2") is True

    def test_rate_limit_info(self, sandbox):
        sandbox.check_rate_limit("sess1")
        sandbox.check_rate_limit("sess1")
        info = sandbox.get_rate_limit_info("sess1")
        assert info["calls_in_window"] == 2
        assert info["limit"] == 5
        assert info["remaining"] == 3


# ── A8: 速率计数器清理 ──

class TestRateCounterCleanup:
    """Tests for cleanup_stale_counters (A8)."""

    def test_cleanup_removes_stale_counters(self, sandbox):
        """过期计数器应被清理。"""
        import time as _time
        # 插入一个 61 秒前的计数
        sandbox._rate_counters["old_sess"] = [_time.time() - 61]
        removed = sandbox.cleanup_stale_counters()
        assert removed == 1
        assert "old_sess" not in sandbox._rate_counters

    def test_cleanup_keeps_active_counters(self, sandbox):
        """活跃计数器不应被清理。"""
        import time as _time
        sandbox._rate_counters["active_sess"] = [_time.time()]
        removed = sandbox.cleanup_stale_counters()
        assert removed == 0
        assert "active_sess" in sandbox._rate_counters

    def test_cleanup_mixed(self, sandbox):
        """混合场景：同时存在过期和活跃计数器。"""
        import time as _time
        now = _time.time()
        sandbox._rate_counters["stale1"] = [now - 120]
        sandbox._rate_counters["stale2"] = [now - 90]
        sandbox._rate_counters["fresh"] = [now - 5]
        removed = sandbox.cleanup_stale_counters()
        assert removed == 2
        assert "fresh" in sandbox._rate_counters

    def test_periodic_cleanup_triggered(self, sandbox):
        """check_rate_limit 应每 5 分钟自动触发清理。"""
        import time as _time
        sandbox._rate_counters["old"] = [_time.time() - 120]
        # 模拟上次清理在 6 分钟前
        sandbox._last_rate_cleanup = _time.time() - 360
        sandbox.check_rate_limit("new_sess")
        # 过期计数器应已被清理
        assert "old" not in sandbox._rate_counters


# ──────────────────────────────────────────────
# 6b: 命令执行沙箱
# ──────────────────────────────────────────────

class TestCommandExecution:
    """Tests for command execution sandbox."""

    def test_run_simple_command(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        result = sandbox.run_command("echo hello", ws)
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]
        assert result["sandbox"] == "local"

    def test_run_command_in_workspace(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        # Create a file in workspace
        with open(os.path.join(ws, "test.txt"), "w") as f:
            f.write("content")
        result = sandbox.run_command("ls test.txt", ws)
        assert result["exit_code"] == 0
        assert "test.txt" in result["stdout"]

    def test_command_timeout(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        result = sandbox.run_command("sleep 10", ws, timeout=1)
        assert result.get("timed_out") is True

    def test_command_blacklist_blocks_rm_rf(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        result = sandbox.run_command("rm -rf /", ws)
        assert result.get("blocked") is True
        assert "危险" in result["stderr"]

    def test_command_blacklist_blocks_sudo(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        result = sandbox.run_command("sudo ls", ws)
        assert result.get("blocked") is True

    def test_command_blacklist_blocks_shutdown(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        result = sandbox.run_command("shutdown -h now", ws)
        assert result.get("blocked") is True

    def test_command_output_truncation(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        # Generate output > 10KB
        result = sandbox.run_command("python3 -c \"print('x'*20000)\"", ws)
        assert result["exit_code"] == 0
        if result.get("stdout_truncated"):
            assert len(result["stdout"]) <= 10240

    def test_command_failure_exit_code(self, sandbox):
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        result = sandbox.run_command("false", ws)
        assert result["exit_code"] != 0

    def test_is_command_blocked(self, sandbox):
        assert sandbox._is_command_blocked("rm -rf /") is not None
        assert sandbox._is_command_blocked("sudo apt install") is not None
        assert sandbox._is_command_blocked("ls -la") is None
        assert sandbox._is_command_blocked("python3 script.py") is None


class TestDockerSandbox:
    """Tests for Docker sandbox configuration."""

    def test_docker_config_defaults(self):
        config = SandboxConfig()
        assert config.docker_enabled is False
        assert config.docker_image == "python:3.11-slim"
        assert config.docker_cpu_limit == "1"
        assert config.docker_memory_limit == "512m"
        assert config.docker_network_mode == "none"

    def test_docker_enabled_config(self):
        config = SandboxConfig(docker_enabled=True, docker_image="alpine:latest")
        sandbox = SandboxManager(config=config)
        assert sandbox.config.docker_enabled is True
        assert sandbox.config.docker_image == "alpine:latest"

    def test_docker_not_available_fallback(self, tmp_path):
        """Docker execution returns error when Docker not found."""
        config = SandboxConfig(docker_enabled=True, docker_image="nonexistent:image")
        sandbox = SandboxManager(config=config, backend_root=str(tmp_path))
        ws = sandbox.get_workspace("T1", "U1", "sess1")
        # This will call _run_in_docker which may fail gracefully
        result = sandbox.run_command("echo test", ws)
        assert result["sandbox"] == "docker"
        # Either succeeds or gives an error, but doesn't crash
