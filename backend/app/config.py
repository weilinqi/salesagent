"""
SalesAgent Application Configuration
"""
import logging
from pathlib import Path
import secrets
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Application settings"""
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )

    # App settings
    APP_NAME: str = "SalesAgent"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    PORT: int = Field(default=8002, ge=1, le=65535)
    ENVIRONMENT: Literal["development", "test", "production"] = "development"

    # Database
    DATABASE_URL: str = f"sqlite:///{(BACKEND_DIR / 'salesagent.db').as_posix()}"

    # JWT
    SECRET_KEY: str = Field(default="", repr=False)
    ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, gt=0)

    KNOWLEDGE_DATA_DIR: Path = PROJECT_DIR / "原始数据"
    AUDIO_DEBUG_ENABLED: bool = False
    AUDIO_DEBUG_RETENTION_HOURS: int = Field(default=24, gt=0)
    ENABLE_MODEL_WARMUP: bool = True
    ENABLE_SCHEDULER: bool = True

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def normalize_environment(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_signing_secret(self):
        value = self.SECRET_KEY
        unsafe = (
            len(value.encode("utf-8")) < 32
            or len(set(value)) < 8
            or value in {"your-secret-key-change-in-production", "change-me-in-production"}
        )
        if unsafe:
            if self.ENVIRONMENT == "production":
                raise ValueError("Production requires a strong SECRET_KEY of at least 32 bytes; placeholder secrets are forbidden")
            self.SECRET_KEY = secrets.token_urlsafe(48)
            logging.getLogger(__name__).warning(
                "Using a temporary development JWT key; configure SECRET_KEY to preserve logins across restarts."
            )
        return self

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MiniMax LLM
    MINIMAX_API_KEY: Optional[str] = None
    MINIMAX_BASE_URL: str = "https://api.minimaxi.com/v1"

    # DeepSeek LLM
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    # Volcano Engine (ASR/TTS)
    VOLC_API_KEY: Optional[str] = None
    VOLC_API_SECRET: Optional[str] = None
    VOLC_APP_ID: Optional[str] = None

    # Milvus Vector DB
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""

    # MinIO Storage
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "salesagent"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]


settings = Settings()
