"""FastMCP app: build the server, register tools, manage lifespan."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from . import prompts, resources
from .config import get_settings
from .runtime import get_service, shutdown_service
from .tools import register_all
from .utils import DISCLAIMER


def _make_lifespan(teardown_on_exit: bool):
    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
        """Initialize the shared service on startup, tear it down on shutdown.

        Over HTTP the FastMCP lifespan runs *per connection*, so tearing the
        process-wide singleton down here would kill the background ingestion
        other live sessions depend on. We therefore only tear down under stdio
        (where the lifespan brackets the whole process); HTTP relies on process
        exit to release resources.
        """
        get_service()  # eagerly create the process-wide singleton
        try:
            yield
        finally:
            if teardown_on_exit:
                await shutdown_service()

    return lifespan


def build_server() -> FastMCP:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mcp = FastMCP(
        "Tickscope",
        instructions=(
            "Real-time and historical crypto market data via MCP. "
            "Use get_ticker for current prices, get_ohlcv for candles, "
            "compute_indicators for technical analysis, detect_divergence and "
            "detect_cross for chart signals, and screen_market to scan many "
            "symbols. For a thorough, multi-timeframe judgement (trend confluence, "
            "market-state context and historical signal performance) use deep_analyze. "
            "Responses include source/age_ms freshness. " + DISCLAIMER
        ),
        lifespan=_make_lifespan(teardown_on_exit=settings.transport != "http"),
        host=settings.http_host,
        port=settings.http_port,
    )
    register_all(mcp)
    resources.register(mcp)
    prompts.register(mcp)
    return mcp
