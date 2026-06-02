# Recording the README demo GIF

The top-of-README GIF is the single biggest driver of stars. Two good ways to
make one — both use only public data (no API keys).

## Option A — the scripted terminal demo (fastest)

[`examples/demo.py`](demo.py) runs a full, colorized walkthrough against live
Binance/Bybit/OKX: cold→warm freshness (REST → WebSocket), indicators with
signals, divergence, market structure, and support/resistance.

```bash
uv run examples/demo.py            # BTC/USDT 1h
uv run examples/demo.py ETH/USDT 4h
```

Record it with [`asciinema`](https://asciinema.org) + [`agg`](https://github.com/asciinema/agg)
(crisp, tiny GIFs):

```bash
brew install asciinema agg
asciinema rec demo.cast -c "uv run examples/demo.py"
agg --cols 80 --rows 32 demo.cast docs/demo.gif
```

or with [`vhs`](https://github.com/charmbracelet/vhs) for a fully reproducible recording:

```bash
# demo.tape
Output docs/demo.gif
Set FontSize 16
Set Width 1000
Set Height 700
Type "uv run examples/demo.py" Enter
Sleep 20s
```
```bash
vhs demo.tape
```

## Option B — Claude Code answering live (most compelling)

Register the server (see the README) and screen-record Claude Code answering a
real question, e.g.:

> 바이낸스 BTC/USDT 지금 RSI 얼마고 다이버전스 있어? 직전 스윙 구조도 알려줘.

Make sure the `source: "websocket"` and `age_ms` fields are visible in the tool
output — that on-screen proof of freshness *is* the pitch. Use
[Kap](https://getkap.co) or [Gifox](https://gifox.app) on macOS, target 15–30s,
and drop the result at `docs/demo.gif` so the README picks it up.
