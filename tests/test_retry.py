"""with_retry: exponential-backoff behavior for transient exchange errors."""

from __future__ import annotations

import ccxt
import pytest

from tickscope.core.retry import with_retry

pytestmark = pytest.mark.asyncio


async def test_succeeds_after_transient_errors():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ccxt.RateLimitExceeded("slow down")
        return "ok"

    # base_delay=0 keeps the test instant (no real backoff sleep).
    result = await with_retry(factory, retries=5, base_delay=0)
    assert result == "ok"
    assert calls["n"] == 3  # failed twice, succeeded on the third attempt


async def test_gives_up_after_max_attempts_and_reraises():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise ccxt.DDoSProtection("blocked")

    with pytest.raises(ccxt.DDoSProtection):
        await with_retry(factory, retries=3, base_delay=0)
    assert calls["n"] == 3  # exactly `retries` attempts, then re-raise


async def test_non_transient_error_is_not_retried():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        await with_retry(factory, retries=5, base_delay=0)
    assert calls["n"] == 1  # propagated immediately, no retries


async def test_network_and_timeout_errors_are_retryable():
    for exc_type in (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable):
        calls = {"n": 0}

        async def factory(_exc=exc_type, _calls=calls):
            _calls["n"] += 1
            if _calls["n"] < 2:
                raise _exc("transient")
            return "ok"

        assert await with_retry(factory, retries=3, base_delay=0) == "ok"
        assert calls["n"] == 2
