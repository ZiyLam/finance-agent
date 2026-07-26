# Finance Agent

一个不绑定模型供应商的 AI Agent 起始框架。当前版本提供可测试的核心闭环：消息记忆、模型客户端抽象、工具注册与执行、Agent 循环，以及可替换的命令行入口。

## 目录

```text
src/ai_agent/
  agent.py          # Agent 编排循环与工具调用处理
  config.py         # 环境变量配置
  memory.py         # 对话上下文的窗口化记忆
  messages.py       # 领域消息与模型响应类型
  tools.py          # 工具协议、注册表与内置示例工具
  providers/        # 模型供应商适配层
  skills.py         # 项目本地 Skill 的加载与系统提示词组装
  cli.py            # 本地交互入口
skills/
  financial-investment-analyst/  # 金融分析、风险提醒与研究性观点 Skill
tests/              # 标准库 unittest 测试
```

## 快速开始

需要 Python 3.11 或更高版本：

```powershell
cd 'G:\Program Files\Codex\finance-agent'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
finance-agent
```

默认使用 `EchoModelClient`，它仅用于验证框架线路，不会调用外部模型或网络服务。

启动时，CLI 会自动加载项目根目录 `skills/*/SKILL.md` 中经审阅的 Skill，并把它们加入系统提示词。当前已内置金融分析 Skill；它要求模型标注数据时点和证据、输出风险情景，且不执行交易或提供保证收益的个性化荐股。

## 接入真实模型

1. 在 `src/ai_agent/providers/` 新建供应商适配器，并实现 `ModelClient.complete()`。
2. 将适配器注入 `Agent`，或在后续的应用组合层中按 `AGENT_PROVIDER` 选择适配器。
3. 通过实现 `Tool` 协议添加业务工具；工具应在自己的边界内完成鉴权、输入校验和审计。

## AllTick 行情数据

内置 `ai_agent.market_data.AllTickClient`，按 AllTick HTTP 文档封装了：

- 批量最新成交价：`/trade-tick`；
- 单标的历史 K 线：`/kline`；
- 股票（A/港/美股）与外汇、加密货币、商品等的不同 API 路径；
- URL 编码的 `query`、唯一 `trace`、`ret/msg/trace` 错误处理；
- 免费套餐的本地保护限流：10 秒间隔、每分钟 10 次、每天 1000 次，最新价每次最多 5 个代码。

令牌维护入口（推荐，输入不会回显）：

```powershell
finance-agent source set-token alltick
finance-agent source set-token alphavantage
finance-agent source set-token eodhd
finance-agent source set-token biying
finance-agent source status
finance-agent source delete-token biying
```

每个已接入的数据源均保留 `set-token`、`status` 与 `delete-token` 维护入口，包括当前不需要鉴权的 AkTools、BaoStock 和 yfinance。后者的维护项仅用于将来服务变更或操作者自行备忘，当前适配器不会读取或发送其中的值；状态命令会明确标示这一点。

设置命令会用 Windows DPAPI 对令牌加密，并保存到当前 Windows 用户的本地应用数据目录；令牌绝不会写入项目、`.env.example` 或 Git。环境变量仍适用于临时会话和部署，并优先于安全存储：

```powershell
$env:ALLTICK_API_TOKEN = '在此设置你自己的令牌'
finance-agent
```

设置变量后，CLI 会额外注册 `alltick_market_data` 工具。它支持 `latest_quotes` 与 `historical_candles` 两种只读动作，供真实模型适配器调用；默认 Echo 模型不会发起网络请求。

## 后续数据源扩展入口

后续数据源的凭证维护统一由 [data_sources.py](src/ai_agent/data_sources.py) 管理。新增一个 `DataSourceDefinition` 后，`finance-agent source list`、`source status`、`source set-token` 与 `source delete-token` 会自动识别该名称；该条目需定义显示名称、环境变量名，以及当前适配器是否实际使用凭证。随后再独立实现数据客户端、输入校验、限流、工具注册、测试与金融 Skill 的数据口径说明。这样，单纯保存未来凭证不会意外触发网络请求或使 Agent 使用未实现的数据源。

