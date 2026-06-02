<div align="center">

# TickFeed MCP

**面向任意 AI 智能体的实时、免费加密货币行情数据 —— 通过 MCP。**

[![PyPI](https://img.shields.io/pypi/v/tickfeed-mcp.svg)](https://pypi.org/project/tickfeed-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/tickfeed-mcp.svg)](https://pypi.org/project/tickfeed-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/seungdori/tickfeed-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/seungdori/tickfeed-mcp/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-blue.svg)](https://mypy-lang.org/)
[![MCP](https://img.shields.io/badge/MCP-server-6E56CF.svg)](https://modelcontextprotocol.io)

[English](README.md) · [한국어](README.ko.md) · **中文** · [日本語](README.ja.md)

![TickFeed demo](docs/demo-agent.gif)

</div>

TickFeed 是一个可自托管的 [Model Context Protocol](https://modelcontextprotocol.io) 服务器，为任意 MCP 客户端（Claude Code、Cursor、Codex、Gemini CLI 等）**免费提供实时与历史加密货币行情数据**。它在后台持续维持交易所的 WebSocket 长连接，因此你的智能体可以直接从中读取**亚秒级延迟**的实时价格。同一个服务器还提供 **73 个技术指标**与**图表结构识别**，无需 API 密钥。

> ⚠️ 教育/研究工具。本工具不提供金融、投资或交易建议，也不保证数据的准确性与时效性。

---

## 目录

- [为什么](#为什么) · [运行演示](#运行演示) · [30 秒安装](#30-秒安装)
- [支持的交易所](#支持的交易所) · [工具](#工具) · [指标](#指标73-个) · [结构识别](#结构识别)
- [示例提示词](#示例提示词) · [配置](#配置) · [开发](#开发) · [路线图](#路线图)

## 为什么

交易类智能体正在爆发式增长，而其底层数据层依然碎片化、仅支持 REST 轮询、且常常收费。TickFeed 为这些智能体提供**实时、免费的行情数据**，全部来自一个服务器 —— 多个交易所，无需 API 密钥。

## 运行演示

```bash
uv run examples/demo.py            # BTC/USDT 实时演示（无需 API 密钥）
uv run examples/demo.py ETH/USDT 4h
```

一个连接 Binance/Bybit/OKX 实时数据的彩色终端演示 —— 冷启动→热缓存的新鲜度（REST → WebSocket）、带信号的指标、背离、市场结构以及支撑/阻力。将其制作成上方 GIF 的方法见 [examples/RECORDING.md](examples/RECORDING.md)。

## 30 秒安装

```bash
uvx tickfeed-mcp
```

在你的客户端中注册（Claude Code 示例，[`examples/claude_code_config.json`](examples/claude_code_config.json)）：

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

Cursor、Codex 和 Gemini CLI 在各自的 MCP 配置文件中使用相同的 `command`/`args`/`env` 结构。

## 支持的交易所

| 交易所 | REST | WebSocket |
|---|:---:|:---:|
| Binance | ✅ | ✅ |
| Bybit | ✅ | ✅ |
| OKX | ✅ | ✅ |

任何 [ccxt](https://github.com/ccxt/ccxt) 支持的交易所都可通过 `TICKFEED_EXCHANGES` 启用。仅公开数据 —— 无需密钥。

## 工具

| 工具 | 功能 |
|---|---|
| `list_exchanges` | 已配置的交易所 + 默认值 |
| `list_symbols` | 可交易标的（按计价货币/搜索过滤） |
| `get_ticker` | 当前价格快照（首选行情工具） |
| `get_recent_trades` | 来自实时缓冲区的最近成交 |
| `get_ohlcv` | 历史 K 线（DuckDB 缓存） |
| `get_orderbook` | 订单簿快照 + 价差 |
| `compute_indicators` | 73 个指标（RSI/MACD/Supertrend/WaveTrend/Squeeze/…）及衍生信号 |
| `detect_divergence` | 常规/隐藏的多空背离（价格 vs 振荡器） |
| `detect_cross` | Pine 风格的 `ta.crossover`/`ta.crossunder`（任意两条序列） |
| `detect_patterns` | K 线形态（吞没、锤子、星线等）及方向偏好 |
| `analyze_structure` | 市场结构：摆动点、趋势、BOS / CHoCH |
| `find_support_resistance` | 由摆动点聚类得到的支撑/阻力区 |
| `screen_market` | 按指标/价格条件筛选多个标的 |
| `get_aggregated_price` | 成交量加权价格 + 跨交易所价差（套利） |
| `get_funding_rate` | 永续合约资金费率 |
| `watch_symbol` | 预热实时订阅（可选） |
| `get_watched_symbols` | 活跃订阅 + 缓冲区状态 |
| `server_status` | 健康检查 / 诊断 |

每个行情响应都包含 `source`（`websocket`|`rest`）、`age_ms` 和 `timestamp`，因此数据的新鲜度随时都能核对。

### 指标（73 个）

- **均线 / 叠加：** `sma ema wma smma dema tema hma vwma zlema alma kama trima lsma vidya t3 vwap vwapbands bbands donchian keltner supertrend ichimoku psar`
- **动量：** `rsi stochrsi macd ppo stoch cci willr roc mom tsi ao cmo uo dpo trix coppock kst fisher rvi mfi wavetrend squeeze qqe crsi stc elderray zscore linregslope`
- **波动率：** `atr natr stdev hv chop ulcer massindex`
- **成交量：** `obv adl cmf chaikinosc eom fi pvt vo klinger`
- **趋势：** `adx dmi aroon vortex`
- **结构：** `heikinashi pivots`

规格为 `"name:p1,p2"` 格式，同时也接受 **Pine Script 语法** —— `ta.rsi(14)`、`ta.ema(20)`、`ta.wt(10,21)`、`ta.sqz` —— 因此 TradingView 用户可以直接粘贴熟悉的表达式。衍生信号包括超买/超卖 state、MACD/PPO/WaveTrend/QQE 交叉、振荡器的零轴交叉、Supertrend/PSAR 方向与翻转、squeeze 开/关、DMI/Heikin-Ashi 趋势，以及 Ichimoku 云图位置。内置加密/Pine 热门指标（WaveTrend、TTM Squeeze、QQE、Connors RSI、Schaff Trend Cycle、VIDYA、T3）。新增一个指标只需在 `REGISTRY` 中声明一行。

### 结构识别

除了数值指标，TickFeed 还能描述*图表上正在发生什么*：`detect_patterns` 为 K 线形态（吞没、锤子/上吊线、十字星家族、早晨/黄昏之星、红三兵/黑三鸦等）命名并标注方向偏好；`analyze_structure` 返回标注为 HH/HL/LH/LL 的摆动高低点、推断出的趋势，以及结构突破（BOS）/ 性质改变（CHoCH）事件（SMC 风格）；`find_support_resistance` 将摆动点聚类为支撑/阻力区并计数触碰次数。有了这些，智能体就能用交易者的语言*描述*图表。

### 资源

支持的客户端还可以将实时状态作为 MCP 资源读取：`tickfeed://status`、`tickfeed://watched`，以及模板 `tickfeed://ticker/{exchange}/{symbol}`。

## 示例提示词

- “币安 BTC/USDT 现在多少钱，24 小时涨跌幅是多少？”
- “计算 BTC/USDT 的 1 小时 RSI 和 MACD，看看有没有背离。”
- “在成交量前 30 的 USDT 交易对里，筛选出 RSI 低于 30 的。”
- “Bybit 上 BTC 永续合约现在的资金费率是多少？”
- “展示 ETH/USDT 订单簿前 10 档的价差。”

## 配置

所有设置均为环境变量（见 [`.env.example`](.env.example)）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TICKFEED_EXCHANGES` | `binance,bybit,okx` | 启用的交易所（逗号分隔） |
| `TICKFEED_DEFAULT_EXCHANGE` | `binance` | 省略 `exchange` 时的默认值 |
| `TICKFEED_MAX_WATCHED_SYMBOLS` | `25` | 并发 WS 订阅上限（超出按 LRU 释放） |
| `TICKFEED_RING_BUFFER_SIZE` | `1000` | 每个标的的成交缓冲区大小 |
| `TICKFEED_OHLCV_CACHE_PATH` | `~/.tickfeed/ohlcv.duckdb` | DuckDB 缓存文件 |
| `TICKFEED_OHLCV_CACHE_TTL_S` | `60` | 最新 K 线的新鲜度窗口 |
| `TICKFEED_REST_RETRIES` | `3` | 瞬时 REST 错误（限频/网络）的重试次数 |
| `TICKFEED_SCREEN_CONCURRENCY` | `5` | 筛选/聚合时的并发标的数 |
| `TICKFEED_TRANSPORT` | `stdio` | `stdio` 或 `http` |
| `TICKFEED_LOG_LEVEL` | `INFO` | 日志级别 |

## 开发

```bash
uv venv && uv pip install -e ".[dev]"
pytest                # 约 100 个单元 + MCP 集成测试（不含实时）
pytest -m live        # 实时交易所测试（Binance/Bybit/OKX，本地运行）
ruff check . && mypy  # 代码检查 + 类型门禁
```

测试覆盖：指标数学与参考值的对照、服务缓存/auto-watch 逻辑、完整的 MCP 工具路径（`tests/test_mcp_integration.py` 通过 `mcp.call_tool` 调用）、价格结构识别，以及针对真实交易所运行整条链路的实时套件。项目结构与贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 路线图

- [x] Pine Script 风格指标映射（`ta.rsi`、`ta.crossover` 等）
- [x] 73 个指标 + K 线形态 + 市场结构（BOS/CHoCH）
- [x] 多交易所聚合（加权价格 / 价差）
- [x] watched 标的的 MCP 资源推送
- [ ] 锚定 / 会话 VWAP
- [ ] 更多交易所（Kraken、Bitget、Gate 等）
- [ ] Agent Skill（`SKILL.md`）封装

## 贡献

欢迎提交 Issue 和 PR —— 见 [CONTRIBUTING.md](CONTRIBUTING.md) 与[行为准则](CODE_OF_CONDUCT.md)。请保持依赖精简，并将 v1 范围维持为只读（公开数据，不执行下单，无 API 密钥）。

## 许可证

[MIT](LICENSE) © TickFeed contributors.

## 免责声明

本工具**仅用于教育与研究目的**。它并非金融、投资或交易建议。行情数据可能存在延迟、不完整或不准确，请勿据此做出真实交易决策。请遵守各交易所的服务条款与限频规则。见 [SECURITY.md](SECURITY.md)。
