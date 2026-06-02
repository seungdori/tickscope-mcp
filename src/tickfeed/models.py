"""Pydantic I/O models for MCP tools.

Every market-data response carries the freshness contract: ``source``,
``age_ms`` and ``timestamp`` (ISO-8601 UTC).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Source = Literal["websocket", "rest"]


class FreshnessMixin(BaseModel):
    """Common freshness fields proving the real-time value proposition."""

    source: Source
    age_ms: int | None = None
    timestamp: str | None = None


class TickerOut(FreshnessMixin):
    exchange: str
    symbol: str
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    volume_24h: float | None = None
    change_24h_pct: float | None = None


class Trade(BaseModel):
    ts: str | None = None
    price: float
    amount: float
    side: str | None = None


class RecentTradesOut(BaseModel):
    exchange: str
    symbol: str
    count: int
    source: Source
    trades: list[Trade]


class Candle(BaseModel):
    ts: str | None
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVOut(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    candles: list[Candle]
    meta: dict[str, Any]


class OrderbookOut(FreshnessMixin):
    exchange: str
    symbol: str
    bids: list[list[float]]
    asks: list[list[float]]
    spread: float | None = None
    spread_pct: float | None = None


class ExchangeListOut(BaseModel):
    configured: list[str]
    default: str


class SymbolListOut(BaseModel):
    exchange: str
    count: int
    symbols: list[str]


class IndicatorsOut(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    as_of: str | None
    results: dict[str, Any]
    series: dict[str, Any] | None = None


class ScreenOut(BaseModel):
    exchange: str
    timeframe: str
    matched: list[dict[str, Any]]
    errors: list[dict[str, Any]] = Field(default_factory=list)


class FundingRateOut(BaseModel):
    exchange: str
    symbol: str
    funding_rate: float | None = None
    next_funding_time: str | None = None
    mark_price: float | None = None
    index_price: float | None = None
    timestamp: str | None = None


class WatchedSymbol(BaseModel):
    exchange: str
    symbol: str
    channels: list[str]
    buffer_size: int
    last_update: str | None = None
    staleness_ms: int | None = None


class WatchedListOut(BaseModel):
    watched: list[WatchedSymbol]


class WatchStatusOut(BaseModel):
    status: str
    exchange: str
    symbol: str
    channels: list[str]


class ServerStatusOut(BaseModel):
    uptime_s: float
    exchanges: list[str]
    watched_count: int
    ohlcv_cache_rows: int
    ccxt_version: str
    ws_reconnects: int


class Divergence(BaseModel):
    bias: Literal["bullish", "bearish"]
    kind: Literal["regular", "hidden"]
    from_bars_ago: int
    to_bars_ago: int
    price: list[float]
    oscillator: list[float]


class DivergenceOut(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    as_of: str | None = None
    oscillator: str
    pivots: dict[str, int]
    divergences: list[Divergence]
    has_divergence: bool


class CrossOut(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    as_of: str | None = None
    series_a: str
    series_b: str
    value_a: float | None = None
    value_b: float | None = None
    relation: str
    cross: Literal["crossover", "crossunder", "none"]
    bars_since_cross: int | None = None


class ExchangeQuote(BaseModel):
    exchange: str
    symbol: str
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume_24h: float | None = None
    source: Source
    age_ms: int | None = None


class AggregatedPriceOut(BaseModel):
    symbol: str
    exchange_count: int
    weighted_avg: float
    mean: float
    min: dict[str, Any]
    max: dict[str, Any]
    arb_spread: float
    arb_spread_pct: float | None = None
    quotes: list[ExchangeQuote]
    timestamp: str | None = None


class CandlePattern(BaseModel):
    pattern: str
    bias: Literal["bullish", "bearish", "neutral"]
    bars_ago: int
    ts: str | None = None


class PatternsOut(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    as_of: str | None = None
    patterns: list[CandlePattern]
    count: int
    latest_candle: dict[str, Any]


class Swing(BaseModel):
    type: Literal["high", "low"]
    price: float
    label: str | None = None
    bars_ago: int


class StructureOut(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    as_of: str | None = None
    trend: Literal["uptrend", "downtrend", "range"]
    current_price: float
    last_swing_high: Swing | None = None
    last_swing_low: Swing | None = None
    swings: list[Swing] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


class SRZone(BaseModel):
    level: float
    touches: int
    distance_pct: float


class SupportResistanceOut(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    as_of: str | None = None
    current_price: float
    support: list[SRZone] = Field(default_factory=list)
    resistance: list[SRZone] = Field(default_factory=list)
