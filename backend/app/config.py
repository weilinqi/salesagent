"""
SalesAgent Application Configuration
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        hide_input_in_errors=True
    )

    # App settings
    APP_NAME: str = "SalesAgent"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite:///./salesagent.db"

    # JWT
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MiniMax LLM
    MINIMAX_TERTIARY_API_KEY: Optional[str] = None
    MINIMAX_FALLBACK_API_KEY: Optional[str] = None
    AUDIO_DEBUG_ENABLED: bool = False
    AUDIO_DEBUG_RETENTION_HOURS: int = 24
    MINIMAX_USE_PROXY: bool = False
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