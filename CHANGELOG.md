# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-06-02

Initial release.

### Added

- **MCP server** (FastMCP, stdio + optional streamable-HTTP) with 19 tools.
- **Real-time data:** background `ccxt.pro` WebSocket ingestion with reconnect,
  auto-watch on first query, and `source` / `age_ms` / `timestamp` freshness on
  every market-data response.
- **Market data:** `get_ticker`, `get_recent_trades`, `get_ohlcv` (DuckDB-cached),
  `get_orderbook`, `get_funding_rate`, `list_symbols`, `list_exchanges`.
- **73 technical indicators** via a single registry, with derived signals and
  **Pine Script syntax** (`ta.rsi(14)`, `ta.sqz`, …). Includes crypto/Pine
  favorites: WaveTrend, TTM Squeeze, QQE, Connors RSI, Schaff Trend Cycle,
  VIDYA, T3, DMI, Aroon, Vortex.
- **Analysis:** `detect_divergence` (regular/hidden), `detect_cross`,
  `screen_market`, `get_aggregated_price` (cross-exchange weighted price + arb
  spread).
- **Structure recognition:** `detect_patterns` (candlestick patterns),
  `analyze_structure` (HH/HL/LH/LL, trend, BOS/CHoCH), `find_support_resistance`.
- **Deep analysis:** `deep_analyze` — multi-timeframe trend confluence,
  statistical & market-state context (price percentile, ADX/efficiency trend
  state, ATR volatility state), and a strictly causal historical-signal event
  study, synthesized into a verdict. `compute_indicators` carries the
  market-state context inline.
- **Resources:** `tickscope://status`, `tickscope://watched`,
  `tickscope://ticker/{exchange}/{symbol}`.
- **Prompts:** `/deep_analyze` slash command (MCP prompt) for an on-demand,
  guided multi-timeframe read.
- **Resilience:** rate-limit-aware exponential backoff on REST, structured error
  envelopes, bounded concurrency for multi-symbol work.
- **Performance:** DuckDB and pandas work runs off the event loop
  (`asyncio.to_thread`), an in-memory L1 OHLCV cache, a per-exchange REST
  concurrency gate, and a single bulk `fetch_tickers` for screening.
- Packaging for `uvx tickscope-mcp`; unit + MCP-integration + live test suites;
  `ruff` + `mypy` CI gates; multi-language READMEs (EN/KO/ZH/JA).

[Unreleased]: https://github.com/seungdori/tickscope-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/seungdori/tickscope-mcp/releases/tag/v0.1.0
