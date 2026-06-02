"""Market-data tools: ticker, recent trades, OHLCV, orderbook, funding rate."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_service
from ._guard import guard


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @guard()
    async def get_ticker(symbol: str, exchange: str | None = None) -> dict[str, Any]:
        """Get the current price snapshot for a symbol (the primary quote tool).

        Returns last/bid/ask, 24h high/low/volume, 24h change %, plus freshness
        fields ``source`` (websocket|rest), ``age_ms`` and ``timestamp``. The
        first (cold) call answers via REST and starts a live WebSocket watch, so
        subsequent calls return fresher websocket-sourced data.
        """
        return await get_service().get_ticker(exchange, symbol)

    @mcp.tool()
    @guard()
    async def get_recent_trades(
        symbol: str, exchange: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Get the most recent executed trades (ticks) from the live buffer.

        Falls back to a REST snapshot (and starts watching) when the buffer is
        cold. ``limit`` is capped at 1000.
        """
        return await get_service().get_recent_trades(exchange, symbol, limit)

    @mcp.tool()
    @guard()
    async def get_ohlcv(
        symbol: str,
        exchange: str | None = None,
        timeframe: str = "1h",
        limit: int = 200,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Get historical OHLCV candles (basis for charts and indicators).

        Served from a DuckDB cache first, topping up only the missing tail via
        REST. ``timeframe`` accepts values like ``1m,5m,15m,1h,4h,1d``;
        ``since`` accepts ISO-8601 or epoch-ms. ``limit`` is capped at 1000.
        """
        return await get_service().get_ohlcv(exchange, symbol, timeframe, limit, since)

    @mcp.tool()
    @guard()
    async def get_orderbook(
        symbol: str, exchange: str | None = None, depth: int = 20
    ) -> dict[str, Any]:
        """Get the current order book snapshot with computed spread.

        Returns top-``depth`` bids/asks (capped at 100), ``spread`` and
        ``spread_pct``, plus freshness fields. Uses the live WebSocket buffer
        when warm, otherwise REST.
        """
        return await get_service().get_orderbook(exchange, symbol, depth)

    @mcp.tool()
    @guard()
    async def get_funding_rate(symbol: str, exchange: str | None = None) -> dict[str, Any]:
        """Get the current (and predicted) funding rate for a perpetual future.

        Symbol should be a perpetual (e.g. ``BTC/USDT:USDT``). Returns a
        structured error if the exchange does not support funding rates.
        """
        return await get_service().get_funding_rate(exchange, symbol)
