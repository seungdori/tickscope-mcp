"""MCP tool registration. Each module exposes ``register(mcp)``."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import analysis, indicators, market, meta, screen, watch


def register_all(mcp: FastMCP) -> None:
    """Register every TickFeed tool onto the FastMCP app."""
    meta.register(mcp)
    market.register(mcp)
    indicators.register(mcp)
    screen.register(mcp)
    watch.register(mcp)
    analysis.register(mcp)
