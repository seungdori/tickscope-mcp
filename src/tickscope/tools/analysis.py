"""Analysis tools: divergence detection, Pine-style cross, multi-exchange price."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_service
from ._guard import guard


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @guard()
    async def detect_divergence(
        symbol: str,
        exchange: str | None = None,
        timeframe: str = "1h",
        oscillator: str = "rsi:14",
        limit: int = 200,
        left: int = 5,
        right: int = 5,
    ) -> dict[str, Any]:
        """Detect regular/hidden bullish & bearish divergence between price and
        an oscillator.

        Compares the two most recent confirmed pivot highs (for bearish) and
        pivot lows (for bullish). ``oscillator`` is any indicator spec
        (``rsi:14``, ``macd:12,26,9``, ``cci:20``, ``mfi:14``, …). ``left`` and
        ``right`` set the pivot confirmation window. Returns the detected
        divergences with their pivot price/oscillator values and bar offsets.
        """
        return await get_service().detect_divergence(
            exchange, symbol, timeframe, limit, oscillator, left, right
        )

    @mcp.tool()
    @guard()
    async def detect_cross(
        symbol: str,
        series_a: str,
        series_b: str,
        exchange: str | None = None,
        timeframe: str = "1h",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Pine-style crossover analysis (``ta.crossover``/``ta.crossunder``).

        ``series_a`` and ``series_b`` are each an indicator spec (``ema:20``,
        ``ta.sma(50)``), a price source (``close``, ``hl2``, …) or a numeric
        constant (``"30"``). Example: a golden cross is
        ``series_a="ema:50", series_b="ema:200"``. Returns the latest values,
        their relation, whether a cross happened on the last bar, and how many
        bars since the last cross.
        """
        return await get_service().evaluate_cross(
            exchange, symbol, timeframe, limit, series_a, series_b
        )

    @mcp.tool()
    @guard()
    async def detect_patterns(
        symbol: str,
        exchange: str | None = None,
        timeframe: str = "1h",
        lookback: int = 10,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Detect candlestick patterns on the most recent ``lookback`` candles.

        Recognizes doji (incl. dragonfly/gravestone), hammer/hanging man,
        inverted hammer/shooting star, marubozu, spinning top, bullish/bearish
        engulfing & harami, piercing line, dark cloud cover, tweezers, morning/
        evening star, and three white soldiers/black crows. Each result carries
        its conventional ``bias`` (bullish/bearish/neutral) and ``bars_ago``.
        """
        return await get_service().detect_patterns(
            exchange, symbol, timeframe, limit, lookback
        )

    @mcp.tool()
    @guard()
    async def analyze_structure(
        symbol: str,
        exchange: str | None = None,
        timeframe: str = "1h",
        left: int = 3,
        right: int = 3,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Analyze market structure: swing highs/lows, trend, BOS / CHoCH.

        Builds an alternating swing sequence from confirmed pivots, labels each
        as HH/HL/LH/LL, infers ``trend`` (uptrend/downtrend/range), and reports
        whether the latest bar broke the most recent swing as a Break of
        Structure (continuation) or Change of Character (reversal). ``left``/
        ``right`` set the pivot confirmation window.
        """
        return await get_service().analyze_structure(
            exchange, symbol, timeframe, limit, left, right
        )

    @mcp.tool()
    @guard()
    async def find_support_resistance(
        symbol: str,
        exchange: str | None = None,
        timeframe: str = "1h",
        tolerance_pct: float = 0.5,
        max_levels: int = 6,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Find clustered support/resistance zones from swing pivots.

        Groups pivot highs/lows that lie within ``tolerance_pct`` of each other
        into zones; each zone's ``touches`` is its strength. Returns the nearest
        ``support`` (below price) and ``resistance`` (above price) zones with
        their distance from the current price.
        """
        return await get_service().find_support_resistance(
            exchange, symbol, timeframe, limit, tolerance_pct, max_levels
        )

    @mcp.tool()
    @guard()
    async def get_aggregated_price(
        symbol: str, exchanges: list[str] | None = None
    ) -> dict[str, Any]:
        """Aggregate a symbol's price across multiple exchanges (arbitrage view).

        Fetches the ticker on each configured (or given) exchange concurrently
        and returns the 24h-volume-weighted average price, the simple mean, the
        cheapest/most-expensive venue, and the cross-exchange spread
        (``arb_spread`` / ``arb_spread_pct``) — the foundation for spotting
        arbitrage. Venues that fail or lack the symbol are skipped.
        """
        return await get_service().get_aggregated_price(symbol, exchanges)
