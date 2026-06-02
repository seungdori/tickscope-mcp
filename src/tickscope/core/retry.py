"""Async retry with exponential backoff for transient exchange errors.

Spec §9.2: multi-symbol / REST work must retry ``RateLimitExceeded`` (and
related network errors) with exponential backoff, up to a bounded number of
attempts. ccxt's ``enableRateLimit`` paces requests, but bursts and transient
network failures still surface as exceptions that are worth one or two retries
before giving up.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import ccxt

logger = logging.getLogger("tickscope.retry")

T = TypeVar("T")

# Transient ccxt errors that warrant a retry.
RETRYABLE: tuple[type[Exception], ...] = (
    ccxt.RateLimitExceeded,
    ccxt.DDoSProtection,
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
)


async def with_retry(
    factory: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    label: str = "rest",
) -> T:
    """Await ``factory()``, retrying transient failures with exponential backoff.

    ``factory`` must be a zero-arg coroutine *factory* (e.g. ``lambda:
    inst.fetch_ticker(sym)``) so each attempt starts a fresh awaitable. Non-
    transient errors propagate immediately; the final transient error is
    re-raised after ``retries`` attempts.
    """
    attempt = 0
    delay = base_delay
    while True:
        try:
            return await factory()
        except RETRYABLE as exc:
            attempt += 1
            if attempt >= retries:
                raise
            logger.warning(
                "%s transient error (%s); retry %d/%d in %.2fs",
                label,
                type(exc).__name__,
                attempt,
                retries,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
