"""Technical-indicator engine (functional, pandas/numpy).

Implements a broad indicator set directly to keep results deterministic and
avoid heavy/native dependencies. Each indicator is a plain function returning a
pandas Series (or DataFrame for multi-output ones) aligned to the input candle
index, and is wired into the dispatch via a single ``REGISTRY`` table so adding
one is a one-line declaration. The current list is exposed as ``SUPPORTED`` and
surfaced in the ``compute_indicators`` tool docstring.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# --- primitive indicator functions -------------------------------------------


def _rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing (RMA): SMA seed then recursive smoothing.

    This matches the reference behaviour used by TradingView and Wilder's
    original RSI/ATR/ADX definitions (as opposed to a plain EWM from index 0).
    """
    n = len(values)
    out = np.full(n, np.nan)
    if n < period:
        return out
    seed = float(np.mean(values[:period]))
    out[period - 1] = seed
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def _wilder_rma_series(series: pd.Series, period: int) -> pd.Series:
    """Wilder RMA seeded at the first full window of valid values.

    Robust to any number of leading NaNs: it seeds the SMA at the first index
    that has ``period`` consecutive non-NaN inputs, then recurses (carrying the
    previous value through any interior NaN). This handles both the single
    leading NaN from ``diff`` (RSI/ATR) and the long NaN warmup of DX (ADX),
    while reproducing the original seed position/value for the single-NaN case.
    """
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    valid = ~np.isnan(arr)
    start = None
    count = 0
    for i in range(n):
        if valid[i]:
            count += 1
            if count >= period:
                start = i
                break
        else:
            count = 0
    if start is None:
        return pd.Series(out, index=series.index)
    out[start] = float(np.mean(arr[start - period + 1 : start + 1]))
    for i in range(start + 1, n):
        x = arr[i] if valid[i] else out[i - 1]
        out[i] = (out[i - 1] * (period - 1) + x) / period
    return pd.Series(out, index=series.index)


def sma(close: pd.Series, period: int = 20) -> pd.Series:
    return close.rolling(period).mean()


def ema(close: pd.Series, period: int = 20) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def wma(close: pd.Series, period: int = 20) -> pd.Series:
    weights = np.arange(1, period + 1)
    return close.rolling(period).apply(
        lambda x: float(np.dot(x, weights) / weights.sum()), raw=True
    )


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder_rma_series(gain, period)
    avg_loss = _wilder_rma_series(loss, period)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bbands(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    width = upper - lower
    percent_b = (close - lower) / width.replace(0, np.nan)
    return pd.DataFrame(
        {"upper": upper, "mid": mid, "lower": lower, "percent_b": percent_b}
    )


def _true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = _true_range(df)
    return _wilder_rma_series(tr, period)


def stoch(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> pd.DataFrame:
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    raw_k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    k_line = raw_k.rolling(smooth).mean()
    d_line = k_line.rolling(d).mean()
    return pd.DataFrame({"k": k_line, "d": d_line})


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    return (typical * df["volume"]).cumsum() / cum_vol


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (trend strength); see :func:`dmi` for +DI/-DI."""
    return dmi(df, period)["adx"]


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = typical.rolling(period).mean()
    mean_dev = typical.rolling(period).apply(
        lambda x: float(np.abs(x - x.mean()).mean()), raw=True
    )
    return (typical - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))


def willr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R: momentum oscillator in the range [-100, 0]."""
    high_max = df["high"].rolling(period).max()
    low_min = df["low"].rolling(period).min()
    rng = (high_max - low_min).replace(0, np.nan)
    return -100 * (high_max - df["close"]) / rng


def roc(close: pd.Series, period: int = 12) -> pd.Series:
    """Rate of Change as a percentage."""
    prev = close.shift(period)
    return 100 * (close - prev) / prev.replace(0, np.nan)


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index: volume-weighted RSI in the range [0, 100].

    Uses ``period`` real price changes (the leading diff-NaN bar is excluded so
    the first value lands at index ``period``, matching the RSI/ATR warmup
    convention). A window with no negative flow saturates to 100 (fully
    overbought) rather than returning NaN.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    raw_flow = typical * df["volume"]
    direction = typical.diff()
    valid = direction.notna()
    pos = raw_flow.where(direction > 0, 0.0).where(valid)
    neg = raw_flow.where(direction < 0, 0.0).where(valid)
    pos_sum = pos.rolling(period).sum()
    neg_sum = neg.rolling(period).sum()
    # neg_sum == 0 -> ratio == inf -> MFI 100 (matches the standard limit).
    ratio = pos_sum / neg_sum
    return 100 - (100 / (1 + ratio))


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian channel: rolling high/low envelope and its midline."""
    upper = df["high"].rolling(period).max()
    lower = df["low"].rolling(period).min()
    mid = (upper + lower) / 2
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower})


def keltner(
    df: pd.DataFrame, period: int = 20, mult: float = 2.0, atr_period: int = 10
) -> pd.DataFrame:
    """Keltner channel: EMA midline +/- ``mult`` * ATR."""
    mid = ema(df["close"], period)
    rng = atr(df, atr_period)
    upper = mid + mult * rng
    lower = mid - mult * rng
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower})


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """Supertrend trend-following overlay with direction (+1 up / -1 down)."""
    atr_ = atr(df, period).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    n = len(close)
    upper = hl2 + mult * atr_
    lower = hl2 - mult * atr_
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = np.full(n, np.nan)
    line = np.full(n, np.nan)
    for i in range(n):
        # Warmup: skip until ATR is defined, then seed the bands cleanly so a
        # leading NaN never propagates into the recursive final bands.
        if np.isnan(atr_[i]):
            continue
        if i == 0 or np.isnan(final_lower[i - 1]):
            final_upper[i] = upper[i]
            final_lower[i] = lower[i]
            trend[i] = 1.0
            line[i] = lower[i]
            continue
        final_upper[i] = (
            upper[i]
            if (upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1])
            else final_upper[i - 1]
        )
        final_lower[i] = (
            lower[i]
            if (lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1])
            else final_lower[i - 1]
        )
        if close[i] > final_upper[i - 1]:
            trend[i] = 1.0
        elif close[i] < final_lower[i - 1]:
            trend[i] = -1.0
        else:
            trend[i] = trend[i - 1]
        line[i] = final_lower[i] if trend[i] > 0 else final_upper[i]
    return pd.DataFrame(
        {"supertrend": line, "direction": trend}, index=df.index
    )


def ichimoku(
    df: pd.DataFrame, conversion: int = 9, base: int = 26, span_b: int = 52
) -> pd.DataFrame:
    """Ichimoku Kinko Hyo components (non-displaced, for latest-value use)."""

    def _mid(period: int) -> pd.Series:
        return (df["high"].rolling(period).max() + df["low"].rolling(period).min()) / 2

    tenkan = _mid(conversion)
    kijun = _mid(base)
    senkou_a = (tenkan + kijun) / 2
    senkou_b = _mid(span_b)
    return pd.DataFrame(
        {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b}
    )


def psar(
    df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2
) -> pd.DataFrame:
    """Parabolic SAR with trend direction (+1 long / -1 short)."""
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    n = len(high)
    sar = np.full(n, np.nan)
    trend = np.full(n, np.nan)
    if n < 2:
        return pd.DataFrame({"psar": sar, "direction": trend}, index=df.index)
    up = True
    af = step
    ep = high[0]
    sar[0] = low[0]
    trend[0] = 1.0
    for i in range(1, n):
        prev = sar[i - 1]
        cur = prev + af * (ep - prev)
        if up:
            cur = min(cur, low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
            if low[i] < cur:
                up = False
                cur = ep
                ep = low[i]
                af = step
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + step, max_step)
        else:
            cur = max(cur, high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
            if high[i] > cur:
                up = True
                cur = ep
                ep = high[i]
                af = step
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + step, max_step)
        sar[i] = cur
        trend[i] = 1.0 if up else -1.0
    return pd.DataFrame({"psar": sar, "direction": trend}, index=df.index)


# --- extended moving averages -------------------------------------------------


def smma(close: pd.Series, period: int = 7) -> pd.Series:
    """Smoothed (Wilder/running) moving average — same as Wilder RMA of price."""
    arr = close.to_numpy(dtype=float)
    return pd.Series(_rma(arr, period), index=close.index)


def dema(close: pd.Series, period: int = 20) -> pd.Series:
    """Double EMA: 2*EMA - EMA(EMA), reduces lag."""
    e1 = ema(close, period)
    e2 = ema(e1, period)
    return 2 * e1 - e2


def tema(close: pd.Series, period: int = 20) -> pd.Series:
    """Triple EMA: 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA))."""
    e1 = ema(close, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    return 3 * e1 - 3 * e2 + e3


def hma(close: pd.Series, period: int = 20) -> pd.Series:
    """Hull Moving Average: WMA(2*WMA(n/2) - WMA(n), sqrt(n)) — low lag, smooth."""
    half = max(1, int(period // 2))
    sqrt_n = max(1, round(period**0.5))
    return wma(2 * wma(close, half) - wma(close, period), sqrt_n)


def vwma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume-Weighted Moving Average."""
    pv = (df["close"] * df["volume"]).rolling(period).sum()
    vol = df["volume"].rolling(period).sum().replace(0, np.nan)
    return pv / vol


