<div align="center">

# TickFeed MCP

**Real-time, free crypto market data for any AI agent — via MCP.**

[![PyPI](https://img.shields.io/pypi/v/tickfeed-mcp.svg)](https://pypi.org/project/tickfeed-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/tickfeed-mcp.svg)](https://pypi.org/project/tickfeed-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/seungdori/tickfeed-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/seungdori/tickfeed-mcp/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-blue.svg)](https://mypy-lang.org/)
[![MCP](https://img.shields.io/badge/MCP-server-6E56CF.svg)](https://modelcontextprotocol.io)

**English** · [한국어](README.ko.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md)

<!-- Live Claude Code walkthrough — see examples/RECORDING.md -->
![TickFeed demo](docs/demo-agent.gif)

</div>

TickFeed is a self-hostable [Model Context Protocol](https://modelcontextprotocol.io) server that gives any MCP client (Claude Code, Cursor, Codex, Gemini CLI, …) **real-time and historical crypto market data for free**. It keeps exchange WebSocket connections warm in the background, so your agent reads prices that are fresh to the sub-second, straight from a live connection. The same server covers **73 technical indicators** and **chart-structure recognition**, with no API keys.

> ⚠️ Educational/research tool. It does not provide financial, investment, or trading advice, and it does not guarantee data accuracy or timeliness.

---

## Contents

- [Why](#why) · [See it run](#see-it-run) · [30-second install](#30-second-install)
- [Supported exchanges](#supported-exchanges) · [Tools](#tools) · [Indicators](#indicators-73) · [Structure recognition](#structure-recognition)
- [Example prompts](#example-prompts) · [Configuration](#configuration) · [Development](#development) · [Roadmap](#roadmap)

## Why

Trading agents are exploding, yet their data layer stays fragmented, REST-poll-only, and often locked behind a paywall. TickFeed gives those agents **real-time, free market data** from one server — many exchanges, no API keys.

## See it run

```bash
uv run examples/demo.py            # live BTC/USDT walkthrough (no API keys)
uv run examples/demo.py ETH/USDT 4h
```

A colorized terminal walkthrough — cold→warm freshness (REST → WebSocket), indicators with signals, divergence, market structure, and support/resistance — against live Binance/Bybit/OKX. See [examples/RECORDING.md](examples/RECORDING.md) to turn it into the GIF above.

## 30-second install

```bash
uvx tickfeed-mcp
```

Register it with your client (Claude Code example, [`examples/claude_code_config.json`](examples/claude_code_config.json)):

```json
{
  "mcpServers": {
    "tickfeed": {
      "command": "uvx",
      "args": ["tickfeed-mcp"],
      "env": {
        "TICKFEED_EXCHANGES": "binance,bybit,okx",
        "TICKFEED_DEFAULT_EXCHANGE": "binance"
      }
    }
  }
}
```

Cursor, Codex and Gemini CLI use the same `command`/`args`/`env` shape in their respective MCP config files.

## Supported exchanges

| Exchange | REST | WebSocket |
|---|:---:|:---:|
| Binance | ✅ | ✅ |
| Bybit | ✅ | ✅ |
| OKX | ✅ | ✅ |

Any [ccxt](https://github.com/ccxt/ccxt)-supported exchange can be enabled via `TICKFEED_EXCHANGES`. Public data only — no keys required.

## Tools

| Tool | What it does |
|---|---|
| `list_exchanges` | Configured exchanges + default |
| `list_symbols` | Tradable symbols (filter by quote/search) |
| `get_ticker` | Current price snapshot (primary quote tool) |
| `get_recent_trades` | Recent executed trades from the live buffer |
| `get_ohlcv` | Historical candles (DuckDB-cached) |
| `get_orderbook` | Order book snapshot + spread |
| `compute_indicators` | 73 indicators (RSI/MACD/Supertrend/WaveTrend/Squeeze/…) with derived signals |
| `detect_divergence` | Regular/hidden bullish & bearish divergence (price vs oscillator) |
| `detect_cross` | Pine-style `ta.crossover`/`ta.crossunder` between any two series |
| `detect_patterns` | Candlestick patterns (engulfing, hammer, stars, …) with bias |
| `analyze_structure` | Market structure: swings, trend, BOS / CHoCH |
| `find_support_resistance` | Clustered support/resistance zones from pivots |
| `deep_analyze` | Multi-timeframe read: trend confluence + market-state context + historical signal performance, with a synthesized verdict |
| `screen_market` | Scan many symbols by indicator/price filters |
| `get_aggregated_price` | Volume-weighted price + cross-exchange spread (arbitrage) |
| `get_funding_rate` | Perpetual funding rate |
| `watch_symbol` | Pre-warm a live subscription (optional) |
| `get_watched_symbols` | Active subscriptions + buffer state |
| `server_status` | Health / diagnostics |

Every market-data response includes `source` (`websocket`|`rest`), `age_ms`, and `timestamp` so the freshness is always provable.

### Indicators (73)

- **MAs / overlays:** `sma ema wma smma dema tema hma vwma zlema alma kama trima lsma vidya t3 vwap vwapbands bbands donchian keltner supertrend ichimoku psar`
- **Momentum:** `rsi stochrsi macd ppo stoch cci willr roc mom tsi ao cmo uo dpo trix coppock kst fisher rvi mfi wavetrend squeeze qqe crsi stc elderray zscore linregslope`
- **Volatility:** `atr natr stdev hv chop ulcer massindex`
- **Volume:** `obv adl cmf chaikinosc eom fi pvt vo klinger`
- **Trend:** `adx dmi aroon vortex`
- **Structure:** `heikinashi pivots`

Specs are `"name:p1,p2"` and also accept **Pine Script syntax** — `ta.rsi(14)`, `ta.ema(20)`, `ta.wt(10,21)`, `ta.sqz` — so TradingView users can paste familiar expressions. Derived signals include overbought-oversold state, MACD/PPO/WaveTrend/QQE cross, zero-line cross for oscillators, Supertrend/PSAR direction & flip, squeeze on/off, DMI/Heikin-Ashi trend, and Ichimoku cloud position. Includes crypto/Pine favorites (WaveTrend, TTM Squeeze, QQE, Connors RSI, Schaff Trend Cycle, VIDYA, T3). Adding a new indicator is a one-line `REGISTRY` declaration.

### Structure recognition

On top of numeric indicators, TickFeed describes *what the chart is doing*: `detect_patterns` names candlestick patterns (engulfing, hammer/hanging man, doji family, morning/evening star, three soldiers/crows, …) with their bias; `analyze_structure` returns swing highs/lows labeled HH/HL/LH/LL, the inferred trend, and Break-of-Structure / Change-of-Character events (SMC-style); `find_support_resistance` clusters swing pivots into support/resistance zones with touch counts. These give an agent the vocabulary to describe a chart the way a trader would.

### Deep analysis

`deep_analyze` answers a question about a symbol in one call, instead of making the agent chain a dozen tools. It returns:

- **Multi-timeframe trend confluence** — the same symbol read across a 1d/4h/1h ladder, with whether the timeframes agree or conflict.
- **Market-state context** — where price sits in its recent range (percentile), the trend state (`trending_up` / `trending_down` / `ranging`, from ADX + Kaufman efficiency ratio), and the volatility state (from ATR percentile), so a bare "RSI 30" reads against the conditions it showed up in.
- **Historical signal performance** — for the current divergence, the forward-return distribution of every past *confirmed* occurrence on this symbol/timeframe (count, win rate, median). A strictly causal event study — no look-ahead, no repaint.
- **A synthesized verdict** — bias, confidence, timeframe agreement, the execution-timeframe market state, and explicit caveats, all computed deterministically in Python so the call never hinges on the model eyeballing raw numbers.

`compute_indicators` now carries the same market-state context inline (it's ~free), and signal history is memoized per closed bar, so warm reads stay fast. Clients that support MCP prompts expose this as a slash command — `/mcp__tickfeed__deep_analyze` (symbol + timeframe) — to trigger a full read on demand.

### Resources

Supporting clients can also read live state as MCP resources: `tickfeed://status`, `tickfeed://watched`, and the template `tickfeed://ticker/{exchange}/{symbol}`.

## Example prompts

- "What's BTC/USDT trading at on Binance right now, and the 24h change?"
- "Compute the 1h RSI and MACD for BTC/USDT and tell me if there's a divergence."
- "Screen the top 30 USDT pairs by volume for ones with RSI below 30."
- "What's the current perpetual funding rate for BTC on Bybit?"
- "Show me the ETH/USDT order book spread for the top 10 levels."

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|---|---|---|
| `TICKFEED_EXCHANGES` | `binance,bybit,okx` | Enabled exchanges (comma-separated) |
| `TICKFEED_DEFAULT_EXCHANGE` | `binance` | Default when `exchange` is omitted |
| `TICKFEED_MAX_WATCHED_SYMBOLS` | `25` | Max concurrent WS subscriptions (LRU evicted) |
| `TICKFEED_RING_BUFFER_SIZE` | `1000` | Per-symbol trade buffer size |
| `TICKFEED_OHLCV_CACHE_PATH` | `~/.tickfeed/ohlcv.duckdb` | DuckDB cache file |
| `TICKFEED_OHLCV_CACHE_TTL_S` | `60` | Freshness window for the newest candle |
| `TICKFEED_REST_RETRIES` | `3` | Retry attempts for transient REST errors (rate limit / network) |
| `TICKFEED_SCREEN_CONCURRENCY` | `5` | Max concurrent symbols during screening/aggregation |
| `TICKFEED_TRANSPORT` | `stdio` | `stdio` or `http` |
| `TICKFEED_LOG_LEVEL` | `INFO` | Log level |

## Development

```bash
uv venv && uv pip install -e ".[dev]"
pytest                # ~100 unit + MCP-integration tests (live excluded)
pytest -m live        # live exchange tests (Binance/Bybit/OKX, run locally)
ruff check . && mypy  # lint + type gates
```

Tests cover indicator math against reference values, service cache/auto-watch logic, the full MCP tool path (`tests/test_mcp_integration.py` calls tools through `mcp.call_tool`), price-structure recognition, and a live suite that exercises the whole stack against real exchanges. See [CONTRIBUTING.md](CONTRIBUTING.md) for the project layout and contribution flow.

## Roadmap

- [x] Pine Script-style indicator mapping (`ta.rsi`, `ta.crossover`, …)
- [x] 73 indicators + candlestick patterns + market structure (BOS/CHoCH)
- [x] Multi-exchange aggregation (weighted price / spread)
- [x] MCP resource push for watched symbols
- [ ] Anchored / session VWAP
- [ ] More exchanges (Kraken, Bitget, Gate, …)
- [ ] Agent Skill (`SKILL.md`) wrapper

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md). Keep dependencies minimal and the v1 scope read-only (public data, no order execution, no API secrets).

## License

[MIT](LICENSE) © TickFeed contributors.

## Disclaimer

This tool is for **educational and research purposes only**. It is not financial, investment, or trading advice. Market data may be delayed, incomplete, or inaccurate; do not rely on it for real trading decisions. Respect each exchange's terms of service and rate limits. See [SECURITY.md](SECURITY.md).
