"""Shared test fixtures: a fake ccxt exchange and an in-memory service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from tickscope.config import Settings
from tickscope.core.service import MarketDataService


class FakeExchange:
    """Minimal ccxt-compatible stub recording call counts (no network)."""

    def __init__(self, last_price: float = 67000.0) -> None:
        self.last_price = last_price
        self.markets = {
            "BTC/USDT": {"symbol": "BTC/USDT", "id": "BTCUSDT", "quote": "USDT", "base": "BTC", "spot": True},
            "ETH/USDT": {"symbol": "ETH/USDT", "id": "ETHUSDT", "quote": "USDT", "base": "ETH", "spot": True},
        }
        self.has = {
            "watchTicker": True,
            "watchTrades": True,
            "watchOrderBook": True,
            "watchOHLCV": True,
            "fetchFundingRate": True,
            "fetchTickers": True,
        }
        self.calls: dict[str, int] = {}

    def _count(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    async def load_markets(self, reload: bool = False) -> dict[str, Any]:
        self._count("load_markets")
        return self.markets

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        self._count("fetch_ticker")
        # ETH moves more than BTC so metric filters are testable.
        pct = 6.0 if symbol.startswith("ETH") else 1.5
        return {
            "last": self.last_price, "bid": self.last_price - 1, "ask": self.last_price + 1,
            "high": 68000.0, "low": 66000.0, "baseVolume": 1234.5,
            "percentage": pct, "timestamp": int(time.time() * 1000),
        }

    async def fetch_trades(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        self._count("fetch_trades")
        now = int(time.time() * 1000)
        return [
            {"timestamp": now, "price": 67000.0 + i, "amount": 0.01, "side": "buy"}
            for i in range(limit)
        ]

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        self._count("fetch_order_book")
        return {
            "bids": [[66999.0 - i, 1.0] for i in range(limit)],
            "asks": [[67001.0 + i, 1.0] for i in range(limit)],
            "timestamp": int(time.time() * 1000),
        }

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1h", since: int | None = None, limit: int = 200
    ) -> list[list[float]]:
        self._count("fetch_ohlcv")
        tf_ms = 3_600_000
        end = (int(time.time() * 1000) // tf_ms) * tf_ms
        rows = []
        for i in range(limit):
            ts = end - (limit - 1 - i) * tf_ms
            base = 67000.0 + i
            rows.append([ts, base, base + 50, base - 50, base + 10, 100.0 + i])
        return rows

    async def fetch_tickers(self) -> dict[str, Any]:
        self._count("fetch_tickers")
        return {
            "BTC/USDT": {"quoteVolume": 1_000_000, "percentage": 2.0, "baseVolume": 100, "last": 67000},
            "ETH/USDT": {"quoteVolume": 500_000, "percentage": 6.0, "baseVolume": 200, "last": 3500},
        }

    async def fetch_funding_rate(self, symbol: str) -> dict[str, Any]:
        self._count("fetch_funding_rate")
        now = int(time.time() * 1000)
        return {
            "fundingRate": 0.0001,
            "fundingTimestamp": now,
            "nextFundingTimestamp": now + 8 * 3_600_000,
            "markPrice": 67000.0, "indexPrice": 66990.0, "timestamp": now,
        }

    async def watch_ticker(self, symbol: str) -> dict[str, Any]:
        # Mimic a blocking websocket read so the watch loop does not busy-spin.
        await asyncio.sleep(3600)
        return await self.fetch_ticker(symbol)

    async def watch_trades(self, symbol: str) -> list[dict[str, Any]]:
        await asyncio.sleep(3600)
        return await self.fetch_trades(symbol)

    async def watch_order_book(self, symbol: str) -> dict[str, Any]:
        await asyncio.sleep(3600)
        return await self.fetch_order_book(symbol)

    async def watch_ohlcv(self, symbol: str, timeframe: str = "1m") -> list[list[float]]:
        await asyncio.sleep(3600)
        return []

    async def close(self) -> None:
        return None


@pytest.fixture()
def fake_exchange() -> FakeExchange:
    return FakeExchange()


@pytest_asyncio.fixture()
async def service(tmp_path, fake_exchange) -> AsyncIterator[MarketDataService]:
    settings = Settings(
        exchanges=["binance"],
        default_exchange="binance",
        ohlcv_cache_path=str(tmp_path / "test.duckdb"),
    )
    svc = MarketDataService(settings)

    async def _get(_exchange_id: str) -> FakeExchange:
        return fake_exchange

    async def _load(_exchange_id: str, reload: bool = False) -> dict[str, Any]:
        return fake_exchange.markets

    svc.exchanges.get = _get  # type: ignore[assignment]
    svc.exchanges.load_markets = _load  # type: ignore[assignment]
    try:
        yield svc
    finally:
        await svc.ingestion.stop()
        svc.store.close()


@pytest_asyncio.fixture()
async def multi_service(tmp_path) -> AsyncIterator[MarketDataService]:
    """Service backed by three fake exchanges with distinct prices."""
    settings = Settings(
        exchanges=["binance", "bybit", "okx"],
        default_exchange="binance",
        ohlcv_cache_path=str(tmp_path / "multi.duckdb"),
    )
    svc = MarketDataService(settings)
    prices = {"binance": 67000.0, "bybit": 67100.0, "okx": 66950.0}
    instances = {ex: FakeExchange(last_price=p) for ex, p in prices.items()}

    async def _get(exchange_id: str) -> FakeExchange:
        return instances[exchange_id.lower()]

    async def _load(exchange_id: str, reload: bool = False) -> dict[str, Any]:
        return instances[exchange_id.lower()].markets

    svc.exchanges.get = _get  # type: ignore[assignment]
    svc.exchanges.load_markets = _load  # type: ignore[assignment]
    try:
        yield svc
    finally:
        await svc.ingestion.stop()
        svc.store.close()
