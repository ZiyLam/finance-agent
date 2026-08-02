# Finance Agent

Finance Agent 是一个面向个人金融研究的自然语言应用。它把模型的语言理解能力与受控的只读数据工具结合起来，输出带数据时点、风险提示、研究范围和证据限制的结果；它不交易、不下单，也不承诺收益。

> 本文是项目的统一说明和学习入口：介绍项目目标、运行路径、各框架的职责与安全边界。Web、小程序、数据源和简历材料等文档只补充各自场景的操作或表述，不重复维护核心架构说明。

## 从哪里开始

初次了解项目时，建议按以下顺序阅读：

1. 本文的“核心运行路径”和“框架职责”；
2. [Web 工作台说明](web/README.md)，了解一次自然语言请求如何进入系统；
3. [数据源与确定性研究参考](docs/data-sources.md)，了解数据证据、回退和运行命令；
4. [微信小程序后端接入说明](docs/mini-program-backend.md)，仅在需要小程序/API 集成时阅读。

## 核心运行路径

```text
用户请求
  → 输入限制与证券实体解析
  → 专业版明确日期 / 多市场 / 多指数 / 研究指标：并行确定性指数研究
  → 简单且唯一的证券：确定性快路径 / 结构化快照
  → 开放或复杂的问题：LCEL 本地 RAG → LangChain / LangGraph Agent
  → 受控的只读工具调用（如市场数据、可选 ima 知识库检索）
  → 自然语言回答，或确定性研究报告 / JSON
```

不是每个请求都要经过 LLM。能由明确规则、安全完成的证券查询和研究报告，会优先使用确定性路径，降低幻觉、成本和延迟；证券名称存在歧义时，系统展示候选项而不猜测标的。

## 框架职责与边界

| 层级 | 主要职责 | 不负责什么 |
| --- | --- | --- |
| 应用层 | 输入限制、实体解析、Web 会话、确定性快路径和报告路由 | 不让模型决定数据权限或伪造缺失事实 |
| LCEL 本地 RAG | 取回应用维护的研究边界、场景和工具能力说明 | 不替代用户资料库，也不检索不受信任网页内容 |
| LangChain + LangGraph | 编排“模型选择工具 → 工具执行 → 结果回传 → 再决策”的循环 | 不是模型提供方、数据源或长期记忆系统 |
| 模型适配层 | 将 Codex CLI、千帆等接入统一消息与 Tool-calling 协议 | 不直接执行外部数据源或保存业务凭据 |
| 金融分析 Skill | 向模型提供研究口径、证据和风险提示等领域约束 | 不授予新权限，也不替代数据证据 |
| `ToolRegistry` | 唯一工具执行边界：显式副作用声明、只读准入、参数校验和错误脱敏 | 不允许变更型工具或绕过注册表的数据源调用 |
| `ConversationMemory` | 保存当前会话的有限消息窗口 | 不是持久化记忆；服务重启或会话过期后会清除 |
| 确定性研究模块 | 制定数据源回退计划、保留证据和生成结构化报告 | 不由 LLM 自由补全数据或直接给出投资指令 |

当前 Agent 最多进行 5 轮工具调用。会话历史保存用户、助手和工具消息；教学图中常见的 “Thinking” 是帮助理解的抽象，不应视为会被保存或向用户输出的原始思维链。

## 知识、记忆与数据的区别

- **会话记忆**：当前对话的短期上下文，默认保留 20 条消息窗口；Web 会话默认空闲 30 分钟失效，最多缓存 50 个会话。
- **本地 RAG**：应用内、可审阅的运行说明，用于告知 Agent 研究边界和工具能力；它不是外部知识库的替代品。
- **腾讯 ima 知识库（可选）**：作为显式的只读 `ima_knowledge_search` 工具接入私有资料。配置客户端凭据与知识库 ID，或以精确名称选择知识库；名称在首次检索时解析，启动时不会访问 ima。结果仅返回受限标题和摘要，重要结论仍须与公司披露、监管文件等一级来源交叉核验。
- **行情数据**：通过已注册的只读工具访问；来源、采集时间、失败记录和限制会留在确定性研究结果中。

