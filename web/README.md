# Finance Agent Web 研究工作台

本文是 [项目主说明](../README.md) 的 Web 使用补充，聚焦工作台启动、请求链路和访问控制；项目总体架构与模块职责请先阅读主说明。

该目录是 Finance Agent 的正式 Web 前端，通过 API 调用服务端的 LangChain、模型和只读行情工具。开发时可由 FastAPI 在 `/web/` 托管；部署时也可放到独立静态站点。两种方式共用同一套页面和 `api-client.js`，不复制业务请求代码。

## 启动

先在项目根目录安装依赖，再启动本地服务：

```powershell
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' -m pip install -e .
finance-agent-api
```

随后打开 [http://127.0.0.1:8000/web/](http://127.0.0.1:8000/web/)。页面需要 HTTP 静态服务和可访问的 API，不能使用 `file://` 双击运行。

## 独立部署

前端部署前修改 `runtime-config.js` 中的公开 API 地址；该文件不得包含 API Key：

```js
globalThis.FINANCE_AGENT_CONFIG = Object.freeze({
  apiBaseUrl: "https://api.example.com",
});
```

后端使用以下配置。Origin 必须是前端页面的精确 `scheme://host[:port]`，不能带路径、尾部 `/` 或通配符：

```text
AGENT_SERVE_WEB=false
AGENT_WEB_ALLOWED_ORIGINS=https://web.example.com
AGENT_WEB_ACCESS_TOKEN=<高强度随机值>
```

本地可分别启动 `python -m http.server --directory web 8011` 和端口 8010 的 API 进行联调。后端的 `/openapi.json` 以及 `python scripts/export_openapi.py --output <文件>` 是前端客户端的唯一接口契约。当前原生 Web 和小程序仍使用各自的视图代码；未来迁移 Vue/uni-app 时应复用生成的 API 类型与客户端，而不是强行共用页面样式文件。

Web 的语义颜色来自 `../frontend/design-tokens.json` 生成的 `design-tokens.css`。修改跨端颜色时更新令牌源并运行 `python scripts/generate_design_tokens.py`，不要直接编辑生成文件；Web 响应式布局仍在 `styles.css` 独立维护。

## 运行链路

```text
浏览器 /web/
  ├─ 精简版 → POST /v1/web/chat { conversation_id, content }
  │    └─ 宽松意图识别 → 确定性快路径，或 LCEL 本地 RAG → LangChain Agent
  └─ 专业版 → POST /v1/web/professional-research
       └─ 明确日期、市场、指数和指标 → 多指数并行确定性研究
```

`/v1/web/status` 返回模型提供方、可用工具名称、运行状态和专业版可选目录，永不返回 API Key、令牌或其他凭据。

精简版保留不设固定格式的自然语言文本框。系统先做宽松意图识别，再选择确定性快路径或由 LCEL RAG 增强后交给 Agent；证券代码、市场或日期缺失时，可以结合问题分析或自然追问。

专业版用于明确范围：日期默认过去一周，可多选 A 股、港股、美股、日本和欧洲市场，并从服务端维护的 18 个指数目录中最多勾选 6 个指数。目录包含上证指数、深证成指、恒生指数、标普 500、纳斯达克综合指数（纳指）、纳斯达克 100、道琼斯、罗素 2000、日经 225、富时 100、DAX 和 CAC 40 等常用基准；直接勾选指数会自动启用所属市场。研究指标包括最新行情、区间表现、市场情绪、估值/风格、成分行业和风险。多个指数并行执行，每个指数的行情类指标共用一次日线读取；只选静态风格或风险时不会调用行情数据源，也不会调用 LLM。单个指数最多读取 120 个交易日，结果会标注实际覆盖日期和未接入的数据边界。

两种模式的检索语料都不会包含令牌、原始行情响应或不受信任的网络内容。

`POST /v1/web/reports { content }` 仍保留给需要确定性证据报告的程序化调用；该路径会严格解析研究范围，并在范围不足时返回结构化澄清项。

## 访问控制

默认 API 绑定 `127.0.0.1`，因此无需额外令牌。本地以外的访问会被拒绝；如确有远程访问需求，设置服务端环境变量 `AGENT_WEB_ACCESS_TOKEN` 为高强度随机值，并在网页连接面板输入相同值。该值仅保存在当前浏览器会话，不写入 `localStorage`、导出文件或 Git。CORS 只决定浏览器是否可发起请求，不替代访问令牌或用户鉴权。

## 结果复制

研究结果可复制为 Markdown；网页不会再把研究输入或结果保存到浏览器 `localStorage`。

## 参数配置

从工作台顶栏的“参数配置”，或直接打开
`http://127.0.0.1:8000/web/sources.html`，可以维护数据源目录中的令牌。页面使用
共享 API 客户端，而不是读取 `.env` 或把令牌留在浏览器：

```text
GET    /v1/web/sources
PUT    /v1/web/sources/{source}/token
DELETE /v1/web/sources/{source}/token
```

页面只展示令牌是否已配置和配置来源，不回显令牌正文。输入的新令牌只在提交请求
中交给后端，并由当前 Windows 用户的 DPAPI 加密写入本地应用数据目录；删除操作
也只删除本地加密副本，不会修改环境变量。

凭据维护接口始终只接受 API 服务端看到的 loopback 客户端。独立部署的远程网页
可以执行研究，但不能通过该页面读取、写入或删除数据源令牌。

令牌以外的服务参数仍遵循各适配器的运行时配置。例如 AkTools 的服务地址目前
由 `AKTOOLS_BASE_URL` 环境变量（或默认本机地址）决定，设置页会展示这一来源，
但不会伪装成已由网页保存。
