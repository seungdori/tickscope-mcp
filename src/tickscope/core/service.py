"""MarketDataService — the single coordinator all tools flow through.

Policy: warm cache first -> REST fallback (returns immediately) -> trigger
auto-watch so subsequent calls answer from the WebSocket buffer. Historical
OHLCV is served from DuckDB first, topping up only the missing tail via REST.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

import pandas as pd

from ..config import Settings
from ..utils import (
    DISCLAIMER,
    TickscopeError,
    age_ms,
    iso_or_ms_to_ms,
    ms_to_iso,
    normalize_symbol,
    now_iso,
)
from . import analysis, context, indicators_engine, signal_history, structure
from .cache import MarketCache
from .exchange_manager import ExchangeManager, ccxt_version
from .ingestion import IngestionManager
from .retry import with_retry
from .storage import OHLCVStore

_TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}

_TIMEFRAME_UNIT_MS = {
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
    "M": 2_592_000_000,  # 30-day month approximation
}


def timeframe_to_ms(timeframe: str) -> int:
    """Milliseconds for a ccxt timeframe (``"5m"``, ``"4h"``, ``"1d"``, ``"1M"``).

    Falls back to parsing ``<int><unit>`` for timeframes not in the common map
    so the freshness window never silently mis-sizes (e.g. ``"8h"``).
    """
    fixed = _TIMEFRAME_MS.get(timeframe)
    if fixed is not None:
        return fixed
    tf = timeframe.strip()
    if len(tf) >= 2 and tf[:-1].isdigit() and tf[-1] in _TIMEFRAME_UNIT_MS:
        return int(tf[:-1]) * _TIMEFRAME_UNIT_MS[tf[-1]]
    return 3_600_000  # last-resort default (1h)


class MarketDataService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.exchanges = ExchangeManager(settings.exchanges)
        self.cache = MarketCache(settings.ring_buffer_size)
        self.store = OHLCVStore(settings.resolved_cache_path)
        self.ingestion = IngestionManager(
            self.exchanges, self.cache, max_watched=settings.max_watched_symbols
        )
        # One REST concurrency gate per exchange (lazily created). Bounds the
        # number of simultaneous in-flight REST calls so that offloading CPU /
        # DuckDB work off the event loop never lets requests burst past an
        # exchange's rate limit. Works alongside ccxt's enableRateLimit pacing.
        self._rest_sems: dict[str, asyncio.Semaphore] = {}
        # Memoized signal event-studies, keyed by the last candle ts so the work
        # is reused for the whole bar and only recomputed once a new bar closes.
        self._signal_perf_memo: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
        self.started_at = time.time()

    # --- helpers --------------------------------------------------------
    def _exchange_id(self, exchange: str | None) -> str:
        return (exchange or self.settings.default_exchange).lower()

    def _rest_sem(self, label: str) -> asyncio.Semaphore:
        """Per-exchange REST concurrency gate (derived from the call label)."""
        ex = label.rsplit(":", 1)[-1] if ":" in label else "_"
        sem = self._rest_sems.get(ex)
        if sem is None:
            sem = asyncio.Semaphore(self.settings.rest_concurrency)
            self._rest_sems[ex] = sem
        return sem

    async def _rest(self, factory: Any, *, label: str) -> Any:
        """Run a REST coroutine factory with rate-limit-aware retry (§9.2).

        Acquires the per-exchange REST gate first so concurrent multi-symbol
        work cannot exceed ``rest_concurrency`` in-flight calls to one venue —
        REST stays on the event loop (never a worker thread), so ccxt's
        ``enableRateLimit`` pacing is always honoured.
        """
        async with self._rest_sem(label):
            return await with_retry(factory, retries=self.settings.rest_retries, label=label)

    @staticmethod
    def _warmup_limit(limit: int, period: int) -> int:
        """Candle count to fetch so a ``period``-bar indicator has enough warmup.

        Gives Wilder-smoothed / double-smoothed indicators room to converge
        (``2*period``) while honoring the caller's ``limit`` as a floor and
        capping at the 1000-candle REST ceiling. The buffer only raises the
        fetch when the period genuinely needs it, so a short request for a
        low-period or cumulative indicator (obv/vwap) stays at ``limit`` and
        keeps its requested anchor window.
        """
        if period <= 0:
            return limit
        return min(max(limit, period * 2 + 10), 1000)

    async def _normalize(self, exchange: str, symbol: str) -> str:
        try:
            markets = await self.exchanges.load_markets(exchange)
        except TickscopeError:
            markets = None
        return normalize_symbol(symbol, markets)

    # --- ticker ---------------------------------------------------------
    async def get_ticker(self, exchange: str | None, symbol: str) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)

        cached = self.cache.get_ticker(ex, sym)
        if cached is not None:
            self.ingestion.touch(ex, sym)
            return self._format_ticker(ex, sym, cached.data, "websocket", cached.age_ms)

        inst = await self.exchanges.get(ex)
        data = await self._rest(lambda: inst.fetch_ticker(sym), label=f"fetch_ticker:{ex}")
        await self.ingestion.ensure_watch(ex, sym, ("ticker", "trades"))
        return self._format_ticker(ex, sym, data, "rest", age_ms(data.get("timestamp")))

    @staticmethod
    def _format_ticker(
        exchange: str, symbol: str, t: dict[str, Any], source: str, ms_age: int | None
    ) -> dict[str, Any]:
        return {
            "exchange": exchange,
            "symbol": symbol,
            "last": t.get("last"),
            "bid": t.get("bid"),
            "ask": t.get("ask"),
            "high_24h": t.get("high"),
            "low_24h": t.get("low"),
            "volume_24h": t.get("baseVolume"),
            "change_24h_pct": t.get("percentage"),
            "timestamp": ms_to_iso(t.get("timestamp")) or now_iso(),
            "source": source,
            "age_ms": ms_age,
        }

    # --- recent trades --------------------------------------------------
    async def get_recent_trades(
        self, exchange: str | None, symbol: str, limit: int = 50
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        limit = max(1, min(limit, 1000))

        buf = self.cache.get_trades(ex, sym)
        if buf is not None and len(buf) > 0:
            self.ingestion.touch(ex, sym)
            items = buf.latest(limit)
            return {
                "exchange": ex,
                "symbol": sym,
                "count": len(items),
                "source": "websocket",
                "trades": [self._format_trade(t) for t in items],
            }

        inst = await self.exchanges.get(ex)
        raw = await self._rest(lambda: inst.fetch_trades(sym, limit=limit), label=f"fetch_trades:{ex}")
        await self.ingestion.ensure_watch(ex, sym, ("ticker", "trades"))
        # ccxt may ignore ``limit`` and return more rows; report the count of
        # what we actually return, mirroring the websocket branch.
        items = raw[-limit:]
        return {
            "exchange": ex,
            "symbol": sym,
            "count": len(items),
            "source": "rest",
            "trades": [self._format_trade(t) for t in items],
        }

    @staticmethod
    def _format_trade(t: dict[str, Any]) -> dict[str, Any]:
        return {
            "ts": ms_to_iso(t.get("timestamp")),
            "price": t.get("price"),
            "amount": t.get("amount"),
            "side": t.get("side"),
        }

    # --- orderbook ------------------------------------------------------
    async def get_orderbook(
        self, exchange: str | None, symbol: str, depth: int = 20
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        depth = max(1, min(depth, 100))

        cached = self.cache.get_orderbook(ex, sym)
        if cached is not None:
            self.ingestion.touch(ex, sym)
            return self._format_orderbook(ex, sym, cached.data, depth, "websocket", cached.age_ms)

        inst = await self.exchanges.get(ex)
        data = await self._rest(
            lambda: inst.fetch_order_book(sym, limit=depth), label=f"fetch_order_book:{ex}"
        )
        await self.ingestion.ensure_watch(ex, sym, ("orderbook",))
        return self._format_orderbook(ex, sym, data, depth, "rest", age_ms(data.get("timestamp")))

    @staticmethod
    def _format_orderbook(
        exchange: str,
        symbol: str,
        ob: dict[str, Any],
        depth: int,
        source: str,
        ms_age: int | None,
    ) -> dict[str, Any]:
        bids = [[b[0], b[1]] for b in (ob.get("bids") or [])[:depth]]
        asks = [[a[0], a[1]] for a in (ob.get("asks") or [])[:depth]]
        spread = None
        spread_pct = None
        if bids and asks:
            best_bid, best_ask = bids[0][0], asks[0][0]
            spread = round(best_ask - best_bid, 8)
            if best_bid:
                spread_pct = round((best_ask - best_bid) / best_bid * 100, 6)
        return {
            "exchange": exchange,
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "spread": spread,
            "spread_pct": spread_pct,
            "source": source,
            "age_ms": ms_age,
            "timestamp": ms_to_iso(ob.get("timestamp")) or now_iso(),
        }

    # --- OHLCV (DuckDB cache first) ------------------------------------
    async def _ohlcv_rows(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        since_ms: int | None = None,
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """Return numeric candle rows ``[ts,o,h,l,c,v]`` + meta (cache-first).

        Shared by :meth:`get_ohlcv` (which serializes to dicts) and the indicator
        path (which builds a DataFrame directly), so candles are never round-
        tripped through ISO-string dicts and re-parsed back to floats.
        """
        limit = max(1, min(limit, 1000))
        tf_ms = timeframe_to_ms(timeframe)
        now_ms = int(time.time() * 1000)
        ttl_ms = self.settings.ohlcv_cache_ttl_s * 1000

        # L1: serve a plain "last N closed candles" request straight from RAM,
        # skipping DuckDB *and* the exchange while the series is within TTL.
        # Closed candles are immutable, and the forming bar is re-overlaid from
        # the websocket each time, so this stays correct — and saves a REST call.
        if since_ms is None:
            mem = self.cache.get_recent_ohlcv(exchange, symbol, timeframe)
            if mem is not None:
                mem_rows, fetched_ms = mem
                if len(mem_rows) >= limit and (now_ms - fetched_ms) < ttl_ms:
                    return self._finalize_rows(
                        exchange, symbol, timeframe, mem_rows[-limit:], tf_ms, limit, hit=True
                    )

        # L2: DuckDB-backed cache, REST top-up on miss. DuckDB is synchronous,
        # so every call runs on a worker thread — a cold lookup never blocks the
        # event loop or the websocket ingestion that keeps the warm cache fresh.
        cached = await asyncio.to_thread(
            self.store.query, exchange, symbol, timeframe, since_ms=since_ms, limit=limit
        )
        latest_ts = await asyncio.to_thread(self.store.latest_ts, exchange, symbol, timeframe)

        # Fresh enough if it has the requested count and the newest candle is
        # within one timeframe + TTL of now.
        fresh = (
            len(cached) >= limit
            and latest_ts is not None
            and (now_ms - latest_ts) < (tf_ms + ttl_ms)
        )

        if fresh and since_ms is None:
            rows = cached[-limit:]
            hit = True
        else:
            inst = await self.exchanges.get(exchange)
            raw = await self._rest(
                lambda: inst.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit),
                label=f"fetch_ohlcv:{exchange}",
            )
            if raw:
                await asyncio.to_thread(self.store.upsert, exchange, symbol, timeframe, raw)
            rows = (
                await asyncio.to_thread(
                    self.store.query, exchange, symbol, timeframe, since_ms=since_ms, limit=limit
                )
            )[-limit:]
            hit = False

        # Refresh the L1 hot cache for the next call (plain recent request only).
        if since_ms is None and rows:
            self.cache.set_recent_ohlcv(exchange, symbol, timeframe, rows, now_ms)

        return self._finalize_rows(exchange, symbol, timeframe, rows, tf_ms, limit, hit=hit)

    def _finalize_rows(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        rows: list[list[float]],
        tf_ms: int,
        limit: int,
        *,
        hit: bool,
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """Overlay the live (forming) candle and assemble the response meta."""
        rows, live_age = self._overlay_live_candle(exchange, symbol, timeframe, rows, tf_ms)
        # The overlay may append the forming candle; keep the response at limit.
        rows = rows[-limit:]
        meta: dict[str, Any] = {
            "count": len(rows),
            "cache_hit": hit,
            "live": live_age is not None,
        }
        if live_age is not None:
            meta["live_candle_age_ms"] = live_age
        return rows, meta

    async def get_ohlcv(
        self,
        exchange: str | None,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 200,
        since: str | int | None = None,
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        since_ms = iso_or_ms_to_ms(since)
        rows, meta = await self._ohlcv_rows(ex, sym, timeframe, limit, since_ms)
        candles = [
            {
                "ts": ms_to_iso(int(r[0])),
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
            }
            for r in rows
        ]
        return {
            "exchange": ex,
            "symbol": sym,
            "timeframe": timeframe,
            "candles": candles,
            "meta": meta,
        }

    def _overlay_live_candle(
        self, exchange: str, symbol: str, timeframe: str, rows: list[list[float]], tf_ms: int
    ) -> tuple[list[list[float]], int | None]:
        """Overlay the live (forming) candle from the WS buffer onto ``rows``.

        Returns ``(rows, age_ms)``; ``age_ms`` is ``None`` when no live candle
        is being watched for this (exchange, symbol, timeframe). The forming
        candle replaces the last bar when it shares its timestamp, or is
        appended only when it is exactly the next timeframe boundary — never
        across a gap, which would feed a non-contiguous series to indicators.
        """
        live = self.cache.get_live_candle(exchange, symbol, timeframe)
        if live is None or not rows:
            return rows, None
        candle = list(live.data)
        live_ts = int(candle[0])
        last_ts = int(rows[-1][0])
        if live_ts == last_ts:
            rows = [*rows[:-1], candle]
        elif live_ts == last_ts + tf_ms:
            rows = [*rows, candle]
        else:
            # Stale tail or a multi-period gap: dropping the live candle is
            # safer than stitching a discontinuity into the candle series.
            return rows, None
        return rows, live.age_ms

    async def _ohlcv_dataframe(
        self, exchange: str, symbol: str, timeframe: str, limit: int, *, with_ts: bool = False
    ) -> pd.DataFrame:
        rows, _ = await self._ohlcv_rows(exchange, symbol, timeframe, limit)
        if not rows:
            raise TickscopeError(
                {
                    "error": {
                        "type": "NoData",
                        "message": f"No OHLCV data for {symbol} {timeframe}.",
                        "exchange": exchange,
                        "symbol": symbol,
                        "retryable": True,
                    }
                }
            )
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        ohlcv = df[["open", "high", "low", "close", "volume"]].astype(float)
        if with_ts:
            ohlcv.index = pd.Index([ms_to_iso(int(t)) for t in df["ts"]], name="ts")
        return ohlcv

    # --- price-structure recognition -----------------------------------
    async def detect_patterns(
        self, exchange: str | None, symbol: str, timeframe: str, limit: int, lookback: int
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        df = await self._ohlcv_dataframe(ex, sym, timeframe, max(limit, lookback + 10), with_ts=True)
        out = await asyncio.to_thread(structure.detect_candlestick_patterns, df, lookback=lookback)
        return {"exchange": ex, "symbol": sym, "timeframe": timeframe, "as_of": now_iso(), **out}

    async def analyze_structure(
        self, exchange: str | None, symbol: str, timeframe: str, limit: int, left: int, right: int
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        df = await self._ohlcv_dataframe(ex, sym, timeframe, max(limit, 60))
        out = await asyncio.to_thread(structure.market_structure, df, left=left, right=right)
        return {"exchange": ex, "symbol": sym, "timeframe": timeframe, "as_of": now_iso(), **out}

    async def find_support_resistance(
        self,
        exchange: str | None,
        symbol: str,
        timeframe: str,
        limit: int,
        tolerance_pct: float,
        max_levels: int,
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        df = await self._ohlcv_dataframe(ex, sym, timeframe, max(limit, 60))
        out = await asyncio.to_thread(
            structure.support_resistance,
            df,
            lookback=limit,
            tolerance_pct=tolerance_pct,
            max_levels=max_levels,
        )
        return {"exchange": ex, "symbol": sym, "timeframe": timeframe, "as_of": now_iso(), **out}

    # --- indicators -----------------------------------------------------
    async def compute_indicators(
        self,
        exchange: str | None,
        symbol: str,
        timeframe: str,
        limit: int,
        indicators: list[str],
        include_series: bool = False,
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        fetch = self._warmup_limit(limit, indicators_engine.max_period(indicators))
        df = await self._ohlcv_dataframe(ex, sym, timeframe, fetch)
        results, series = await asyncio.to_thread(
            indicators_engine.compute, df, indicators, include_series=include_series
        )
        # ★2 statistical / market-state context — near-free, makes every value
        # interpretable ("RSI 30 in a strong downtrend != RSI 30 in a range").
        ctx = await asyncio.to_thread(context.statistical_context, df)
        return {
            "exchange": ex,
            "symbol": sym,
            "timeframe": timeframe,
            "as_of": now_iso(),
            "results": results,
            "context": ctx,
            "series": series if include_series else None,
        }

    # --- divergence / cross --------------------------------------------
    async def detect_divergence(
        self,
        exchange: str | None,
        symbol: str,
        timeframe: str,
        limit: int,
        oscillator: str,
        left: int,
        right: int,
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        # Warmup must cover the oscillator period plus several pivot windows.
        period = indicators_engine.max_period([oscillator]) + 2 * max(left, right)
        df = await self._ohlcv_dataframe(ex, sym, timeframe, self._warmup_limit(limit, period))
        out = await asyncio.to_thread(
            analysis.detect_divergence, df, oscillator, left=left, right=right
        )
        return {"exchange": ex, "symbol": sym, "timeframe": timeframe, "as_of": now_iso(), **out}

    async def evaluate_cross(
        self,
        exchange: str | None,
        symbol: str,
        timeframe: str,
        limit: int,
        series_a: str,
        series_b: str,
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        period = indicators_engine.max_period([series_a, series_b])
        df = await self._ohlcv_dataframe(ex, sym, timeframe, self._warmup_limit(limit, period))
        out = await asyncio.to_thread(analysis.evaluate_cross, df, series_a, series_b)
        return {"exchange": ex, "symbol": sym, "timeframe": timeframe, "as_of": now_iso(), **out}

    # --- deep multi-timeframe analysis (★1 confluence + ★2 context + ★3 stats) ---
    DEFAULT_TF_LADDER = ("1d", "4h", "1h")

    async def deep_analyze(
        self,
        exchange: str | None,
        symbol: str,
        *,
        timeframes: list[str] | None = None,
        oscillator: str = "rsi:14",
        horizon: int = 10,
        history: int = 800,
    ) -> dict[str, Any]:
        """Multi-timeframe read + statistical context + historical signal stats.

        Heavier than the single-shot tools (several timeframes + an event study),
        so it is meant for "is this setup worth caring about?" questions rather
        than quick single-value lookups. Timeframes are fetched and computed
        concurrently and off the event loop, so warm reads stay fast.
        """
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        tfs = list(timeframes or self.DEFAULT_TF_LADDER) or list(self.DEFAULT_TF_LADDER)

        async def per_tf(tf: str) -> tuple[str, dict[str, Any]]:
            df = await self._ohlcv_dataframe(ex, sym, tf, 300)
            return tf, await asyncio.to_thread(self._tf_snapshot, df, oscillator)

        snaps = dict(await asyncio.gather(*(per_tf(tf) for tf in tfs)))

        # Historical signal performance on the execution (lowest) timeframe,
        # over a long window so the event study has enough occurrences.
        exec_tf = tfs[-1]
        perf = await self._signal_perf(ex, sym, exec_tf, oscillator, horizon, history)

        return {
            "exchange": ex,
            "symbol": sym,
            "as_of": now_iso(),
            "oscillator": oscillator,
            "timeframes": {tf: snaps[tf] for tf in tfs},
            "signal_history": perf,
            "verdict": self._synthesize(snaps, tfs, exec_tf, perf),
            "disclaimer": DISCLAIMER,
        }

    @staticmethod
    def _tf_snapshot(df: pd.DataFrame, oscillator: str) -> dict[str, Any]:
        """Per-timeframe read (runs in a worker thread): trend, momentum, context."""
        ms = structure.market_structure(df)
        rsi_last = indicators_engine.last(indicators_engine.rsi(df["close"], 14))
        div = analysis.detect_divergence(df, oscillator)
        return {
            "trend": ms["trend"],
            "events": ms["events"],
            "rsi": round(rsi_last, 1) if rsi_last is not None else None,
            "context": context.statistical_context(df),
            "divergences": div["divergences"],
        }

    async def _signal_perf(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        oscillator: str,
        horizon: int,
        history: int,
    ) -> dict[str, Any]:
        rows, _ = await self._ohlcv_rows(exchange, symbol, timeframe, history)
        if not rows:
            return {
                "signal": f"divergence({oscillator})",
                "bullish": {"count": 0},
                "bearish": {"count": 0},
            }
        # Memoize per last-closed bar: same bar -> reuse; new bar -> recompute.
        key = (exchange, symbol, timeframe, oscillator, horizon, int(rows[-1][0]), len(rows))
        cached = self._signal_perf_memo.get(key)
        if cached is not None:
            self._signal_perf_memo.move_to_end(key)
            return cached
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        perf = await asyncio.to_thread(
            signal_history.divergence_performance, df, oscillator, horizon=horizon
        )
        self._signal_perf_memo[key] = perf
        self._signal_perf_memo.move_to_end(key)
        while len(self._signal_perf_memo) > 128:
            self._signal_perf_memo.popitem(last=False)
        return perf

    @staticmethod
    def _synthesize(
        snaps: dict[str, dict[str, Any]],
        tfs: list[str],
        exec_tf: str,
        perf: dict[str, Any],
    ) -> dict[str, Any]:
        """Deterministic, explainable verdict from multi-TF trend + state + stats.

        The numeric reasoning is done here in Python (not left to the LLM eyeing
        raw values), which is the main guard against agent misjudgement.
        """
        trends = [snaps[tf]["trend"] for tf in tfs]
        up = trends.count("uptrend")
        down = trends.count("downtrend")
        bias = "bullish" if up > down else "bearish" if down > up else "neutral"
        agreement = max(up, down)
        score = agreement / len(tfs) if tfs else 0.0

        market_state = snaps[exec_tf].get("context", {}).get("trend_state")
        caveats: list[str] = []
        if market_state == "ranging":
            caveats.append(
                "Execution timeframe is ranging — trend/momentum signals are less reliable here."
            )
            score *= 0.7
        if up and down:
            caveats.append("Timeframes disagree on trend; treat the directional bias cautiously.")

        rel = perf.get(bias) if bias in ("bullish", "bearish") else None
        if isinstance(rel, dict) and 0 < rel.get("count", 0) < 5:
            caveats.append(
                f"Signal-history sample is small (n={rel['count']}); the statistics are noisy."
            )

        confidence = "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"
        return {
            "bias": bias,
            "confidence": confidence,
            "timeframe_agreement": f"{agreement}/{len(tfs)}",
            "trend_by_timeframe": {tf: snaps[tf]["trend"] for tf in tfs},
            "execution_market_state": market_state,
            "caveats": caveats,
        }

    # --- multi-exchange aggregation ------------------------------------
    async def get_aggregated_price(
        self, symbol: str, exchanges: list[str] | None = None
    ) -> dict[str, Any]:
        """Volume-weighted price and cross-exchange spread (arbitrage view)."""
        targets = [e.lower() for e in (exchanges or self.exchanges.configured)]
        sem = asyncio.Semaphore(self.settings.screen_concurrency)

        async def fetch(ex: str) -> dict[str, Any] | None:
            async with sem:
                try:
                    sym = await self._normalize(ex, symbol)
                    cached = self.cache.get_ticker(ex, sym)
                    source: str
                    ms_age: int | None
                    if cached is not None:
                        self.ingestion.touch(ex, sym)
                        t, source, ms_age = cached.data, "websocket", cached.age_ms
                    else:
                        inst = await self.exchanges.get(ex)
                        t = await self._rest(
                            lambda: inst.fetch_ticker(sym), label=f"fetch_ticker:{ex}"
                        )
                        await self.ingestion.ensure_watch(ex, sym, ("ticker",))
                        source, ms_age = "rest", age_ms(t.get("timestamp"))
                    if t.get("last") is None:
                        return None
                    return {
                        "exchange": ex,
                        "symbol": sym,
                        "last": t.get("last"),
                        "bid": t.get("bid"),
                        "ask": t.get("ask"),
                        "volume_24h": t.get("baseVolume"),
                        "source": source,
                        "age_ms": ms_age,
                    }
                except Exception:  # noqa: BLE001 - skip venues that fail/lack the symbol
                    return None

        quotes = [q for q in await asyncio.gather(*(fetch(e) for e in targets)) if q]
        if not quotes:
            raise TickscopeError(
                {
                    "error": {
                        "type": "NoData",
                        "message": f"No exchange returned a price for {symbol}.",
                        "exchange": None,
                        "symbol": symbol,
                        "retryable": True,
                    }
                }
            )
        prices = [q["last"] for q in quotes]
        weights = [q["volume_24h"] or 0.0 for q in quotes]
        total_w = sum(weights)
        if total_w > 0:
            vwap_price = sum(p * w for p, w in zip(prices, weights, strict=True)) / total_w
        else:
            vwap_price = sum(prices) / len(prices)
        best = max(quotes, key=lambda q: q["last"])
        worst = min(quotes, key=lambda q: q["last"])
        spread = best["last"] - worst["last"]
        spread_pct = (spread / worst["last"] * 100) if worst["last"] else None
        return {
            "symbol": symbol,
            "exchange_count": len(quotes),
            "weighted_avg": round(vwap_price, 8),
            "mean": round(sum(prices) / len(prices), 8),
            "min": {"exchange": worst["exchange"], "price": worst["last"]},
            "max": {"exchange": best["exchange"], "price": best["last"]},
            "arb_spread": round(spread, 8),
            "arb_spread_pct": round(spread_pct, 6) if spread_pct is not None else None,
            "quotes": quotes,
            "timestamp": now_iso(),
        }

    # --- screening ------------------------------------------------------
    _VALID_OPS = ("<", "<=", ">", ">=", "==", "!=")

    @classmethod
    def _validate_filters(cls, filters: list[dict[str, Any]]) -> None:
        """Validate screen filters up front (§6): clear error beats silent miss."""
        if not filters:
            raise TickscopeError(
                cls._bad_request("screen_market requires at least one filter.")
            )
        for i, f in enumerate(filters):
            if not isinstance(f, dict) or not ("indicator" in f or "metric" in f):
                raise TickscopeError(
                    cls._bad_request(
                        f"filter[{i}] must specify an 'indicator' or 'metric' key."
                    )
                )
            op = f.get("op")
            if op not in cls._VALID_OPS:
                raise TickscopeError(
                    cls._bad_request(
                        f"filter[{i}] has invalid op {op!r}; "
                        f"expected one of {list(cls._VALID_OPS)}."
                    )
                )
            if f.get("value") is None:
                raise TickscopeError(
                    cls._bad_request(f"filter[{i}] is missing a numeric 'value'.")
                )

    @staticmethod
    def _bad_request(message: str) -> dict[str, Any]:
        return {
            "error": {
                "type": "BadRequest",
                "message": message,
                "exchange": None,
                "symbol": None,
                "retryable": False,
            }
        }

    async def screen_market(
        self,
        exchange: str | None,
        symbols: list[str] | None,
        quote: str,
        top_n: int,
        timeframe: str,
        filters: list[dict[str, Any]],
        sort_by: str,
    ) -> dict[str, Any]:
        self._validate_filters(filters)
        ex = self._exchange_id(exchange)
        needs_ticker = any("metric" in f for f in filters) or sort_by in self._TICKER_METRICS

        # One bulk fetch_tickers() up front, reused both to pick the volume
        # leaders and to satisfy every row's ticker metrics — instead of an N+1
        # storm of one fetch_ticker per symbol, which would needlessly burn the
        # rate limit. Empty when the venue lacks fetchTickers; rows then fall
        # back to a per-symbol fetch only where one is actually needed.
        tickers: dict[str, Any] = {}
        if symbols:
            targets = symbols
            if needs_ticker:
                tickers = await self._fetch_tickers_safe(ex)
        else:
            tickers = await self._fetch_tickers_safe(ex)
            targets = await self._rank_by_volume(ex, tickers, quote, top_n)

        semaphore = asyncio.Semaphore(self.settings.screen_concurrency)
        matched: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        async def evaluate(sym: str) -> None:
            async with semaphore:
                try:
                    row = await self._screen_one(ex, sym, timeframe, filters, sort_by, tickers)
                    if row is not None:
                        matched.append(row)
                except TickscopeError as exc:
                    errors.append({"symbol": sym, **exc.payload["error"]})
                except Exception as exc:  # noqa: BLE001
                    errors.append({"symbol": sym, "type": type(exc).__name__, "message": str(exc)})

        await asyncio.gather(*(evaluate(s) for s in targets))
        matched.sort(key=lambda r: r.get(sort_by, 0) or 0, reverse=True)
        return {"exchange": ex, "timeframe": timeframe, "matched": matched, "errors": errors}

    async def _fetch_tickers_safe(self, exchange: str) -> dict[str, Any]:
        """One bulk ticker snapshot for the whole venue (a single REST call).

        Returns ``{}`` when the exchange has no ``fetchTickers`` (or the call
        fails), so callers transparently fall back to per-symbol tickers.
        """
        inst = await self.exchanges.get(exchange)
        if not (getattr(inst, "has", {}) or {}).get("fetchTickers"):
            return {}
        try:
            return await self._rest(lambda: inst.fetch_tickers(), label=f"fetch_tickers:{exchange}")
        except Exception:  # noqa: BLE001 - degrade to per-symbol tickers
            return {}

    async def _rank_by_volume(
        self, exchange: str, tickers: dict[str, Any], quote: str, top_n: int
    ) -> list[str]:
        """Top ``top_n`` spot symbols for ``quote`` by 24h quote volume."""
        markets = await self.exchanges.load_markets(exchange)
        candidates = [
            (sym, t.get("quoteVolume") or 0)
            for sym, t in tickers.items()
            if sym in markets
            and markets[sym].get("quote") == quote.upper()
            and markets[sym].get("spot", True)
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in candidates[:top_n]]

    _TICKER_METRICS = ("change_24h_pct", "volume_24h", "last")

    async def _screen_one(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        filters: list[dict[str, Any]],
        sort_by: str | None = None,
        tickers: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        indicator_specs = [f["indicator"] for f in filters if "indicator" in f]
        # Fetch the ticker when a filter needs it OR when sorting by a ticker
        # metric (e.g. the flagship "top volume + RSI<30" screen), so each row
        # carries volume_24h for sorting and display.
        needs_ticker = any("metric" in f for f in filters) or sort_by in self._TICKER_METRICS

        indicator_values: dict[str, Any] = {}
        if indicator_specs:
            fetch = self._warmup_limit(200, indicators_engine.max_period(indicator_specs))
            df = await self._ohlcv_dataframe(exchange, symbol, timeframe, fetch)
            results, _ = await asyncio.to_thread(indicators_engine.compute, df, indicator_specs)
            indicator_values = results

        metrics: dict[str, Any] = {}
        if needs_ticker:
            # Prefer the row's entry from the bulk snapshot; only hit REST for a
            # symbol the snapshot did not cover (keeps screening to ~1 ticker call).
            t = (tickers or {}).get(symbol)
            if t is None:
                inst = await self.exchanges.get(exchange)
                t = await self._rest(
                    lambda: inst.fetch_ticker(symbol), label=f"fetch_ticker:{exchange}"
                )
            metrics = {
                "change_24h_pct": t.get("percentage"),
                "volume_24h": t.get("baseVolume"),
                "last": t.get("last"),
            }

        row: dict[str, Any] = {"symbol": symbol, **metrics}
        for f in filters:
            value = self._resolve_filter_value(f, indicator_values, metrics)
            row_key = f.get("indicator") or f.get("metric")
            if row_key:
                row[str(row_key)] = value
            if not self._passes(value, f.get("op", "=="), f.get("value")):
                return None
        return row

    @staticmethod
    def _resolve_filter_value(
        f: dict[str, Any], indicators: dict[str, Any], metrics: dict[str, Any]
    ) -> float | None:
        if "indicator" in f:
            name, params = indicators_engine.parse_spec(f["indicator"])
            key = indicators_engine.spec_key(name, params)
            entry = indicators.get(key, {})
            if isinstance(entry, dict):
                for field in ("value", "macd", "k"):
                    if field in entry:
                        return entry[field]
            return None
        if "metric" in f:
            return metrics.get(f["metric"])
        return None

    @staticmethod
    def _passes(value: float | None, op: str, target: Any) -> bool:
        if value is None or target is None:
            return False
        try:
            if op == "<":
                return value < target
            if op == "<=":
                return value <= target
            if op == ">":
                return value > target
            if op == ">=":
                return value >= target
            if op == "==":
                return value == target
            if op == "!=":
                return value != target
        except TypeError:
            return False
        return False

    # --- funding rate ---------------------------------------------------
    async def get_funding_rate(self, exchange: str | None, symbol: str) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        inst = await self.exchanges.get(ex)
        if not (getattr(inst, "has", {}) or {}).get("fetchFundingRate"):
            raise TickscopeError(
                {
                    "error": {
                        "type": "NotSupported",
                        "message": f"{ex} does not support funding rates.",
                        "exchange": ex,
                        "symbol": sym,
                        "retryable": False,
                    }
                }
            )
        data = await self._rest(
            lambda: inst.fetch_funding_rate(sym), label=f"fetch_funding_rate:{ex}"
        )
        return {
            "exchange": ex,
            "symbol": sym,
            "funding_rate": data.get("fundingRate"),
            # Prefer the *next* funding timestamp (this field's semantics);
            # fall back to the current one only if the exchange omits it.
            "next_funding_time": ms_to_iso(data.get("nextFundingTimestamp"))
            or ms_to_iso(data.get("fundingTimestamp")),
            "mark_price": data.get("markPrice"),
            "index_price": data.get("indexPrice"),
            "timestamp": ms_to_iso(data.get("timestamp")) or now_iso(),
        }

    # --- symbols / meta -------------------------------------------------
    async def list_symbols(
        self,
        exchange: str | None,
        quote: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        markets = await self.exchanges.load_markets(ex)
        symbols = list(markets.keys())
        if quote:
            q = quote.upper()
            symbols = [s for s in symbols if markets[s].get("quote") == q]
        if search:
            term = search.upper()
            symbols = [s for s in symbols if term in s.upper()]
        symbols.sort()
        return {"exchange": ex, "count": len(symbols), "symbols": symbols[:limit]}

    async def watch_symbol(
        self, exchange: str | None, symbol: str, channels: list[str]
    ) -> dict[str, Any]:
        ex = self._exchange_id(exchange)
        sym = await self._normalize(ex, symbol)
        active = await self.ingestion.ensure_watch(ex, sym, tuple(channels))
        return {"status": "watching", "exchange": ex, "symbol": sym, "channels": active}

    def get_watched_symbols(self) -> dict[str, Any]:
        info = self.ingestion.watched_info()
        watched = [
            {
                "exchange": item["exchange"],
                "symbol": item["symbol"],
                "channels": item["channels"],
                "buffer_size": item["buffer_size"],
                "last_update": ms_to_iso(item["last_update_ms"]) if item["last_update_ms"] else None,
                "staleness_ms": item["staleness_ms"],
            }
            for item in info
        ]
        return {"watched": watched}

    def server_status(self) -> dict[str, Any]:
        return {
            "uptime_s": round(time.time() - self.started_at, 1),
            "exchanges": self.exchanges.configured,
            "watched_count": self.ingestion.watched_count,
            "ohlcv_cache_rows": self.store.row_count(),
            "ccxt_version": ccxt_version(),
            "ws_reconnects": self.ingestion.ws_reconnects,
            "disclaimer": DISCLAIMER,
        }

    def list_exchanges(self) -> dict[str, Any]:
        return {"configured": self.exchanges.configured, "default": self.settings.default_exchange}

    async def aclose(self) -> None:
        await self.ingestion.stop()
        await self.exchanges.close()
        self.store.close()
