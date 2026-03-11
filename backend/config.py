"""
Claw-for-SaaS global configuration.
Uses pydantic-settings to load from environment variables and .env files.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings"""

    # ─── LLM Configuration ───
    llm_base_url: str = Field(
        default="http://localhost:11434/v1",
        description="LLM API base URL (OpenAI-compatible)",
    )
    llm_model: str = Field(
        default="qwen2.5",
        description="Model name",
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
    agent_context_budget_tokens: int = Field(
        default=28000,
        description="Messages array max token budget",
    )

    # ─── Server ───
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_debug: bool = Field(default=True)

    # ─── External API (optional, for MCP-style tool bridges) ───
    external_api_base_url: str = Field(
        default="",
        description="External API base URL for custom tool bridges",
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

    # ─── Memory ───
    memory_storage_dir: str = Field(
        default="data/memory",
        description="Memory persistence directory",
    )
    conversation_window_size: int = Field(
        default=10,
        description="Conversation memory sliding window size",
    )
    conversation_max_tokens: int = Field(
        default=8000,
        description="Conversation memory max tokens",
    )
    correction_decay_days: int = Field(
        default=90,
        description="User correction memory decay days",
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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Global singleton
settings = Settings()
