# Contributing to Tickscope MCP

Thanks for your interest! Issues and PRs are welcome. This project aims to be a
small, well-tested, read-only market-data MCP server — please keep changes in
that spirit.

## Ground rules

- **Read-only, public data only.** v1 never executes orders, reads balances, or
  requires API secrets. Do not add features that cross that boundary (see
  [SECURITY.md](SECURITY.md)).
- **Minimal dependencies.** Prefer the standard library, `pandas`/`numpy`, and
  the existing stack over new dependencies.
- **Everything is typed and linted.** `ruff` and `mypy` must pass.
- **New behavior needs a test.** Indicators need a math/property test; tools and
  services need a service- or MCP-level test.

## Development setup

```bash
uv venv && uv pip install -e ".[dev]"
pytest                # unit + MCP-integration tests (live excluded)
pytest -m live        # live exchange tests (hits Binance/Bybit/OKX; run locally)
ruff check . && mypy  # lint + type gates
uv run examples/demo.py   # live end-to-end smoke
```

## Project layout

```
tickscope-mcp/
├── src/tickscope/
│   ├── __main__.py            # console entrypoint (tickscope / uvx tickscope-mcp)
│   ├── server.py              # FastMCP app, lifespan, tool + resource registration
│   ├── runtime.py             # process-wide MarketDataService singleton
│   ├── config.py              # pydantic-settings (TICKSCOPE_* env vars)
│   ├── models.py              # pydantic I/O contracts
│   ├── resources.py           # MCP resources (status / watched / ticker)
│   ├── utils.py               # symbol/time normalization, structured errors, disclaimer
│   ├── tools/                 # MCP tool registration (thin; delegate to the service)
│   │   ├── meta.py · market.py · indicators.py · screen.py · watch.py · analysis.py
│   │   └── _guard.py          # decorator: any exception -> structured {error:{…}}
│   └── core/
│       ├── service.py         # MarketDataService — the single coordinator
│       ├── exchange_manager.py# ccxt / ccxt.pro instances
│       ├── ingestion.py       # background WebSocket watch loops + reconnect
│       ├── cache.py           # ring buffers + ticker/orderbook/live-candle caches
│       ├── storage.py         # DuckDB OHLCV cache
│       ├── retry.py           # rate-limit-aware exponential backoff
│       ├── indicators_engine.py # 73 indicators via a single REGISTRY table
│       ├── analysis.py        # divergence, Pine-style cross, pivots
│       └── structure.py       # candlestick patterns, market structure, S/R
├── tests/                     # unit, MCP-integration, and @pytest.mark.live suites
└── examples/                  # demo.py, RECORDING.md, client config, prompts
```

The flow is always: **tool → `MarketDataService` → cache-first, REST fallback,
auto-watch**. Tools contain no business logic.

## Adding an indicator

The engine is registry-driven — adding one is a single declaration:

1. Write the pure function in `core/indicators_engine.py` (takes `df["close"]`
   or `df`, returns a `pd.Series` or `pd.DataFrame`).
2. Add one `REGISTRY["name"] = _Ind(fn, defaults, …)` entry.
3. Add a math/property test in `tests/test_indicators.py`.

`SUPPORTED`, `series_for`, `max_period`, and the tool docstring all derive from
the registry automatically.

## Commit / PR checklist

- [ ] `ruff check .` and `mypy` pass
- [ ] `pytest` (non-live) passes; new behavior has a test
- [ ] Docstrings updated (tool docstrings guide LLM tool selection — keep them clear)
- [ ] Scope stays read-only / public-data

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
