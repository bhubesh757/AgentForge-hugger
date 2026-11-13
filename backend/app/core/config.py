"""Application settings (env vars per API_CONTRACTS.md section 15)."""

from __future__ import annotations

import base64
import hashlib
from functools import cached_property
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.1"
API_VERSION = "v1"
API_PREFIX = "/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    DATABASE_URL: str = "postgresql+asyncpg://agentforge:agentforge@postgres:5432/agentforge"
    REDIS_URL: str = "redis://redis:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    EXECUTION_DISPATCH: Literal["kafka", "inline"] = "kafka"
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_SECONDS: int = 900
    REFRESH_TOKEN_TTL_SECONDS: int = 604800
    CREDENTIAL_ENCRYPTION_KEY: str = ""
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    LLM_MOCK_MODE: bool = False
    SANDBOX_IMAGE: str = "agentforge-sandbox:1.0.1"
    SANDBOX_TIMEOUT_SECONDS: int = 30
    SANDBOX_MEMORY_MB: int = 256
    SANDBOX_CPUS: float = 0.5
    SANDBOX_ALLOWED_PACKAGES: str = "requests,httpx,pydantic,python-dateutil"
    SANDBOX_NETWORK: str = "none"
    LOG_LEVEL: str = "INFO"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    EMBEDDING_DIM: int = 768
    AUTH_RATE_LIMIT_PER_MINUTE: int = 20

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        if self.is_production:
            if len(self.JWT_SECRET) < 32:
                raise ValueError("JWT_SECRET must be set (>=32 chars) in production")
            if not self.CREDENTIAL_ENCRYPTION_KEY:
                raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be set in production")
            if self.LLM_MOCK_MODE:
                raise ValueError("LLM_MOCK_MODE must not be enabled in production")
        return self

    @cached_property
    def jwt_secret(self) -> str:
        # Dev-only fallback so `uvicorn app.main:app` works out of the box; prod is enforced above.
        return self.JWT_SECRET or "dev-insecure-jwt-secret-change-me-please-0123456789"

    @cached_property
    def fernet_key(self) -> bytes:
        if self.CREDENTIAL_ENCRYPTION_KEY:
            return self.CREDENTIAL_ENCRYPTION_KEY.encode()
        digest = hashlib.sha256(("agentforge-dev-fernet:" + self.jwt_secret).encode()).digest()
        return base64.urlsafe_b64encode(digest)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_packages(self) -> set[str]:
        return {p.strip().lower() for p in self.SANDBOX_ALLOWED_PACKAGES.split(",") if p.strip()}


settings = Settings()
