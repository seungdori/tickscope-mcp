# TickFeed MCP — 구현 명세서 (Implementation Spec)

> **목적:** 이 문서는 Claude Code에게 전달하여 구현을 의뢰하기 위한 기술 명세서다.
> **한 줄 정의:** 모든 MCP 클라이언트(Claude Code, Cursor, Codex, Gemini CLI 등)에 **실시간 + 과거 암호화폐 시세 데이터를 무료로** 제공하는, 셀프호스팅 가능한 단일 MCP 서버.
> **버전:** v0.1 (MVP 명세) · **작성일:** 2026-06-02

---

## 0. Claude Code에게 — 작업 방식 지시

1. **이 문서를 처음부터 끝까지 읽고**, 섹션 12의 "구현 단계(Phases)"를 **순서대로** 진행하라. 각 단계는 독립적으로 동작/테스트 가능한 산출물을 갖는다.
2. 각 단계 끝의 **수용 기준(Acceptance Criteria)**을 충족해야 다음 단계로 넘어간다.
3. 라이브러리 버전·API는 학습 시점 이후 바뀌었을 수 있으니, **구현 직전 최신 문서를 확인**하라(특히 `ccxt`, `mcp`/`fastmcp`의 현재 권장 API).
4. **v1 범위는 "공개 시장 데이터 읽기 전용"이다.** 주문 실행, API 시크릿 요구, 개인 계정 데이터는 **범위 밖**이다(섹션 16 참고). 이 경계를 임의로 넘지 마라.
5. 설명 산문은 한국어, 코드·식별자·툴 이름·파일 구조는 영어로 작성한다.
6. 모든 외부 호출(거래소)은 **실패할 수 있다고 가정**하고, LLM이 이해할 수 있는 **구조화된 에러**를 반환하라(스택 트레이스 노출 금지, 섹션 9).

---

## 1. 프로젝트 개요

### 1.1 무엇을 만드는가
- 어떤 MCP 클라이언트에서든 호출 가능한 **시세 데이터 MCP 서버**.
- 백그라운드에서 거래소 WebSocket을 유지하여 **신선한** 시세를 제공하고, 과거 캔들·지표·스크리닝까지 단일 서버에서 처리한다.
- `uvx tickfeed-mcp` 한 줄로 실행되는 **낮은 마찰의 설치 경험**을 목표로 한다.

### 1.2 왜 (포지셔닝)
- 트레이딩 에이전트(TradingAgents 등)는 폭발적으로 성장 중이나, 그 밑단의 데이터 레이어는 **파편화 + REST 폴링 전용 + 유료 의존**이다.
- TickFeed의 포지셔닝: **"에이전트용 시세 데이터 — 단, 실시간이고 무료다."** ("X but real-time and free")

### 1.3 범위 (Scope)

| 포함 (v1) | 제외 (v1, 향후 별도 모듈) |
|---|---|
| 공개 시세 데이터 읽기 (ticker, trades, OHLCV, orderbook) | 주문 실행 / 잔고 조회 / 출금 |
| 기술 지표 계산 (TA) | API 시크릿 요구 기능 |
| 멀티 심볼 스크리닝 | 백테스팅 엔진 (별도 프로젝트) |
| 백그라운드 WebSocket 인제스션 + 캐시 | 사용자 인증/멀티테넌시 |
| stdio 트랜스포트 (HTTP/SSE는 옵션) | 데이터 재판매/저장 영속화 서비스 |

---

## 2. 핵심 설계 원칙 & 가장 중요한 제약

> ⚠️ **이 섹션이 프로젝트 전체에서 가장 중요하다. 반드시 숙지하라.**

### 2.1 MCP는 요청/응답이다 — "스트리밍"의 진짜 의미
MCP 툴 호출은 **JSON-RPC 기반의 call → return**이다. 거래소 WebSocket처럼 클라이언트로 데이터를 **계속 푸시하는 것이 아니다.** 따라서 "실시간"은 다음과 같이 구현한다:

1. 서버가 **백그라운드 asyncio 태스크**로 거래소 WebSocket(`ccxt.pro`의 `watch_*`)을 유지한다.
2. 들어오는 틱/캔들/호가를 **인메모리 링 버퍼 + ticker 캐시**에 계속 갱신한다.
3. 에이전트가 `get_ticker` 등을 호출하면, 서버는 **항상 따뜻한 버퍼에서 1초 미만으로 신선한 값**을 즉시 반환한다.

