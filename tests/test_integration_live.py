"""Live integration tests against real exchanges.

Excluded from CI by default; run locally with ``pytest -m live``.
"""

from __future__ import annotations

import asyncio

import pytest

from tickscope.config import Settings
from tickscope.core.service import MarketDataService

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


@pytest.fixture()
async def live_service(tmp_path):
    svc = MarketDataService(
        Settings(
            exchanges=["binance"],
            default_exchange="binance",
            ohlcv_cache_path=str(tmp_path / "live.duckdb"),
        )
    )
    try:
        yield svc
    finally:
        await svc.aclose()


async def test_cold_to_warm_transition(live_service):
    cold = await live_service.get_ticker("binance", "BTC/USDT")
    assert cold["source"] == "rest"
    assert cold["last"] is not None

    # Give the auto-started websocket watch time to fill the cache.
    for _ in range(20):
        await asyncio.sleep(1)
        if live_service.cache.get_ticker("binance", "BTC/USDT") is not None:
            break

    warm = await live_service.get_ticker("binance", "BTC/USDT")
    assert warm["source"] == "websocket"
    assert warm["age_ms"] is not None


async def test_ohlcv_cache_hit_second_call(live_service):
    first = await live_service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    assert first["meta"]["count"] > 0
    second = await live_service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    assert second["meta"]["cache_hit"] is True


async def test_orderbook_and_trades_live(live_service):
    ob = await live_service.get_orderbook("binance", "BTC/USDT", 10)
    assert ob["bids"] and ob["asks"]
    assert ob["spread"] is not None and ob["spread"] >= 0
    trades = await live_service.get_recent_trades("binance", "BTC/USDT", 20)
    assert trades["count"] > 0


async def test_indicators_live(live_service):
    out = await live_service.compute_indicators(
        "binance", "BTC/USDT", "1h", 200,
        ["rsi:14", "macd:12,26,9", "ema:200", "supertrend:10,3", "wavetrend"], False,
    )
    assert out["results"]["rsi_14"]["value"] is not None
    assert out["results"]["ema_200"]["value"] is not None  # auto-warmup
    assert "direction" in out["results"]["supertrend_10_3"]


async def test_structure_and_patterns_live(live_service):
    div = await live_service.detect_divergence("binance", "BTC/USDT", "4h", 200, "rsi:14", 5, 5)
    assert "has_divergence" in div
    struct = await live_service.analyze_structure("binance", "BTC/USDT", "4h", 200, 3, 3)
    assert struct["trend"] in ("uptrend", "downtrend", "range")
    sr = await live_service.find_support_resistance("binance", "BTC/USDT", "1h", 200, 0.5, 6)
    assert "support" in sr and "resistance" in sr
    pats = await live_service.detect_patterns("binance", "BTC/USDT", "1h", 200, 15)
    assert "patterns" in pats and pats["latest_candle"] is not None


async def test_aggregated_price_live(tmp_path):
    svc = MarketDataService(
        Settings(
            exchanges=["binance", "bybit", "okx"],
            default_exchange="binance",
            ohlcv_cache_path=str(tmp_path / "agg.duckdb"),
        )
    )
    try:
        out = await svc.get_aggregated_price("BTC/USDT")
        assert out["exchange_count"] >= 2
        assert out["weighted_avg"] > 0
        assert out["arb_spread"] >= 0
    finally:
        await svc.aclose()


async def test_funding_rate_live(tmp_path):
    svc = MarketDataService(
        Settings(
            exchanges=["binance"],
            default_exchange="binance",
            ohlcv_cache_path=str(tmp_path / "fund.duckdb"),
        )
    )
    try:
        out = await svc.get_funding_rate("binance", "BTC/USDT:USDT")
        assert out["funding_rate"] is not None
    finally:
        await svc.aclose()
