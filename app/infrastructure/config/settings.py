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

    # Model gateway (defaults only; per-request selection uses the catalog)
    default_model_provider: str = "openai"
    default_model_name: str | None = None
    enabled_providers: str = ""
    model_call_max_retries: int = 2
    model_call_retry_base_seconds: float = 1.0

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4-turbo-preview"
    openai_models: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    anthropic_models: str = ""

    # Operator-configured OpenAI-compatible endpoint (never request-controlled)
    openai_compatible_enabled: bool = False
    openai_compatible_provider_id: str = "openai-compatible"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: str | None = None
    openai_compatible_models: str = ""

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

    # Production hardening
    cancellation_backend: str = "local"  # local | redis
    max_concurrent_runs_per_user: int = 4
    max_request_body_bytes: int = 1_048_576
    max_message_chars: int = 32_000
    llm_request_timeout_seconds: float = 120.0
    web_render_isolated: bool = False
    redis_required: bool = False
    database_pool_recycle_seconds: int = 1800
    database_pool_timeout_seconds: float = 30.0

    # OAuth identity (login only; do not persist provider tokens)
    google_oauth_enabled: bool = False
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://127.0.0.1:8000/api/v1/auth/google/callback"
    github_oauth_enabled: bool = False
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str = "http://127.0.0.1:8000/api/v1/auth/github/callback"
    oauth_state_ttl_seconds: int = 600
    oauth_exchange_ttl_seconds: int = 120
    oauth_http_timeout_seconds: float = 10.0
    oauth_post_login_redirect: str | None = None
    oauth_vscode_redirect: str | None = "vscode://bytebuddhi.bytebuddhi/oauth"
    oauth_cli_redirect: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def uses_redis_coordination(self) -> bool:
        return self.cancellation_backend.strip().lower() == "redis" or self.redis_required

    def validate_runtime_configuration(self) -> None:
        """Fail closed on unsafe production configuration."""
        self.validate_oauth_configuration()
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
        if "*" in self.cors_origins:
            raise RuntimeError("Production CORS_ORIGINS must not include *")
        if self.web_render_enabled and not self.web_render_isolated:
            raise RuntimeError("Production WEB_RENDER_ENABLED requires WEB_RENDER_ISOLATED=true")
        backend = self.cancellation_backend.strip().lower()
        if backend not in {"local", "redis"}:
            raise RuntimeError("CANCELLATION_BACKEND must be local or redis")
        self.validate_oauth_configuration()

    def validate_oauth_configuration(self) -> None:
        """Fail closed on incomplete or unsafe OAuth identity configuration."""
        self._validate_oauth_provider(
            "Google",
            enabled=self.google_oauth_enabled,
            client_id=self.google_client_id,
            client_secret=self.google_client_secret,
            redirect_uri=self.google_redirect_uri,
        )
        self._validate_oauth_provider(
            "GitHub",
            enabled=self.github_oauth_enabled,
            client_id=self.github_client_id,
            client_secret=self.github_client_secret,
            redirect_uri=self.github_redirect_uri,
        )
        if self.oauth_state_ttl_seconds < 60 or self.oauth_state_ttl_seconds > 600:
            raise RuntimeError("OAUTH_STATE_TTL_SECONDS must be between 60 and 600")
        if self.oauth_exchange_ttl_seconds < 30 or self.oauth_exchange_ttl_seconds > 300:
            raise RuntimeError("OAUTH_EXCHANGE_TTL_SECONDS must be between 30 and 300")
        if self.oauth_post_login_redirect:
            self._assert_configured_redirect(
                "OAUTH_POST_LOGIN_REDIRECT",
                self.oauth_post_login_redirect,
                allow_vscode=False,
            )
        if self.oauth_vscode_redirect:
            self._assert_configured_redirect(
                "OAUTH_VSCODE_REDIRECT",
                self.oauth_vscode_redirect,
                allow_vscode=True,
            )
        if self.oauth_cli_redirect:
            self._assert_configured_redirect(
                "OAUTH_CLI_REDIRECT",
                self.oauth_cli_redirect,
                allow_vscode=False,
                require_loopback=True,
            )

    def _validate_oauth_provider(
        self,
        name: str,
        *,
        enabled: bool,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str,
    ) -> None:
        has_id = bool((client_id or "").strip())
        has_secret = bool((client_secret or "").strip())
        if has_id != has_secret:
            raise RuntimeError(f"{name} OAuth client ID and client secret must both be set")
        if enabled and not has_id:
            raise RuntimeError(f"{name} OAuth is enabled but client ID/secret are missing")
        if enabled:
            self._assert_configured_redirect(f"{name} redirect URI", redirect_uri, allow_vscode=False)

    def _assert_configured_redirect(
        self,
        name: str,
        url: str,
        *,
        allow_vscode: bool,
        require_loopback: bool = False,
    ) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(url.strip())
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError(f"{name} must be an absolute URL")
        host = (parsed.hostname or "").lower()
        loopback = host in {"127.0.0.1", "localhost", "::1"}
        if allow_vscode and parsed.scheme == "vscode":
            return
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError(f"{name} must use http(s)")
        if require_loopback and not loopback:
            raise RuntimeError(f"{name} must be a loopback URL")
        if parsed.scheme == "http" and self.is_production and not loopback:
            raise RuntimeError(f"{name} must use HTTPS in production")

    def validate_model_settings(self) -> None:
        """Validate catalog defaults. Production also requires credentialed default model."""
        if self.openai_compatible_enabled:
            url = (self.openai_compatible_base_url or "").strip()
            if not url:
                raise RuntimeError("OPENAI_COMPATIBLE_BASE_URL is required when OPENAI_COMPATIBLE_ENABLED=true")
            if not url.startswith("http"):
                raise RuntimeError("OPENAI_COMPATIBLE_BASE_URL must be an http(s) URL configured by the operator")
        from app.infrastructure.llm.provider_factory import (
            build_model_catalog,
            validate_default_model_availability,
        )

        build_model_catalog(self)
        if self.is_production:
            validate_default_model_availability(self)


# Global settings instance
settings = Settings()