```powershell
finance-agent source list
```

## 必盈 API 数据

内置 `ai_agent.market_data.BiyingClient`，封装了必盈 API 的沪深 A 股股票代码检索和“实时交易（公开数据）”接口。它通过 `biying_market_data` 提供 `find_stocks`（最多 20 条匹配）与 `realtime_quote` 两种只读动作，返回价格、涨跌幅、成交量、动态市盈率、市净率及接口返回的更新时间。

必盈证书同样通过 `finance-agent source set-token biying` 加密保存，或用临时变量 `BIYING_API_LICENCE` 覆盖。默认本地限流为 0.2 秒间隔、每分钟 300 次、每天 100 次；每日上限采用文档中心免费版的保守值，确认你的证书套餐后再调整。

## AkTools / AKShare 数据

AkTools 不是托管的免鉴权行情 API；它是把 AKShare 函数封装成 HTTP 服务的开源工具。因此本项目无需、也不会保存 AkTools Token，但使用前需要由你在本机或自己的容器环境启动服务。按照 [AkTools 官方文档](https://aktools.akfamily.xyz/aktools/) 可任选一种方式：

```powershell
python -m pip install aktools
python -m aktools
```

或使用文档示例镜像：

```powershell
docker run -p 8080:8080 registry.cn-shanghai.aliyuncs.com/akfamily/aktools:1.8.95
```

默认服务地址是 `http://127.0.0.1:8080`。如果服务部署在其他受你控制的地址，在启动 Agent 前设置：

```powershell
$env:AKTOOLS_BASE_URL = 'http://127.0.0.1:8080'
finance-agent source status aktools
finance-agent source check aktools
finance-agent
```

Agent 启动不会探测网络，而是始终注册只读的 `aktools_market_data` 工具；所以 AkTools 尚未运行并不会影响 AllTick 或必盈。`finance-agent source check aktools` 只读取并显示运行中服务的当前 AkTools 版本；是否升级由使用者决定。首次调用失败时，工具会提示启动本地服务。当前封装了文档的 `stock_zh_a_hist`：传入 6 位沪深 A 股代码、`YYYYMMDD` 日期区间、`daily`/`weekly`/`monthly` 周期，以及 `qfq`（前复权）或 `hfq`（后复权）。为了不挤占模型上下文，工具最多返回最近 120 根 K 线；完整区间行数会一并标明。

## BaoStock 数据

项目依赖官方 `baostock` Python 包，并以匿名会话按其文档执行 `login()`、`query_history_k_data_plus()` 和 `logout()`；不需要 API Token，也不会保存账号密码。`baostock_market_data` 当前提供 A 股日/周/月历史 K 线：代码使用 BaoStock 格式（如 `sh.600000`、`sz.000001`），日期为 `YYYY-MM-DD`，频率使用 `d`、`w` 或 `m`，复权参数使用官方 `adjustflag`：`1` 后复权、`2` 前复权、`3` 不复权。

BaoStock 公布的限制为同一 IP 每日不超过 50,000 次访问；本项目默认采用每进程 5,000 次/日和 0.1 秒最小间隔的本地保护值，以便为同 IP 的其他研究或手工查询预留余量。可用下列命令确认其无 Token 配置状态：

```powershell
finance-agent source status baostock
```

## Alpha Vantage 数据

项目内置 `alphavantage_market_data`，使用 Alpha Vantage 官方 HTTP API 提供三种只读操作：`daily_candles`（全球股票原始日线 OHLCV）、`global_quote`（单标的最新报价）与 `symbol_search`（代码/公司搜索）。日线固定使用官方免费密钥可用的 `TIME_SERIES_DAILY` + `outputsize=compact`，因此单次最多返回最近 100 根，不包含复权价格、分红或拆股事件；如需这些数据，应改用具备相应权限的来源并标注口径。

密钥通过以下入口加密保存，或以临时环境变量 `ALPHAVANTAGE_API_KEY` 覆盖；它不会被写进项目、`.env.example` 或 Git：

```powershell
finance-agent source set-token alphavantage
finance-agent source status alphavantage
```

根据 Alpha Vantage 官方文档，免费服务上限为每天 25 次请求。本项目额外采用每进程每天 25 次、最小 15 秒间隔的本地保护；不要绕过该限制。免费 `GLOBAL_QUOTE` 默认是每日收盘后更新的数据，不能表述为实时或 15 分钟延迟美国行情；后两者需要提供商授权。所有 Alpha Vantage 数据只能用于研究核验，不构成交易指令或收益承诺。

## EOD Historical Data（EODHD）数据

`eodhd_market_data` 通过 EODHD 官方 REST API 提供全球标的的日/周/月历史 OHLCV（`historical_candles`）和活跃标的检索（`search`）。历史查询须使用 EODHD 的交易所后缀代码，例如 `AAPL.US`、`0700.HK`、`EURUSD.FOREX` 或 `BTC-USD.CC`；输入日期为 `YYYY-MM-DD`，周期为 `d`、`w` 或 `m`。每项查询最多向模型返回最近 120 根，但响应始终标示完整返回行数。

EODHD 免费计划文档列出每天 20 次 API 调用，且历史数据仅限最近一年。本项目按每进程每天 20 次、最小 3 秒间隔设置本地保护；套餐权限或时间范围不足时，工具会返回错误而不会猜测或补齐数据。历史字段可能包含 `adjusted_close`，但必须按响应实际字段理解，不能把数据描述为交易所实时成交；EODHD 也明确说明其数据并非当然实时或准确，不能作为自动交易或个性化投资结论的唯一依据。

使用以下命令加密保存或维护凭证：

```powershell
finance-agent source set-token eodhd
finance-agent source status eodhd
```

## yfinance / Yahoo Finance 数据

项目依赖官方 `yfinance` Python 包，并通过 `yfinance_market_data` 提供单标的日/周/月历史 OHLCV 数据。它不需要 Token；Yahoo 代码示例包括 `AAPL`、`0700.HK`、`600000.SS`、`^GSPC` 和 `BTC-USD`。输入 `start_date` 与 `end_date` 采用 `YYYY-MM-DD`，其中 yfinance 遵循 Yahoo 的约定：`end_date` 为排他上界；要包含某日的日线时，应传入下一日作为 `end_date`。

yfinance 官方文档说明它是对 Yahoo 公开 API 的开源封装，Yahoo 数据仅限个人研究与教育用途。该数据源只能用于核验历史价格、成交量和调整口径，不能视为实时行情、交易所原始数据或可再分发的数据。为避免触发未公开的 Yahoo 限制，项目默认设置每进程 1,000 次/日与 0.5 秒最小间隔的本地保护值。

如需将 yfinance 的时区和 Cookie 缓存保存在指定位置，可设置 `YFINANCE_CACHE_DIR`。当前 Windows 安装建议设为 `G:\Program Files\Python314\yfinance-cache`，避免默认写入用户配置目录。

```powershell
finance-agent source status yfinance
```

可选环境变量：

```text
AGENT_PROVIDER=echo
AGENT_MODEL=local-echo
AGENT_SYSTEM_PROMPT=You are a helpful AI agent.
AGENT_MEMORY_WINDOW=20
AKTOOLS_BASE_URL=http://127.0.0.1:8080
```

## 验证

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

## 下一步建议

- 选择模型供应商，并实现其流式响应和工具调用适配器。
- 增加持久化会话/长期记忆与用户身份边界。
- 为每个具有副作用的工具补充权限策略、结构化日志和集成测试。
