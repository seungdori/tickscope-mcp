"""Technical-indicator tool: compute_indicators."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_service
from ._guard import guard


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @guard()
    async def compute_indicators(
        symbol: str,
        indicators: list[str],
        exchange: str | None = None,
        timeframe: str = "1h",
        limit: int = 200,
        include_series: bool = False,
    ) -> dict[str, Any]:
        """Compute technical indicators for a symbol/timeframe.

        ``indicators`` is a list of specs ``"name:param1,param2"``, e.g.
        ``["rsi:14", "macd:12,26,9", "ema:20", "bbands:20,2", "supertrend:10,3",
        "stochrsi", "ichimoku"]``. Pine-style aliases like ``"ta.rsi(14)"`` and
        ``"ta.ema(20)"`` are also accepted.

        Supported (73):
        - MAs/overlays: sma, ema, wma, smma, dema, tema, hma, vwma, zlema, alma,
          kama, trima, lsma, vidya, t3, vwap, vwapbands, bbands, donchian,
          keltner, supertrend, ichimoku, psar
        - Momentum: rsi, stochrsi, macd, ppo, stoch, cci, willr, roc, mom, tsi,
          ao, cmo, uo, dpo, trix, coppock, kst, fisher, rvi, mfi, wavetrend,
          squeeze, qqe, crsi, stc, elderray, zscore, linregslope
        - Volatility: atr, natr, stdev, hv, chop, ulcer, massindex
        - Volume: obv, adl, cmf, chaikinosc, eom, fi, pvt, vo, klinger
        - Trend: adx, dmi, aroon, vortex
        - Structure: heikinashi, pivots

        Returns each indicator's latest value(s) plus derived signals: RSI/MFI/
        StochRSI/UO/CRSI/STC overbought-oversold ``state``; MACD/PPO/WaveTrend/
        QQE ``cross``; zero-line ``cross`` for oscillators (ao/tsi/cmo/trix/
        roc/mom/zscore); ``supertrend``/``psar`` ``direction`` & ``flip``;
        ``squeeze`` on/off; ``dmi``/``heikinashi`` trend; ``ichimoku`` cloud
        ``signal``. Set ``include_series=true`` for each indicator's primary
        time series. Pine aliases include ``ta.wt``, ``ta.sqz``, ``ta.ha``.
        """
        return await get_service().compute_indicators(
            exchange, symbol, timeframe, limit, indicators, include_series
        )
