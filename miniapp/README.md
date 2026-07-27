# Finance Agent 微信小程序

这是原生微信小程序客户端，负责微信登录、研究问题提交、澄清展示、任务轮询和报告阅读。它不包含模型、行情或供应商凭据。

## 本地导入

1. 用微信开发者工具导入此 `miniapp/` 目录。
2. 在 `project.config.json` 填写你的测试 AppID；`touristappid` 仅用于尚未配置 AppID 的开发占位。
3. 在 [config.ts](config.ts) 填写后端 HTTPS 地址。
4. 在微信公众平台把该地址配置为合法请求域名，然后使用真机测试微信登录。

## 与后端的契约

- `wx.login()` 获得 code 后只发送到 `POST /v1/auth/wechat/login`。
- 后端返回短期 Bearer Token，小程序只把它保存到本地存储并在请求头发送。
- 研究请求返回 `needs_clarification` 或 `queued`；小程序对任务状态轮询，不直接请求模型或行情 API。

在发布前，请替换占位域名、完成微信主体/域名/HTTPS 配置，并核验隐私政策、用户协议和数据源再分发许可。

个人使用首版应在服务端设置 `AGENT_PERSONAL_MODE=true`，并用一次开发登录得到的不透明 `user_id` 配置 `AGENT_ALLOWED_USER_IDS`。这样即使其他微信用户拿到小程序，也不能取得会话 Token。
