"""IngestionManager: watch startup, cache population, channel support, LRU, resilience."""

from __future__ import annotations

import asyncio

import ccxt
import pytest

from tickfeed.core.cache import MarketCache
from tickfeed.core.exchange_manager import ExchangeManager
from tickfeed.core.ingestion import IngestionManager

pytestmark = pytest.mark.asyncio


class WatchFake:
    """ccxt.pro-ish stub: watch_ticker yields one update then blocks; the other
    channels block immediately so the watch loops never busy-spin."""

    def __init__(self, *, support=("watchTicker", "watchTrades")):
        self.has = dict.fromkeys(support, True)
        self.markets = {
            "BTC/USDT": {"symbol": "BTC/USDT", "quote": "USDT", "base": "BTC", "spot": True}
        }
        self.ticker_calls = 0
        self.fail_once = False
        self._failed = False
        self._block = asyncio.Event()

    async def watch_ticker(self, symbol):
        self.ticker_calls += 1
        if self.fail_once and not self._failed:
            self._failed = True
            raise ccxt.NetworkError("transient")
        if self.ticker_calls <= 2:
            return {"last": 100.0, "bid": 99.0, "ask": 101.0, "timestamp": 1}
        await self._block.wait()
        return {}

    async def watch_trades(self, symbol):
        await self._block.wait()
        return []

    async def watch_order_book(self, symbol):
        await self._block.wait()
        return {}

    async def watch_ohlcv(self, symbol, timeframe="1m"):
        await self._block.wait()
        return []

    async def close(self):
        self._block.set()


def _manager(fake, *, max_watched=25):
    exmgr = ExchangeManager(["binance"])

    async def _get(_exchange_id):
        return fake

    exmgr.get = _get  # type: ignore[assignment]
    cache = MarketCache(100)
    return IngestionManager(exmgr, cache, max_watched=max_watched), cache


async def _wait_until(predicate, *, tries=300) -> bool:
    for _ in range(tries):
        if predicate():
            return True
        await asyncio.sleep(0)
    return False


async def test_ensure_watch_starts_channels_and_populates_cache():
    fake = WatchFake()
    mgr, cache = _manager(fake)
    active = await mgr.ensure_watch("binance", "BTC/USDT", ("ticker", "trades"))
    assert set(active) == {"ticker", "trades"}
    assert mgr.is_watching("binance", "BTC/USDT")
    populated = await _wait_until(lambda: cache.get_ticker("binance", "BTC/USDT") is not None)
    await mgr.stop()
    assert populated
    ticker = cache.get_ticker("binance", "BTC/USDT")
    assert ticker is not None and ticker.data["last"] == 100.0


async def test_ensure_watch_skips_unsupported_channels():
    fake = WatchFake(support=("watchTicker",))  # trades/orderbook/ohlcv unsupported
    mgr, _ = _manager(fake)
    active = await mgr.ensure_watch("binance", "BTC/USDT", ("orderbook", "ohlcv:5m"))
    await mgr.stop()
    assert active == []


async def test_lru_evicts_oldest_when_over_cap():
    fake = WatchFake()
    mgr, _ = _manager(fake, max_watched=2)
    await mgr.ensure_watch("binance", "AAA/USDT", ("ticker",))
    await mgr.ensure_watch("binance", "BBB/USDT", ("ticker",))
    await mgr.ensure_watch("binance", "CCC/USDT", ("ticker",))  # evicts AAA
    assert mgr.watched_count == 2
    assert not mgr.is_watching("binance", "AAA/USDT")
    assert mgr.is_watching("binance", "BBB/USDT")
    assert mgr.is_watching("binance", "CCC/USDT")
    await mgr.stop()


async def test_touch_protects_recently_used_from_eviction():
    fake = WatchFake()
    mgr, _ = _manager(fake, max_watched=2)
    await mgr.ensure_watch("binance", "AAA/USDT", ("ticker",))
    await mgr.ensure_watch("binance", "BBB/USDT", ("ticker",))
    mgr.touch("binance", "AAA/USDT")  # AAA becomes most-recently-used
    await mgr.ensure_watch("binance", "CCC/USDT", ("ticker",))  # should evict BBB
    assert mgr.is_watching("binance", "AAA/USDT")
    assert not mgr.is_watching("binance", "BBB/USDT")
    await mgr.stop()


async def test_watch_loop_reconnects_after_transient_error(monkeypatch):
    # Make the loop's backoff sleeps instant (but still yield control).
    real_sleep = asyncio.sleep

    async def fast_sleep(_delay=0, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr("tickfeed.core.ingestion.asyncio.sleep", fast_sleep)

    fake = WatchFake()
    fake.fail_once = True  # first watch_ticker raises, then it recovers
    mgr, cache = _manager(fake)
    await mgr.ensure_watch("binance", "BTC/USDT", ("ticker",))
    recovered = await _wait_until(lambda: cache.get_ticker("binance", "BTC/USDT") is not None)
    reconnects = mgr.ws_reconnects
    await mgr.stop()
    assert recovered  # populated the cache after recovering from the error
    assert reconnects >= 1  # the transient failure was counted