def zlema(close: pd.Series, period: int = 20) -> pd.Series:
    """Zero-Lag EMA: EMA of a de-lagged price series."""
    lag = (period - 1) // 2
    de_lagged = 2 * close - close.shift(lag)
    return ema(de_lagged, period)


def alma(close: pd.Series, window: int = 9, offset: float = 0.85, sigma: float = 6.0) -> pd.Series:
    """Arnaud Legoux MA: Gaussian-weighted MA with adjustable offset/sigma."""
    window = int(window)
    # TradingView ta.alma floors the offset term for bar-for-bar parity.
    m = np.floor(offset * (window - 1))
    s = window / sigma
    idx = np.arange(window)
    weights = np.exp(-((idx - m) ** 2) / (2 * s * s))
    weights /= weights.sum()
    return close.rolling(window).apply(lambda x: float(np.dot(x, weights)), raw=True)


def kama(close: pd.Series, period: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Adaptive MA: smoothing adapts to the efficiency ratio."""
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    if n <= period:
        return pd.Series(out, index=close.index)
    change = np.abs(arr[period:] - arr[:-period])
    volatility = pd.Series(np.abs(np.diff(arr))).rolling(period).sum().to_numpy()
    fast_sc = 2 / (fast + 1)
    slow_sc = 2 / (slow + 1)
    out[period - 1] = arr[period - 1]
    for i in range(period, n):
        vol = volatility[i - 1]
        er = change[i - period] / vol if vol else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        out[i] = out[i - 1] + sc * (arr[i] - out[i - 1])
    return pd.Series(out, index=close.index)


def trima(close: pd.Series, period: int = 20) -> pd.Series:
    """Triangular MA: double-smoothed SMA emphasizing the middle of the window."""
    n1 = (period + 1) // 2
    n2 = period // 2 + 1
    return sma(sma(close, n1), n2)


def lsma(close: pd.Series, period: int = 20) -> pd.Series:
    """Least-Squares (linear regression) MA: endpoint of the rolling regression line."""
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    denom = float(((x - x_mean) ** 2).sum())

    def _endpoint(y: np.ndarray) -> float:
        y_mean = y.mean()
        slope = float(((x - x_mean) * (y - y_mean)).sum()) / denom
        intercept = y_mean - slope * x_mean
        return intercept + slope * (period - 1)

    return close.rolling(period).apply(_endpoint, raw=True)


# --- extended momentum / oscillators ------------------------------------------


def mom(close: pd.Series, period: int = 10) -> pd.Series:
    """Momentum: price change over ``period`` bars (absolute, not %)."""
    return close - close.shift(period)


def stochrsi(
    close: pd.Series, rsi_period: int = 14, stoch_period: int = 14, k: int = 3, d: int = 3
) -> pd.DataFrame:
    """Stochastic RSI: a stochastic oscillator applied to RSI (range 0-100)."""
    r = rsi(close, rsi_period)
    low_min = r.rolling(stoch_period).min()
    high_max = r.rolling(stoch_period).max()
    raw = 100 * (r - low_min) / (high_max - low_min).replace(0, np.nan)
    k_line = raw.rolling(k).mean()
    d_line = k_line.rolling(d).mean()
    return pd.DataFrame({"k": k_line, "d": d_line})


def tsi(close: pd.Series, long: int = 25, short: int = 13) -> pd.Series:
    """True Strength Index: double-smoothed momentum oscillator (range ~-100..100)."""
    mom_ = close.diff()
    abs_mom = mom_.abs()
    smooth = ema(ema(mom_, long), short)
    abs_smooth = ema(ema(abs_mom, long), short).replace(0, np.nan)
    return 100 * smooth / abs_smooth


def ao(df: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.Series:
    """Awesome Oscillator: SMA(median,5) - SMA(median,34)."""
    median = (df["high"] + df["low"]) / 2
    return sma(median, fast) - sma(median, slow)


def ppo(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Percentage Price Oscillator: MACD expressed as a percentage of the slow EMA."""
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow).replace(0, np.nan)
    ppo_line = 100 * (fast_ema - slow_ema) / slow_ema
    signal_line = ema(ppo_line, signal)
    return pd.DataFrame({"ppo": ppo_line, "signal": signal_line, "hist": ppo_line - signal_line})