→ **가치 제안의 핵심:** 콜드 REST 호출(수백 ms~수 초, 레이트리밋 위험)이 아니라, 이미 살아있는 연결에서 즉답한다.

### 2.2 콜드 스타트 처리 (UX 핵심)
- 서버가 막 떴거나 해당 심볼을 아직 watch하지 않았다면 버퍼는 비어 있다.
- **규칙: 첫 호출 시 REST로 즉시 스냅샷을 반환하면서, 동시에 해당 심볼의 WS watch를 자동 시작**한다("auto-watch on first query"). 이후 호출부터는 버퍼에서 즉답.
- 에이전트가 명시적으로 `watch_symbol`을 부를 필요가 없게 하라(마찰 제거).

### 2.3 신선도 투명성
- 모든 시세 응답에 `source`(`"websocket"` | `"rest"`)와 `age_ms`(데이터 나이, 밀리초) 필드를 포함하라.
- 이는 LLM이 데이터의 신선도를 인지하고 사용자에게 정확히 전달하게 한다 — 동시에 "실시간"이라는 가치 제안을 응답마다 증명한다.

### 2.4 리소스 기반 푸시는 옵션 (Phase 4+)
- MCP `resources` + subscription으로 watched 심볼을 푸시 가능하나, 클라이언트 지원이 제각각이다.
- v1은 **툴 폴링 방식**으로 충분하다. 리소스 푸시는 후순위 강화 기능으로 둔다.

---

## 3. 기술 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| 언어 | **Python 3.11+** | ccxt·pandas·TA 생태계가 가장 성숙. asyncio로 WS 인제스션 자연스러움 |
| MCP 프레임워크 | **MCP Python SDK의 `FastMCP`** (`from mcp.server.fastmcp import FastMCP`) | 표준·안정. (대안: 기능이 더 풍부한 standalone `fastmcp` 2.x — Claude Code가 현 시점 권장안을 확인 후 택1) |
| 거래소 연동 | **`ccxt`** (REST) + **`ccxt.pro`** (WebSocket `watch_*`) | 100+ 거래소 통합 인터페이스. 단일 의존성으로 멀티거래소 |
| 비동기 HTTP | ccxt 내장 (`ccxt.async_support`) | 별도 클라이언트 불필요 |
| 지표 계산 | **`pandas` + `pandas-ta`** (1차) | 광범위한 지표. 설치 이슈 시 핵심 지표 직접 구현 또는 `ta`로 폴백. TA-Lib은 선택적 가속(시스템 lib 필요) |
| 과거 데이터 캐시 | **DuckDB** (`duckdb`) | 임베디드·파일 기반·빠른 분석 쿼리. 서버 불필요 |
| 설정/검증 | **`pydantic` + `pydantic-settings`** | 툴 I/O 스키마 + 환경설정 |
| 성능(옵션) | `uvloop` (Linux/macOS) | 이벤트 루프 가속 |
| 패키징 | `pyproject.toml` + **PyPI 배포** | `uvx tickfeed-mcp` 즉시 실행 |
| 개발도구 | `pytest`, `pytest-asyncio`, `ruff`, `mypy` | 테스트·린트·타입체크 |

---

## 4. 아키텍처

```
┌───────────────────────────────────────────────────┐
│  MCP Client (Claude Code / Cursor / Codex / Gemini) │
└───────────────────────────┬───────────────────────┘
                            │ JSON-RPC over stdio (기본) / HTTP+SSE (옵션)
┌───────────────────────────▼───────────────────────┐
│  TickFeed MCP Server (FastMCP)                      │
│  ┌──────────────┐   ┌────────────────────────────┐ │
│  │  Tool Layer  │   │  Resource Layer (옵션,후순위)│ │
│  └──────┬───────┘   └──────────────┬─────────────┘ │
│         │                          │               │
│  ┌──────▼──────────────────────────▼─────────────┐ │
│  │  Market Data Service (코어 조정자)             │ │
│  │   - 캐시 조회 우선, 미스 시 REST 폴백          │ │
│  │   - auto-watch 트리거                          │ │
│  │   - 지표 엔진 호출                             │ │
│  └──────┬───────────────────────────┬────────────┘ │
│         │                           │              │
│  ┌──────▼───────┐          ┌────────▼───────────┐  │
│  │ WS Ingestion │          │  REST Fetcher       │  │
│  │ (background  │          │  (ccxt async,       │  │
│  │  asyncio     │          │   on-demand +       │  │
│  │  tasks,      │          │   historical OHLCV) │  │
│  │  ccxt.pro)   │          │                     │  │
│  └──────┬───────┘          └────────┬───────────┘  │
│         │                           │              │
│  ┌──────▼───────────────────────────▼────────────┐ │
│  │  Storage Layer                                 │ │
│  │   - In-memory ring buffers (ticks/trades)      │ │
│  │   - Ticker cache (symbol → latest snapshot)    │ │
│  │   - DuckDB (historical OHLCV cache)            │ │
│  └────────────────────────────────────────────────┘ │
└───────────────────────────┬───────────────────────┘
                            │
            ┌───────────────▼────────────────┐
            │ Exchanges (ccxt + ccxt.pro WS)  │
            │ Binance · Bybit · OKX · ...     │
            └─────────────────────────────────┘
```

