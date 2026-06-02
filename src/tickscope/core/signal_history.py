"""Historical signal performance (★3) — an event study on this symbol.

For every *past* occurrence of a signal, measure what price did next. This
turns "there's a bullish divergence" into evidence: "the last 18 confirmed
bullish RSI divergences on this symbol/timeframe returned a median +1.9% over
the next 10 bars, 61% positive, worst −4.2%."

Strictly causal — there is no look-ahead / repaint:

* A divergence is counted only at the bar where its confirming pivot has fully
  formed (``index = pivot + right``); that is the first bar an agent could have
  acted on it.
* The forward window uses only bars *after* that confirmation bar, and
  occurrences too recent to have a full ``horizon`` ahead are dropped.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from . import indicators_engine as ie
from .analysis import pivot_indices


def _forward_stats(close: np.ndarray, indices: list[int], horizon: int) -> dict[str, Any]:
    """Forward-return distribution (in %) ``horizon`` bars after each index."""
    rets: list[float] = []
    n = len(close)
    for i in indices:
        j = i + horizon
        if j < n and close[i] > 0 and np.isfinite(close[i]) and np.isfinite(close[j]):
            rets.append(close[j] / close[i] - 1.0)
    if not rets:
        return {"count": 0}
    a = np.asarray(rets, dtype=float) * 100.0
    return {
        "count": int(a.size),
        "median_pct": round(float(np.median(a)), 3),
        "mean_pct": round(float(a.mean()), 3),
        "win_rate_pct": round(float((a > 0).mean() * 100.0), 1),
        "p25_pct": round(float(np.percentile(a, 25)), 3),
        "p75_pct": round(float(np.percentile(a, 75)), 3),
        "worst_pct": round(float(a.min()), 3),
        "best_pct": round(float(a.max()), 3),
    }


def divergence_performance(
    df: pd.DataFrame,
    oscillator: str = "rsi:14",
    *,
    left: int = 5,
    right: int = 5,
    horizon: int = 10,
) -> dict[str, Any]:
    """Forward-return distribution after every past *confirmed* regular divergence.

    Bullish: a lower pivot low in price while the oscillator makes a higher low.
    Bearish: a higher pivot high in price while the oscillator makes a lower high.
    Consecutive confirmed pivots are compared, matching how the live
    :func:`analysis.detect_divergence` reads the most recent pair.
    """
    n = len(df)
    osc = ie.series_for(df, oscillator).to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    bullish_idx: list[int] = []
    lows = pivot_indices(low, left, right, high=False)
    for p1, p2 in pairwise(lows):
        if np.isnan(osc[p1]) or np.isnan(osc[p2]):
            continue
        if low[p2] < low[p1] and osc[p2] > osc[p1]:  # regular bullish
            bullish_idx.append(p2 + right)  # actionable only once confirmed

    bearish_idx: list[int] = []
    highs = pivot_indices(high, left, right, high=True)
    for p1, p2 in pairwise(highs):
        if np.isnan(osc[p1]) or np.isnan(osc[p2]):
            continue
        if high[p2] > high[p1] and osc[p2] < osc[p1]:  # regular bearish
            bearish_idx.append(p2 + right)

    return {
        "signal": f"divergence({oscillator})",
        "horizon_bars": horizon,
        "history_bars": n,
        "pivots": {"left": left, "right": right},
        "bullish": _forward_stats(close, bullish_idx, horizon),
        "bearish": _forward_stats(close, bearish_idx, horizon),
        "note": (
            "Forward return measured from the bar each divergence was confirmed "
            "(no look-ahead). Descriptive history, not a prediction."
        ),
    }
