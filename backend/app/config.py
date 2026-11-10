"""Application configuration (environment driven)."""
import base64
import hashlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "full" = PostgreSQL + RabbitMQ, "lite" = SQLite + in-process queue (no Docker needed)
    run_mode: str = "lite"
    environment: str = "development"  # development | production
    database_url: str = "sqlite:///./securetokens_lite.db"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    admin_api_key: str = "st_admin_dev_key"
    demo_api_key: str = "st_dev_demo_key"
    seed_demo: bool = True
    # Fernet key (urlsafe base64, 32 bytes). A dev-only key is derived when unset.
    secret_encryption_key: str = ""

    # Webhook delivery
    allow_localhost_webhooks: bool = True  # DEVELOPMENT ONLY
    dev_allowed_hosts: str = "localhost,127.0.0.1,::1,receiver"
    webhook_retry_schedule: str = "0,30,120,600,1800"  # seconds before attempt N+1 (index 0 unused/immediate)
    webhook_timeout_seconds: float = 5.0
    webhook_max_response_bytes: int = 2048
    webhook_retry_jitter: float = 0.1
    webhook_poll_interval: float = 1.0
    outbox_poll_interval: float = 0.5

    # Simulation (all values are demo data)
    execution_delay_seconds: float = 2.0
    reserve_initial_balance: float = 10000.0
    policy_limit_per_claim: float = 1000.0
    credit_rate_per_1k_tokens: float = 5.0

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def retry_schedule(self) -> list[float]:
        return [float(x) for x in self.webhook_retry_schedule.split(",") if x.strip()]

    @property
    def max_attempts(self) -> int:
        return len(self.retry_schedule)

    @property
    def fernet_key(self) -> bytes:
        if self.secret_encryption_key:
            return self.secret_encryption_key.encode()
        # Dev-only fallback. Never use in production.
        return base64.urlsafe_b64encode(hashlib.sha256(b"securetokens-dev-only-key").digest())


@lru_cache
def get_settings() -> Settings:
    return Settings()
