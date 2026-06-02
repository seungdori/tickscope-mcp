"""@guard: every tool failure becomes a structured envelope, never a traceback."""

from __future__ import annotations

import ccxt
import pytest

from tickscope.tools._guard import guard
from tickscope.utils import TickscopeError

pytestmark = pytest.mark.asyncio


async def test_guard_passes_through_success():
    @guard()
    async def ok(symbol=None, exchange=None):
        return {"value": 42}

    assert await ok(symbol="BTC/USDT") == {"value": 42}


async def test_guard_returns_tickscope_error_payload_verbatim():
    payload = {
        "error": {
            "type": "NoData",
            "message": "no candles",
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "retryable": True,
        }
    }

    @guard()
    async def boom(symbol=None, exchange=None):
        raise TickscopeError(payload)

    out = await boom(symbol="BTC/USDT", exchange="binance")
    assert out == payload  # domain error carries its own structured payload


async def test_guard_wraps_generic_exception_and_scopes_exchange_symbol():
    @guard()
    async def boom(symbol=None, exchange=None):
        raise ccxt.RateLimitExceeded("slow down")

    out = await boom(exchange="binance", symbol="BTC/USDT")
    err = out["error"]
    assert err["type"] == "RateLimitExceeded"
    assert err["exchange"] == "binance"  # scoped from kwargs
    assert err["symbol"] == "BTC/USDT"
    assert err["retryable"] is True  # ccxt rate-limit errors are transient
    assert "message" in err


async def test_guard_never_leaks_a_raw_exception():
    @guard()
    async def boom(symbol=None, exchange=None):
        raise RuntimeError("kaboom")

    out = await boom()  # must not raise
    assert out["error"]["type"] == "RuntimeError"
    assert out["error"]["retryable"] is False
