"""
Batch 1 tests: #47 symlink防护, #45 SecretRedactor补全, #25 LLM warmup,
#31 Model Switch Compact, #16 ExecPolicy持久化
"""

import json
import os
import tempfile

import pytest

from core.sandbox import SandboxConfig, SandboxManager
from core.secret_redactor import SecretRedactor
from core.exec_policy import ExecPolicy


# ── #47 Sandbox symlink 防护 ──


class TestSymlinkProtection:

    def test_normal_path_passes(self, tmp_path):
        sm = SandboxManager(SandboxConfig(workspace_base_dir=str(tmp_path)))
        workspace = str(tmp_path / "ws")
        os.makedirs(workspace, exist_ok=True)
        subdir = os.path.join(workspace, "subdir")
        os.makedirs(subdir, exist_ok=True)
        result = sm.validate_path(subdir, workspace)
        assert result == os.path.realpath(subdir)

    def test_symlink_within_workspace_passes(self, tmp_path):
        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        target = os.path.join(workspace, "real")
        os.makedirs(target)
        link = os.path.join(workspace, "link")
        os.symlink(target, link)
        sm = SandboxManager(SandboxConfig())
        result = sm.validate_path(link, workspace)
        assert result == os.path.realpath(link)

    def test_symlink_outside_workspace_blocked(self, tmp_path):
        """symlink 指向 workspace 外 → realpath 解析后被拦截。"""
        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        outside = str(tmp_path / "outside")
        os.makedirs(outside)
        link = os.path.join(workspace, "escape")
        os.symlink(outside, link)
        sm = SandboxManager(SandboxConfig())
        with pytest.raises(PermissionError):
            sm.validate_path(link, workspace)

    def test_path_outside_workspace_blocked(self, tmp_path):
        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        outside = str(tmp_path / "other")
        os.makedirs(outside)
        sm = SandboxManager(SandboxConfig())
        with pytest.raises(PermissionError, match="不在工作空间内"):
            sm.validate_path(outside, workspace)


# ── #45 SecretRedactor 模式补全 ──


class TestSecretRedactorPatterns:

    def setup_method(self):
        self.redactor = SecretRedactor()

    def test_github_token(self):
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh1234"
        result = self.redactor.redact(text)
        assert "[REDACTED_GITHUB_TOKEN]" in result
        assert "ghp_" not in result

    def test_gitlab_token(self):
        text = "glpat-xxxxxxxxxxxxxxxxxxxx"
        result = self.redactor.redact(text)
        assert "[REDACTED_GITLAB_TOKEN]" in result

    def test_google_api_key(self):
        text = "key=AIzaSyB_abcdef1234567890ABCDEFGHIJKLMNO"
        result = self.redactor.redact(text)
        assert "[REDACTED_GOOGLE_KEY]" in result

    def test_slack_token(self):
        for prefix in ("xoxb-", "xoxp-", "xoxs-"):
            text = f"token: {prefix}1234567890-abcdefghij"
            result = self.redactor.redact(text)
            assert "[REDACTED_SLACK_TOKEN]" in result, f"Failed for {prefix}"

    def test_npm_token(self):
        text = "npm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = self.redactor.redact(text)
        assert "[REDACTED_NPM_TOKEN]" in result

    def test_aws_key_still_works(self):
        text = "AKIAIOSFODNN7EXAMPLE"
        result = self.redactor.redact(text)
        assert "[REDACTED_AWS_KEY]" in result

    def test_openai_key_still_works(self):
        text = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        result = self.redactor.redact(text)
        assert "[REDACTED_API_KEY]" in result

    def test_safe_text_unchanged(self):
        text = "Hello, this is a normal response with no secrets."
        assert self.redactor.redact(text) == text


# ── #25 LLM warmup ──


class TestLLMWarmup:

    @pytest.mark.asyncio
    async def test_warmup_creates_client(self):
        from core.llm_client import LLMGatewayClient, LLMClientConfig
        client = LLMGatewayClient(LLMClientConfig(base_url="http://127.0.0.1:1"))
        await client.warmup()
        # Should not raise even if connection fails
        assert client._client is not None
        await client.close()


# ── #31 Model Switch Compact ──


class TestModelSwitchCompact:

    def test_fallback_window_used_when_smaller(self):
        """fallback 窗口更小时，runtime 使用较小值。"""
        from unittest.mock import patch
        from core.runtime import RuntimeConfig

        with patch("dependencies.get_settings") as mock_settings:
            s = mock_settings.return_value
            s.agent_max_iterations = 25
            s.llm_default_max_tokens = 4096
            s.agent_max_tool_result_chars = 0
            s.agent_tool_timeout_s = 30
            s.agent_parallel_tool_calls = True
            s.agent_context_budget_tokens = 0
            s.agent_model_context_window = 128000
            s.agent_context_budget_ratio = 0.8
            s.agent_compress_threshold_ratio = 0.70
            s.agent_context_budget_min = 16000
            s.llm_fallback_model = "small-model"
            s.llm_fallback_context_window = 32000

            from dependencies import get_runtime_config
            # Clear lru_cache
            get_runtime_config.cache_clear()
            try:
                config = get_runtime_config()
                assert config.model_context_window == 32000
            finally:
                get_runtime_config.cache_clear()


# ── #16 ExecPolicy 持久化 ──


class TestExecPolicyApprovals:

    def test_approve_and_check(self, tmp_path):
        policy = ExecPolicy(approvals_dir=str(tmp_path))
        policy.approve_command("T1", "U1", "npm install")
        assert policy.is_approved("T1", "U1", "npm install foo")
        assert not policy.is_approved("T1", "U1", "rm -rf /")

    def test_approval_persists(self, tmp_path):
        policy = ExecPolicy(approvals_dir=str(tmp_path))
        policy.approve_command("T1", "U1", "docker compose")
        # New instance reads from disk
        policy2 = ExecPolicy(approvals_dir=str(tmp_path))
        assert policy2.is_approved("T1", "U1", "docker compose up")

    def test_check_with_approval_bypasses_block(self, tmp_path):
        policy = ExecPolicy(approvals_dir=str(tmp_path))
        # sudo is normally blocked
        safe, _ = policy.check_command("sudo apt install")
        assert not safe
        # After approval, it passes
        policy.approve_command("T1", "U1", "sudo apt install")
        safe, _ = policy.check_command_with_approval("sudo apt install vim", "T1", "U1")
        assert safe

    def test_no_approval_falls_through(self, tmp_path):
        policy = ExecPolicy(approvals_dir=str(tmp_path))
        safe, reason = policy.check_command_with_approval("sudo rm -rf /", "T1", "U1")
        assert not safe

    def test_duplicate_approval_no_crash(self, tmp_path):
        policy = ExecPolicy(approvals_dir=str(tmp_path))
        policy.approve_command("T1", "U1", "docker run")
        policy.approve_command("T1", "U1", "docker run")
        approvals = policy.load_approvals("T1", "U1")
        assert approvals.count("docker run") == 1

    def test_load_empty(self, tmp_path):
        policy = ExecPolicy(approvals_dir=str(tmp_path))
        assert policy.load_approvals("T1", "U1") == []
