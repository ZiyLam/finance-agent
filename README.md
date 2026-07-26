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

可选环境变量：

```text
AGENT_PROVIDER=echo
AGENT_MODEL=local-echo
AGENT_SYSTEM_PROMPT=You are a helpful AI agent.
AGENT_MEMORY_WINDOW=20
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
