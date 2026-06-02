"""Tests for price-structure recognition: patterns, structure, S/R."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tickscope.core import structure as st


def _df(o, h, low, c):
    return pd.DataFrame(
        {"open": o, "high": h, "low": low, "close": c, "volume": [1.0] * len(c)}
    )


def test_detect_bullish_engulfing():
    o = [10.0, 9.6, 9.2, 10.0, 8.8]
    c = [9.8, 9.3, 8.9, 9.0, 10.2]
    h = [10.1, 9.7, 9.3, 10.1, 10.3]
    low = [9.7, 9.2, 8.8, 8.7, 8.6]
    out = st.detect_candlestick_patterns(_df(o, h, low, c), lookback=3)
    names = {p["pattern"] for p in out["patterns"]}
    assert "bullish_engulfing" in names
    eng = next(p for p in out["patterns"] if p["pattern"] == "bullish_engulfing")
    assert eng["bias"] == "bullish" and eng["bars_ago"] == 0


def test_detect_doji():
    # A near-zero body with balanced shadows => doji.
    out = st.detect_candlestick_patterns(
        _df([10.0, 10.0], [10.6, 10.5], [9.4, 9.5], [10.0, 10.02]), lookback=1
    )
    assert any(p["pattern"] == "doji" for p in out["patterns"])


def test_detect_three_black_crows():
    o = [10.0, 9.5, 9.0]
    c = [9.4, 8.9, 8.4]
    h = [10.1, 9.6, 9.1]
    low = [9.3, 8.8, 8.3]
    out = st.detect_candlestick_patterns(_df(o, h, low, c), lookback=3)
    assert any(p["pattern"] == "three_black_crows" for p in out["patterns"])


def test_latest_candle_metrics():
    out = st.detect_candlestick_patterns(
        _df([10.0], [11.0], [9.0], [10.5]), lookback=1
    )
    lc = out["latest_candle"]
    assert lc["type"] == "bullish"
    assert 0.0 <= lc["body_pct"] <= 1.0


def _zigzag_uptrend() -> pd.DataFrame:
    # Higher highs and higher lows, junctions sliced to avoid tied pivots.
    segs = [
        np.linspace(100, 110, 8),
        np.linspace(110, 104, 6)[1:],
        np.linspace(104, 118, 8)[1:],
        np.linspace(118, 111, 6)[1:],
        np.linspace(111, 126, 9)[1:],
    ]
    base = np.concatenate(segs)
    return pd.DataFrame(
        {"open": base, "high": base + 0.4, "low": base - 0.4, "close": base,
         "volume": [1.0] * len(base)}
    )


def test_market_structure_uptrend_and_bos():
    ms = st.market_structure(_zigzag_uptrend(), left=2, right=2)
    assert ms["trend"] == "uptrend"
    labels = [s["label"] for s in ms["swings"] if s["label"]]
    assert "HH" in labels and "HL" in labels
    assert any(e["type"] == "BOS" and e["bias"] == "bullish" for e in ms["events"])


def test_market_structure_downtrend():
    up = _zigzag_uptrend()
    # Mirror the uptrend into a downtrend.
    base = (300 - up["close"]).to_numpy()
    df = pd.DataFrame(
        {"open": base, "high": base + 0.4, "low": base - 0.4, "close": base,
         "volume": [1.0] * len(base)}
    )
    ms = st.market_structure(df, left=2, right=2)
    assert ms["trend"] == "downtrend"


def test_empty_dataframe_is_safe():
    empty = pd.DataFrame({"open": [], "high": [], "low": [], "close": [], "volume": []})
    assert st.detect_candlestick_patterns(empty) == {
        "patterns": [], "count": 0, "latest_candle": None
    }
    ms = st.market_structure(empty)
    assert ms["trend"] == "range" and ms["current_price"] is None
    sr = st.support_resistance(empty)
    assert sr["current_price"] is None and sr["support"] == [] and sr["resistance"] == []


def test_dragonfly_and_gravestone_doji():
    dragonfly = _df([100.0], [100.05], [95.0], [100.02])
    assert any(
        p["pattern"] == "dragonfly_doji"
        for p in st.detect_candlestick_patterns(dragonfly, 1)["patterns"]
    )
    gravestone = _df([100.0], [105.0], [99.97], [99.98])
    assert any(
        p["pattern"] == "gravestone_doji"
        for p in st.detect_candlestick_patterns(gravestone, 1)["patterns"]
    )


def test_nonfinite_price_is_safe():
    import numpy as np

    df = _df([100.0, 101.0], [101.0, 102.0], [99.0, 100.0], [100.5, np.nan])
    sr = st.support_resistance(df)
    assert sr["current_price"] is None


def test_support_resistance_clusters_touches():
    df = _zigzag_uptrend()
    sr = st.support_resistance(df, lookback=100, left=2, right=2, tolerance_pct=1.0)
    assert sr["current_price"] > 0
    all_zones = sr["support"] + sr["resistance"]
    assert all_zones  # at least one zone found
    assert all(z["touches"] >= 1 for z in all_zones)
    # support levels are below price, resistance at/above
    assert all(z["level"] < sr["current_price"] for z in sr["support"])
    assert all(z["level"] >= sr["current_price"] for z in sr["resistance"])
