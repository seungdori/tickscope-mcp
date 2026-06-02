# Demo prompts

Real-usage prompts for driving Tickscope from an MCP client (Claude Code, Cursor, Codex, …).
Prompts are written in Korean here (that's what the README GIF was recorded with); they work in any language. Each note says which tool(s) the agent ends up calling.

## Quick price (freshness)

> 바이낸스 BTC/USDT 지금 시세랑 24시간 변동률 알려줘.

`get_ticker`. The first call returns `source: "rest"`; a follow-up returns `source: "websocket"` with a much smaller `age_ms` — on-screen proof the price is live.

## Deep analysis — one call, full read ⭐

> 이 SOL/USDT 셋업 진입할 만해? 여러 타임프레임으로 깊게 분석해줘.

`deep_analyze`. Returns multi-timeframe trend confluence, market-state context (price percentile, trend state, volatility state), the historical performance of the current divergence on this pair, and a synthesized verdict (bias / confidence / caveats). Clients with prompt support can also trigger it as the `/deep_analyze` slash command.

## Indicators with market-state context

> BTC/USDT 1시간봉 RSI랑 MACD 봐줘 — 지금 시장 상태에서 그 RSI가 의미 있는 수준인지도.

`compute_indicators` with `["rsi:14","macd"]`. The response carries inline market-state context (trend state, volatility, where price sits in its recent range), so a bare "RSI 30" is read against the conditions it showed up in. Specs accept Pine syntax (`ta.rsi(14)`, `ta.sqz`).

## Signal + historical performance ⭐

> BTC/USDT 4시간봉 RSI 다이버전스 있어? 있으면 이 종목에서 과거에 그 신호 결과가 어땠는지도.

`detect_divergence` for the live signal, plus the event study inside `deep_analyze`: for every past *confirmed* occurrence on this symbol/timeframe it reports the forward-return distribution (count, win rate, median). Strictly causal — measured from the bar the signal confirmed, no look-ahead, no repaint.

## Screening — find candidates

> USDT 거래량 상위 50개 중 RSI 30 미만인 것만 스크리닝해줘.

`screen_market` with `filters=[{"indicator":"rsi:14","op":"<","value":30}]`, `quote="USDT"`, `top_n=50`. Combine filters, e.g. add `{"metric":"change_24h_pct","op":">","value":5}` for "oversold *and* up on the day".

## Golden / death cross (Pine-style)

> ETH/USDT 일봉에서 EMA 50이 EMA 200을 골든크로스했는지 봐줘.

`detect_cross` with `series_a="ema:50", series_b="ema:200"` — current relation, whether a cross happened on the last bar, and bars since. Series accept Pine syntax (`ta.ema(50)`).

## Levels & structure — entries / stops / targets

> ETH/USDT 4시간봉 주요 지지·저항 짚어주고, 방금 구조 깨졌는지(BOS/CHoCH)도 봐줘.

`find_support_resistance` (clustered zones with touch counts + distance from price) and `analyze_structure` (HH/HL/LH/LL swings, inferred trend, Break of Structure / Change of Character on the latest bar).

## Candlestick patterns

> BTC/USDT 4시간봉 최근 캔들에 패턴 잡힌 거 있어?

`detect_patterns` — named patterns (bullish engulfing, hammer, evening star, …) with their bias and how many bars back each formed.

## Funding rate (perps)

> Bybit BTC 무기한 펀딩비 지금 얼마야? 과열이야?

`get_funding_rate` on a perpetual such as `BTC/USDT:USDT`. Stretched or negative funding hints at crowded positioning / squeeze risk.

## Order book spread

> ETH/USDT 호가창 상위 10호가 스프레드 보여줘.

`get_orderbook` with `depth=10` — returns the top levels plus `spread` and `spread_pct`.

## Cross-exchange spread / Kimchi premium

> BTC/USDT 바이낸스·바이비트·OKX 가격 모아서 차익 스프레드 보여줘.
> 업비트 vs 바이낸스 BTC 프리미엄 지금 몇 %야?

`get_aggregated_price` — volume-weighted price across venues, cheapest/most-expensive, and `arb_spread` / `arb_spread_pct`. For the Upbit premium, enable Upbit first: `TICKSCOPE_EXCHANGES=binance,upbit` (ccxt.pro supports 81 exchanges incl. Upbit/Bithumb).

## Live monitoring

> BTC/USDT 계속 지켜보다가 흐름 바뀌면 알려줘.

`watch_symbol` pre-warms a WebSocket subscription; the agent then reads `get_ticker` / `get_watched_symbols` from the warm buffer (sub-second `age_ms`) on a loop.

## Strategy development (Pine workflow)

> 내 진입 조건이 "RSI 다이버전스 + 직전 지지선 근처"인데, BTC/USDT 4시간봉에서 지금 충족돼?

Combines `detect_divergence` + `find_support_resistance` to check a Pine/strategy entry condition against live data, and `deep_analyze`'s event study gives a quick read on how that setup has historically resolved on this symbol.
