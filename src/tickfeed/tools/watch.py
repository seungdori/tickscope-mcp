"""Watch-management tools: watch_symbol, get_watched_symbols."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_service
from ._guard import guard


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @guard()
    async def watch_symbol(
        symbol: str,
        exchange: str | None = None,
        channels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Pre-warm a live WebSocket subscription for a symbol (optional).

        Most tools auto-watch on first use, so this is only needed to warm a
        buffer ahead of time. ``channels`` defaults to ``["ticker","trades"]``;
        valid channels are ticker, trades, orderbook, and ohlcv. For ohlcv,
        suffix the timeframe so the forming candle overlays your ``get_ohlcv``
        queries on that timeframe — e.g. ``"ohlcv:1h"`` to enrich 1h candles
        (a bare ``"ohlcv"`` defaults to 1m and only overlays 1m queries). When
        the watch cap is exceeded, the least-recently-used symbol is released.
        """
        return await get_service().watch_symbol(
            exchange, symbol, channels or ["ticker", "trades"]
        )

    @mcp.tool()
    @guard()
    async def get_watched_symbols() -> dict[str, Any]:
        """List currently active WebSocket subscriptions and their buffer state
        (diagnostic): channels, buffer size, last update and staleness."""
        return get_service().get_watched_symbols()
