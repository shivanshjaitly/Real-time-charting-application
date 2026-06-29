"""Configuration via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHART_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "*"
    tick_interval_seconds: float = 1.0   # live price tick interval (real seconds)
    history_candles: int = 200
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
