"""In-memory hot caches: ring buffers for trades, latest ticker/orderbook.

These hold the freshest WebSocket data so tool calls answer from a warm buffer
in well under a second instead of issuing a cold REST request.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

# Cap on distinct (exchange, symbol, timeframe) candle series kept hot in RAM.
# Each entry is at most ~1000 rows; 256 series is a few MB and covers far more
# symbols than the watch cap, while bounding memory for wide screens.
_MAX_OHLCV_SERIES = 256


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class CachedValue:
    """A payload plus the wall-clock time it was last updated."""

    data: Any
    updated_ms: int = field(default_factory=_now_ms)

    @property
    def age_ms(self) -> int:
        return max(_now_ms() - self.updated_ms, 0)


class RingBuffer:
    """Fixed-size FIFO buffer keeping the most recent ``maxlen`` items."""

    def __init__(self, maxlen: int):
        self._items: deque[Any] = deque(maxlen=maxlen)
        self.updated_ms: int = 0

    def extend(self, items: list[Any]) -> None:
        if not items:
            return
        self._items.extend(items)
        self.updated_ms = _now_ms()

    def latest(self, limit: int) -> list[Any]:
        if limit <= 0:
            return []
        data = list(self._items)
        return data[-limit:]

    def __len__(self) -> int:
        return len(self._items)

    @property
    def age_ms(self) -> int:
        return max(_now_ms() - self.updated_ms, 0) if self.updated_ms else 0


class MarketCache:
    """Per (exchange, symbol) hot storage for tickers, trades and orderbooks."""

    def __init__(self, ring_buffer_size: int):
        self._ring_buffer_size = ring_buffer_size
        self.tickers: dict[tuple[str, str], CachedValue] = {}
        self.orderbooks: dict[tuple[str, str], CachedValue] = {}
        self.trades: dict[tuple[str, str], RingBuffer] = {}
        # Live (forming) candle per (exchange, symbol, timeframe), fed by
        # the ccxt.pro watch_ohlcv loop. Value is the latest [ts,o,h,l,c,v].
        self.live_candles: dict[tuple[str, str, str], CachedValue] = {}
        # L1 hot cache of recently-fetched closed candles per
        # (exchange, symbol, timeframe) -> (rows, fetched_ms). Lets repeated
        # indicator/structure calls within the TTL skip both DuckDB and the
        # exchange entirely. LRU-bounded by _MAX_OHLCV_SERIES.
        self.recent_ohlcv: OrderedDict[tuple[str, str, str], tuple[list[list[float]], int]] = (
            OrderedDict()
        )

    @staticmethod
    def _key(exchange: str, symbol: str) -> tuple[str, str]:
        return (exchange.lower(), symbol.upper())

    # ticker -------------------------------------------------------------
    def set_ticker(self, exchange: str, symbol: str, data: Any) -> None:
        self.tickers[self._key(exchange, symbol)] = CachedValue(data)

    def get_ticker(self, exchange: str, symbol: str) -> CachedValue | None:
        return self.tickers.get(self._key(exchange, symbol))

    # orderbook ----------------------------------------------------------
    def set_orderbook(self, exchange: str, symbol: str, data: Any) -> None:
        self.orderbooks[self._key(exchange, symbol)] = CachedValue(data)

    def get_orderbook(self, exchange: str, symbol: str) -> CachedValue | None:
        return self.orderbooks.get(self._key(exchange, symbol))

    # trades -------------------------------------------------------------
    def append_trades(self, exchange: str, symbol: str, items: list[Any]) -> None:
        buf = self.trades.get(self._key(exchange, symbol))
        if buf is None:
            buf = RingBuffer(self._ring_buffer_size)
            self.trades[self._key(exchange, symbol)] = buf
        buf.extend(items)

    def get_trades(self, exchange: str, symbol: str) -> RingBuffer | None:
        return self.trades.get(self._key(exchange, symbol))

    # live OHLCV candle -------------------------------------------------
    def set_live_candle(self, exchange: str, symbol: str, timeframe: str, candle: Any) -> None:
        key = (exchange.lower(), symbol.upper(), timeframe)
        self.live_candles[key] = CachedValue(candle)

    def get_live_candle(
        self, exchange: str, symbol: str, timeframe: str
    ) -> CachedValue | None:
        return self.live_candles.get((exchange.lower(), symbol.upper(), timeframe))

    # recent closed candles (L1) ----------------------------------------
    def get_recent_ohlcv(
        self, exchange: str, symbol: str, timeframe: str
    ) -> tuple[list[list[float]], int] | None:
        """Return ``(rows, fetched_ms)`` for a hot candle series, or ``None``."""
        key = (exchange.lower(), symbol.upper(), timeframe)
        entry = self.recent_ohlcv.get(key)
        if entry is not None:
            self.recent_ohlcv.move_to_end(key)  # LRU touch
        return entry

    def set_recent_ohlcv(
        self, exchange: str, symbol: str, timeframe: str, rows: list[list[float]], fetched_ms: int
    ) -> None:
        key = (exchange.lower(), symbol.upper(), timeframe)
        self.recent_ohlcv[key] = (rows, fetched_ms)
        self.recent_ohlcv.move_to_end(key)
        while len(self.recent_ohlcv) > _MAX_OHLCV_SERIES:
            self.recent_ohlcv.popitem(last=False)
