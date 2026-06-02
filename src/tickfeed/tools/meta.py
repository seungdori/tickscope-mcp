"""Meta / diagnostic tools: list_exchanges, list_symbols, server_status."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_service
from ._guard import guard


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @guard()
    async def list_exchanges() -> dict[str, Any]:
        """List the exchanges this server is configured to use.

        Returns the configured exchange ids and the default one used when a
        tool call omits the ``exchange`` argument.
        """
        return get_service().list_exchanges()

    @mcp.tool()
    @guard()
    async def list_symbols(
        exchange: str | None = None,
        quote: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List tradable symbols on an exchange, optionally filtered.

        Use to discover valid symbols before other calls. ``quote`` filters by
        quote currency (e.g. ``USDT``); ``search`` is a case-insensitive
        substring match (e.g. ``BTC``).
        """
        return await get_service().list_symbols(exchange, quote, search, limit)

    @mcp.tool()
    @guard()
    async def server_status() -> dict[str, Any]:
        """Health and diagnostics: uptime, exchanges, watch count, cache rows,
        ccxt version, and WebSocket reconnect count."""
        return get_service().server_status()
