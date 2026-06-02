"""Tests for higher-level analysis: divergence, cross, aggregation, retry."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tickfeed.core import analysis
from tickfeed.core.retry import with_retry

# asyncio_mode = "auto" (pyproject) runs async tests automatically; no mark needed.


def _bullish_divergence_df() -> pd.DataFrame:
    # Price makes a LOWER low while RSI makes a HIGHER low (regular bullish).
    # Junction values are sliced off so each trough is a unique strict minimum.
    lead = np.linspace(100, 102, 18)  # warmup so RSI is defined at the first pivot
    seg1_down = np.linspace(102, 82, 12)[1:]  # steep drop -> low RSI
    seg1_up = np.linspace(82, 96, 10)[1:]
    seg2_down = np.linspace(96, 80, 18)[1:]  # lower price low, gentler -> higher RSI
    seg2_up = np.linspace(80, 92, 10)[1:]
    close = np.concatenate([lead, seg1_down, seg1_up, seg2_down, seg2_up])
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
         "volume": [1000.0] * len(close)}
    )


def test_detect_divergence_bullish_regular():
    out = analysis.detect_divergence(_bullish_divergence_df(), "rsi:14", left=3, right=3)
    assert out["has_divergence"] is True
    div = out["divergences"][0]
    assert div["bias"] == "bullish"
    assert div["kind"] == "regular"
    # price lower low, oscillator higher low
    assert div["price"][1] < div["price"][0]
    assert div["oscillator"][1] > div["oscillator"][0]


def test_pivot_indices_rejects_ties():
    # Strict-extremum semantics: a value tied within the window is NOT a pivot.
    vals = np.array([1.0, 5.0, 2.0, 5.0, 2.0, 1.0, 0.0])
    highs = analysis.pivot_indices(vals, 2, 2, high=True)
    assert 3 not in highs  # index 3 (5.0) ties index 1 (5.0) -> not a pivot
    # A clean unique peak is detected.
    clean = np.array([1.0, 2.0, 9.0, 2.0, 1.0])
    assert analysis.pivot_indices(clean, 2, 2, high=True) == [2]


def test_detect_divergence_none_on_trending():
    # Monotonic uptrend: no opposing pivots -> no divergence.
    close = pd.Series(np.linspace(100, 200, 80))
    df = pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
         "volume": [1000.0] * 80}
    )
    out = analysis.detect_divergence(df, "rsi:14")
    assert out["has_divergence"] is False


def test_evaluate_cross_golden_cross():
    # Fast series overtakes slow series -> crossover.
    n = 60
    close = pd.Series(list(np.linspace(100, 90, 30)) + list(np.linspace(90, 120, 30)))
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close,
         "volume": [1000.0] * n}
    )
    out = analysis.evaluate_cross(df, "ema:5", "ema:20")
    assert out["relation"] == "a_above_b"
    assert out["cross"] in {"crossover", "none"}


# --- retry ----------------------------------------------------------------


async def test_with_retry_succeeds_after_transient():
    import ccxt

    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ccxt.RateLimitExceeded("slow down")
        return "ok"

    result = await with_retry(flaky, retries=3, base_delay=0.0)
    assert result == "ok"
    assert attempts["n"] == 2


async def test_with_retry_propagates_non_retryable():
    import ccxt

    async def bad():
        raise ccxt.BadSymbol("nope")

    with pytest.raises(ccxt.BadSymbol):
        await with_retry(bad, retries=3, base_delay=0.0)


# --- service-level: funding, live candle, aggregation ---------------------


async def test_funding_uses_next_timestamp(service, fake_exchange):
    out = await service.get_funding_rate("binance", "BTC/USDT")
    now_ms = int(__import__("time").time() * 1000)
    # next_funding_time should be ~8h in the future (nextFundingTimestamp),
    # not the current fundingTimestamp.
    from tickfeed.utils import iso_or_ms_to_ms

    next_ms = iso_or_ms_to_ms(out["next_funding_time"])
    assert next_ms is not None and next_ms > now_ms + 3_600_000


async def test_ohlcv_live_candle_overlay(service):
    base = await service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    last_ts_iso = base["candles"][-1]["ts"]
    from tickfeed.utils import iso_or_ms_to_ms

    last_ts = iso_or_ms_to_ms(last_ts_iso)
    # Inject a forming candle that updates the most recent bar's close.
    service.cache.set_live_candle(
        "binance", "BTC/USDT", "1h", [last_ts, 1.0, 2.0, 0.5, 1.5, 9.0]
    )
    updated = await service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    assert updated["meta"]["live"] is True
    assert updated["candles"][-1]["close"] == pytest.approx(1.5)


async def test_ohlcv_live_overlay_append_respects_limit(service):
    base = await service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    from tickfeed.utils import iso_or_ms_to_ms

    last_ts = iso_or_ms_to_ms(base["candles"][-1]["ts"])
    # A forming candle exactly one timeframe ahead -> appended, but trimmed.
    service.cache.set_live_candle(
        "binance", "BTC/USDT", "1h", [last_ts + 3_600_000, 1.0, 2.0, 0.5, 1.5, 9.0]
    )
    updated = await service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    assert updated["meta"]["count"] == 50  # never exceeds the requested limit
    assert updated["candles"][-1]["close"] == pytest.approx(1.5)


async def test_ohlcv_live_overlay_drops_gapped_candle(service):
    base = await service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    from tickfeed.utils import iso_or_ms_to_ms

    last_ts = iso_or_ms_to_ms(base["candles"][-1]["ts"])
    # A forming candle several periods ahead (a gap) must be dropped, not stitched.
    service.cache.set_live_candle(
        "binance", "BTC/USDT", "1h", [last_ts + 10 * 3_600_000, 1.0, 2.0, 0.5, 1.5, 9.0]
    )
    updated = await service.get_ohlcv("binance", "BTC/USDT", "1h", 50)
    assert updated["meta"]["live"] is False
    assert updated["candles"][-1]["close"] != pytest.approx(1.5)


async def test_screen_sort_by_volume_with_indicator_only_filter(service):
    # Flagship scenario: indicator-only filter, sort by volume_24h. Each matched
    # row must still carry volume_24h so sorting works (regression).
    out = await service.screen_market(
        "binance", ["BTC/USDT", "ETH/USDT"], "USDT", 30, "1h",
        [{"indicator": "rsi:14", "op": ">", "value": 0}], "volume_24h",
    )
    assert out["matched"]
    assert all("volume_24h" in row for row in out["matched"])


async def test_aggregated_price_across_exchanges(multi_service):
    out = await multi_service.get_aggregated_price("BTC/USDT")
    assert out["exchange_count"] == 3
    # bybit highest (67100), okx lowest (66950)
    assert out["max"]["exchange"] == "bybit"
    assert out["min"]["exchange"] == "okx"
    assert out["arb_spread"] == pytest.approx(150.0)
    assert out["weighted_avg"] > 0