模型、数据源和所有凭据只在服务端或本机安全存储中使用。令牌不应写入 Git、前端代码或文档。

## 快速开始

需要 Python 3.11 或更高版本。当前 Windows 开发环境共享 `G:\Program Files\Codex\.venv`：

```powershell
cd 'G:\Program Files\Codex\finance-agent'
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' -m pip install -e .

# 本地对话入口（默认使用已登录的 Codex CLI）
.\resources\finance-agent.ps1

# Web 研究工作台
finance-agent-api
# 浏览器访问 http://127.0.0.1:8000/web/
```

默认服务仅绑定 `127.0.0.1`。如需远程访问，必须设置高强度的 `AGENT_WEB_ACCESS_TOKEN`，且不要把它提交到 Git。Web 界面必须通过 FastAPI 托管访问，不能直接双击 `web/index.html`。

研究工作台默认使用精简版自然语言输入；切换到专业版后，可明确选择日期区间、A 股、港股、美股、日本和欧洲市场，以及多个指数和研究指标。指数目录包含上证指数、沪深 300、恒生指数、标普 500、纳斯达克综合指数、纳斯达克 100、道琼斯、罗素 2000、日经 225、富时 100、DAX 与 CAC 40 等常用基准；直接勾选指数会自动启用所属市场。专业版多指数请求走确定性并行链路，不调用 LLM；每个指数的行情类指标共用一次日线读取，只选择静态风格或风险时不访问行情数据源。

参数配置页 `/web/sources.html` 将行情数据源与 LLM 提供方分为两个模块，并将“令牌是否配置”和“实际连通状态”分开显示；千帆及未来模型统一归入 LLM 模块。连通测试仅在手动点击后执行最小只读请求；远端失败会以红色标记，并保留检查时间和耗时。批量测试最多并发 4 个来源，默认每项等待 4 秒，可通过 `AGENT_SOURCE_CHECK_MAX_PARALLEL` 和 `AGENT_SOURCE_CHECK_TIMEOUT_SECONDS` 调整。

### 模型与测试

- 默认提供方为 `codex`，复用本机已登录的 Codex CLI，适合个人自测；正式多用户部署应改用独立、可审计的模型 API。
- 也可设置 `AGENT_PROVIDER=qianfan` 使用已接入的千帆兼容接口；凭据通过 Windows DPAPI 安全存储或临时环境变量提供。
- 将 `AGENT_PROVIDER=echo` 后运行 CLI，可在不访问模型的情况下检查 Agent 框架。

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

`pyproject.toml` 将 LangChain 限制在 `>=1.3,<2.0`：保证项目所用的 1.x API 可用，同时避免未验证的 2.0 破坏性更新。

### 服务端诊断日志

通过 `finance-agent-api` 启动后，服务会输出 JSON Lines 诊断日志。默认位置为 `%LOCALAPPDATA%\FinanceAgent\logs\finance-agent.jsonl`，单个文件最大 5 MB，保留 3 个轮转副本；可用 `AGENT_LOG_DIR` 指定其他受控目录，并用 `AGENT_LOG_LEVEL` 设为 `DEBUG`、`INFO`、`WARNING` 或 `ERROR`。

日志覆盖 HTTP 请求、RAG、实体解析、模型调用、LangGraph 工具循环、工具执行和数据源回退。每条 API 请求都有 `X-Request-ID` 可与日志关联；日志不记录用户问题原文、Prompt、工具参数/返回值、异常原文或令牌。

```powershell
Get-Content "$env:LOCALAPPDATA\FinanceAgent\logs\finance-agent.jsonl" -Tail 100
```

## 数据源与确定性报告

