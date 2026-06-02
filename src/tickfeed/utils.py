"""Shared helpers: symbol normalization, time conversion, structured errors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import ccxt

# Spec §16: surfaced in server meta (instructions + server_status) and README.
DISCLAIMER = (
    "For educational and research use only — not financial, investment, or "
    "trading advice. Market data may be delayed, incomplete, or inaccurate."
)

# ccxt exception types that are transient and worth retrying.
_RETRYABLE_TYPES: tuple[type[Exception], ...] = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.DDoSProtection,
    ccxt.RateLimitExceeded,
    ccxt.ExchangeNotAvailable,
)


class TickFeedError(Exception):
    """Domain error that already carries a structured, LLM-friendly payload."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        super().__init__(payload.get("error", {}).get("message", "TickFeed error"))


def now_iso() -> str:
    """Current UTC time as ISO-8601 with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms_to_iso(timestamp_ms: int | float | None) -> str | None:
    """Convert epoch milliseconds to ISO-8601 UTC; ``None`` passes through."""
    if timestamp_ms is None:
        return None
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def iso_or_ms_to_ms(value: str | int | float | None) -> int | None:
    """Parse an ISO-8601 string or epoch-ms value into epoch milliseconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = value.strip()
    if text.isdigit():
        return int(text)
    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def age_ms(timestamp_ms: int | float | None) -> int | None:
    """Milliseconds elapsed since ``timestamp_ms`` (clamped at 0)."""
    if timestamp_ms is None:
        return None
    delta = int(datetime.now(UTC).timestamp() * 1000) - int(timestamp_ms)
    return max(delta, 0)


def normalize_symbol(symbol: str, markets: dict[str, Any] | None = None) -> str:
    """Normalize a user symbol to ccxt unified ``BASE/QUOTE`` form.

    Accepts already-unified symbols (``BTC/USDT``, ``BTC/USDT:USDT``) and tries
    to split compact forms (``BTCUSDT``) using the exchange ``markets`` map when
    available, otherwise common quote-currency heuristics.
    """
    raw = symbol.strip().upper()
    if "/" in raw:
        return raw

    if markets:
        # ccxt market ids (e.g. "BTCUSDT") map back to unified symbols.
        for market in markets.values():
            market_id = str(market.get("id", "")).upper()
            if market_id == raw:
                return str(market["symbol"])

    common_quotes = ("USDT", "USDC", "USD", "BUSD", "BTC", "ETH", "EUR", "DAI")
    for quote in common_quotes:
        if raw.endswith(quote) and len(raw) > len(quote):
            return f"{raw[: -len(quote)]}/{quote}"
    return raw


def error_payload(exc: Exception, *, exchange: str | None = None, symbol: str | None = None) -> dict[str, Any]:
    """Build the standard structured error envelope from any exception."""
    if isinstance(exc, TickFeedError):
        return exc.payload
    retryable = isinstance(exc, _RETRYABLE_TYPES)
    return {
        "error": {
            "type": type(exc).__name__,
            "message": str(exc) or type(exc).__name__,
            "exchange": exchange,
            "symbol": symbol,
            "retryable": retryable,
        }
    }
