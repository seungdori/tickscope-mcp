"""Higher-level chart analysis built on the indicator engine.

Adds two trader-facing primitives that go beyond raw indicator values:

* :func:`detect_divergence` — regular / hidden bullish & bearish divergence
  between price and an oscillator, via confirmed pivot highs/lows.
* :func:`evaluate_cross` — Pine ``ta.crossover``/``ta.crossunder`` between any
  two series (indicator specs, price sources or constants).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import indicators_engine as ie


def _pivot_indices(values: np.ndarray, left: int, right: int, *, high: bool) -> list[int]:
    """Indices of confirmed pivots (unique strict extrema in the window).

    The center bar must be strictly greater (for a pivot high) or strictly less
    (for a pivot low) than *every* bar in the ``left`` bars before and ``right``
    bars after it, and is only reported once those ``right`` bars have formed —
    matching Pine's ``ta.pivothigh``/``ta.pivotlow`` confirmation. Strict
    comparison on both sides rejects ties on flat tops/double bottoms so no
    spurious pivots leak into the divergence comparison.
    """
    out: list[int] = []
    n = len(values)
    for i in range(left, n - right):
        center = values[i]
        if np.isnan(center):
            continue
        before = values[i - left : i]
        after = values[i + 1 : i + right + 1]
        if np.isnan(before).any() or np.isnan(after).any():
            continue
        if high:
            if (center > before).all() and (center > after).all():
                out.append(i)
        else:
            if (center < before).all() and (center < after).all():
                out.append(i)
    return out


def detect_divergence(
    df: pd.DataFrame,
    oscillator: str = "rsi:14",
    *,
    left: int = 5,
    right: int = 5,
) -> dict[str, Any]:
    """Detect divergence between price and ``oscillator`` on the latest pivots.

    Compares the two most recent confirmed pivot highs (bearish) and pivot lows
    (bullish). Returns a list of detected divergences with the pivot values and
    bar offsets so an agent can explain *where* the divergence is.
    """
    osc = ie.series_for(df, oscillator)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    osc_arr = osc.to_numpy(dtype=float)
    n = len(df)

    found: list[dict[str, Any]] = []

    def _bars_ago(idx: int) -> int:
        return n - 1 - idx

    highs = _pivot_indices(high, left, right, high=True)
    if len(highs) >= 2:
        p1, p2 = highs[-2], highs[-1]
        ph1, ph2 = high[p1], high[p2]
        oh1, oh2 = osc_arr[p1], osc_arr[p2]
        if not (np.isnan(oh1) or np.isnan(oh2)):
            if ph2 > ph1 and oh2 < oh1:
                found.append(_div("bearish", "regular", p1, p2, ph1, ph2, oh1, oh2, _bars_ago))
            elif ph2 < ph1 and oh2 > oh1:
                found.append(_div("bearish", "hidden", p1, p2, ph1, ph2, oh1, oh2, _bars_ago))

    lows = _pivot_indices(low, left, right, high=False)
    if len(lows) >= 2:
        p1, p2 = lows[-2], lows[-1]
        pl1, pl2 = low[p1], low[p2]
        ol1, ol2 = osc_arr[p1], osc_arr[p2]
        if not (np.isnan(ol1) or np.isnan(ol2)):
            if pl2 < pl1 and ol2 > ol1:
                found.append(_div("bullish", "regular", p1, p2, pl1, pl2, ol1, ol2, _bars_ago))
            elif pl2 > pl1 and ol2 < ol1:
                found.append(_div("bullish", "hidden", p1, p2, pl1, pl2, ol1, ol2, _bars_ago))

    return {
        "oscillator": oscillator,
        "pivots": {"left": left, "right": right},
        "divergences": found,
        "has_divergence": bool(found),
    }


def _div(
    bias: str,
    kind: str,
    i1: int,
    i2: int,
    price1: float,
    price2: float,
    osc1: float,
    osc2: float,
    bars_ago: Any,
) -> dict[str, Any]:
    return {
        "bias": bias,
        "kind": kind,
        "from_bars_ago": bars_ago(i1),
        "to_bars_ago": bars_ago(i2),
        "price": [round(float(price1), 8), round(float(price2), 8)],
        "oscillator": [round(float(osc1), 6), round(float(osc2), 6)],
    }


def evaluate_cross(df: pd.DataFrame, series_a: str, series_b: str) -> dict[str, Any]:
    """Pine-style crossover analysis between two resolvable series."""
    a = ie.series_for(df, series_a)
    b = ie.series_for(df, series_b)
    last_a = ie._last(a)
    last_b = ie._last(b)
    relation = "unknown"
    if last_a is not None and last_b is not None:
        relation = "a_above_b" if last_a > last_b else "a_below_b" if last_a < last_b else "equal"
    return {
        "series_a": series_a,
        "series_b": series_b,
        "value_a": last_a,
        "value_b": last_b,
        "relation": relation,
        "cross": ie.cross_state(a, b),
        "bars_since_cross": ie.bars_since_cross(a, b),
    }