### 컴포넌트 책임
- **Tool Layer:** MCP 툴 등록·입력 검증·출력 직렬화. 비즈니스 로직 없음(서비스에 위임).
- **Market Data Service:** "캐시 우선 → 미스 시 REST → auto-watch 시작"의 조정자. 모든 툴이 통과하는 단일 진입점.
- **WS Ingestion:** 거래소별 백그라운드 태스크. `watch_trades`/`watch_ticker`/`watch_ohlcv`/`watch_order_book` 루프. 재연결·백오프 포함.
- **REST Fetcher:** 콜드 스타트 스냅샷 + 과거 OHLCV(WS로 못 받는 긴 히스토리).
- **Storage:** 링 버퍼(고정 크기, 최신 N개 유지) + ticker 캐시(dict) + DuckDB(과거 캔들 영속 캐시로 중복 호출 방지).

---

## 5. 프로젝트 구조

```
tickfeed-mcp/
├── pyproject.toml
├── README.md                      # 섹션 14 가이드대로 (런칭용)
├── LICENSE                        # MIT
├── .env.example
├── .gitignore
├── src/
│   └── tickfeed/
│       ├── __init__.py
│       ├── __main__.py            # python -m tickfeed 진입점
│       ├── server.py              # FastMCP 앱 생성 + 툴 등록 + lifespan(인제스션 시작/종료)
│       ├── config.py              # pydantic-settings 기반 Settings
│       ├── models.py              # 모든 툴 I/O pydantic 모델
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── meta.py            # list_exchanges, list_symbols, server_status
│       │   ├── market.py          # get_ticker, get_recent_trades, get_ohlcv, get_orderbook, get_funding_rate
│       │   ├── indicators.py      # compute_indicators
│       │   ├── screen.py          # screen_market
│       │   └── watch.py           # watch_symbol, get_watched_symbols
│       ├── core/
│       │   ├── __init__.py
│       │   ├── exchange_manager.py  # ccxt/ccxt.pro 인스턴스 생성·캐시·종료
│       │   ├── service.py           # MarketDataService (조정자)
│       │   ├── ingestion.py         # 백그라운드 WS 태스크 + 재연결
│       │   ├── cache.py             # RingBuffer, TickerCache
│       │   ├── storage.py           # DuckDB OHLCV 캐시
│       │   └── indicators_engine.py # TA 계산
│       └── utils.py               # 시간/심볼 정규화, 에러 래핑
├── tests/
│   ├── conftest.py
│   ├── fixtures/                  # 녹화된 거래소 응답 (CI용)
│   ├── test_indicators.py         # 지표 수학 검증 (알려진 값 대조)
│   ├── test_market.py
│   ├── test_service.py
│   └── test_integration_live.py   # @pytest.mark.live (CI 기본 제외)
└── examples/
    ├── claude_code_config.json    # 클라이언트 등록 예시
    └── demo_prompts.md            # 데모용 프롬프트 모음 (GIF 촬영용)
```

---

## 6. MCP 툴 명세 (핵심)

> **공통 규칙**
> - 모든 입력은 pydantic으로 검증한다.
> - `exchange`가 생략되면 `TICKFEED_DEFAULT_EXCHANGE`를 사용한다.
> - 심볼 표기는 ccxt 통합 표기(`BASE/QUOTE`, 예: `BTC/USDT`)를 표준으로 받되, `BTCUSDT` 같은 입력도 정규화한다.
> - 시세성 응답에는 항상 `source`, `age_ms`, `timestamp`(ISO-8601, UTC)를 포함한다.
> - 에러는 섹션 9의 구조화 포맷으로 반환한다(예외를 그대로 던지지 않는다).
> - **각 툴의 docstring/description은 LLM이 도구를 정확히 고르도록 명확하게 작성**하라(언제 쓰는지, 무엇을 반환하는지).

