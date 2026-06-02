"""Deep multi-timeframe analysis tool: deep_analyze."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_service
from ._guard import guard


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @guard()
    async def deep_analyze(
        symbol: str,
        exchange: str | None = None,
        timeframes: list[str] | None = None,
        oscillator: str = "rsi:14",
        horizon: int = 10,
    ) -> dict[str, Any]:
        """Thorough, evidence-backed read of one symbol across multiple timeframes.

        Returns, in a single call:
        - per-timeframe trend (HH/HL structure, BOS/CHoCH) and momentum,
        - statistical & market-state context (price percentile, ADX/efficiency
          trend state, ATR volatility state) so each value is interpretable,
        - the historical forward-return distribution of the current divergence
          signal on this symbol/timeframe — a strictly causal event study,
        - a synthesized verdict: bias, confidence, multi-timeframe agreement and
          explicit caveats.

        Prefer this over the lighter ``compute_indicators`` / ``analyze_structure``
        / ``detect_divergence`` when the user wants a thorough judgement, asks
        whether a setup is worth taking, or says "analyze X deeply". It is heavier
        (reads several timeframes + runs an event study), so use the single-shot
        tools for quick one-value questions.

        ``timeframes`` defaults to a 1d/4h/1h ladder (highest -> execution).
        Read-only public market data; not financial advice.
        """
        return await get_service().deep_analyze(
            exchange,
            symbol,
            timeframes=timeframes,
            oscillator=oscillator,
            horizon=horizon,
        )
