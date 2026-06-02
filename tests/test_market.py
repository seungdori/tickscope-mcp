"""Unit tests for utils: symbol normalization, time, structured errors."""

from __future__ import annotations

import ccxt

from tickscope.config import Settings
from tickscope.utils import (
    age_ms,
    error_payload,
    iso_or_ms_to_ms,
    ms_to_iso,
    normalize_symbol,
)


def test_normalize_already_unified():
    assert normalize_symbol("BTC/USDT") == "BTC/USDT"
    assert normalize_symbol("btc/usdt") == "BTC/USDT"
    assert normalize_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"


def test_normalize_compact_heuristic():
    assert normalize_symbol("BTCUSDT") == "BTC/USDT"
    assert normalize_symbol("ETHUSDC") == "ETH/USDC"


def test_normalize_with_markets():
    markets = {"BTC/USDT": {"symbol": "BTC/USDT", "id": "BTCUSDT"}}
    assert normalize_symbol("BTCUSDT", markets) == "BTC/USDT"


def test_time_roundtrip():
    ms = 1_700_000_000_000
    iso = ms_to_iso(ms)
    assert iso is not None and iso.endswith("Z")
    assert iso_or_ms_to_ms(iso) == ms
    assert iso_or_ms_to_ms("1700000000000") == ms
    assert iso_or_ms_to_ms(ms) == ms


def test_age_ms_non_negative():
    assert age_ms(None) is None
    assert age_ms(0) is not None and age_ms(0) >= 0


def test_settings_parses_comma_separated_exchanges(monkeypatch):
    # Regression: pydantic-settings must not JSON-parse this env var.
    monkeypatch.setenv("TICKSCOPE_EXCHANGES", "binance,bybit,okx")
    settings = Settings()
    assert settings.exchanges == ["binance", "bybit", "okx"]


def test_error_payload_retryable_classification():
    net = error_payload(ccxt.NetworkError("down"), exchange="binance", symbol="BTC/USDT")
    assert net["error"]["retryable"] is True
    assert net["error"]["type"] == "NetworkError"

    bad = error_payload(ccxt.BadSymbol("nope"), exchange="binance", symbol="XXX")
    assert bad["error"]["retryable"] is False