### 6.1 `list_exchanges`
- **목적:** 설정에서 활성화된(또는 지원되는) 거래소 목록 반환.
- **파라미터:** 없음.
- **반환:**
  ```json
  { "configured": ["binance", "bybit", "okx"], "default": "binance" }
  ```
- **수용 기준:** 설정값과 일치하는 목록을 반환한다.

### 6.2 `list_symbols`
- **목적:** 특정 거래소의 거래 가능 심볼 목록(필터 가능).
- **파라미터:**
  | 이름 | 타입 | 필수 | 기본 | 설명 |
  |---|---|---|---|---|
  | `exchange` | string | N | default | 거래소 |
  | `quote` | string | N | null | 견적통화 필터(예: `USDT`) |
  | `search` | string | N | null | 부분 일치 필터(예: `BTC`) |
  | `limit` | int | N | 100 | 최대 개수 |
- **반환:** `{ "exchange": "...", "count": N, "symbols": ["BTC/USDT", ...] }`
- **동작 노트:** 마켓 목록은 거래소당 1회 로드 후 캐시(`load_markets`).

### 6.3 `get_ticker`
- **목적:** 심볼의 현재 시세 스냅샷(최우선 사용 툴).
- **파라미터:** `exchange?`, `symbol`(필수)
- **반환:**
  ```json
  {
    "exchange": "binance",
    "symbol": "BTC/USDT",
    "last": 67432.1,
    "bid": 67431.9,
    "ask": 67432.3,
    "high_24h": 68000.0,
    "low_24h": 66500.0,
    "volume_24h": 12345.6,
    "change_24h_pct": 1.23,
    "timestamp": "2026-06-02T12:34:56Z",
    "source": "websocket",
    "age_ms": 320
  }
  ```
- **동작 노트:** ticker 캐시 우선 → 미스 시 REST 즉시 반환 + auto-watch 시작.
- **수용 기준:** 콜드 상태 첫 호출은 `source:"rest"`, 잠시 후 재호출은 `source:"websocket"` & 더 작은 `age_ms`.

### 6.4 `get_recent_trades`
- **목적:** 최근 체결(틱) 내역을 라이브 버퍼에서 반환.
- **파라미터:** `exchange?`, `symbol`(필수), `limit`(기본 50, 최대 1000)
- **반환:**
  ```json
  {
    "exchange":"binance","symbol":"BTC/USDT","count":50,"source":"websocket",
    "trades":[ { "ts":"...", "price":67432.1, "amount":0.012, "side":"buy" } ]
  }
  ```
- **동작 노트:** 버퍼가 비었으면 REST `fetch_trades`로 폴백 + watch 시작.

### 6.5 `get_ohlcv`
- **목적:** 과거 캔들(차트/지표 계산의 기반).
- **파라미터:**
  | 이름 | 타입 | 필수 | 기본 | 설명 |
  |---|---|---|---|---|
  | `exchange` | string | N | default | |
  | `symbol` | string | Y | | |
  | `timeframe` | string | N | `1h` | `1m,5m,15m,1h,4h,1d` 등 |
  | `limit` | int | N | 200 | 캔들 수 (최대 1000) |
  | `since` | string | N | null | ISO-8601 또는 epoch ms |
- **반환:** OHLCV 배열 `[{ "ts","open","high","low","close","volume" }, ...]` + `meta`(개수, 캐시 hit 여부).
- **동작 노트:** **DuckDB 캐시 우선** → 부족분만 REST 보충 후 저장(중복 호출·레이트리밋 절감).
- **수용 기준:** 동일 요청 2회차는 캐시 hit으로 외부 호출 0회.

### 6.6 `get_orderbook`
- **목적:** 현재 호가창 스냅샷.
- **파라미터:** `exchange?`, `symbol`(필수), `depth`(기본 20, 최대 100)
- **반환:** `{ "bids":[[price,amount],...], "asks":[[price,amount],...], "spread", "spread_pct", "source","age_ms","timestamp" }`
- **동작 노트:** WS `watch_order_book` 버퍼 우선 → 미스 시 REST.

