"""End-to-end MCP tool-layer integration tests (deterministic, no network).

These exercise the *real* MCP path — ``build_server`` registration, the
``@guard`` wrapper, FastMCP argument validation, and result serialization — by
calling tools through ``mcp.call_tool`` with a fake-exchange-backed service
injected into the process-wide runtime singleton.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio

import tickscope.runtime as runtime

pytestmark = pytest.mark.asyncio

ToolCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@pytest_asyncio.fixture()
async def mcp_call(service) -> AsyncIterator[ToolCall]:
    """Wire the fake-backed ``service`` into the runtime singleton, build the
    server, and return a helper that calls tools through the real MCP path."""
    runtime._service = service

    from tickscope.server import build_server

    mcp = build_server()

    async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result: Any = await mcp.call_tool(name, arguments)
        # FastMCP (convert_result=True) returns (content_blocks, structured).
        return result[1] if isinstance(result, tuple) else result

    try:
        yield call
    finally:
        runtime._service = None


async def test_get_ticker_through_mcp(mcp_call):
    result = await mcp_call("get_ticker", {"symbol": "BTC/USDT"})
    assert result["symbol"] == "BTC/USDT"
    assert result["source"] in ("rest", "websocket")
    assert "age_ms" in result and "timestamp" in result


async def test_list_exchanges_and_status(mcp_call):
    ex = await mcp_call("list_exchanges", {})
    assert ex["configured"] == ["binance"] and ex["default"] == "binance"
    status = await mcp_call("server_status", {})
    assert "ccxt_version" in status and "disclaimer" in status


async def test_ohlcv_and_indicators_through_mcp(mcp_call):
    candles = await mcp_call("get_ohlcv", {"symbol": "BTC/USDT", "timeframe": "1h", "limit": 100})
    assert candles["meta"]["count"] > 0
    ind = await mcp_call(
        "compute_indicators",
        {"symbol": "BTC/USDT", "indicators": ["rsi:14", "macd:12,26,9", "supertrend:10,3"]},
    )
    assert "rsi_14" in ind["results"]
    assert "state" in ind["results"]["rsi_14"]
    assert "direction" in ind["results"]["supertrend_10_3"]


async def test_analysis_tools_through_mcp(mcp_call):
    div = await mcp_call("detect_divergence", {"symbol": "BTC/USDT", "oscillator": "rsi:14"})
    assert "has_divergence" in div
    cross = await mcp_call(
        "detect_cross", {"symbol": "BTC/USDT", "series_a": "ema:5", "series_b": "ema:20"}
    )
    assert cross["cross"] in ("crossover", "crossunder", "none")


async def test_structure_tools_through_mcp(mcp_call):
    pats = await mcp_call("detect_patterns", {"symbol": "BTC/USDT", "lookback": 10})
    assert "patterns" in pats and "latest_candle" in pats
    struct = await mcp_call("analyze_structure", {"symbol": "BTC/USDT"})
    assert struct["trend"] in ("uptrend", "downtrend", "range")
    sr = await mcp_call("find_support_resistance", {"symbol": "BTC/USDT"})
    assert "support" in sr and "resistance" in sr


async def test_screen_market_through_mcp(mcp_call):
    out = await mcp_call(
        "screen_market",
        {
            "symbols": ["BTC/USDT", "ETH/USDT"],
            "filters": [{"metric": "change_24h_pct", "op": ">", "value": 5}],
        },
    )
    assert "matched" in out and "errors" in out


async def test_funding_rate_through_mcp(mcp_call):
    out = await mcp_call("get_funding_rate", {"symbol": "BTC/USDT"})
    assert out["funding_rate"] is not None
    assert out["next_funding_time"] is not None


async def test_structured_error_through_mcp(mcp_call):
    # An invalid screen filter must come back as the structured error envelope,
    # not a raised exception, proving the @guard path works through MCP.
    out = await mcp_call(
        "screen_market",
        {"filters": [{"indicator": "rsi:14", "op": "BAD", "value": 30}]},
    )
    assert "error" in out
    assert out["error"]["type"] == "BadRequest"
    assert out["error"]["retryable"] is False
