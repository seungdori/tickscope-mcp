#!/usr/bin/env python
"""Tickscope live demo — a recordable walkthrough of the value proposition.

Runs against public Binance data (no API keys) and narrates a full analysis:
cold→warm freshness (REST → WebSocket), indicators with signals, divergence,
market structure, and support/resistance. Ideal for screen-recording the README
GIF.

    uv run examples/demo.py            # or: python examples/demo.py
    uv run examples/demo.py ETH/USDT 4h
"""

from __future__ import annotations

import asyncio
import logging
import sys

from tickscope.config import Settings
from tickscope.core.service import MarketDataService

# Keep the walkthrough clean (no background WS reconnect chatter) for recording.
logging.getLogger().setLevel(logging.ERROR)

# Minimal ANSI styling (no dependencies).
DIM, BOLD, GREEN, CYAN, YELLOW, RESET = (
    "\033[2m", "\033[1m", "\033[32m", "\033[36m", "\033[33m", "\033[0m",
)


def header(text: str) -> None:
    print(f"\n{BOLD}{CYAN}━━ {text} {'━' * max(0, 56 - len(text))}{RESET}")


def kv(label: str, value: object, *, good: bool = False) -> None:
    color = GREEN if good else ""
    print(f"  {label:<18}{color}{value}{RESET}")


async def main(symbol: str, timeframe: str) -> None:
    svc = MarketDataService(
        Settings(exchanges=["binance", "bybit", "okx"], default_exchange="binance")
    )
    try:
        print(f"{BOLD}Tickscope{RESET} {DIM}— real-time, free market data for AI agents{RESET}")
        print(f"{DIM}symbol={symbol}  timeframe={timeframe}{RESET}")

        header("1. Live price — watch it go from REST to WebSocket")
        cold = await svc.get_ticker("binance", symbol)
        kv("last", cold["last"])
        kv("source", cold["source"], good=False)
        kv("age_ms", cold["age_ms"])
        print(f"  {DIM}…auto-watch started; waiting for the WebSocket to warm up…{RESET}")
        for _ in range(15):
            await asyncio.sleep(1)
            if svc.cache.get_ticker("binance", symbol) is not None:
                break
        warm = await svc.get_ticker("binance", symbol)
        kv("last", warm["last"])
        kv("source", warm["source"], good=warm["source"] == "websocket")
        kv("age_ms", warm["age_ms"], good=True)
        print(f"  {GREEN}↑ sub-second-fresh, straight from a live connection.{RESET}")

        header("2. Indicators with derived signals")
        ind = await svc.compute_indicators(
            "binance", symbol, timeframe, 200,
            ["rsi:14", "macd:12,26,9", "supertrend:10,3", "wavetrend"], False,
        )
        r = ind["results"]
        kv("RSI(14)", f"{r['rsi_14']['value']}  ({r['rsi_14']['state']})")
        macd = r["macd_12_26_9"]
        kv("MACD", f"hist={macd['hist']}  cross={macd['cross']}")
        st = r["supertrend_10_3"]
        kv("Supertrend", f"{st['value']}  dir={st['direction']} flip={st['flip']}")
        kv("WaveTrend", f"wt1={r['wavetrend']['wt1']}  cross={r['wavetrend']['cross']}")

        header("3. RSI divergence")
        div = await svc.detect_divergence("binance", symbol, timeframe, 200, "rsi:14", 5, 5)
        if div["divergences"]:
            for d in div["divergences"]:
                kv(f"{d['bias']} {d['kind']}", f"price {d['price']}  rsi {d['oscillator']}", good=True)
        else:
            kv("divergence", "none on the latest pivots")

        header("4. Market structure (SMC)")
        ms = await svc.analyze_structure("binance", symbol, timeframe, 200, 3, 3)
        kv("trend", ms["trend"], good=ms["trend"] != "range")
        if ms["last_swing_high"]:
            kv("last swing high", f"{ms['last_swing_high']['price']} ({ms['last_swing_high']['label']})")
        if ms["last_swing_low"]:
            kv("last swing low", f"{ms['last_swing_low']['price']} ({ms['last_swing_low']['label']})")
        for ev in ms["events"]:
            kv("event", f"{YELLOW}{ev['type']} {ev['bias']}{RESET} @ {ev['level']}", good=True)

        header("5. Support / resistance")
        sr = await svc.find_support_resistance("binance", symbol, timeframe, 200, 0.5, 4)
        for z in sr["resistance"][:3]:
            kv("resistance", f"{z['level']}  ({z['touches']} touches, {z['distance_pct']}%)")
        kv("current", sr["current_price"], good=True)
        for z in sr["support"][:3]:
            kv("support", f"{z['level']}  ({z['touches']} touches, {z['distance_pct']}%)")

        header("6. Cross-exchange price (arbitrage view)")
        agg = await svc.get_aggregated_price(symbol)
        kv("weighted avg", agg["weighted_avg"])
        kv("cheapest", f"{agg['min']['exchange']} @ {agg['min']['price']}")
        kv("priciest", f"{agg['max']['exchange']} @ {agg['max']['price']}")
        kv("arb spread", f"{agg['arb_spread']} ({agg['arb_spread_pct']}%)", good=True)

        print(f"\n{DIM}One server, one connection — real-time and free.{RESET}\n")
    finally:
        await svc.aclose()


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC/USDT"
    tf = sys.argv[2] if len(sys.argv) > 2 else "1h"
    asyncio.run(main(sym, tf))
