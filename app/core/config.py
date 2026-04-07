from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Все настройки приложения загружаются из переменных окружения.
    pydantic-settings автоматически читает .env файл.

    lru_cache гарантирует что Settings создаётся один раз —
    это важно для производительности (не читать файл при каждом запросе).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str
    database_url_sync: str  # нужен для Alembic (не поддерживает async)

    # Redis
    redis_url: str

    # Kafka
    kafka_bootstrap_servers: str

    # ClickHouse
    clickhouse_host: str
    clickhouse_port: int = 9000
    clickhouse_db: str

    # Security
    secret_key: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # ЮKassa
    yukassa_shop_id: str
    yukassa_secret_key: str
    yukassa_webhook_secret: str
    reconciliation_stuck_seconds: int = 600

    # Sentry
    sentry_dsn: str = ""

    # Environment
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
