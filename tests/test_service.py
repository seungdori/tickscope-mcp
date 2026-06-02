"""Service-level tests: cache hit/miss, auto-watch, cold->warm transition."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_get_ticker_cold_is_rest_and_starts_watch(service, fake_exchange):
    result = await service.get_ticker("binance", "BTC/USDT")
    assert result["source"] == "rest"
    assert result["last"] == 67000.0
    # auto-watch should have been triggered on the cold call
    assert service.ingestion.is_watching("binance", "BTC/USDT")


async def test_get_ticker_warm_is_websocket(service, fake_exchange):
    # Simulate a websocket update landing in the cache.
    service.cache.set_ticker("binance", "BTC/USDT", {
        "last": 67050.0, "bid": 67049.0, "ask": 67051.0,
        "high": 68000.0, "low": 66000.0, "baseVolume": 1, "percentage": 1.0,
        "timestamp": None,
    })
    result = await service.get_ticker("binance", "BTC/USDT")
    assert result["source"] == "websocket"
    assert result["last"] == 67050.0


async def test_symbol_normalization(service):
    result = await service.get_ticker("binance", "BTCUSDT")
    assert result["symbol"] == "BTC/USDT"


async def test_ohlcv_second_call_is_cache_hit(service, fake_exchange):
    first = await service.get_ohlcv("binance", "BTC/USDT", "1h", 100)
    assert first["meta"]["cache_hit"] is False
    calls_after_first = fake_exchange.calls.get("fetch_ohlcv", 0)

    second = await service.get_ohlcv("binance", "BTC/USDT", "1h", 100)
    assert second["meta"]["cache_hit"] is True
    # No additional external fetch on the cached second call.
    assert fake_exchange.calls.get("fetch_ohlcv", 0) == calls_after_first


async def test_recent_trades_cold_then_warm(service, fake_exchange):
    cold = await service.get_recent_trades("binance", "BTC/USDT", 10)
    assert cold["source"] == "rest"
    assert cold["count"] == 10

    service.cache.append_trades("binance", "BTC/USDT", [
        {"timestamp": None, "price": 1.0, "amount": 1.0, "side": "sell"}
    ])
    warm = await service.get_recent_trades("binance", "BTC/USDT", 10)
    assert warm["source"] == "websocket"


async def test_orderbook_spread(service):
    ob = await service.get_orderbook("binance", "BTC/USDT", 5)
    assert ob["source"] == "rest"
    assert ob["spread"] == pytest.approx(2.0)
    assert len(ob["bids"]) == 5


async def test_compute_indicators_via_service(service):
    out = await service.compute_indicators(
        "binance", "BTC/USDT", "1h", 200, ["rsi:14", "ema:20"], False
    )
    assert "rsi_14" in out["results"]
    assert "ema_20" in out["results"]


async def test_screen_market_concurrency_and_errors(service):
    out = await service.screen_market(
        "binance", ["BTC/USDT", "ETH/USDT"], "USDT", 30, "1h",
        [{"metric": "change_24h_pct", "op": ">", "value": 5}], "volume_24h",
    )
    # Only ETH has change > 5 in the fake tickers.
    matched_symbols = {m["symbol"] for m in out["matched"]}
    assert "ETH/USDT" in matched_symbols
    assert "BTC/USDT" not in matched_symbols


async def test_screen_market_uses_bulk_tickers_not_n_plus_1(service, fake_exchange):
    # A metric screen over N symbols must issue ONE bulk fetch_tickers, never
    # one fetch_ticker per symbol (which would burn the exchange rate limit).
    out = await service.screen_market(
        "binance", ["BTC/USDT", "ETH/USDT"], "USDT", 30, "1h",
        [{"metric": "change_24h_pct", "op": ">", "value": 5}], "volume_24h",
    )
    assert {m["symbol"] for m in out["matched"]} == {"ETH/USDT"}
    assert fake_exchange.calls.get("fetch_tickers", 0) == 1
    assert fake_exchange.calls.get("fetch_ticker", 0) == 0  # no per-symbol storm


async def test_ohlcv_l1_cache_skips_store_on_repeat(service, fake_exchange):
    # The in-memory L1 cache should serve a repeated recent-candles request
    # without touching DuckDB (store.query) or the exchange again.
    calls = {"query": 0}
    original_query = service.store.query

    def counting_query(*args, **kwargs):
        calls["query"] += 1
        return original_query(*args, **kwargs)

    service.store.query = counting_query  # type: ignore[assignment]

    await service.compute_indicators("binance", "BTC/USDT", "1h", 100, ["rsi:14"], False)
    fetches_after_first = fake_exchange.calls.get("fetch_ohlcv", 0)
    queries_after_first = calls["query"]

    await service.compute_indicators("binance", "BTC/USDT", "1h", 100, ["rsi:14"], False)
    # Second call is an L1 hit: no extra REST fetch and no extra DuckDB query.
    assert fake_exchange.calls.get("fetch_ohlcv", 0) == fetches_after_first
    assert calls["query"] == queries_after_first


async def test_screen_market_invalid_op_raises():
    from tickfeed.core.service import MarketDataService
    from tickfeed.utils import TickFeedError

    with pytest.raises(TickFeedError):
        MarketDataService._validate_filters([{"indicator": "rsi:14", "op": "<<", "value": 30}])
    with pytest.raises(TickFeedError):
        MarketDataService._validate_filters([{"op": "<", "value": 30}])  # no indicator/metric
    with pytest.raises(TickFeedError):
        MarketDataService._validate_filters([])  # empty


async def test_long_period_indicator_warms_up_with_small_limit(service):
    # ema:200 with a tiny limit must still produce a value (auto-warmup).
    out = await service.compute_indicators(
        "binance", "BTC/USDT", "1h", 20, ["ema:200", "sma:200"], False
    )
    assert out["results"]["ema_200"]["value"] is not None
    assert out["results"]["sma_200"]["value"] is not None


async def test_funding_rate(service):
    out = await service.get_funding_rate("binance", "BTC/USDT")
    assert out["funding_rate"] == pytest.approx(0.0001)


async def test_server_status(service):
    status = service.server_status()
    assert status["exchanges"] == ["binance"]
    assert "ccxt_version" in status