### 6.7 `compute_indicators`
- **목적:** 지정 심볼/타임프레임에 대해 요청한 기술 지표 계산(차별화 핵심 툴).
- **파라미터:**
  | 이름 | 타입 | 필수 | 기본 | 설명 |
  |---|---|---|---|---|
  | `exchange` | string | N | default | |
  | `symbol` | string | Y | | |
  | `timeframe` | string | N | `1h` | |
  | `limit` | int | N | 200 | 계산용 캔들 수 |
  | `indicators` | string[] | Y | | 지표 스펙 리스트(아래) |
  | `include_series` | bool | N | false | true면 전체 시계열도 반환 |
- **지표 스펙 표기:** `"name:param1,param2"` 형식.
  - 예: `["rsi:14", "macd:12,26,9", "ema:20", "ema:50", "bbands:20,2", "atr:14", "stoch:14,3,3", "vwap"]`
- **반환:** 지표별 **최신값**(+ 옵션 시계열), 그리고 **파생 신호**(예: `rsi_state: "overbought"|"oversold"|"neutral"`, `macd_cross: "bullish"|"bearish"|"none"`).
  ```json
  {
    "symbol":"BTC/USDT","timeframe":"1h","as_of":"...",
    "results":{
      "rsi_14": { "value": 71.3, "state":"overbought" },
      "macd_12_26_9": { "macd": 120.4, "signal": 90.1, "hist": 30.3, "cross":"bullish" },
      "ema_20": { "value": 67010.2 },
      "bbands_20_2": { "upper":..., "mid":..., "lower":..., "percent_b":0.92 }
    }
  }
  ```
- **동작 노트:** 내부적으로 `get_ohlcv`를 재사용해 캔들 확보 후 엔진 계산. 지원 지표 목록은 docstring에 명시.
- **수용 기준:** 알려진 입력에 대해 RSI/EMA/MACD 값이 기준 구현과 오차 허용범위 내 일치(테스트로 검증).

### 6.8 `screen_market`
- **목적:** 여러 심볼을 지표/가격 조건으로 스크리닝.
- **파라미터:**
  | 이름 | 타입 | 필수 | 기본 | 설명 |
  |---|---|---|---|---|
  | `exchange` | string | N | default | |
  | `symbols` | string[] | N | null | 대상(미지정 시 견적통화 상위 N) |
  | `quote` | string | N | `USDT` | symbols 미지정 시 사용 |
  | `top_n` | int | N | 30 | 거래량 상위 N개 자동 선택 |
  | `timeframe` | string | N | `1h` | |
  | `filters` | object[] | Y | | 조건 리스트(아래) |
  | `sort_by` | string | N | `volume_24h` | 정렬 기준 |
- **필터 표기 예:** `[{"indicator":"rsi:14","op":"<","value":30}, {"metric":"change_24h_pct","op":">","value":5}]`
- **반환:** 조건을 통과한 심볼 + 관련 지표/메트릭 값 배열.
- **동작 노트:** 다수 심볼 처리 시 **동시성 제한 + 레이트리밋 준수**(섹션 9). 부분 실패는 결과에 포함하되 `errors` 배열로 분리.
- **수용 기준:** 30개 심볼 스크리닝이 레이트리밋 위반 없이 완료된다.

### 6.9 `get_funding_rate` (파생상품)
- **목적:** 무기한 선물의 현재(및 예측) 펀딩비.
- **파라미터:** `exchange?`, `symbol`(필수, 예: `BTC/USDT:USDT`)
- **반환:** `{ "symbol","funding_rate","next_funding_time","mark_price","index_price","timestamp" }`
- **동작 노트:** 거래소가 미지원이면 구조화 에러 반환.

### 6.10 `watch_symbol` (명시적 워밍업, 옵션)
- **목적:** 특정 심볼의 WS 구독을 미리 시작(버퍼 워밍).
- **파라미터:** `exchange?`, `symbol`(필수), `channels`(기본 `["ticker","trades"]`)
- **반환:** `{ "status":"watching","symbol":"...","channels":[...] }`
- **동작 노트:** `TICKFEED_MAX_WATCHED_SYMBOLS` 한도 초과 시 가장 오래 미사용 심볼을 LRU로 해제.

### 6.11 `get_watched_symbols`
- **목적:** 현재 활성 WS 구독 및 버퍼 상태 조회(진단용).
- **반환:** `{ "watched":[{ "exchange","symbol","channels","buffer_size","last_update":"...","staleness_ms" }] }`

