# 数据源与确定性研究参考

本文是 [项目主说明](../README.md) 的运行补充，面向需要配置数据源、执行确定性研究或扩展数据来源的开发者。项目目标、框架职责和安全边界以主说明为准。

## 共同规则

- 所有行情工具均为只读研究工具，不执行交易、不下单，也不构成收益承诺。
- Token 可通过 `finance-agent source set-token <source>` 用 Windows DPAPI 加密保存；临时环境变量优先，真实凭据绝不应写入项目或 Git。
- 数据源能力标签只用于路由，不代表实时性、可再分发性或准确性承诺。
- 不能保证代码映射、日期范围或证据要求时，工具会记录失败并依照计划回退，不猜测或填充数据。
- Web 参数配置页的连通测试只在用户点击后发出最小只读请求；结果仅返回状态、检查时间和耗时，不返回 URL、响应体、异常原文或凭据。远端失败为红色，本地服务或依赖不可用会单独分类。
- 行情来源归入 `data_source` 配置分组；千帆、百炼等模型提供方归入 `llm` 分组并在独立 LLM 模块展示。新增模型时应显式声明该分组，避免进入行情数据源统计和批量测试。
- 百炼默认从 `BAILIAN_WORKSPACE_ID` 推导业务空间专属端点；`AGENT_BAILIAN_BASE_URL` 仅作为非敏感 HTTPS 端点覆盖项，适用于供应商迁移期间的兼容回退。端点切换不应修改或复制 API Key。

```powershell
finance-agent source list
finance-agent source status
finance-agent source set-token eodhd
finance-agent source delete-token eodhd
```

## 路由、执行与报告

`SecurityAnalysisRequest` 是单标的研究的标准输入：`symbol`、`market`、`scenario`；历史场景还需要 `start_date` 和 `end_date`。规划会生成 `security-analysis-plan/v1`，指定主数据源、回退顺序和证据字段；该步骤不读取凭据、不访问网络。

```powershell
finance-agent route catalog
finance-agent route scenarios
finance-agent route plan a_share_price_history a_share 600000 codex 2026-01-01 2026-01-31

.\resources\finance-agent.ps1 analyze a_share_price_history a_share 600000 2026-01-01 2026-01-31
.\resources\finance-agent.ps1 report a_share 600000 2026-01-01 2026-01-31
```

`analyze` 返回 `security-analysis-result/v1`，保留来源、采集时间、时效标签、失败记录和风险标记。`report` 在满足跨源历史证据要求后才生成 `security-research-report/v1`；缺少价格序列或双源核验时会降低信心或拒绝价格结论。

## 已接入来源

| 来源 | 主要用途 | 配置或使用提示 |
| --- | --- | --- |
| AllTick | 多市场最新价与历史 K 线 | 需要 Token；调用受本地限流保护 |
| TickFlow | A 股、港美股的实时快照与日期限定日线 | 需要 API Key；统一代码为 `代码.交易所`，如 `600000.SH`、`0005.HK`、`AAPL.US` |
| 智兔数服 | 沪深 A 股与沪深指数的实时快照、日期限定日线 | 需要 API Key；使用 `代码.交易所`，如 `600000.SH`、`000905.SH`；历史请求本地限制为最多 366 天，以避免官网未提供分页/行数上限时产生大响应 |
| 必盈 | A 股代码检索与实时交易公开数据 | 需要许可证；结果带接口更新时间 |
| AkTools / AKShare | 本机或自管 HTTP 服务中的 A 股历史数据 | 不需要 Token，但须自行启动服务；默认地址为 `http://127.0.0.1:8080` |
| BaoStock | A 股日、周、月历史 K 线 | 不需要 Token；使用 BaoStock 格式代码，如 `sh.600000` |
| Alpha Vantage | 全球日线、报价与证券搜索 | 需要 API Key；免费额度与返回范围受提供方限制 |
| EODHD | 全球历史 OHLCV 与活跃标的搜索 | 需要 Token；使用交易所后缀代码，如 `AAPL.US`、`0700.HK` |
| yfinance | 单标的日、周、月历史 OHLCV | 不需要 Token；仅用于个人研究和教育，不能描述为交易所实时数据 |

### 启动 AkTools

AkTools 是 AKShare 的 HTTP 包装服务，不是托管行情 API。可在自己控制的环境启动：

```powershell
python -m pip install aktools
python -m aktools

# 或使用官方示例镜像
docker run -p 8080:8080 registry.cn-shanghai.aliyuncs.com/akfamily/aktools:1.8.95
```

如部署在其他受控地址，设置 `AKTOOLS_BASE_URL`，然后用以下命令检查可访问性：

```powershell
$env:AKTOOLS_BASE_URL = 'http://127.0.0.1:8080'
finance-agent source check aktools
```

## 扩展新的数据源

1. 在 `src/ai_agent/data_sources.py` 增加 `DataSourceDefinition`，声明显示名称、环境变量、凭据实际使用状态、路由优先级和延迟分类。
2. 实现数据客户端、输入校验、限流和工具注册，并保持 `ToolRegistry` 作为唯一执行边界。
3. 补充路由能力、数据口径说明与自动化测试。

仅保存一个未来数据源的凭据不应触发网络请求，也不应使 Agent 自动使用尚未实现的工具。
