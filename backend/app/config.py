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
    SQL_ECHO: bool = False

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
    MQTT_TELEMETRY_TOPIC: str = "teltonika/+/telemetry"
    MQTT_DTC_TOPIC: str = "teltonika/+/dtc"

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

    # ── Rule engine freshness guard ───────────────────────────────────────────
    # FMC150 devices buffer records when out of coverage and burst-upload them
    # later. Readings are always STORED, but rules are only evaluated for
    # records fresher than this — replayed history must not fire phantom alerts.
    RULE_MAX_RECORD_AGE_SECONDS: int = 300

    # Dashboard live tiles: Redis snapshots older than this are treated as offline
    # (no sensor values, ignition, or speed shown).
    TELEMETRY_LIVE_MAX_AGE_SECONDS: int = 300

    # Offline watchdog: vehicles with no telemetry for this long (and no active
    # alerts) revert to GREY health. Checked every WATCHDOG_INTERVAL_SECONDS.
    OFFLINE_AFTER_SECONDS: int = 300
    WATCHDOG_INTERVAL_SECONDS: int = 60

    # Raw sensor_readings older than this are dropped by the Timescale
    # retention policy (1m/1h continuous aggregates are kept).
    READINGS_RETENTION_DAYS: int = 365

    # Rule engine: in-process rule cache TTL (invalidated on rules CRUD too).
    RULES_CACHE_TTL_SECONDS: int = 30


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