### 6.12 `server_status`
- **목적:** 헬스체크/진단. 업타임, 활성 거래소, 구독 수, 캐시 통계, ccxt 버전.
- **반환:** `{ "uptime_s","exchanges":[...],"watched_count","ohlcv_cache_rows","ccxt_version","ws_reconnects" }`

---

## 7. 데이터 소스 & 거래소 연동

- **MVP 거래소(3~4개):** `binance`, `bybit`, `okx` (+ 여유 시 `coinbase`). 모두 공개 데이터는 키 불필요.
- **REST:** `ccxt.async_support` — `fetch_ticker`, `fetch_trades`, `fetch_ohlcv`, `fetch_order_book`, `fetch_funding_rate`, `load_markets`.
- **WebSocket:** `ccxt.pro` — `watch_ticker`, `watch_trades`, `watch_ohlcv`, `watch_order_book`. 각 거래소 인스턴스는 하나만 생성해 재사용.
- **거래소 인스턴스 생성 시:** `{ "enableRateLimit": True }` 설정. 인스턴스는 `exchange_manager`가 캐시하고 종료 시 `await exchange.close()` 호출.
- **심볼 정규화:** 입력 `BTCUSDT` → `BTC/USDT`로 변환하는 유틸 제공(거래소 마켓 메타 활용).

---

## 8. 설정 (Configuration)

`.env` / 환경변수 (pydantic-settings). `.env.example` 제공.

| 변수 | 기본 | 설명 |
|---|---|---|
| `TICKFEED_EXCHANGES` | `binance,bybit,okx` | 활성 거래소(콤마 구분) |
| `TICKFEED_DEFAULT_EXCHANGE` | `binance` | 기본 거래소 |
| `TICKFEED_MAX_WATCHED_SYMBOLS` | `25` | 동시 WS 구독 상한(초과 시 LRU 해제) |
| `TICKFEED_RING_BUFFER_SIZE` | `1000` | 심볼당 틱 버퍼 크기 |
| `TICKFEED_OHLCV_CACHE_PATH` | `~/.tickfeed/ohlcv.duckdb` | DuckDB 파일 경로 |
| `TICKFEED_OHLCV_CACHE_TTL_S` | `60` | 최신 캔들 캐시 신선도(초) |
| `TICKFEED_TRANSPORT` | `stdio` | `stdio` \| `http` |
| `TICKFEED_HTTP_HOST` / `TICKFEED_HTTP_PORT` | `127.0.0.1` / `8765` | HTTP 트랜스포트 시 |
| `TICKFEED_LOG_LEVEL` | `INFO` | 로그 레벨 |

> **중요:** v1은 거래소 **API 키를 요구하지 않는다.** 키 입력은 어디에도 강제하지 마라(섹션 16).

---

## 9. 에러 처리 & 레이트 리밋

### 9.1 구조화 에러
- ccxt 예외(`NetworkError`, `ExchangeError`, `RateLimitExceeded`, `BadSymbol`, `ExchangeNotAvailable` 등)를 잡아 **표준 형태로 반환**:
  ```json
  { "error": { "type":"BadSymbol", "message":"...", "exchange":"binance", "symbol":"BTC/USDT", "retryable": false } }
  ```
- `retryable`은 네트워크/레이트리밋 계열만 `true`. LLM이 재시도 여부를 판단할 수 있게 한다.

### 9.2 레이트 리밋
- ccxt `enableRateLimit=True` 기본 사용.
- 멀티 심볼 작업(`screen_market`)은 `asyncio.Semaphore`로 **동시성 제한**(예: 거래소당 5) + 지수 백오프 재시도(`RateLimitExceeded` 시 최대 3회).
- 과거 OHLCV는 **DuckDB 캐시로 외부 호출 최소화**.

### 9.3 WebSocket 복원력
- 인제스션 태스크는 예외 시 **지수 백오프 재연결**(상한 30s)하고 `ws_reconnects` 카운터 증가.
- watched 심볼의 마지막 갱신이 N초 이상 정체되면 응답의 `age_ms`로 노출되어 LLM이 인지.

---

## 10. 저장소 & 캐싱 전략

| 데이터 | 저장 | 정책 |
|---|---|---|
| 최근 틱/체결 | 인메모리 **RingBuffer**(고정 크기) | 최신 N개 유지, 오래된 것 폐기 |
| 최신 ticker/orderbook | 인메모리 **dict 캐시** | WS 갱신마다 덮어쓰기, `age_ms` 계산용 타임스탬프 보관 |
| 과거 OHLCV | **DuckDB** 테이블 `(exchange, symbol, timeframe, ts) PK` | upsert. 동일 구간 재요청 시 캐시 hit. 최신 캔들만 TTL로 갱신 |

