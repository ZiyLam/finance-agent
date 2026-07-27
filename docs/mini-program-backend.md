# 微信小程序后端接入说明

## 当前交付边界

`src/ai_agent/api/` 提供一个 FastAPI 开发版服务：

- 微信 code 换取内部用户标识并签发短期会话 Token；
- 对话按用户和会话隔离；
- 自然语言先经过确定性解析，信息不完整时返回结构化澄清项；
- 完整请求进入任务队列，Worker 复用已有的确定性规划、执行与报告模块；
- API 不把供应商 Token、原始 WeChat openid 或本机凭据返回给客户端。

首期个人使用时，设置 `AGENT_PERSONAL_MODE=true` 和 `AGENT_ALLOWED_USER_IDS=wx_...`，只允许该内部用户 ID 登录。首次在开发环境通过微信登录后，登录响应会给出不含 openid 的不透明 `user_id`；把它写入服务端环境变量后，再打开个人模式。生产响应不会返回该字段。

## 模型叙述层

研究任务始终先生成确定性的证据与报告。个人模式默认 `AGENT_API_NARRATOR_PROVIDER=codex`：它使用本机已登录 Codex CLI 当前选定的模型；只要 `AGENT_MODEL` 为空，就不会覆盖该本地默认选择。该方式适合个人受控使用，不应视为多用户生产模型网关。

如需显式改用已经接入的千帆，将 `AGENT_API_NARRATOR_PROVIDER=qianfan` 并在服务端配置千帆 Token。两种模型都只能接收报告中的范围、观察、风险、限制和下一步动作，不能调用工具或读取原始外部数据。模型不可用、未配置或限流时，任务仍返回确定性报告，并标记 `narration_status`，不会编造替代结论。

启动本地服务：

```powershell
$env:AGENT_SESSION_SECRET = '至少 32 个字符的随机服务端密钥'
$env:WECHAT_APP_ID = '你的微信小程序 AppID'
$env:WECHAT_APP_SECRET = '只存放在服务端的 AppSecret'
python -m ai_agent.api.server
```

开发服务默认仅监听 `127.0.0.1:8000`。真实小程序无法访问本机回环地址；联调时应使用受控 HTTPS 隧道或测试环境域名，并在微信公众平台登记合法请求域名。

## 生产接入缺口（需要部署方提供）

当前 `InMemoryApplicationStore`、`InMemoryTaskQueue`、`InMemoryRateLimiter`、`InMemoryTtlCache` 仅用于单进程开发和测试。生产发布前必须替换为：

| 开发实现 | 生产替换 | 责任方需要提供 |
| --- | --- | --- |
| 进程内会话/任务存储 | PostgreSQL | 数据库实例、备份策略、连接串和迁移权限 |
| 进程内队列 | Redis + 独立 Worker 队列 | Redis、Worker 容器与死信/重试策略 |
| 进程内限流/缓存 | Redis 原子限流和 TTL 缓存 | 每数据源配额、每用户预算和缓存时效 |
| 本机 DPAPI TokenStore | Secret Manager/Vault | 服务身份、密钥轮换与审计策略 |
| Codex CLI 自测适配器 | 正式模型 API | 模型供应商、生产 Key、并发和成本预算 |

在没有这些配置前，不应将 API 暴露到公网，也不应启动多个 API/Worker 实例。

## 研究任务接口

```text
POST /v1/auth/wechat/login
POST /v1/conversations
POST /v1/conversations/{conversation_id}/messages
GET  /v1/tasks/{task_id}
GET  /v1/reports/{report_id}
```

`POST /messages` 返回的 `status` 为 `needs_clarification`、`queued`、`completed` 或 `failed`。当状态为 `needs_clarification` 时，客户端必须让用户确认字段，而不是擅自猜测代码或日期。