项目可按场景选择和回退数据源，例如 AkTools、TickFlow、智兔数服、BaoStock、AllTick、必盈、Alpha Vantage、EODHD 和 yfinance。数据源能力是路由条件，不代表实时性、授权范围或准确性的额外承诺。每个来源还维护粗粒度的延迟分类和路由优先级：同一研究能力下优先调用低延迟、较高优先级的来源；实际耗时以服务端 `tool_execution_*` 日志的 `duration_ms` 为准，而不是该分类的承诺。

```powershell
# 查看已知来源与配置状态
finance-agent source list
finance-agent source status

# 浏览路由能力；以下命令只生成计划，不访问网络
finance-agent route catalog
finance-agent route scenarios
finance-agent route plan a_share_price_history a_share 600000 codex 2026-01-01 2026-01-31

# 执行只读分析或生成市场数据研究报告
.\resources\finance-agent.ps1 analyze a_share_price_history a_share 600000 2026-01-01 2026-01-31
.\resources\finance-agent.ps1 report a_share 600000 2026-01-01 2026-01-31
```

研究报告基于实际返回的价格序列和跨源核验生成，不能替代完整公司基本面研究。没有满足证据要求时，系统会降低信心或拒绝形成结论，而不是补造数据。各来源的权限、速率、代码格式和使用限制见 [数据源与确定性研究参考](docs/data-sources.md)。

## 目录导览

```text
src/ai_agent/
  application/    用例编排、实体解析、确定性快路径与 Web 会话
    index_catalog.py  经复核的指数静态目录；统一按 key 维护
    index_research.py 指数解析与研究主干，不承载大段静态资料
    web_workspace.py        Web 会话、快速路径与知识检索入口
    professional_research.py 专业版多指数并行研究编排
    web_report.py           确定性报告与可选模型解说
  langchain/      LangChain/LangGraph Agent、RAG、消息记忆与工具适配
  providers/      模型提供方适配
  market_data/    行情数据客户端
  knowledge_base/ ima 知识库客户端与只读检索
  data_sources.py 数据源/LLM 提供方目录、优先级与启用配置
  tooling/        工具核心、行情适配器与知识库适配器
  tools.py        保留旧导入路径的薄兼容门面
  api/
    app.py                 FastAPI 装配、中间件与健康检查
    web_routes.py          Web 工作台和数据源配置路由
    mini_program_routes.py 微信小程序路由
web/              FastAPI 托管的 Web 前端
  app.js           页面启动与请求编排
  api-client.js    同源 API 客户端
  research-form.js 精简/专业研究表单
  result-renderer.js 研究结果渲染与 Markdown 导出
miniapp/          微信小程序客户端
docs/             场景化补充说明
tests/            自动化测试
```

## 补充文档

| 文档 | 适用场景 |
| --- | --- |
| [Web 工作台](web/README.md) | 启动 Web、了解页面请求链路与本地访问控制 |
| [数据源与确定性研究](docs/data-sources.md) | 配置来源、理解路由、报告证据与各数据源限制 |
| [微信小程序后端](docs/mini-program-backend.md) | API 契约、微信登录与生产部署缺口 |
| [微信小程序客户端](miniapp/README.md) | 导入小程序工程、设置后端 HTTPS 地址 |
| [共享运行环境](resources/README.md) | 本机运行环境和数据源运行目录 |
| [项目亮点（简历版）](docs/interview-finance-agent.md) | 面试、简历和项目复盘表述 |
| [工程验证基线](docs/verification.md) | 测试分类、性能基线、风险覆盖与部署前缺口 |
| [跨项目代码质量准则](../knowledge-base/standards/code-quality-principles.md) | 六项基础原则、外部接口隔离、体量审查与合并检查清单 |

## 当前限制

- 数据源和模型权限、时效性受各提供方套餐与网络状态限制；结果应保留来源和时间口径。
- Web 会话与默认 API 存储、队列、缓存和限流仅适合单进程开发，不可直接作为公网多实例部署方案。
- 财报、公告、监管披露等完整基本面证据尚未构成基础行情快照的一部分；系统应明确提示未接入，而非给出未经证据支持的结论。
