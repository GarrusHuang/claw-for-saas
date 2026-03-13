"""
Claw-for-SaaS global configuration.
Uses pydantic-settings to load from environment variables and .env files.
"""

from pydantic_settings import BaseSettings
from pydantic import Field, model_validator


class Settings(BaseSettings):
    """Application settings"""

    # ─── LLM Configuration ───
    llm_base_url: str = Field(
        default="http://localhost:11434/v1",
        description="LLM API base URL (OpenAI-compatible)",
    )
    llm_model: str = Field(
        default="",
        description="Model name (required — set via LLM_MODEL env var)",
    )
    llm_api_key: str = Field(
        default="not-needed",
        description="API Key (not needed for local models)",
    )
    llm_timeout_s: float = Field(
        default=120.0,
        description="LLM request timeout in seconds",
    )
    llm_max_retries: int = Field(
        default=3,
        description="LLM max retry count",
    )
    llm_default_temperature: float = Field(
        default=0.7,
        description="Default temperature",
    )
    llm_default_top_p: float = Field(
        default=0.8,
        description="Default top_p",
    )
    llm_default_max_tokens: int = Field(
        default=4096,
        description="Max tokens per LLM call",
    )
    llm_enable_thinking: bool = Field(
        default=False,
        description="Enable thinking mode (chat_template_kwargs.enable_thinking)",
    )

    # ─── Agent Runtime ───
    agent_max_iterations: int = Field(
        default=25,
        description="ReAct loop max iterations",
    )
    agent_tool_timeout_s: float = Field(
        default=30.0,
        description="Single tool call timeout in seconds",
    )
    agent_parallel_tool_calls: bool = Field(
        default=True,
        description="Enable parallel read-only tool calls",
    )
    agent_max_tool_result_chars: int = Field(
        default=3000,
        description="Max chars per tool result (0=unlimited)",
    )
    # ─── A4: Context Management ───
    agent_model_context_window: int = Field(
        default=32000,
        description="Model context window size in tokens (0=use agent_context_budget_tokens directly)",
    )
    agent_context_budget_ratio: float = Field(
        default=0.8,
        description="Context budget as ratio of model window (reserve 20% for output)",
    )
    agent_compress_threshold_ratio: float = Field(
        default=0.85,
        description="Trigger compression at this fraction of budget (early trigger)",
    )
    agent_context_budget_tokens: int = Field(
        default=0,
        description="Override: fixed token budget (0=auto from model_context_window * ratio)",
    )
    agent_context_budget_min: int = Field(
        default=16000,
        description="Minimum context budget (hard floor)",
    )
    agent_file_page_size: int = Field(
        default=50000,
        description="Default file page size in characters for pagination",
    )

    # ─── LLM Vision (A4-4i: 多模态) ───
    llm_supports_vision: bool = Field(
        default=False,
        description="Whether the LLM model supports vision/image input",
    )

    # ─── MCP (A2: 标准工具接口) ───
    mcp_enabled: bool = Field(
        default=False,
        description="Enable MCP standard tool interface",
    )
    mcp_base_url: str = Field(
        default="",
        description="MCP HTTP provider base URL (empty=use DefaultMCPProvider)",
    )
    mcp_timeout_s: float = Field(
        default=30.0,
        description="MCP HTTP request timeout in seconds",
    )

    # ─── Server ───
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_debug: bool = Field(default=False)
    cors_allowed_origins: str = Field(
        default="*",
        description="CORS allowed origins (comma-separated, '*' for all)",
    )

    # ─── External API (optional, for MCP-style tool bridges) ───
    external_api_base_url: str = Field(
        default="",
        description="External API base URL for custom tool bridges",
    )

    # ─── Plugins ───
    plugins_dir: str = Field(
        default="plugins",
        description="Plugins directory path",
    )

    # ─── Security Sandbox (A6) ───
    sandbox_workspace_dir: str = Field(
        default="data/workspace",
        description="Workspace base directory for file sandbox",
    )
    sandbox_max_disk_quota_mb: int = Field(
        default=500,
        description="Max disk quota per user in MB",
    )
    sandbox_network_whitelist: str = Field(
        default="",
        description="Comma-separated allowed domains/URL prefixes (empty=allow all non-private)",
    )
    sandbox_block_private_networks: bool = Field(
        default=True,
        description="Block access to private/internal network addresses",
    )
    sandbox_rate_limit_per_minute: int = Field(
        default=100,
        description="Max tool calls per session per minute",
    )
    sandbox_docker_enabled: bool = Field(
        default=False,
        description="Enable Docker sandbox for command execution (requires Docker)",
    )
    sandbox_docker_image: str = Field(
        default="python:3.11-slim",
        description="Docker image for command sandbox",
    )
    sandbox_docker_cpu_limit: str = Field(
        default="1",
        description="Docker CPU limit",
    )
    sandbox_docker_memory_limit: str = Field(
        default="512m",
        description="Docker memory limit",
    )

    # ─── File Upload ───
    max_file_upload_mb: int = Field(
        default=100,
        description="Maximum file upload size in MB",
    )
    file_retention_days: int = Field(
        default=7,
        description="用户上传的会话文件保留天数 (0=不清理)",
    )

    # ─── Skills ───
    skills_dir: str = Field(
        default="skills",
        description="Skills directory path",
    )
    skill_max_l2_tokens: int = Field(
        default=5000,
        description="Max token estimate for single Skill L2 body",
    )
    skill_max_prompt_chars: int = Field(
        default=30000,
        description="A7: Max total chars for all Skills in system prompt",
    )
    skill_max_single_chars: int = Field(
        default=10000,
        description="A7: Max chars for a single Skill body",
    )

    # ─── Memory (A8: Markdown 分层笔记) ───
    memory_storage_dir: str = Field(
        default="data/memory",
        description="Memory persistence directory (三级: global/tenant/user)",
    )
    memory_max_prompt_chars: int = Field(
        default=8000,
        description="Max chars for memory injection into system prompt",
    )

    # ─── Scheduler (A9) ───
    scheduler_enabled: bool = Field(
        default=True,
        description="Enable cron scheduler background loop",
    )
    scheduler_check_interval_s: int = Field(
        default=60,
        description="Scheduler tick interval in seconds",
    )
    scheduler_data_dir: str = Field(
        default="data/schedules",
        description="Scheduler task persistence directory",
    )
    scheduler_timezone: str = Field(
        default="Asia/Shanghai",
        description="Timezone for cron schedule interpretation (IANA tz name)",
    )

    # ─── Webhook (A9) ───
    webhook_data_dir: str = Field(
        default="data/webhooks",
        description="Webhook config persistence directory",
    )
    webhook_timeout_s: float = Field(
        default=10.0,
        description="Webhook POST request timeout in seconds",
    )
    webhook_max_retries: int = Field(
        default=3,
        description="Webhook max retry count with exponential backoff",
    )

    # ─── Auth ───
    auth_enabled: bool = Field(
        default=False,
        description="Enable authentication (False = dev mode with default user)",
    )
    auth_mode: str = Field(
        default="jwt",
        description="Auth mode: jwt | api_key",
    )
    auth_jwt_secret: str = Field(
        default="",
        description="JWT HS256 secret key",
    )
    auth_jwt_algorithm: str = Field(
        default="HS256",
        description="JWT algorithm",
    )
    auth_session_expire_s: int = Field(
        default=86400,
        description="JWT token lifetime in seconds",
    )
    auth_default_tenant_id: str = Field(
        default="default",
        description="Default tenant ID when auth is disabled",
    )
    auth_default_user_id: str = Field(
        default="U001",
        description="Default user ID when auth is disabled",
    )

    # ─── Database ───
    db_path: str = Field(
        default="data/claw.db",
        description="SQLite database file path",
    )

    # ─── Logging ───
    log_level: str = Field(default="INFO")
    log_format: str = Field(
        default="console",
        description="console | json",
    )

    @model_validator(mode="after")
    def _validate_auth_jwt_secret(self) -> "Settings":
        if self.auth_enabled and self.auth_mode == "jwt" and not self.auth_jwt_secret:
            raise ValueError(
                "auth_jwt_secret must be set when auth_enabled=True and auth_mode='jwt'"
            )
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Global singleton
settings = Settings()
