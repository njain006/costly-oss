from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # MongoDB
    mongo_url: str = "mongodb://localhost:27017"
    db_name: str = "costly"

    # JWT
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Encryption
    encryption_key: str = ""

    # Email / SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    app_url: str = "http://localhost:3000"

    # Google OAuth
    google_client_id: str = ""

    # CORS
    cors_origins: List[str] = ["http://localhost:3000"]

    # LLM (AI agent backend)
    llm_api_key: str = ""
    llm_provider: str = "anthropic"  # anthropic, openai
    llm_model: str = "claude-sonnet-4-20250514"

    # Redis
    redis_url: str = "redis://localhost:6379"
    # Background precompute of Snowflake pages. Each run uses your Snowflake
    # warehouse (roughly 10-15 min of an X-Small on a busy account), so it
    # costs credits. ACCOUNT_USAGE lags 1-3h anyway; 0 turns it off.
    prewarm_interval_hours: int = 6

    model_config = {"env_file": ".env", "extra": "ignore"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.smtp_from:
            self.smtp_from = self.smtp_user


settings = Settings()

if not settings.jwt_secret or settings.jwt_secret == "change-this-secret-key":
    raise RuntimeError(
        "JWT_SECRET is not configured. "
        "Generate one with: openssl rand -hex 32"
    )
