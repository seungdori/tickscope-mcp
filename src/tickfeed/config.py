"""Configuration via environment variables (pydantic-settings).

All settings are prefixed with ``TICKFEED_``. v1 requires no API keys.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Loaded from environment / .env once per process."""

    model_config = SettingsConfigDict(
        env_prefix="TICKFEED_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # NoDecode: keep pydantic-settings from JSON-parsing the env var; the
    # validator below handles comma-separated input.
    exchanges: Annotated[list[str], NoDecode] = ["binance", "bybit", "okx"]
    default_exchange: str = "binance"

    max_watched_symbols: int = 25
    ring_buffer_size: int = 1000

    ohlcv_cache_path: str = "~/.tickfeed/ohlcv.duckdb"
    ohlcv_cache_ttl_s: int = 60

    # REST resilience (spec §9.2): retry transient errors with exponential backoff.
    rest_retries: int = 3
    # Bounded concurrency for multi-symbol work (screen_market, aggregation).
    screen_concurrency: int = 5

    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8765

    log_level: str = "INFO"

    @field_validator("exchanges", mode="before")
    @classmethod
    def _split_exchanges(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def resolved_cache_path(self) -> Path:
        """Absolute DuckDB path with ``~`` and env vars expanded; parent ensured."""
        expanded = os.path.expandvars(os.path.expanduser(self.ohlcv_cache_path))
        path = Path(expanded)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
