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
    llm_fallback_model: str = Field(
        default="",
        description="Fallback model when primary model is unavailable (empty=no fallback)",
    )
    llm_fallback_base_url: str = Field(
        default="",
        description="Fallback LLM API base URL (空=复用主地址)",
    )
    llm_fallback_api_key: str = Field(
        default="",
        description="Fallback LLM API key (空=复用主 key)",
    )
    llm_fallback_context_window: int = Field(
        default=0,
        description="Fallback 模型上下文窗口 (0=与主模型相同)。若更小，runtime 自动使用较小值确保不溢出",
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
        default=0,
        description="Max chars per tool result (0=dynamic: 30%% of context window, min 3000)",
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
        default=0.70,
        description="Trigger compression at this fraction of budget (early trigger for multi-stage)",
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

    # ─── Tool Search (2.3: 延迟加载) ───
    agent_tool_deferred_threshold: int = Field(
        default=30,
        description="工具总数超过此阈值时自动切换延迟加载模式",
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
    sandbox_writable_roots: str = Field(
        default="",
        description="Comma-separated writable sub-directories within workspace (empty=entire workspace writable)",
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
    session_retention_days: int = Field(
        default=30,
        description="会话 JSONL 文件保留天数 (0=不清理)",
    )

    # ─── Skills ───
    skills_dir: str = Field(
        default="skills",
        description="Skills directory path",
    )
    skill_max_prompt_chars: int = Field(
        default=30000,
        description="A7: Max total chars for all Skills in system prompt",
    )
    skill_max_single_chars: int = Field(
        default=10000,
        description="A7: Max chars for a single Skill body",
    )

    # ─── Memory (A8: Markdown 分层笔记 + 自动提取) ───
    memory_auto_extract_enabled: bool = Field(
        default=True,
        description="Enable auto-extraction of user preferences/corrections after each conversation",
    )
    memory_auto_extract_max_tokens: int = Field(
        default=300,
        description="Max tokens for auto-extract LLM call",
    )
    memory_storage_dir: str = Field(
        default="data/memory",
        description="Memory persistence directory (三级: global/tenant/user)",
    )
    memory_max_prompt_chars: int = Field(
        default=8000,
        description="Max chars for memory injection into system prompt",
    )
    memory_merge_interval_hours: int = Field(
        default=6,
        description="Interval in hours between auto-learning memory merge runs",
    )
    memory_merge_max_per_run: int = Field(
        default=50,
        description="Max number of users to merge per run",
    )
    memory_retention_days: int = Field(
        default=30,
        description="记忆条目过期天数 (0=不清理, 仅清理 usage_count==0 的条目)",
    )
    memory_workflow_tracking_enabled: bool = Field(
        default=True,
        description="Enable workflow fingerprint tracking for Skill suggestion",
    )
    memory_workflow_repeat_threshold: int = Field(
        default=3,
        description="Workflow repeat count threshold to trigger Skill suggestion",
    )

    # ─── Collaboration Mode Presets (#28) ───
    mode_presets: str = Field(
        default='{"quick":{"max_iterations":10,"temperature":0.5},"deep":{"max_iterations":25,"temperature":0.7},"creative":{"max_iterations":15,"temperature":0.9}}',
        description="JSON: 命名模式预设 → RuntimeConfig 覆盖参数",
    )

    # ─── Prompt Templates (#27) ───
    prompt_templates_dir: str = Field(
        default="data/prompt_templates",
        description="用户级 Prompt 模板存储目录",
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

    # ─── Observability (OpenTelemetry) ───
    otel_enabled: bool = Field(
        default=False,
        description="启用 OpenTelemetry 分布式追踪",
    )
    otel_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP gRPC endpoint",
    )
    otel_service_name: str = Field(
        default="claw-for-saas",
        description="OTel service name",
    )

    # ─── Guardian (3.4: AI 风险评估) ───
    guardian_enabled: bool = Field(
        default=False,
        description="启用 Guardian AI 风险评估 (高风险工具调用前 LLM 审查)",
    )
    guardian_model: str = Field(
        default="",
        description="Guardian LLM 模型名 (空=复用主模型)",
    )
    guardian_base_url: str = Field(
        default="",
        description="Guardian LLM API 地址 (空=复用主地址)",
    )
    guardian_api_key: str = Field(
        default="",
        description="Guardian LLM API Key (空=复用主 key)",
    )
    guardian_risk_threshold: int = Field(
        default=80,
        description="风险评分阈值 (0-100)，>= 此值则阻止",
    )
    guardian_timeout_s: float = Field(
        default=30.0,
        description="Guardian LLM 调用超时秒数",
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