def cmo(close: pd.Series, period: int = 14) -> pd.Series:
    """Chande Momentum Oscillator (range -100..100)."""
    delta = close.diff()
    up = delta.clip(lower=0).rolling(period).sum()
    down = (-delta.clip(upper=0)).rolling(period).sum()
    denom = (up + down).replace(0, np.nan)
    return 100 * (up - down) / denom


def uo(df: pd.DataFrame, short: int = 7, medium: int = 14, long: int = 28) -> pd.Series:
    """Ultimate Oscillator: weighted buying pressure across three timeframes."""
    prev_close = df["close"].shift(1)
    bp = df["close"] - pd.concat([df["low"], prev_close], axis=1).min(axis=1)
    tr = pd.concat([df["high"], prev_close], axis=1).max(axis=1) - pd.concat(
        [df["low"], prev_close], axis=1
    ).min(axis=1)
    tr = tr.replace(0, np.nan)

    def _avg(n: int) -> pd.Series:
        return bp.rolling(n).sum() / tr.rolling(n).sum()

    return 100 * (4 * _avg(short) + 2 * _avg(medium) + _avg(long)) / 7


def dpo(close: pd.Series, period: int = 20) -> pd.Series:
    """Detrended Price Oscillator: price minus a displaced SMA."""
    shift = period // 2 + 1
    return close - sma(close, period).shift(shift)


def trix(close: pd.Series, period: int = 15) -> pd.Series:
    """TRIX: rate of change of a triple-smoothed EMA, as a percentage."""
    e3 = ema(ema(ema(close, period), period), period)
    return 100 * e3.diff() / e3.shift(1).replace(0, np.nan)


def coppock(close: pd.Series, wma_period: int = 10, roc1: int = 14, roc2: int = 11) -> pd.Series:
    """Coppock Curve: WMA of summed long-term rate-of-change."""
    return wma(roc(close, roc1) + roc(close, roc2), wma_period)


def kst(close: pd.Series) -> pd.DataFrame:
    """Know Sure Thing: weighted sum of four smoothed ROCs, plus signal."""
    r1 = sma(roc(close, 10), 10)
    r2 = sma(roc(close, 15), 10)
    r3 = sma(roc(close, 20), 10)
    r4 = sma(roc(close, 30), 15)
    line = r1 * 1 + r2 * 2 + r3 * 3 + r4 * 4
    return pd.DataFrame({"kst": line, "signal": sma(line, 9)})


def fisher(df: pd.DataFrame, period: int = 9) -> pd.DataFrame:
    """Fisher Transform of price (sharp turning-point oscillator) + trigger."""
    median = ((df["high"] + df["low"]) / 2).to_numpy(dtype=float)
    n = len(median)
    low = pd.Series(median).rolling(period).min().to_numpy()
    high = pd.Series(median).rolling(period).max().to_numpy()
    val = np.zeros(n)
    fish = np.full(n, np.nan)
    prev_val = 0.0
    prev_fish = 0.0
    for i in range(n):
        rng = high[i] - low[i]
        if np.isnan(rng) or rng == 0:
            continue
        x = 0.66 * ((median[i] - low[i]) / rng - 0.5) + 0.67 * prev_val
        x = min(max(x, -0.999), 0.999)
        val[i] = x
        f = 0.5 * np.log((1 + x) / (1 - x)) + 0.5 * prev_fish
        fish[i] = f
        prev_val = x
        prev_fish = f
    series = pd.Series(fish, index=df.index)
    return pd.DataFrame({"fisher": series, "trigger": series.shift(1)})


def rvi(df: pd.DataFrame, period: int = 10) -> pd.DataFrame:
    """Relative Vigor Index: closing strength relative to range, plus signal."""
    co = df["close"] - df["open"]
    hl = df["high"] - df["low"]
    num = co + 2 * co.shift(1) + 2 * co.shift(2) + co.shift(3)
    den = hl + 2 * hl.shift(1) + 2 * hl.shift(2) + hl.shift(3)
    rvi_line = num.rolling(period).sum() / den.rolling(period).sum().replace(0, np.nan)
    signal = (rvi_line + 2 * rvi_line.shift(1) + 2 * rvi_line.shift(2) + rvi_line.shift(3)) / 6
    return pd.DataFrame({"rvi": rvi_line, "signal": signal})


# --- extended volatility ------------------------------------------------------


def stdev(close: pd.Series, period: int = 20) -> pd.Series:
    """Rolling population standard deviation of close."""
    return close.rolling(period).std(ddof=0)


def natr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Normalized ATR: ATR as a percentage of close."""
    return 100 * atr(df, period) / df["close"].replace(0, np.nan)


def hv(close: pd.Series, period: int = 20) -> pd.Series:
    """Historical volatility: rolling std of log returns, as a percentage (per bar)."""
    log_ret = np.log(close / close.shift(1))
    return 100 * log_ret.rolling(period).std(ddof=0)


def chop(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Choppiness Index (0-100): high = choppy/ranging, low = trending."""
    tr = _true_range(df)
    atr_sum = tr.rolling(period).sum()
    high_max = df["high"].rolling(period).max()
    low_min = df["low"].rolling(period).min()
    rng = (high_max - low_min).replace(0, np.nan)
    return 100 * np.log10(atr_sum / rng) / np.log10(period)


def ulcer(close: pd.Series, period: int = 14) -> pd.Series:
    """Ulcer Index: RMS of percentage drawdown over the window (downside risk)."""
    roll_max = close.rolling(period).max()
    drawdown = 100 * (close - roll_max) / roll_max
    return np.sqrt((drawdown**2).rolling(period).mean())


def massindex(df: pd.DataFrame, period: int = 25, ema_period: int = 9) -> pd.Series:
    """Mass Index: range-expansion reversal indicator."""
    rng = df["high"] - df["low"]
    e1 = ema(rng, ema_period)
    e2 = ema(e1, ema_period).replace(0, np.nan)
    return (e1 / e2).rolling(period).sum()


# --- extended volume ----------------------------------------------------------


def _money_flow_volume(df: pd.DataFrame) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    return (mfm * df["volume"]).fillna(0.0)


