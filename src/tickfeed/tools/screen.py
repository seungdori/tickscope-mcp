"""Multi-symbol screening tool: screen_market."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_service
from ._guard import guard


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @guard()
    async def screen_market(
        filters: list[dict[str, Any]],
        exchange: str | None = None,
        symbols: list[str] | None = None,
        quote: str = "USDT",
        top_n: int = 30,
        timeframe: str = "1h",
        sort_by: str = "volume_24h",
    ) -> dict[str, Any]:
        """Screen many symbols by indicator and price conditions.

        ``filters`` is a list of conditions, each either indicator- or
        metric-based, e.g.
        ``[{"indicator":"rsi:14","op":"<","value":30},
        {"metric":"change_24h_pct","op":">","value":5}]``.
        ``op`` is one of ``< <= > >= == !=``.

        When ``symbols`` is omitted, the top ``top_n`` symbols by 24h volume for
        the given ``quote`` currency are screened. Runs with bounded concurrency
        to respect rate limits; per-symbol failures are returned in ``errors``.
        """
        return await get_service().screen_market(
            exchange, symbols, quote, top_n, timeframe, filters, sort_by
        )
