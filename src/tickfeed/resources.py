"""MCP resources exposing live server state (spec §2.4, §15).

Resources let supporting clients read watched-symbol state and warm tickers as
addressable URIs (and, where the client supports it, subscribe to updates).
Tools remain the primary interface; resources are an additive enhancement.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .runtime import get_service
from .utils import error_payload


def _dump(payload: Any) -> str:
    return json.dumps(payload, default=str)


def register(mcp: FastMCP) -> None:
    @mcp.resource(
        "tickfeed://status",
        name="server_status",
        description="TickFeed health and diagnostics snapshot.",
        mime_type="application/json",
    )
    def status() -> str:
        try:
            return _dump(get_service().server_status())
        except Exception as exc:  # noqa: BLE001 - return the structured envelope
            return _dump(error_payload(exc))

    @mcp.resource(
        "tickfeed://watched",
        name="watched_symbols",
        description="Currently watched symbols with buffer state and staleness.",
        mime_type="application/json",
    )
    def watched() -> str:
        try:
            return _dump(get_service().get_watched_symbols())
        except Exception as exc:  # noqa: BLE001 - return the structured envelope
            return _dump(error_payload(exc))

    @mcp.resource(
        "tickfeed://ticker/{exchange}/{symbol}",
        name="ticker",
        description=(
            "Latest ticker snapshot for an exchange/symbol "
            "(symbol may be compact, e.g. BTCUSDT). Includes source/age_ms."
        ),
        mime_type="application/json",
    )
    async def ticker(exchange: str, symbol: str) -> str:
        try:
            return _dump(await get_service().get_ticker(exchange, symbol))
        except Exception as exc:  # noqa: BLE001 - return the structured envelope
            return _dump(error_payload(exc, exchange=exchange, symbol=symbol))
