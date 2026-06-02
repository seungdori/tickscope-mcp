# Demo prompts

Real-usage prompts for showcasing Tickscope in an MCP client (great for the README GIF).

## Live price

> 바이낸스 BTC/USDT 지금 시세랑 24시간 변동률 알려줘.

Uses `get_ticker`. Notice `source: "rest"` on the first call, then `source: "websocket"` with a smaller `age_ms` on the follow-up.

## Indicators + divergence

> BTC/USDT 1시간봉 RSI랑 MACD 계산해서 다이버전스 있는지 봐줘.

Uses `compute_indicators` with `["rsi:14", "macd:12,26,9"]` and reads the derived `state` / `cross` signals.

## Screening

> USDT 페어 거래량 상위 30개 중 RSI 30 미만인 것만 스크리닝해줘.

Uses `screen_market` with `filters=[{"indicator":"rsi:14","op":"<","value":30}]` and `quote="USDT"`, `top_n=30`.

## Funding rate

> Bybit BTC 무기한 펀딩비 지금 얼마야?

Uses `get_funding_rate` on a perpetual symbol such as `BTC/USDT:USDT`.

## Order book spread

> ETH/USDT 호가창 상위 10호가 스프레드 보여줘.

Uses `get_orderbook` with `depth=10`; returns `spread` and `spread_pct`.

## RSI divergence (auto-detected)

> BTC/USDT 4시간봉에서 RSI 다이버전스 잡아줘.

Uses `detect_divergence` with `oscillator="rsi:14"`. Returns regular/hidden
bullish & bearish divergences with the pivot price/oscillator values and how
many bars back each pivot is.

## Golden / death cross (Pine-style)

> ETH/USDT 일봉에서 EMA 50이 EMA 200을 골든크로스했는지 봐줘.

Uses `detect_cross` with `series_a="ema:50", series_b="ema:200"`. Reports the
current relation, whether a cross happened on the last bar, and bars since the
last cross. Series accept Pine syntax too (`ta.ema(50)`).

## Cross-exchange arbitrage view

> BTC/USDT 바이낸스·바이비트·OKX 가격 모아서 차익 스프레드 보여줘.

Uses `get_aggregated_price`. Returns the volume-weighted average price, the
cheapest/most-expensive venue, and `arb_spread` / `arb_spread_pct`.

## Candlestick patterns

> BTC/USDT 4시간봉 최근 캔들에서 패턴 잡힌 거 있어?

Uses `detect_patterns`. Returns named patterns (e.g. bullish engulfing, hammer,
evening star) with their bias and how many bars back each formed.

## Market structure (HH/HL, BOS/CHoCH)

> ETH/USDT 일봉 시장 구조 분석해줘 — 추세랑 구조 깨짐 있는지.

Uses `analyze_structure`. Returns the swing sequence (HH/HL/LH/LL), the trend,
and any Break of Structure / Change of Character on the latest bar.

## Support & resistance

> SOL/USDT 1시간봉 주요 지지·저항 레벨 알려줘.

Uses `find_support_resistance`. Returns clustered support/resistance zones with
touch counts and distance from the current price.
