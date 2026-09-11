from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "ByteBuddhi"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4

    # Database
    database_url: PostgresDsn | str = Field(
        default="postgresql+asyncpg://bytebuddhi:password@localhost:5432/bytebuddhi"
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # Redis
    redis_url: RedisDsn | str = Field(default="redis://localhost:6379/0")
    redis_max_connections: int = 50

    # Auth
    jwt_secret_key: str = Field(default="your-super-secret-jwt-key-change-this")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4-turbo-preview"
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # Web research (provider-agnostic; adapters selected in infrastructure)
    web_search_provider: str = "duckduckgo"
    web_search_endpoint: str = "https://html.duckduckgo.com/html/"
    web_search_max_results: int = 5
    web_search_timeout_seconds: float = 10.0
    web_fetch_timeout_seconds: float = 15.0
    web_fetch_max_response_bytes: int = 1_000_000
    web_fetch_max_redirects: int = 5
    web_fetch_max_retries: int = 3
    web_research_max_pages: int = 5
    web_research_max_concurrent_fetches: int = 4
    web_research_max_extracted_chars: int = 10_000
    web_research_max_total_chars: int = 30_000
    web_research_max_duration_seconds: float = 30.0
    web_research_preview_chars: int = 800
    web_render_enabled: bool = False
    web_render_timeout_seconds: float = 20.0
    web_render_max_pages: int = 2
    web_render_max_browser_instances: int = 1
    web_user_agent: str = "ByteBuddhi/0.1 (web-research; +https://github.com/bytebuddhi)"

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_api_key: str | None = None
    langchain_project: str = "bytebuddhi-dev"

    # CORS
    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://localhost:5173"])

    # Rate Limiting
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000

    # File Upload
    max_upload_size_mb: int = 50
    allowed_extensions: list[str] = Field(default=[".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h"])

    # Observability / OpenTelemetry
    telemetry_enabled: bool = True
    otel_service_name: str = "bytebuddhi"
    otel_exporter: str = "console"  # "console" | "otlp" | "none"
    otel_otlp_endpoint: str = "http://localhost:4317"
    otel_tracing_enabled: bool = True
    otel_metrics_enabled: bool = True
    otel_sampling_rate: float = 1.0

    # Workspace policy
    workspace_mode: str = "local"
    workspace_root: str = "storage/workspaces"

    # Rate limiting / proxy
    trusted_proxy_ips: list[str] = Field(default_factory=list)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    def validate_runtime_configuration(self) -> None:
        """Fail closed on unsafe production configuration."""
        if not self.is_production:
            return
        weak_secrets = {
            "your-super-secret-jwt-key-change-this",
            "your-super-secret-jwt-key-change-this-to-something-secure",
            "change-me",
            "secret",
        }
        if self.jwt_secret_key in weak_secrets or len(self.jwt_secret_key) < 32:
            raise RuntimeError("Production JWT_SECRET_KEY is missing or too weak")
        if self.debug:
            raise RuntimeError("Production must not run with DEBUG=true")
        db_url = str(self.database_url)
        if "bytebuddhi:password@" in db_url:
            raise RuntimeError("Production DATABASE_URL must not use the development default password")
        if self.workspace_mode.strip().lower() != "managed":
            raise RuntimeError("Production requires WORKSPACE_MODE=managed")


# Global settings instance
settings = Settings()
