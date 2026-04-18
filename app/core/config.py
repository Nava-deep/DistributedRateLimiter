from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    project_name: str = Field(default="distributed-rate-limiter", alias="PROJECT_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    app_instance_name: str = Field(default="api-1", alias="APP_INSTANCE_NAME")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/distributed_rate_limiter",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_socket_timeout_seconds: float = Field(
        default=1.0,
        alias="REDIS_SOCKET_TIMEOUT_SECONDS",
    )
    admin_token: str = Field(default="change-me", alias="ADMIN_TOKEN")
    policy_cache_ttl_seconds: int = Field(default=30, alias="POLICY_CACHE_TTL_SECONDS")
    local_policy_cache_ttl_seconds: int = Field(
        default=15,
        alias="LOCAL_POLICY_CACHE_TTL_SECONDS",
    )
    policy_refresh_channel: str = Field(
        default="distributed-rate-limiter.policy-refresh",
        alias="POLICY_REFRESH_CHANNEL",
    )
    strict_startup_checks: bool = Field(default=False, alias="STRICT_STARTUP_CHECKS")
    enable_policy_pubsub: bool = Field(default=True, alias="ENABLE_POLICY_PUBSUB")
    enable_local_fallback_limiter: bool = Field(
        default=False,
        alias="ENABLE_LOCAL_FALLBACK_LIMITER",
    )
    local_fallback_state_ttl_seconds: int = Field(
        default=120,
        alias="LOCAL_FALLBACK_STATE_TTL_SECONDS",
    )
    redis_retry_attempts: int = Field(default=1, alias="REDIS_RETRY_ATTEMPTS")
    redis_retry_backoff_ms: int = Field(default=25, alias="REDIS_RETRY_BACKOFF_MS")
    request_timeout_seconds: float = Field(default=1.0, alias="REQUEST_TIMEOUT_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def policy_cache_key(self) -> str:
        return f"{self.project_name}:policies:active"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
