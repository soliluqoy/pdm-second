"""
PREDICT — Application Configuration
Centralized settings loaded from environment variables via pydantic-settings.
"""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "PREDICT"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://predict:predict_dev_password@postgres:5432/predict"
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── MQTT ──────────────────────────────────────────────────────────────────
    MQTT_HOST: str = "mosquitto"
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str = "predict_sim"
    MQTT_PASSWORD: str = "predict_sim_pass"
    MQTT_TELEMETRY_TOPIC: str = "fmc150/+/telemetry"
    MQTT_DTC_TOPIC: str = "fmc150/+/dtc"

    # ── Backend ───────────────────────────────────────────────────────────────
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
    )

    # ── Shadow Mode ───────────────────────────────────────────────────────────
    # When True, generated work orders are created in "shadow" status for review
    # rather than "open" status for immediate action.
    SHADOW_MODE: bool = True

    @field_validator("CORS_ORIGINS")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        """Keep as comma-separated string; parsed into list via property."""
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse the comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (singleton)."""
    return Settings()


# Module-level singleton for convenient import
settings = get_settings()