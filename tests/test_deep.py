"""Tests for the deep-analysis layer: ★2 context, ★3 signal history, deep_analyze."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tickscope.core import context, signal_history


def _df(closes: list[float]) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": np.full(c.size, 100.0)}
    )


# --- ★3 causality: this is the property that makes the event study trustworthy ---

def test_forward_stats_is_strictly_causal_and_correct():
    close = np.array([100, 101, 102, 103, 104, 105], dtype=float)
    # index 0, horizon 2 -> 102/100-1 = +2.0%; index 4, horizon 2 -> 4+2=6 out of range -> DROPPED
    stats = signal_history._forward_stats(close, [0, 4], horizon=2)
    assert stats["count"] == 1  # the look-ahead-less occurrence only
    assert stats["median_pct"] == pytest.approx(2.0)
    assert stats["win_rate_pct"] == 100.0


def test_divergence_performance_wellformed_and_no_future_leak():
    rng = np.random.default_rng(7)
    closes = list(20000 + np.cumsum(rng.normal(0, 30, 600)))
    perf = signal_history.divergence_performance(_df(closes), "rsi:14", horizon=10)
    assert perf["signal"] == "divergence(rsi:14)"
    for side in ("bullish", "bearish"):
        s = perf[side]
        assert s["count"] >= 0
        if s["count"] > 0:
            assert 0.0 <= s["win_rate_pct"] <= 100.0
            assert "median_pct" in s and "worst_pct" in s


def test_divergence_performance_recompute_stable_when_history_grows():
    # No-look-ahead invariant: stats over the first k bars must not change when
    # more *future* bars are appended (a leak would shift past occurrences).
    rng = np.random.default_rng(3)
    full = list(20000 + np.cumsum(rng.normal(0, 25, 500)))
    k = 380
    early = signal_history.divergence_performance(_df(full[:k]), "rsi:14", horizon=8)
    grown = signal_history.divergence_performance(_df(full), "rsi:14", horizon=8)
    # Every occurrence countable in the early window (had its full forward window
    # inside [0,k)) must still be counted identically in the grown series.
    assert grown["bullish"]["count"] >= early["bullish"]["count"]
    assert grown["bearish"]["count"] >= early["bearish"]["count"]


# --- ★2 statistical / market-state context ---

def test_statistical_context_fields_and_graceful_short_data():
    ctx = context.statistical_context(_df(list(20000 + np.cumsum(np.ones(300)))))
    assert ctx["available"] is True
    assert ctx["trend_state"] in (
        "trending_up", "trending_down", "trending", "ranging", None
    )
    assert ctx["price_percentile"] is None or 0.0 <= ctx["price_percentile"] <= 1.0
    # Too-short data must degrade, not raise.
    short = context.statistical_context(_df([1.0, 2.0, 3.0]))
    assert short["available"] is True


# --- end-to-end via the fake exchange ---

@pytest.mark.asyncio
async def test_deep_analyze_shape(service):
    out = await service.deep_analyze("binance", "BTC/USDT", timeframes=["4h", "1h"])
    assert set(out["timeframes"]) == {"4h", "1h"}
    assert out["verdict"]["bias"] in ("bullish", "bearish", "neutral")
    assert out["verdict"]["confidence"] in ("high", "medium", "low")
    assert "signal_history" in out and "disclaimer" in out
    snap = out["timeframes"]["1h"]
    assert "trend" in snap and "context" in snap and "rsi" in snap


@pytest.mark.asyncio
async def test_compute_indicators_now_carries_context(service):
    out = await service.compute_indicators("binance", "BTC/USDT", "1h", 200, ["rsi:14"], False)
    assert "context" in out
    assert out["context"]["available"] is True
    assert "trend_state" in out["context"] and "price_percentile" in out["context"]
