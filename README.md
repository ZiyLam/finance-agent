# AI Agent Framework

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
cd 'G:\Program Files\Codex\ai-agent'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
ai-agent
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
ai-agent source set-token alltick
ai-agent source set-token biying
ai-agent source status
ai-agent source delete-token biying
```

设置命令会用 Windows DPAPI 对令牌加密，并保存到当前 Windows 用户的本地应用数据目录；令牌绝不会写入项目、`.env.example` 或 Git。环境变量仍适用于临时会话和部署，并优先于安全存储：

```powershell
$env:ALLTICK_API_TOKEN = '在此设置你自己的令牌'
ai-agent
```

设置变量后，CLI 会额外注册 `alltick_market_data` 工具。它支持 `latest_quotes` 与 `historical_candles` 两种只读动作，供真实模型适配器调用；默认 Echo 模型不会发起网络请求。

## 必盈 API 数据

内置 `ai_agent.market_data.BiyingClient`，封装了必盈 API 的沪深 A 股股票代码检索和“实时交易（公开数据）”接口。它通过 `biying_market_data` 提供 `find_stocks`（最多 20 条匹配）与 `realtime_quote` 两种只读动作，返回价格、涨跌幅、成交量、动态市盈率、市净率及接口返回的更新时间。

必盈证书同样通过 `ai-agent source set-token biying` 加密保存，或用临时变量 `BIYING_API_LICENCE` 覆盖。默认本地限流为 0.2 秒间隔、每分钟 300 次、每天 100 次；每日上限采用文档中心免费版的保守值，确认你的证书套餐后再调整。

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
ai-agent source status aktools
ai-agent source check aktools
ai-agent
```

Agent 启动不会探测网络，而是始终注册只读的 `aktools_market_data` 工具；所以 AkTools 尚未运行并不会影响 AllTick 或必盈。`ai-agent source check aktools` 只读取并显示运行中服务的当前 AkTools 版本；是否升级由使用者决定。首次调用失败时，工具会提示启动本地服务。当前封装了文档的 `stock_zh_a_hist`：传入 6 位沪深 A 股代码、`YYYYMMDD` 日期区间、`daily`/`weekly`/`monthly` 周期，以及 `qfq`（前复权）或 `hfq`（后复权）。为了不挤占模型上下文，工具最多返回最近 120 根 K 线；完整区间行数会一并标明。

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