def adl(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution Line (cumulative money-flow volume)."""
    return _money_flow_volume(df).cumsum()


def cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Chaikin Money Flow (range -1..1)."""
    mfv = _money_flow_volume(df)
    vol = df["volume"].rolling(period).sum().replace(0, np.nan)
    return mfv.rolling(period).sum() / vol


def chaikinosc(df: pd.DataFrame, fast: int = 3, slow: int = 10) -> pd.Series:
    """Chaikin Oscillator: EMA(fast) - EMA(slow) of the A/D line."""
    line = adl(df)
    return ema(line, fast) - ema(line, slow)


def eom(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Ease of Movement: price change per unit of volume, smoothed."""
    median = (df["high"] + df["low"]) / 2
    distance = median.diff()
    box_ratio = (df["volume"] / 1e8) / (df["high"] - df["low"]).replace(0, np.nan)
    emv = distance / box_ratio.replace(0, np.nan)
    return sma(emv, period)


def fi(df: pd.DataFrame, period: int = 13) -> pd.Series:
    """Elder's Force Index: price change times volume, EMA-smoothed."""
    raw = df["close"].diff() * df["volume"]
    return ema(raw, period)


def pvt(df: pd.DataFrame) -> pd.Series:
    """Price Volume Trend: cumulative volume weighted by percentage price change."""
    return (df["close"].pct_change() * df["volume"]).fillna(0.0).cumsum()


def vo(df: pd.DataFrame, fast: int = 5, slow: int = 10) -> pd.Series:
    """Volume Oscillator: percentage spread between fast and slow volume EMAs."""
    fast_ema = ema(df["volume"], fast)
    slow_ema = ema(df["volume"], slow).replace(0, np.nan)
    return 100 * (fast_ema - slow_ema) / slow_ema


def klinger(
    df: pd.DataFrame, fast: int = 34, slow: int = 55, signal: int = 13
) -> pd.DataFrame:
    """Klinger Volume Oscillator: long-term volume-force trend, plus signal."""
    hlc = (df["high"] + df["low"] + df["close"]).to_numpy(dtype=float)
    dm = (df["high"] - df["low"]).to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)
    n = len(hlc)
    vforce = np.full(n, np.nan)
    trend_prev = 0
    cm_prev = 0.0
    dm_prev = 0.0
    for i in range(1, n):
        trend = 1 if hlc[i] > hlc[i - 1] else -1
        cm = (cm_prev + dm[i]) if trend == trend_prev else (dm_prev + dm[i])
        ratio = abs(2 * (dm[i] / cm - 1)) if cm else 0.0
        vforce[i] = volume[i] * trend * ratio * 100
        trend_prev, cm_prev, dm_prev = trend, cm, dm[i]
    vf = pd.Series(vforce, index=df.index)
    kvo = ema(vf, fast) - ema(vf, slow)
    return pd.DataFrame({"kvo": kvo, "signal": ema(kvo, signal)})


# --- extended trend / directional ---------------------------------------------


def aroon(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Aroon Up/Down and Oscillator: time since the window's high/low (0-100)."""

    def _since_high(x: np.ndarray) -> float:
        return float(np.argmax(x[::-1]))

    def _since_low(x: np.ndarray) -> float:
        return float(np.argmin(x[::-1]))

    win = period + 1
    since_high = df["high"].rolling(win).apply(_since_high, raw=True)
    since_low = df["low"].rolling(win).apply(_since_low, raw=True)
    up = 100 * (period - since_high) / period
    down = 100 * (period - since_low) / period
    return pd.DataFrame({"up": up, "down": down, "oscillator": up - down})


def vortex(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Vortex Indicator: VI+ and VI- capturing directional trend movement."""
    tr = _true_range(df)
    vm_plus = (df["high"] - df["low"].shift(1)).abs()
    vm_minus = (df["low"] - df["high"].shift(1)).abs()
    tr_sum = tr.rolling(period).sum().replace(0, np.nan)
    return pd.DataFrame(
        {
            "vi_plus": vm_plus.rolling(period).sum() / tr_sum,
            "vi_minus": vm_minus.rolling(period).sum() / tr_sum,
        }
    )


def dmi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Directional Movement Index: ADX with its +DI / -DI components."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )
    atr_ = _wilder_rma_series(_true_range(df), period)
    plus_di = 100 * _wilder_rma_series(plus_dm, period) / atr_
    minus_di = 100 * _wilder_rma_series(minus_dm, period) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame(
        {"adx": _wilder_rma_series(dx, period), "plus_di": plus_di, "minus_di": minus_di}
    )


# --- adaptive / composite (Pine & crypto favorites) ---------------------------


def vidya(close: pd.Series, period: int = 14) -> pd.Series:
    """Chande's Variable Index Dynamic Average: EMA whose alpha scales with CMO."""
    k = 2 / (period + 1)
    vol_index = (cmo(close, period).abs() / 100).to_numpy()
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    seed = None
    for i in range(n):
        if np.isnan(arr[i]):
            continue
        if seed is None:
            out[i] = arr[i]
            seed = i
            continue
        vi = vol_index[i]
        # No measurable volatility (flat / undefined CMO) -> hold the prior value.
        alpha = 0.0 if np.isnan(vi) else k * vi
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=close.index)


def t3(close: pd.Series, period: int = 5, vfactor: float = 0.7) -> pd.Series:
    """Tillson T3: six chained EMAs blended for a smooth, low-lag overlay."""
    e1 = ema(close, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    e4 = ema(e3, period)
    e5 = ema(e4, period)
    e6 = ema(e5, period)
    v = vfactor
    c1 = -(v**3)
    c2 = 3 * v**2 + 3 * v**3
    c3 = -6 * v**2 - 3 * v - 3 * v**3
    c4 = 1 + 3 * v + v**3 + 3 * v**2
    return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


def elderray(df: pd.DataFrame, period: int = 13) -> pd.DataFrame:
    """Elder Ray: bull power (high - EMA) and bear power (low - EMA)."""
    basis = ema(df["close"], period)
    return pd.DataFrame({"bull_power": df["high"] - basis, "bear_power": df["low"] - basis})


def zscore(close: pd.Series, period: int = 20) -> pd.Series:
    """Rolling z-score of price (standard deviations from the mean)."""
    mean = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0).replace(0, np.nan)
    return (close - mean) / std


def linregslope(close: pd.Series, period: int = 14) -> pd.Series:
    """Slope of the rolling linear-regression line (per-bar price change)."""
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    denom = float(((x - x_mean) ** 2).sum())

    def _slope(y: np.ndarray) -> float:
        return float(((x - x_mean) * (y - y.mean())).sum()) / denom

    return close.rolling(period).apply(_slope, raw=True)


def wavetrend(df: pd.DataFrame, channel: int = 10, average: int = 21) -> pd.DataFrame:
    """LazyBear WaveTrend oscillator (wt1 line and wt2 SMA signal)."""
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ema(ap, channel)
    d = ema((ap - esa).abs(), channel)
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ema(ci, average)
    wt2 = sma(wt1, 4)
    return pd.DataFrame({"wt1": wt1, "wt2": wt2})


def squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_mult: float = 2.0,
    kc_period: int = 20,
    kc_mult: float = 1.5,
) -> pd.DataFrame:
    """LazyBear Squeeze Momentum: momentum histogram + BB-in-KC squeeze state."""
    close = df["close"]
    basis = sma(close, bb_period)
    dev = bb_mult * close.rolling(bb_period).std(ddof=0)
    upper_bb, lower_bb = basis + dev, basis - dev
    ma = sma(close, kc_period)
    range_ma = sma(_true_range(df), kc_period)
    upper_kc, lower_kc = ma + range_ma * kc_mult, ma - range_ma * kc_mult
    sqz_on = (lower_bb > lower_kc) & (upper_bb < upper_kc)
    sqz_off = (lower_bb < lower_kc) & (upper_bb > upper_kc)
    state = pd.Series(np.where(sqz_on, 1.0, np.where(sqz_off, -1.0, 0.0)), index=df.index)

    highest = df["high"].rolling(kc_period).max()
    lowest = df["low"].rolling(kc_period).min()
    m2 = (((highest + lowest) / 2) + sma(close, kc_period)) / 2
    source = close - m2
    x = np.arange(kc_period, dtype=float)
    x_mean = x.mean()
    denom = float(((x - x_mean) ** 2).sum())

    def _endpoint(y: np.ndarray) -> float:
        y_mean = y.mean()
        slope = float(((x - x_mean) * (y - y_mean)).sum()) / denom
        return (y_mean - slope * x_mean) + slope * (kc_period - 1)

    momentum = source.rolling(kc_period).apply(_endpoint, raw=True)
    return pd.DataFrame({"momentum": momentum, "squeeze": state})


def qqe(df: pd.DataFrame, rsi_period: int = 14, smooth: int = 5, factor: float = 4.236) -> pd.DataFrame:
    """Quantitative Qualitative Estimation: smoothed RSI with a volatility trail."""
    rsi_ma = ema(rsi(df["close"], rsi_period), smooth)
    wilders = rsi_period * 2 - 1
    atr_rsi = rsi_ma.diff().abs()
    ma_atr_rsi = ema(atr_rsi, wilders)
    dar = ema(ma_atr_rsi, wilders) * factor
    rsi_arr = rsi_ma.to_numpy(dtype=float)
    dar_arr = dar.to_numpy(dtype=float)
    n = len(rsi_arr)
    trail = np.full(n, np.nan)
    prev_tl = None
    for i in range(n):
        if np.isnan(rsi_arr[i]) or np.isnan(dar_arr[i]):
            continue
        if prev_tl is None:
            trail[i] = rsi_arr[i]
            prev_tl = trail[i]
            continue
        rsi_v, d = rsi_arr[i], dar_arr[i]
        new_tl = max(prev_tl, rsi_v - d) if rsi_v > prev_tl else min(prev_tl, rsi_v + d)
        trail[i] = new_tl
        prev_tl = new_tl
    return pd.DataFrame({"rsi_ma": rsi_ma, "signal": pd.Series(trail, index=df.index)})


def crsi(close: pd.Series, rsi_period: int = 3, streak_period: int = 2, rank_period: int = 100) -> pd.Series:
    """Connors RSI: blend of price RSI, streak RSI, and ROC percent-rank."""
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    streak = np.zeros(n)
    for i in range(1, n):
        if arr[i] > arr[i - 1]:
            streak[i] = streak[i - 1] + 1 if streak[i - 1] > 0 else 1
        elif arr[i] < arr[i - 1]:
            streak[i] = streak[i - 1] - 1 if streak[i - 1] < 0 else -1
        else:
            streak[i] = 0
    rsi_price = rsi(close, rsi_period)
    rsi_streak = rsi(pd.Series(streak, index=close.index), streak_period)
    roc1 = close.pct_change() * 100

    def _percent_rank(x: np.ndarray) -> float:
        # Pine ta.percentrank: % of the prior `rank_period` values <= current.
        return float((x[:-1] <= x[-1]).sum()) / rank_period * 100.0

    rank = roc1.rolling(rank_period + 1).apply(_percent_rank, raw=True)
    return (rsi_price + rsi_streak + rank) / 3


def stc(close: pd.Series, fast: int = 23, slow: int = 50, cycle: int = 10) -> pd.Series:
    """Schaff Trend Cycle: a double-stochastic of MACD (0-100, fast cycle)."""
    macd_line = ema(close, fast) - ema(close, slow)

    def _stoch(series: pd.Series, length: int) -> pd.Series:
        low_min = series.rolling(length).min()
        high_max = series.rolling(length).max()
        return 100 * (series - low_min) / (high_max - low_min).replace(0, np.nan)

    k1 = _stoch(macd_line, cycle)
    d1 = k1.ewm(span=3, adjust=False).mean()
    k2 = _stoch(d1, cycle)
    return k2.ewm(span=3, adjust=False).mean()


def vwapbands(df: pd.DataFrame, mult: float = 1.0) -> pd.DataFrame:
    """VWAP with standard-deviation bands (volume-weighted)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    vwap_line = (typical * df["volume"]).cumsum() / cum_vol
    variance = (df["volume"] * (typical - vwap_line) ** 2).cumsum() / cum_vol
    dev = np.sqrt(variance.clip(lower=0))
    return pd.DataFrame(
        {"vwap": vwap_line, "upper": vwap_line + mult * dev, "lower": vwap_line - mult * dev}
    )


# --- price-structure transforms -----------------------------------------------


def heikinashi(df: pd.DataFrame) -> pd.DataFrame:
    """Heikin Ashi candle transform (smoothed open/high/low/close)."""
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    open_arr = df["open"].to_numpy(dtype=float)
    close_hp = ha_close.to_numpy(dtype=float)
    n = len(open_arr)
    ha_open = np.full(n, np.nan)
    if n:
        ha_open[0] = (open_arr[0] + df["close"].to_numpy(dtype=float)[0]) / 2
        for i in range(1, n):
            ha_open[i] = (ha_open[i - 1] + close_hp[i - 1]) / 2
    ha_open_s = pd.Series(ha_open, index=df.index)
    ha_high = pd.concat([df["high"], ha_open_s, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df["low"], ha_open_s, ha_close], axis=1).min(axis=1)
    return pd.DataFrame(
        {"open": ha_open_s, "high": ha_high, "low": ha_low, "close": ha_close}
    )


def pivots(df: pd.DataFrame) -> pd.DataFrame:
    """Classic floor pivot points projected from each prior bar's H/L/C."""
    high = df["high"].shift(1)
    low = df["low"].shift(1)
    close = df["close"].shift(1)
    pp = (high + low + close) / 3
    return pd.DataFrame(
        {
            "pp": pp,
            "r1": 2 * pp - low,
            "s1": 2 * pp - high,
            "r2": pp + (high - low),
            "s2": pp - (high - low),
            "r3": high + 2 * (pp - low),
            "s3": low - 2 * (high - pp),
        }
    )


# --- spec parsing & orchestration --------------------------------------------


# Pine Script aliases -> engine indicator names (leverages TradingView fluency).
_PINE_ALIASES = {
    "wpr": "willr",
    "williamsr": "willr",
    "bb": "bbands",
    "kc": "keltner",
    "dc": "donchian",
    "tr": "atr",
    "stochastic": "stoch",
    "ad": "adl",
    "vi": "vortex",
    "wt": "wavetrend",
    "sqz": "squeeze",
    "ha": "heikinashi",
    "connorsrsi": "crsi",
    "bbpower": "elderray",
}


def parse_spec(spec: str) -> tuple[str, list[float]]:
    """Parse an indicator spec into ``(name, [params])``.

    Accepts the native ``"name:p1,p2"`` form and Pine Script-style forms such
    as ``"ta.rsi(14)"`` or ``"ema(20)"`` (the ``ta.`` prefix and the function-
    call parentheses are normalized away), plus common Pine aliases.
    """
    text = spec.strip()
    if text.lower().startswith("ta."):
        text = text[3:]
    # ``name(args)`` (Pine call form) -> ``name:args``
    if "(" in text and text.rstrip().endswith(")"):
        head, _, tail = text.partition("(")
        text = head.strip() + ":" + tail.rstrip()[:-1]
    name, _, raw_params = text.partition(":")
    name = name.strip().lower()
    name = _PINE_ALIASES.get(name, name)
    params: list[float] = []
    if raw_params:
        for part in raw_params.split(","):
            part = part.strip()
            if not part:
                continue
            params.append(float(part) if "." in part else int(part))
    return name, params


def series_for(df: pd.DataFrame, ref: str) -> pd.Series:
    """Resolve a spec/price-ref/constant to a single aligned pandas Series.

    Used by crossover and divergence analysis. ``ref`` may be a numeric
    constant (``"30"``), a price source (``close|open|high|low|volume|hl2|
    hlc3|ohlc4``), or any indicator spec (``"ema:20"``, ``"ta.rsi(14)"``);
    multi-output indicators resolve to their primary line.
    """
    text = ref.strip()
    try:
        return pd.Series(float(text), index=df.index, dtype=float)
    except ValueError:
        pass
    low = text.lower()
    if low in ("close", "open", "high", "low", "volume"):
        return df[low].astype(float)
    if low == "hl2":
        return (df["high"] + df["low"]) / 2
    if low in ("hlc3", "typical"):
        return (df["high"] + df["low"] + df["close"]) / 3
    if low == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4

    name, params = parse_spec(text)
    ind = REGISTRY.get(name)
    if ind is None:
        raise ValueError(f"cannot resolve series for '{ref}'")
    return _primary_series(ind, _raw(ind, df, params))


def cross_state(a: pd.Series, b: pd.Series) -> str:
    """Pine ``ta.crossover``/``ta.crossunder`` on the latest bar."""
    diff = (a - b).dropna()
    if len(diff) < 2:
        return "none"
    prev, cur = diff.iloc[-2], diff.iloc[-1]
    if prev <= 0 < cur:
        return "crossover"
    if prev >= 0 > cur:
        return "crossunder"
    return "none"


def bars_since_cross(a: pd.Series, b: pd.Series) -> int | None:
    """Number of bars since the most recent sign change of ``a - b``."""
    diff = (a - b).dropna().to_numpy()
    if len(diff) < 2:
        return None
    sign = np.sign(diff)
    for back in range(1, len(sign)):
        if sign[-1] != 0 and sign[-1 - back] != 0 and sign[-1 - back] != sign[-1]:
            return back
    return None


def _key(name: str, params: list[float]) -> str:
    if not params:
        return name
    return name + "_" + "_".join(str(int(p) if p == int(p) else p) for p in params)


def max_period(specs: list[str]) -> int:
    """Largest lookback period across indicator specs (for warmup sizing).

    Lets the service fetch enough candles that even long-period indicators
    (e.g. ``ema:200``) produce a valid latest value regardless of the caller's
    ``limit``. Uses the explicit params when given, else the registry's default
    warmup for that indicator.
    """
    longest = 0
    for spec in specs:
        try:
            name, params = parse_spec(spec)
        except (ValueError, TypeError):
            continue
        if params:
            period = int(max(params))
        else:
            ind = REGISTRY.get(name)
            period = ind.warmup if ind is not None else 20
        longest = max(longest, period)
    return longest


def _last(series: pd.Series) -> float | None:
    series = series.dropna()
    if series.empty:
        return None
    return round(float(series.iloc[-1]), 6)


def _rsi_state(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 70:
        return "overbought"
    if value <= 30:
        return "oversold"
    return "neutral"


def _macd_cross(frame: pd.DataFrame) -> str:
    hist = frame["hist"].dropna()
    if len(hist) < 2:
        return "none"
    prev, cur = hist.iloc[-2], hist.iloc[-1]
    if prev <= 0 < cur:
        return "bullish"
    if prev >= 0 > cur:
        return "bearish"
    return "none"


def _direction_state(direction: pd.Series) -> str:
    d = direction.dropna()
    if d.empty:
        return "unknown"
    return "up" if d.iloc[-1] > 0 else "down"


def _flip_state(direction: pd.Series) -> str:
    """Detect a trend flip on the latest bar for direction-based indicators."""
    d = direction.dropna()
    if len(d) < 2:
        return "none"
    prev, cur = d.iloc[-2], d.iloc[-1]
    if prev <= 0 < cur:
        return "bullish"
    if prev >= 0 > cur:
        return "bearish"
    return "none"


def _ichimoku_signal(close: pd.Series, frame: pd.DataFrame) -> str:
    """Price position relative to the Ichimoku cloud (kumo)."""
    price = _last(close)
    a = _last(frame["senkou_a"])
    b = _last(frame["senkou_b"])
    if price is None or a is None or b is None:
        return "unknown"
    top, bottom = max(a, b), min(a, b)
    if price > top:
        return "above_cloud"
    if price < bottom:
        return "below_cloud"
    return "in_cloud"


def _zero_cross(series: pd.Series) -> str:
    """Bullish/bearish on the latest zero-line crossing of an oscillator."""
    s = series.dropna()
    if len(s) < 2:
        return "none"
    prev, cur = s.iloc[-2], s.iloc[-1]
    if prev <= 0 < cur:
        return "bullish"
    if prev >= 0 > cur:
        return "bearish"
    return "none"


# --- indicator registry ------------------------------------------------------


@dataclass(frozen=True)
class _Ind:
    """One indicator's wiring: function, defaults, output shaping, warmup."""

    fn: Callable[..., pd.Series | pd.DataFrame]
    defaults: tuple[float, ...] = ()
    source: str = "close"  # "close" -> fn(df["close"], *params); "df" -> fn(df, *params)
    primary: str | None = None  # frame column treated as the indicator's main line
    finalize: Callable[[Any, pd.DataFrame], dict[str, Any]] | None = None
    warmup: int = 20  # default lookback when no params are given
    series: bool = True  # expose the primary line under include_series


def _resolve_args(defaults: tuple[float, ...], params: list[float]) -> list[float]:
    """Fill missing trailing params from defaults; ignore extras."""
    return [params[i] if i < len(params) else defaults[i] for i in range(len(defaults))]


def _raw(ind: _Ind, df: pd.DataFrame, params: list[float]) -> pd.Series | pd.DataFrame:
    args = _resolve_args(ind.defaults, params)
    src: Any = df if ind.source == "df" else df["close"]
    return ind.fn(src, *args)


def _primary_series(ind: _Ind, raw: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(raw, pd.Series):
        return raw
    col = ind.primary or str(raw.columns[0])
    return raw[col]


def _series_list(s: pd.Series) -> list[float | None]:
    return s.round(6).where(s.notna(), None).tolist()


# --- output finalizers (raw, df) -> result dict ------------------------------


def _fin_default(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    if isinstance(raw, pd.Series):
        return {"value": _last(raw)}
    return {col: _last(raw[col]) for col in raw.columns}


def _fin_rsi(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    value = _last(raw)
    return {"value": value, "state": _rsi_state(value)}


def _fin_zero(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    return {"value": _last(raw), "cross": _zero_cross(raw)}


def _fin_macd(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    return {
        "macd": _last(raw["macd"]),
        "signal": _last(raw["signal"]),
        "hist": _last(raw["hist"]),
        "cross": _macd_cross(raw),
    }


def _fin_ppo(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    return {
        "ppo": _last(raw["ppo"]),
        "signal": _last(raw["signal"]),
        "hist": _last(raw["hist"]),
        "cross": _zero_cross(raw["hist"]),
    }


def _fin_stochrsi(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    k = _last(raw["k"])
    return {"k": k, "d": _last(raw["d"]), "state": _rsi_state(k)}


def _fin_supertrend(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    return {
        "value": _last(raw["supertrend"]),
        "direction": _direction_state(raw["direction"]),
        "flip": _flip_state(raw["direction"]),
    }


def _fin_psar(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    return {
        "value": _last(raw["psar"]),
        "direction": _direction_state(raw["direction"]),
        "flip": _flip_state(raw["direction"]),
    }


def _fin_ichimoku(raw: Any, df: pd.DataFrame) -> dict[str, Any]:
    return {
        "tenkan": _last(raw["tenkan"]),
        "kijun": _last(raw["kijun"]),
        "senkou_a": _last(raw["senkou_a"]),
        "senkou_b": _last(raw["senkou_b"]),
        "signal": _ichimoku_signal(df["close"], raw),
    }


def _fin_two_line(line: str, signal: str) -> Callable[[Any, pd.DataFrame], dict[str, Any]]:
    """Finalizer factory for line+signal oscillators (adds a crossover state)."""

    def _fin(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
        return {
            line: _last(raw[line]),
            signal: _last(raw[signal]),
            "cross": cross_state(raw[line], raw[signal]),
        }

    return _fin


def _fin_dmi(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    return {
        "adx": _last(raw["adx"]),
        "plus_di": _last(raw["plus_di"]),
        "minus_di": _last(raw["minus_di"]),
        "trend": "bullish" if cross_state(raw["plus_di"], raw["minus_di"]) == "crossover"
        else "bearish" if cross_state(raw["plus_di"], raw["minus_di"]) == "crossunder"
        else ("up" if (_last(raw["plus_di"]) or 0) >= (_last(raw["minus_di"]) or 0) else "down"),
    }


def _fin_squeeze(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    state = _last(raw["squeeze"])
    return {
        "momentum": _last(raw["momentum"]),
        "squeeze": "on" if state == 1 else "off" if state == -1 else "none",
        "cross": _zero_cross(raw["momentum"]),
    }


def _fin_heikinashi(raw: Any, _df: pd.DataFrame) -> dict[str, Any]:
    o, c = _last(raw["open"]), _last(raw["close"])
    return {
        "open": o,
        "high": _last(raw["high"]),
        "low": _last(raw["low"]),
        "close": c,
        "trend": "bullish" if (o is not None and c is not None and c >= o) else "bearish",
    }


REGISTRY: dict[str, _Ind] = {
    # --- moving averages / overlays ---
    "sma": _Ind(sma, (20,), warmup=20),
    "ema": _Ind(ema, (20,), warmup=20),
    "wma": _Ind(wma, (20,), warmup=20),
    "smma": _Ind(smma, (7,), warmup=7),
    "dema": _Ind(dema, (20,), warmup=20),
    "tema": _Ind(tema, (20,), warmup=20),
    "hma": _Ind(hma, (20,), warmup=20),
    "vwma": _Ind(vwma, (20,), source="df", warmup=20),
    "zlema": _Ind(zlema, (20,), warmup=20),
    "alma": _Ind(alma, (9, 0.85, 6.0), warmup=9),
    "kama": _Ind(kama, (10, 2, 30), warmup=30),
    "trima": _Ind(trima, (20,), warmup=20),
    "lsma": _Ind(lsma, (20,), warmup=20),
    "vidya": _Ind(vidya, (14,), warmup=14),
    "t3": _Ind(t3, (5, 0.7), warmup=18),
    "vwap": _Ind(vwap, (), source="df", warmup=1),
    "vwapbands": _Ind(vwapbands, (1.0,), source="df", primary="vwap", warmup=1),
    "bbands": _Ind(bbands, (20, 2.0), primary="mid", warmup=20),
    "donchian": _Ind(donchian, (20,), source="df", primary="mid", warmup=20),
    "keltner": _Ind(keltner, (20, 2.0, 10), source="df", primary="mid", warmup=20),
    "supertrend": _Ind(
        supertrend, (10, 3.0), source="df", primary="supertrend",
        finalize=_fin_supertrend, warmup=10,
    ),
    "ichimoku": _Ind(
        ichimoku, (9, 26, 52), source="df", primary="tenkan",
        finalize=_fin_ichimoku, warmup=52,
    ),
    "psar": _Ind(psar, (0.02, 0.2), source="df", primary="psar", finalize=_fin_psar, warmup=2),
    # --- momentum / oscillators ---
    "rsi": _Ind(rsi, (14,), finalize=_fin_rsi, warmup=14),
    "stochrsi": _Ind(
        stochrsi, (14, 14, 3, 3), primary="k", finalize=_fin_stochrsi, warmup=28
    ),
    "macd": _Ind(macd, (12, 26, 9), primary="macd", finalize=_fin_macd, warmup=26),
    "ppo": _Ind(ppo, (12, 26, 9), primary="ppo", finalize=_fin_ppo, warmup=26),
    "stoch": _Ind(stoch, (14, 3, 3), source="df", primary="k", warmup=14),
    "cci": _Ind(cci, (20,), source="df", warmup=20),
    "willr": _Ind(willr, (14,), source="df", warmup=14),
    "roc": _Ind(roc, (12,), finalize=_fin_zero, warmup=12),
    "mom": _Ind(mom, (10,), finalize=_fin_zero, warmup=10),
    "tsi": _Ind(tsi, (25, 13), finalize=_fin_zero, warmup=25),
    "ao": _Ind(ao, (5, 34), source="df", finalize=_fin_zero, warmup=34),
    "cmo": _Ind(cmo, (14,), finalize=_fin_zero, warmup=14),
    "uo": _Ind(uo, (7, 14, 28), source="df", finalize=_fin_rsi, warmup=28),
    "dpo": _Ind(dpo, (20,), finalize=_fin_zero, warmup=20),
    "trix": _Ind(trix, (15,), finalize=_fin_zero, warmup=15),
    "coppock": _Ind(coppock, (10, 14, 11), finalize=_fin_zero, warmup=24),
    "kst": _Ind(kst, (), primary="kst", warmup=45),
    "fisher": _Ind(fisher, (9,), source="df", primary="fisher", warmup=9),
    "rvi": _Ind(rvi, (10,), source="df", primary="rvi", warmup=10),
    "mfi": _Ind(mfi, (14,), source="df", finalize=_fin_rsi, warmup=14),
    "wavetrend": _Ind(
        wavetrend, (10, 21), source="df", primary="wt1",
        finalize=_fin_two_line("wt1", "wt2"), warmup=21,
    ),
    "squeeze": _Ind(
        squeeze, (20, 2.0, 20, 1.5), source="df", primary="momentum",
        finalize=_fin_squeeze, warmup=20,
    ),
    "qqe": _Ind(
        qqe, (14, 5, 4.236), source="df", primary="rsi_ma",
        finalize=_fin_two_line("rsi_ma", "signal"), warmup=27,
    ),
    "crsi": _Ind(crsi, (3, 2, 100), finalize=_fin_rsi, warmup=100),
    "stc": _Ind(stc, (23, 50, 10), finalize=_fin_rsi, warmup=50),
    "zscore": _Ind(zscore, (20,), finalize=_fin_zero, warmup=20),
    "linregslope": _Ind(linregslope, (14,), finalize=_fin_zero, warmup=14),
    "elderray": _Ind(elderray, (13,), source="df", primary="bull_power", warmup=13),
    # --- volatility ---
    "atr": _Ind(atr, (14,), source="df", warmup=14),
    "natr": _Ind(natr, (14,), source="df", warmup=14),
    "stdev": _Ind(stdev, (20,), warmup=20),
    "hv": _Ind(hv, (20,), warmup=20),
    "chop": _Ind(chop, (14,), source="df", warmup=14),
    "ulcer": _Ind(ulcer, (14,), warmup=14),
    "massindex": _Ind(massindex, (25, 9), source="df", warmup=34),
    # --- volume ---
    "obv": _Ind(obv, (), source="df", warmup=1),
    "adl": _Ind(adl, (), source="df", warmup=1),
    "cmf": _Ind(cmf, (20,), source="df", warmup=20),
    "chaikinosc": _Ind(chaikinosc, (3, 10), source="df", finalize=_fin_zero, warmup=10),
    "eom": _Ind(eom, (14,), source="df", finalize=_fin_zero, warmup=14),
    "fi": _Ind(fi, (13,), source="df", finalize=_fin_zero, warmup=13),
    "pvt": _Ind(pvt, (), source="df", warmup=1),
    "vo": _Ind(vo, (5, 10), source="df", finalize=_fin_zero, warmup=10),
    "klinger": _Ind(klinger, (34, 55, 13), source="df", primary="kvo", warmup=55),
    # --- trend / directional ---
    "adx": _Ind(adx, (14,), source="df", warmup=28),
    "dmi": _Ind(dmi, (14,), source="df", primary="adx", finalize=_fin_dmi, warmup=28),
    "aroon": _Ind(aroon, (14,), source="df", primary="oscillator", warmup=14),
    "vortex": _Ind(vortex, (14,), source="df", primary="vi_plus", warmup=14),
    # --- price-structure transforms ---
    "heikinashi": _Ind(
        heikinashi, (), source="df", primary="close", finalize=_fin_heikinashi, warmup=2
    ),
    "pivots": _Ind(pivots, (), source="df", primary="pp", warmup=2),
}

SUPPORTED: tuple[str, ...] = tuple(REGISTRY)


def compute(
    df: pd.DataFrame, specs: list[str], *, include_series: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute indicators for the candle frame via the registry.

    Returns ``(results, series)`` where ``results`` holds each indicator's
    latest value(s) plus derived signals, and ``series`` holds the primary line
    per indicator when ``include_series`` is set. An unknown or failing
    indicator yields a per-key ``{"error": ...}`` without aborting the batch.
    """
    results: dict[str, Any] = {}
    series: dict[str, Any] = {}

    for spec in specs:
        try:
            name, params = parse_spec(spec)
        except (ValueError, TypeError) as exc:
            results[spec] = {"error": f"invalid spec '{spec}': {exc}"}
            continue
        key = _key(name, params)
        ind = REGISTRY.get(name)
        if ind is None:
            results[key] = {"error": f"unsupported indicator '{name}'"}
            continue
        try:
            raw = _raw(ind, df, params)
            results[key] = (ind.finalize or _fin_default)(raw, df)
            if include_series and ind.series:
                series[key] = _series_list(_primary_series(ind, raw))
        except Exception as exc:  # noqa: BLE001 - isolate one bad indicator
            results[key] = {"error": f"{name}: {exc}"}

    return results, series
