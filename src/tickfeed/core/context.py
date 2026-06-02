"""Statistical & market-state context (★2).

Turns a raw indicator value into a *judgement* by answering two questions a
single number can't: "is this value actually significant relative to its own
history?" and "what market state are we in?". A reading of ``RSI 32`` means
something very different in a quiet range than in a strong downtrend — this
layer makes that explicit.

Cheap (numpy reductions over data already in memory) and free of look-ahead:
every value is taken at the last bar with only past data behind it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import indicators_engine as ie


def _percentile_rank(values: np.ndarray, x: float) -> float | None:
    """Fraction of finite ``values`` strictly below ``x`` (0..1), or None."""
    v = values[np.isfinite(values)]
    if v.size == 0 or not np.isfinite(x):
        return None
    return round(float((v < x).mean()), 4)


def value_percentile(series: pd.Series, *, lookback: int = 250) -> float | None:
    """Percentile of a series' latest value within its own recent history.

    Lets a caller report e.g. "RSI is at the 6th percentile of the last 250
    bars" — context that a bare ``RSI 30`` lacks.
    """
    arr = series.to_numpy(dtype=float)
    if arr.size == 0:
        return None
    win = arr[-lookback:] if arr.size > lookback else arr
    return _percentile_rank(win, arr[-1])


def _trend_state(
    df: pd.DataFrame, close: np.ndarray, adx_period: int, er_period: int
) -> tuple[str | None, float | None, float | None]:
    """Classify the trend state via ADX strength + DI direction.

    Also returns Kaufman's efficiency ratio (0..1; high = directional, low =
    choppy) as a second, smoothing-free read on how "trending" the tape is.
    """
    adx_val = ie._last(ie.adx(df, adx_period))

    er: float | None = None
    if close.size > er_period:
        seg = close[-er_period - 1 :]
        denom = float(np.abs(np.diff(seg)).sum())
        er = round(float(abs(seg[-1] - seg[0]) / denom), 3) if denom > 0 else 0.0

    if adx_val is None:
        return None, None, er

    if adx_val < 20:
        state = "ranging"
    else:
        dmi = ie.dmi(df, adx_period)
        plus = ie._last(dmi["plus_di"])
        minus = ie._last(dmi["minus_di"])
        if plus is not None and minus is not None:
            state = "trending_up" if plus >= minus else "trending_down"
        else:
            state = "trending"
    return state, round(float(adx_val), 1), er


def statistical_context(
    df: pd.DataFrame, *, lookback: int = 250, er_period: int = 20, adx_period: int = 14
) -> dict[str, Any]:
    """Distributional + market-state context for the latest bar of ``df``.

    Degrades gracefully (fields become ``None``) when there is too little
    history for a given measure rather than raising.
    """
    n = len(df)
    if n == 0:
        return {"available": False}

    close = df["close"].to_numpy(dtype=float)
    win = close[-lookback:] if n > lookback else close
    cur = close[-1]

    price_pct = _percentile_rank(win, cur)

    ret_z: float | None = None
    if win.size > 6:
        rets = np.diff(win) / win[:-1]
        rets = rets[np.isfinite(rets)]
        if rets.size > 5 and rets.std() > 0:
            ret_z = round(float((rets[-1] - rets.mean()) / rets.std()), 2)

    atr_pct: float | None = None
    vol_state: str | None = None
    atr = ie.atr(df, adx_period).to_numpy(dtype=float)
    if atr.size:
        atr_win = atr[-lookback:] if atr.size > lookback else atr
        atr_pct = _percentile_rank(atr_win, atr[-1])
        if atr_pct is not None:
            vol_state = "high" if atr_pct >= 0.8 else "low" if atr_pct <= 0.2 else "normal"

    trend_state, adx_val, er = _trend_state(df, close, adx_period, er_period)

    return {
        "available": True,
        "lookback": int(min(n, lookback)),
        "price_percentile": price_pct,
        "return_zscore": ret_z,
        "trend_state": trend_state,
        "adx": adx_val,
        "efficiency_ratio": er,
        "volatility_state": vol_state,
        "atr_percentile": atr_pct,
    }