- DuckDB 스키마는 단일 테이블로 단순화. 인덱스/PK로 구간 조회 최적화.
- 캐시 무효화: 진행 중(미마감) 캔들은 `TICKFEED_OHLCV_CACHE_TTL_S` 경과 시 재조회.

---

## 11. 테스트 전략

- **지표 단위 테스트(필수):** 알려진 입력 시계열에 대해 RSI/EMA/SMA/MACD/Bollinger/ATR 값을 **기준값과 대조**. (이 프로젝트 신뢰성의 핵심.)
- **서비스 테스트:** 캐시 hit/miss, auto-watch 트리거, 콜드→웜 전환 로직을 **모킹된 거래소**로 검증.
- **통합 테스트(라이브):** `@pytest.mark.live`로 분리하여 **CI 기본 제외**(실거래소 의존). 로컬에서만 선택 실행.
- **픽스처:** 거래소 응답을 녹화해 `tests/fixtures/`에 저장, CI는 이를 사용(외부 의존 없이 결정적).
- 린트/타입: `ruff` + `mypy` 통과를 CI 게이트로.

---

## 12. 구현 단계 (Phases) — 순서대로 진행

> 각 단계는 **독립 동작 + 테스트 + 수용 기준 충족**을 만족해야 한다.

### Phase 0 — 스캐폴드 & 파이프 검증
- 프로젝트 구조 생성, `pyproject.toml`, 설정(`config.py`), `exchange_manager`(REST만).
- FastMCP stdio 서버 기동, **`list_exchanges` + `get_ticker`(REST 전용)** 구현.
- **수용 기준:** Claude Code에 stdio MCP로 등록 → `get_ticker("binance","BTC/USDT")` 호출 시 정상 응답.

### Phase 1 — 과거 데이터 & 호가
- `list_symbols`, `get_ohlcv`(+ DuckDB 캐시), `get_orderbook`(REST).
- **수용 기준:** 동일 `get_ohlcv` 2회차가 캐시 hit(외부 호출 0). 호가 스냅샷 정상.

### Phase 2 — 지표 엔진
- `indicators_engine` + `compute_indicators`, `screen_market`.
- 지표 단위 테스트 작성.
- **수용 기준:** 지표 값이 기준 구현과 일치. 30심볼 스크리닝이 레이트리밋 위반 없이 완료.

### Phase 3 — 실시간 WS 인제스션 (핵심 가치)
- `ingestion`(백그라운드 `watch_*` 태스크 + 재연결), `cache`(RingBuffer/TickerCache), server lifespan에 인제스션 시작/종료 연결.
- **auto-watch on first query** 구현. `get_ticker`/`get_recent_trades`/`get_orderbook`가 버퍼 우선.
- `watch_symbol`, `get_watched_symbols`, `server_status`, `source`/`age_ms` 필드.
- **수용 기준:** 콜드 첫 호출 `source:"rest"` → 수 초 후 재호출 `source:"websocket"` & `age_ms` 감소. WS 강제 끊김 후 자동 재연결.

### Phase 4 — 폴리시 & 배포
- 구조화 에러 전수 적용, `get_funding_rate`, HTTP/SSE 트랜스포트(옵션), `uvloop`(옵션).
- **PyPI 배포** 설정, `uvx tickfeed-mcp` 검증.
- `examples/claude_code_config.json`, `examples/demo_prompts.md`, **README**(섹션 14).
- **수용 기준:** 새 머신에서 `uvx tickfeed-mcp`만으로 동작. README의 설치 스니펫이 그대로 작동.

### Phase 5 — 차별화 기능 (런칭 후/여유 시)
- 섹션 15 참고(Pine 스타일 지표 매핑, 멀티거래소 집계, 리소스 푸시 등).

---

## 13. 배포 & 설치

### 13.1 PyPI / 실행
- `pyproject.toml`에 콘솔 스크립트 엔트리포인트(`tickfeed = "tickfeed.__main__:main"`).
- 목표 실행 경험: `uvx tickfeed-mcp` 또는 `pipx run tickfeed-mcp`.

### 13.2 클라이언트 등록 예시 (`examples/claude_code_config.json`)
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
- Cursor/Codex/Gemini CLI용 등록법도 README에 함께 명시.

---

## 14. README 작성 가이드 (런칭 = 성패의 핵심)

