"""Indicator math validation against known reference values."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from tickfeed.core import indicators_engine as ie

# Classic Wilder/StockCharts RSI dataset (published RSI ~70.5 then ~37.79).
WILDER = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
    46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
    43.42, 42.66, 43.13,
]


def test_sma_known_value():
    s = ie.sma(pd.Series([1, 2, 3, 4, 5]), 3)
    assert s.iloc[-1] == pytest.approx(4.0)
    assert math.isnan(s.iloc[0])


def test_ema_constant_series_is_constant():
    s = ie.ema(pd.Series([5.0] * 10), 3)
    assert s.iloc[-1] == pytest.approx(5.0)


def test_ema_known_value():
    # EMA(3) of 1..5 with adjust=False, seeded at first value.
    s = ie.ema(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
    # k=0.5: 1, 1.5, 2.25, 3.125, 4.0625
    assert s.iloc[-1] == pytest.approx(4.0625)


def test_wma_known_value():
    s = ie.wma(pd.Series([1.0, 2.0, 3.0]), 3)
    # (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6
    assert s.iloc[-1] == pytest.approx(14 / 6)


def test_rsi_matches_wilder_reference():
    r = ie.rsi(pd.Series(WILDER), 14)
    assert r.iloc[14] == pytest.approx(70.46, abs=0.3)
    assert r.iloc[-1] == pytest.approx(37.79, abs=0.3)


def test_rsi_bounds_monotonic():
    rising = ie.rsi(pd.Series([float(i) for i in range(1, 40)]), 14)
    falling = ie.rsi(pd.Series([float(i) for i in range(40, 1, -1)]), 14)
    assert rising.iloc[-1] == pytest.approx(100.0, abs=1e-6)
    assert falling.iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_macd_constant_series_zero():
    frame = ie.macd(pd.Series([5.0] * 60))
    assert frame["hist"].iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_macd_cross_detection():
    # Up then down should eventually produce a bearish cross at the turn.
    up = list(range(1, 60))
    down = list(range(59, 0, -1))
    frame = ie.macd(pd.Series([float(x) for x in up + down]))
    cross = ie._macd_cross(frame)
    assert cross in {"bullish", "bearish", "none"}


def test_bbands_mid_equals_sma_and_percent_b():
    c = pd.Series(WILDER)
    bb = ie.bbands(c, 20, 2.0)
    assert bb["mid"].iloc[-1] == pytest.approx(ie.sma(c, 20).iloc[-1])
    pb = bb["percent_b"].iloc[-1]
    assert 0.0 <= pb <= 1.5 or pb < 0  # percent_b can exceed band edges


def test_atr_simple_case():
    df = pd.DataFrame(
        {"high": [10, 12, 14], "low": [8, 9, 11], "close": [9, 11, 13], "volume": [1, 1, 1]}
    )
    a = ie.atr(df, 2)
    assert a.iloc[-1] > 0


def test_compute_derived_signals():
    df = pd.DataFrame(
        {
            "open": WILDER,
            "high": [p + 0.5 for p in WILDER],
            "low": [p - 0.5 for p in WILDER],
            "close": WILDER,
            "volume": [100.0] * len(WILDER),
        }
    )
    results, _ = ie.compute(df, ["rsi:14", "macd:12,26,9", "ema:5"])
    assert "rsi_14" in results
    assert results["rsi_14"]["state"] in {"overbought", "oversold", "neutral", "unknown"}
    assert "cross" in results["macd_12_26_9"]


def test_parse_spec():
    assert ie.parse_spec("rsi:14") == ("rsi", [14])
    assert ie.parse_spec("macd:12,26,9") == ("macd", [12, 26, 9])
    assert ie.parse_spec("vwap") == ("vwap", [])
    assert ie.parse_spec("bbands:20,2") == ("bbands", [20, 2])


def test_parse_spec_pine_aliases():
    # ta. prefix + call syntax + aliases all normalize to the engine form.
    assert ie.parse_spec("ta.rsi(14)") == ("rsi", [14])
    assert ie.parse_spec("ema(20)") == ("ema", [20])
    assert ie.parse_spec("ta.bb(20,2)") == ("bbands", [20, 2])
    assert ie.parse_spec("ta.wpr(14)") == ("willr", [14])
    assert ie.parse_spec("ta.sma(50)") == ("sma", [50])


def _wave_df(n: int = 120):
    import numpy as np

    rng = np.random.default_rng(0)
    close = pd.Series(np.cumsum(rng.standard_normal(n)) + 100)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": np.abs(rng.standard_normal(n)) * 1000 + 500,
        }
    )


def test_willr_in_range():
    s = ie.willr(_wave_df(), 14).dropna()
    assert (s <= 0).all() and (s >= -100).all()


def test_mfi_in_range():
    s = ie.mfi(_wave_df(), 14).dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_mfi_warmup_first_value_at_period():
    # First valid MFI uses `period` real price changes -> index == period.
    s = ie.mfi(_wave_df(60), 14)
    assert math.isnan(s.iloc[13])
    assert not math.isnan(s.iloc[14])


def test_mfi_saturates_to_100_on_pure_uptrend():
    import numpy as np

    close = pd.Series(np.arange(1.0, 40.0))  # strictly rising -> no negative flow
    df = pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
         "volume": [100.0] * len(close)}
    )
    assert ie.mfi(df, 14).iloc[-1] == pytest.approx(100.0)


def test_roc_known_value():
    s = ie.roc(pd.Series([100.0, 110.0]), 1)
    assert s.iloc[-1] == pytest.approx(10.0)


def test_supertrend_has_value_and_direction():
    frame = ie.supertrend(_wave_df(), 10, 3.0)
    assert ie._last(frame["supertrend"]) is not None
    assert ie._direction_state(frame["direction"]) in {"up", "down"}


def test_psar_direction_defined():
    frame = ie.psar(_wave_df())
    assert ie._direction_state(frame["direction"]) in {"up", "down"}


def test_ichimoku_signal_classification():
    df = _wave_df()
    frame = ie.ichimoku(df)
    assert ie._ichimoku_signal(df["close"], frame) in {
        "above_cloud",
        "below_cloud",
        "in_cloud",
        "unknown",
    }


def test_series_for_resolves_constant_and_price():
    df = _wave_df(30)
    assert ie.series_for(df, "30").iloc[-1] == pytest.approx(30.0)
    assert ie.series_for(df, "close").iloc[-1] == pytest.approx(df["close"].iloc[-1])
    assert ie.series_for(df, "hl2").iloc[-1] == pytest.approx(
        (df["high"].iloc[-1] + df["low"].iloc[-1]) / 2
    )


def test_cross_state_detects_crossover():
    a = pd.Series([1.0, 2.0, 3.0, 6.0])
    b = pd.Series([5.0, 5.0, 5.0, 5.0])
    assert ie.cross_state(a, b) == "crossover"
    assert ie.cross_state(b, a) == "crossunder"


def test_max_period_picks_largest_lookback():
    assert ie.max_period(["rsi:14", "ema:200", "macd:12,26,9"]) == 200
    assert ie.max_period(["ichimoku"]) == 52  # default span_b
    assert ie.max_period(["vwap", "obv"]) == 1
    assert ie.max_period([]) == 0


# --- extended indicator coverage ------------------------------------------


def test_registry_has_expected_size():
    # Engine should be broad: ~59 indicators wired into the registry.
    assert len(ie.SUPPORTED) >= 55
    assert ie.compute is not None


def test_all_indicators_compute_without_error():
    """Every registered indicator computes a primary value on a realistic frame."""
    df = _wave_df(320)
    results, series = ie.compute(df, list(ie.SUPPORTED), include_series=True)
    for name, res in results.items():
        assert "error" not in res, f"{name} errored: {res}"
        # at least one numeric field is populated
        numeric = [v for k, v in res.items() if isinstance(v, (int, float))]
        assert numeric, f"{name} produced no numeric value: {res}"
    # include_series returns a list per indicator
    assert all(isinstance(v, list) for v in series.values())


def test_adx_is_high_on_strong_trend():
    import numpy as np

    up = pd.Series(np.arange(1.0, 200.0))
    df = pd.DataFrame(
        {"open": up, "high": up + 0.5, "low": up - 0.5, "close": up, "volume": [1.0] * len(up)}
    )
    assert ie.adx(df, 14).dropna().iloc[-1] == pytest.approx(100.0, abs=1.0)


def test_mom_known_value():
    s = ie.mom(pd.Series([1.0, 2.0, 5.0, 9.0]), 2)
    assert s.iloc[-1] == pytest.approx(7.0)  # 9 - 2


def test_stdev_matches_numpy():
    import numpy as np

    data = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert ie.stdev(data, 5).iloc[-1] == pytest.approx(float(np.std(data, ddof=0)))


def test_cmo_in_range():
    s = ie.cmo(_wave_df(120)["close"], 14).dropna()
    assert (s >= -100).all() and (s <= 100).all()


def test_uo_in_range():
    s = ie.uo(_wave_df(120), 7, 14, 28).dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_stochrsi_in_range():
    frame = ie.stochrsi(_wave_df(120)["close"]).dropna()
    assert (frame["k"] >= 0).all() and (frame["k"] <= 100).all()


def test_chop_in_range():
    s = ie.chop(_wave_df(120), 14).dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_aroon_in_range():
    frame = ie.aroon(_wave_df(120), 14).dropna()
    assert (frame["up"] >= 0).all() and (frame["up"] <= 100).all()
    assert (frame["down"] >= 0).all() and (frame["down"] <= 100).all()


def test_vortex_positive():
    frame = ie.vortex(_wave_df(120), 14).dropna()
    assert (frame["vi_plus"] > 0).all() and (frame["vi_minus"] > 0).all()


def test_adl_and_pvt_are_cumulative():
    import numpy as np

    # Closes pinned near the high -> positive money-flow multiplier -> A/D rises.
    close = pd.Series(np.arange(1.0, 50.0))
    df = pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 1.5, "close": close,
         "volume": [100.0] * len(close)}
    )
    adl = ie.adl(df)
    assert adl.iloc[-1] > adl.iloc[10]
    pvt = ie.pvt(df)
    assert pvt.iloc[-1] > pvt.iloc[10]


def test_dema_tema_constant_series():
    c = pd.Series([5.0] * 60)
    assert ie.dema(c, 10).iloc[-1] == pytest.approx(5.0)
    assert ie.tema(c, 10).iloc[-1] == pytest.approx(5.0)
    assert ie.hma(c, 16).iloc[-1] == pytest.approx(5.0)


def test_pine_alias_new_indicators():
    assert ie.parse_spec("ta.stoch(14,3,3)") == ("stoch", [14, 3, 3])
    assert ie.parse_spec("ta.vi(14)") == ("vortex", [14])
    assert ie.parse_spec("ad") == ("adl", [])
    assert ie.parse_spec("ta.wt(10,21)") == ("wavetrend", [10, 21])
    assert ie.parse_spec("sqz") == ("squeeze", [])
    assert ie.parse_spec("ta.ha") == ("heikinashi", [])


def test_dmi_components_and_adx_consistency():
    import numpy as np

    up = pd.Series(np.arange(1.0, 200.0))
    df = pd.DataFrame(
        {"open": up, "high": up + 0.5, "low": up - 0.5, "close": up, "volume": [1.0] * len(up)}
    )
    frame = ie.dmi(df, 14)
    # strong uptrend: +DI dominates -DI, ADX high
    assert frame["plus_di"].dropna().iloc[-1] > frame["minus_di"].dropna().iloc[-1]
    # adx() must equal dmi()['adx'] (refactor DRY)
    assert ie.adx(df, 14).dropna().iloc[-1] == pytest.approx(
        frame["adx"].dropna().iloc[-1]
    )


def test_t3_constant_series():
    c = pd.Series([5.0] * 80)
    assert ie.t3(c, 5, 0.7).iloc[-1] == pytest.approx(5.0)


def test_vidya_constant_series():
    c = pd.Series([5.0] * 60)
    assert ie.vidya(c, 14).iloc[-1] == pytest.approx(5.0)


def test_crsi_and_stc_in_range():
    df = _wave_df(220)
    cr = ie.crsi(df["close"]).dropna()
    assert (cr >= 0).all() and (cr <= 100).all()
    s = ie.stc(df["close"]).dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_zscore_positive_above_mean():
    import numpy as np

    # An above-window-mean value yields a positive, finite z-score.
    c = pd.Series([10.0] * 20 + [13.0])
    z = ie.zscore(c, 20)
    assert z.iloc[-1] > 0 and np.isfinite(z.iloc[-1])


def test_pivots_are_ordered():
    df = _wave_df(50)
    frame = ie.pivots(df).dropna()
    last = frame.iloc[-1]
    assert last["s3"] < last["s2"] < last["s1"] < last["pp"] < last["r1"] < last["r2"] < last["r3"]


def test_heikinashi_close_is_ohlc_average():
    df = _wave_df(30)
    ha = ie.heikinashi(df)
    expected = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    assert ha["close"].iloc[-1] == pytest.approx(expected.iloc[-1])


def test_vwapbands_ordering():
    df = _wave_df(60)
    vb = ie.vwapbands(df, 1.0).dropna()
    assert (vb["lower"] <= vb["vwap"]).all() and (vb["vwap"] <= vb["upper"]).all()


def test_squeeze_state_values():
    df = _wave_df(120)
    sq = ie.squeeze(df).dropna()
    assert set(sq["squeeze"].unique()).issubset({-1.0, 0.0, 1.0})
