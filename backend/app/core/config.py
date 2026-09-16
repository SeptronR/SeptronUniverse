"""Settings (pydantic-settings) — Prompts/00_PREREQUISITE_Project_Setup.md §3.4."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "SeptronUniverse"
    APP_ENV: str = "development"
    SECRET_KEY: str
    JWT_KID: str = "k1"
    JWT_PREVIOUS_KEYS: dict[str, str] = {}
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]
    PLATFORM_HOSTS: list[str] = ["localhost"]
    READ_ONLY_MODE: bool = False

    DATABASE_URL: str
    PLATFORM_DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    REDIS_URL: str
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    STORAGE_BACKEND: str = "local"
    UPLOAD_DIR: str = "./uploads"
    S3_BUCKET: str | None = None
    S3_REGION: str | None = None
    S3_ENDPOINT_URL: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    SIGNED_URL_TTL_SECONDS: int = 900
    MAX_UPLOAD_MB: int = 25
    # builtin = signature sniffer (no native library); magic = python-magic/libmagic (Docker image, Linux)
    FILE_MIME_SNIFFER: str = "builtin"
    CLAMAV_HOST: str | None = None
    CLAMAV_PORT: int = 3310
    JOB_RETENTION_DAYS: int = 7

    SMS_PROVIDER: str = "mock"
    WHATSAPP_PROVIDER: str = "mock"
    EMAIL_PROVIDER: str = "mock"
    PUSH_PROVIDER: str = "mock"
    PAYMENT_PROVIDER: str = "mock"
    INTEGRATION_ENCRYPTION_KEY: str
    CAPTCHA_PROVIDER: str = "none"
    CAPTCHA_SECRET: str | None = None
    CAPTCHA_SITE_KEY: str | None = None

    SENTRY_DSN: str | None = None
    LOG_LEVEL: str = "INFO"
    INSTALL_SECRET_KEY: str
    SUPERADMIN_EMAIL: str = "superadmin@universe.local"

    @field_validator("DATABASE_URL", "PLATFORM_DATABASE_URL", mode="before")
    @classmethod
    def _asyncpg(cls, v: str | None) -> str | None:
        if not v:
            return v
        return v.replace("postgres://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://")

    @field_validator(
        "S3_BUCKET",
        "S3_REGION",
        "S3_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "SENTRY_DSN",
        "CAPTCHA_SECRET",
        "CAPTCHA_SITE_KEY",
        "CLAMAV_HOST",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v or None


settings = Settings()