> 코드만큼 README/데모에 공을 들여라. 1,000+ 스타의 단일 최대 변수는 런칭이다.

순서:
1. **상단 GIF**(15~30초): Claude Code가 "지금 BTC RSI 얼마고 다이버전스 있어?"에 **라이브로** 답하는 장면. `source:"websocket"`/`age_ms`가 보이면 더 좋다.
2. **한 줄 가치 제안:** "Real-time, free market data for any AI coding agent — via MCP."
3. **Why**(2~3문장): 에이전트용 데이터가 파편화·유료·폴링뿐인 문제.
4. **30초 설치:** `uvx tickfeed-mcp` + config 스니펫(복붙 가능).
5. **지원 거래소 표** / **툴 목록**(한 줄 설명).
6. **예시 프롬프트**(실사용 시나리오 5개).
7. **로드맵** + **기여 가이드** + **라이선스(MIT)**.
8. **면책 고지**(섹션 16): 교육/연구 목적, 투자 조언 아님, 데이터 정확성 무보증.

---

## 15. 차별화 기능 (Phase 5+, 후순위)

- **Pine Script 스타일 지표 매핑:** `ta.rsi`, `ta.sma`, `ta.crossover` 등 Pine 관용 표현을 엔진 지표로 매핑하는 헬퍼/툴. (사용자의 Pine 전문성을 살린 고유 차별점.)
- **멀티거래소 집계:** 동일 심볼의 여러 거래소 가중평균가/스프레드(차익 탐지 토대).
- **MCP 리소스 푸시:** watched 심볼을 리소스로 노출하고 `resources/updated` 알림(지원 클라이언트 한정).
- **Agent Skill 래퍼:** `SKILL.md` + 얇은 스크립트로 동일 기능을 "스킬" 포맷으로도 배포(추천안 #3 QuantSkills와 연계).
- **거래소 확장:** Kraken, Bitget, Gate 등 추가.

---

## 16. 보안 & 법적 고려사항

- **읽기 전용·공개 데이터만.** v1은 주문 실행/잔고/출금/개인 계정 데이터를 **다루지 않는다.** API 시크릿을 요구하지 마라(설치 마찰↓, 책임↓, 안전↑).
- **시크릿 처리:** 향후 인증 기능을 추가하더라도 키는 환경변수로만 받고 로그/응답에 절대 노출하지 마라.
- **면책 고지(README + 서버 메타):** 본 도구는 **교육·연구 목적**이며 금융·투자·트레이딩 조언이 아니다. 데이터 정확성·적시성을 보증하지 않는다. (TradingAgents 등 성공 사례의 관행을 따른다 — 커뮤니티 수용도↑, 책임↓.)
- **거래소 약관 준수:** 공개 데이터라도 각 거래소의 레이트리밋·이용약관을 준수(섹션 9의 레이트리밋 설계가 이를 뒷받침).
- **의존성 보안:** 최소 의존성 유지, 알려진 취약점 점검.

---

## 17. 완료 정의 (Definition of Done, v1)

- [ ] Phase 0~4 전부 수용 기준 충족.
- [ ] 12개 툴 동작 + 구조화 에러 + `source`/`age_ms` 신선도 노출.
- [ ] 지표 단위 테스트 통과, `ruff`/`mypy` CI 게이트 통과.
- [ ] `uvx tickfeed-mcp`로 새 환경에서 즉시 실행.
- [ ] Claude Code에서 콜드→웜 전환이 실제로 관측됨(REST→WebSocket).
- [ ] README + GIF 데모 + 예시 config/프롬프트 완비.
- [ ] MIT 라이선스 + 면책 고지.

---

### 부록 A — 지원 지표 최소 목록 (compute_indicators)
SMA, EMA, WMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, VWAP, OBV, ADX, CCI.
(엔진은 확장 가능하게 설계하고, docstring에 현재 지원 목록을 항상 반영하라.)

### 부록 B — 데모 프롬프트 예시 (examples/demo_prompts.md)
- "바이낸스 BTC/USDT 지금 시세랑 24시간 변동률 알려줘."
- "BTC/USDT 1시간봉 RSI랑 MACD 계산해서 다이버전스 있는지 봐줘."
- "USDT 페어 거래량 상위 30개 중 RSI 30 미만인 것만 스크리닝해줘."
- "BYBIT BTC 무기한 펀딩비 지금 얼마야?"
- "ETH/USDT 호가창 상위 10호가 스프레드 보여줘."
