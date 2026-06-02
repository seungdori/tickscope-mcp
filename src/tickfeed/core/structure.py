"""Price-structure recognition: candlestick patterns, market structure, S/R.

These go beyond numeric indicators — they describe *what the chart is doing* in
the vocabulary a trader (or an LLM narrating a chart) uses: named candle
patterns, swing structure (HH/HL/LH/LL with BOS / CHoCH), and clustered
support/resistance zones. All functions are pure and operate on an OHLCV
DataFrame with float columns ``open/high/low/close/volume``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .analysis import _pivot_indices

# --- candlestick patterns -----------------------------------------------------


def detect_candlestick_patterns(df: pd.DataFrame, lookback: int = 10) -> dict[str, Any]:
    """Detect classic candlestick patterns over the last ``lookback`` bars.

    Returns each detected pattern with its conventional bias and how many bars
    back it completed. Reversal patterns whose meaning depends on context
    (hammer vs hanging man) are named using the local prior trend.
    """
    if len(df) == 0:
        return {"patterns": [], "count": 0, "latest_candle": None}
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    ts = df.index
    n = len(c)
    rng = np.maximum(h - low, 1e-12)
    body = np.abs(c - o)
    body_pct = body / rng
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - low
    bull = c > o

    def _trend(i: int, span: int = 5) -> str:
        j = max(0, i - span)
        if c[i] > c[j]:
            return "up"
        if c[i] < c[j]:
            return "down"
        return "flat"

    def _at(i: int) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        bp = body_pct[i]
        r = rng[i]
        # --- single-candle ---
        if bp < 0.1:
            # Subtype by shadow share of the *range* (the body is ~0 here).
            if lower[i] >= 0.6 * r and upper[i] <= 0.1 * r:
                out.append(("dragonfly_doji", "bullish"))
            elif upper[i] >= 0.6 * r and lower[i] <= 0.1 * r:
                out.append(("gravestone_doji", "bearish"))
            else:
                out.append(("doji", "neutral"))
        else:
            if bp > 0.95:
                out.append(("marubozu", "bullish" if bull[i] else "bearish"))
            # hammer family: small body near the top, long lower shadow
            if lower[i] >= 2 * body[i] and upper[i] <= body[i] and bp < 0.5:
                if _trend(i) == "down":
                    out.append(("hammer", "bullish"))
                else:
                    out.append(("hanging_man", "bearish"))
            # inverted-hammer family: long upper shadow, small body near bottom
            if upper[i] >= 2 * body[i] and lower[i] <= body[i] and bp < 0.5:
                if _trend(i) == "down":
                    out.append(("inverted_hammer", "bullish"))
                else:
                    out.append(("shooting_star", "bearish"))
            if bp < 0.3 and upper[i] > body[i] and lower[i] > body[i]:
                out.append(("spinning_top", "neutral"))
        # --- two-candle ---
        if i >= 1:
            p = i - 1
            if not bull[p] and bull[i] and o[i] <= c[p] and c[i] >= o[p] and body[i] > body[p]:
                out.append(("bullish_engulfing", "bullish"))
            if bull[p] and not bull[i] and o[i] >= c[p] and c[i] <= o[p] and body[i] > body[p]:
                out.append(("bearish_engulfing", "bearish"))
            if not bull[p] and bull[i] and body[i] < body[p] and max(o[i], c[i]) <= o[p] and min(
                o[i], c[i]
            ) >= c[p]:
                out.append(("bullish_harami", "bullish"))
            if bull[p] and not bull[i] and body[i] < body[p] and max(o[i], c[i]) <= c[p] and min(
                o[i], c[i]
            ) >= o[p]:
                out.append(("bearish_harami", "bearish"))
            mid_p = (o[p] + c[p]) / 2
            if not bull[p] and bull[i] and o[i] < low[p] and mid_p < c[i] < o[p]:
                out.append(("piercing_line", "bullish"))
            if bull[p] and not bull[i] and o[i] > h[p] and o[p] < c[i] < mid_p:
                out.append(("dark_cloud_cover", "bearish"))
            tol = 0.001 * c[i]
            if abs(low[i] - low[p]) <= tol and _trend(i) == "down":
                out.append(("tweezer_bottom", "bullish"))
            if abs(h[i] - h[p]) <= tol and _trend(i) == "up":
                out.append(("tweezer_top", "bearish"))
        # --- three-candle ---
        if i >= 2:
            a, b = i - 2, i - 1
            mid_a = (o[a] + c[a]) / 2
            star_small = body[b] < body[a] * 0.5
            if not bull[a] and star_small and bull[i] and c[i] > mid_a and max(o[b], c[b]) < c[a]:
                out.append(("morning_star", "bullish"))
            if bull[a] and star_small and not bull[i] and c[i] < mid_a and min(o[b], c[b]) > c[a]:
                out.append(("evening_star", "bearish"))
            if (
                bull[a] and bull[b] and bull[i]
                and c[i] > c[b] > c[a]
                and o[b] < c[a] and o[i] < c[b]
            ):
                out.append(("three_white_soldiers", "bullish"))
            if (
                not bull[a] and not bull[b] and not bull[i]
                and c[i] < c[b] < c[a]
                and o[b] > c[a] and o[i] > c[b]
            ):
                out.append(("three_black_crows", "bearish"))
        return out

    patterns: list[dict[str, Any]] = []
    start = max(0, n - lookback)
    for i in range(start, n):
        for name, bias in _at(i):
            patterns.append(
                {
                    "pattern": name,
                    "bias": bias,
                    "bars_ago": n - 1 - i,
                    "ts": _iso(ts, i),
                }
            )
    patterns.sort(key=lambda p: p["bars_ago"])
    last = n - 1
    return {
        "patterns": patterns,
        "count": len(patterns),
        "latest_candle": {
            "type": "bullish" if bull[last] else "bearish",
            "body_pct": round(float(body_pct[last]), 4),
            "upper_shadow_pct": round(float(upper[last] / rng[last]), 4),
            "lower_shadow_pct": round(float(lower[last] / rng[last]), 4),
        },
    }


# --- market structure (swings, HH/HL/LH/LL, BOS / CHoCH) ----------------------


def market_structure(df: pd.DataFrame, left: int = 3, right: int = 3) -> dict[str, Any]:
    """Swing structure and trend with break-of-structure / change-of-character.

    Builds an alternating swing sequence from confirmed pivots, labels each
    high/low (HH/HL/LH/LL), infers the prevailing trend, and flags the latest
    bar's break of the most recent swing as a continuation (BOS) or reversal
    (CHoCH).
    """
    if len(df) == 0:
        return {
            "trend": "range",
            "current_price": None,
            "last_swing_high": None,
            "last_swing_low": None,
            "swings": [],
            "events": [],
        }
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(close)

    raw: list[tuple[int, str, float]] = [
        (i, "high", high[i]) for i in _pivot_indices(high, left, right, high=True)
    ]
    raw += [(i, "low", low[i]) for i in _pivot_indices(low, left, right, high=False)]
    raw.sort(key=lambda x: x[0])

    # Collapse consecutive same-type pivots into the more extreme one (zigzag).
    swings: list[tuple[int, str, float]] = []
    for piv in raw:
        if swings and swings[-1][1] == piv[1]:
            prev = swings[-1]
            keep = piv if (piv[2] > prev[2] if piv[1] == "high" else piv[2] < prev[2]) else prev
            swings[-1] = keep
        else:
            swings.append(piv)

    labeled: list[dict[str, Any]] = []
    last_high: float | None = None
    last_low: float | None = None
    for idx, kind, price in swings:
        label = None
        if kind == "high":
            label = "HH" if last_high is not None and price > last_high else "LH" if last_high is not None else None
            last_high = price
        else:
            label = "LL" if last_low is not None and price < last_low else "HL" if last_low is not None else None
            last_low = price
        labeled.append(
            {"type": kind, "price": round(float(price), 8), "label": label, "bars_ago": n - 1 - idx}
        )

    highs = [s for s in labeled if s["type"] == "high"]
    lows = [s for s in labeled if s["type"] == "low"]
    last_high_label = highs[-1]["label"] if highs else None
    last_low_label = lows[-1]["label"] if lows else None
    if last_high_label == "HH" and last_low_label == "HL":
        trend = "uptrend"
    elif last_high_label == "LH" and last_low_label == "LL":
        trend = "downtrend"
    else:
        trend = "range"

    events: list[dict[str, Any]] = []
    price_now = close[-1]
    sh = highs[-1]["price"] if highs else None
    sl = lows[-1]["price"] if lows else None

    def _break_kind(continuation_trend: str) -> str:
        # BOS = break in the trend's direction; CHoCH = counter-trend break in a
        # trending market; a break out of a range is neither — a range breakout.
        if trend == continuation_trend:
            return "BOS"
        return "CHoCH" if trend in ("uptrend", "downtrend") else "range_breakout"

    if sh is not None and np.isfinite(price_now) and price_now > sh:
        events.append(
            {"type": _break_kind("uptrend"), "bias": "bullish", "broke": "swing_high", "level": sh}
        )
    if sl is not None and np.isfinite(price_now) and price_now < sl:
        events.append(
            {"type": _break_kind("downtrend"), "bias": "bearish", "broke": "swing_low", "level": sl}
        )

    return {
        "trend": trend,
        "current_price": round(float(price_now), 8) if np.isfinite(price_now) else None,
        "last_swing_high": highs[-1] if highs else None,
        "last_swing_low": lows[-1] if lows else None,
        "swings": labeled[-8:],
        "events": events,
    }


# --- support / resistance clustering ------------------------------------------


def support_resistance(
    df: pd.DataFrame,
    lookback: int = 150,
    left: int = 3,
    right: int = 3,
    tolerance_pct: float = 0.5,
    max_levels: int = 6,
) -> dict[str, Any]:
    """Cluster swing pivots into support/resistance zones near the current price.

    Pivot highs/lows over the last ``lookback`` bars are grouped when within
    ``tolerance_pct`` of each other; each zone's touch count is its strength.
    Zones are split into support (below price) and resistance (above).
    """
    if len(df) == 0:
        return {"current_price": None, "support": [], "resistance": []}
    price = float(df["close"].iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return {"current_price": None, "support": [], "resistance": []}
    window = df.tail(lookback)
    high = window["high"].to_numpy(dtype=float)
    low = window["low"].to_numpy(dtype=float)

    levels: list[float] = [high[i] for i in _pivot_indices(high, left, right, high=True)]
    levels += [low[i] for i in _pivot_indices(low, left, right, high=False)]
    levels.sort()

    clusters: list[dict[str, Any]] = []
    for lvl in levels:
        if clusters and abs(lvl - clusters[-1]["_sum"] / clusters[-1]["touches"]) <= (
            tolerance_pct / 100 * lvl
        ):
            clusters[-1]["_sum"] += lvl
            clusters[-1]["touches"] += 1
        else:
            clusters.append({"_sum": lvl, "touches": 1})

    zones = []
    for cl in clusters:
        level = cl["_sum"] / cl["touches"]
        zones.append(
            {
                "level": round(level, 8),
                "touches": cl["touches"],
                "distance_pct": round((level - price) / price * 100, 4),
            }
        )

    support = sorted(
        [z for z in zones if z["level"] < price], key=lambda z: price - z["level"]
    )[:max_levels]
    resistance = sorted(
        [z for z in zones if z["level"] >= price], key=lambda z: z["level"] - price
    )[:max_levels]
    return {
        "current_price": round(price, 8),
        "support": support,
        "resistance": resistance,
    }


def _iso(index: pd.Index, i: int) -> str | None:
    try:
        value = index[i]
    except (IndexError, KeyError):
        return None
    return str(value) if value is not None else None
