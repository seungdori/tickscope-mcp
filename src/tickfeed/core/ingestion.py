"""Background WebSocket ingestion via ccxt.pro ``watch_*`` loops.

Each (exchange, symbol, channel) runs an asyncio task that streams updates into
the hot :class:`MarketCache`. Loops reconnect with exponential backoff and the
manager enforces an LRU cap on the number of watched symbols.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any

from .cache import MarketCache
from .exchange_manager import ExchangeManager

logger = logging.getLogger("tickfeed.ingestion")

DEFAULT_CHANNELS = ("ticker", "trades")
_BACKOFF_CAP_S = 30.0


class IngestionManager:
    """Owns background watch tasks and the warm cache they feed."""

    def __init__(
        self,
        exchanges: ExchangeManager,
        cache: MarketCache,
        *,
        max_watched: int = 25,
    ):
        self._exchanges = exchanges
        self._cache = cache
        self._max_watched = max_watched
        # key -> {"task", "channels", "last_used"}; OrderedDict for LRU.
        self._watched: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._lock = asyncio.Lock()
        self.ws_reconnects = 0

    @staticmethod
    def _key(exchange: str, symbol: str) -> tuple[str, str]:
        return (exchange.lower(), symbol.upper())

    def is_watching(self, exchange: str, symbol: str) -> bool:
        return self._key(exchange, symbol) in self._watched

    def touch(self, exchange: str, symbol: str) -> None:
        """Mark a watched symbol as recently used (LRU bookkeeping)."""
        key = self._key(exchange, symbol)
        if key in self._watched:
            self._watched[key]["last_used"] = time.time()
            self._watched.move_to_end(key)

    async def ensure_watch(
        self, exchange: str, symbol: str, channels: tuple[str, ...] = DEFAULT_CHANNELS
    ) -> list[str]:
        """Start watching ``symbol`` if not already; returns active channels."""
        key = self._key(exchange, symbol)
        async with self._lock:
            existing = self._watched.get(key)
            if existing is not None:
                existing["last_used"] = time.time()
                self._watched.move_to_end(key)
                return list(existing["channels"])

            await self._evict_if_needed()

            inst = await self._exchanges.get(exchange)
            tasks = []
            active: list[str] = []
            for channel in channels:
                if not self._supports(inst, channel):
                    continue
                task = asyncio.create_task(
                    self._run_loop(exchange, symbol, channel),
                    name=f"watch:{exchange}:{symbol}:{channel}",
                )
                tasks.append(task)
                active.append(channel)
            self._watched[key] = {
                "tasks": tasks,
                "channels": active,
                "last_used": time.time(),
            }
            return active

    @staticmethod
    def _base_channel(channel: str) -> str:
        """``"ohlcv:5m"`` -> ``"ohlcv"``; plain channels pass through."""
        return channel.split(":", 1)[0].strip().lower()

    @staticmethod
    def _channel_timeframe(channel: str, default: str = "1m") -> str:
        """Extract the timeframe suffix of an ``"ohlcv:<tf>"`` channel."""
        _, _, tf = channel.partition(":")
        return tf.strip() or default

    @classmethod
    def _supports(cls, inst: Any, channel: str) -> bool:
        has = getattr(inst, "has", {}) or {}
        return bool(
            has.get(
                {
                    "ticker": "watchTicker",
                    "trades": "watchTrades",
                    "orderbook": "watchOrderBook",
                    "ohlcv": "watchOHLCV",
                }.get(cls._base_channel(channel), "")
            )
        )

    async def _evict_if_needed(self) -> None:
        while len(self._watched) >= self._max_watched and self._watched:
            old_key, entry = self._watched.popitem(last=False)
            for task in entry["tasks"]:
                task.cancel()
            logger.info("LRU evicted watch for %s", old_key)

    async def _run_loop(self, exchange: str, symbol: str, channel: str) -> None:
        backoff = 1.0
        base = self._base_channel(channel)
        inst = await self._exchanges.get(exchange)
        while True:
            try:
                if base == "ticker":
                    data = await inst.watch_ticker(symbol)
                    self._cache.set_ticker(exchange, symbol, data)
                elif base == "trades":
                    data = await inst.watch_trades(symbol)
                    self._cache.append_trades(exchange, symbol, data)
                elif base == "orderbook":
                    data = await inst.watch_order_book(symbol)
                    self._cache.set_orderbook(exchange, symbol, data)
                elif base == "ohlcv":
                    timeframe = self._channel_timeframe(channel)
                    candles = await inst.watch_ohlcv(symbol, timeframe)
                    if candles:
                        # The last element is the freshest (forming) candle.
                        self._cache.set_live_candle(exchange, symbol, timeframe, candles[-1])
                else:
                    return
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - resilient ingestion loop
                self.ws_reconnects += 1
                logger.warning(
                    "watch %s/%s/%s error: %s (reconnect in %.1fs)",
                    exchange,
                    symbol,
                    channel,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_CAP_S)

    def watched_info(self) -> list[dict[str, Any]]:
        """Diagnostic snapshot of currently watched symbols."""
        out: list[dict[str, Any]] = []
        for (exchange, symbol), entry in self._watched.items():
            trades = self._cache.get_trades(exchange, symbol)
            ticker = self._cache.get_ticker(exchange, symbol)
            buffer_size = len(trades) if trades else 0
            staleness = None
            last_update = None
            if ticker is not None:
                staleness = ticker.age_ms
                last_update = ticker.updated_ms
            elif trades is not None and trades.updated_ms:
                staleness = trades.age_ms
                last_update = trades.updated_ms
            out.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "channels": entry["channels"],
                    "buffer_size": buffer_size,
                    "last_update_ms": last_update,
                    "staleness_ms": staleness,
                }
            )
        return out

    @property
    def watched_count(self) -> int:
        return len(self._watched)

    async def stop(self) -> None:
        """Cancel all watch tasks (call on shutdown)."""
        for entry in self._watched.values():
            for task in entry["tasks"]:
                task.cancel()
        all_tasks = [t for e in self._watched.values() for t in e["tasks"]]
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._watched.clear()
