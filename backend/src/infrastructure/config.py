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
    # 1m bars of history at startup (14400 ≈ 10 days). Higher intervals derived from these.
    # Increase via CHART_SEED_1M_BARS for deeper 1d/1h history.
    seed_1m_bars: int = 14400
    # Recent tail generated at full 1m resolution (4320 ≈ 3 days). Older history uses
    # one synthetic 1m candle per hour for fast startup while keeping 1h/1d correct.
    seed_fine_1m_bars: int = 4320
    # IANA timezone for candle boundaries (e.g. Asia/Kolkata). Empty = server local time.
    candle_timezone: str = ""
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
