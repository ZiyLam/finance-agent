# 凭证生命周期与本地维护规范

本项目把“人维护的凭证来源”“部署环境中的运行时副本”和“应用读取接口”分开。参数页只显示是否配置和连通状态，不返回实际凭证；Linux 容器也不会尝试读取或写入 Windows DPAPI 文件。

## 本地明文文件

固定路径：

```text
G:\Program Files\finance-agent-api-token-backup.txt
```

该文件是个人本地 Staging 的人工维护入口，不是 Git 文件，也不由普通 CI/CD 自动读取。它使用 UTF-8（无 BOM）和严格的 `KEY=VALUE` 格式：

```dotenv
# 注释必须独占一行
ALLTICK_API_TOKEN=replace-with-a-real-value
QIANFAN_API_KEY=
IMA_OPENAPI_CLIENTID=replace-with-a-real-value
```

格式规则：

1. 每行只写一个 `KEY=VALUE`，只按第一个等号分隔。
2. 键名只使用大写 ASCII 字母、数字和下划线。
3. 等号两侧不能有空格，值不能有首尾空白。
4. 值不加单引号或双引号；值内部允许出现 `=` 或 `#`。
5. 空值表示未配置，同步时不会写入 Kubernetes Secret。
6. 允许空行和以 `#` 开头的整行注释，不支持行尾注释；第一个 `=` 后的所有文本（包括 `#`）都会作为值保存。
7. 重复键、未知键、`export KEY=...` 和格式错误会让同步立即失败。

仓库中的 `config/external-secrets.env.example` 是唯一键名契约和标准顺序。规范化脚本会保留现有值、补齐空白可选键、严格复读验证，再原子替换原文件。

## 支持的凭证键

| 分类 | 键名 | 作用 | 当前状态 |
|---|---|---|---|
| 行情 | `ALLTICK_API_TOKEN` | AllTick 行情 | 已注入；**待完成（需用户）：供应商拒绝时确认权限或替换** |
| 行情 | `ALPHAVANTAGE_API_KEY` | Alpha Vantage | 已由本地文件维护 |
| 行情 | `BIYING_API_LICENCE` | 必盈 API | 已注入；**待完成（需用户）：供应商拒绝时确认权限或替换** |
| 行情 | `EODHD_API_TOKEN` | EODHD | 已由本地文件维护 |
| 行情 | `TICKFLOW_API_KEY` | TickFlow | 可选 |
| 行情 | `ZHITU_API_KEY` | 智兔数服 | 可选 |
| 本地服务 | `AKTOOLS_API_TOKEN` | AkTools未来可选认证 | 可选，当前适配器不使用 |
| LLM | `QIANFAN_API_KEY` | 千帆兼容 Chat Completions | **待完成（需用户）：选择真实 LLM 时填写** |
| 知识库 | `IMA_OPENAPI_CLIENTID` | ima OpenAPI客户端标识 | 已由本地文件维护 |
| 知识库 | `IMA_OPENAPI_APIKEY` | ima OpenAPI密钥 | 已由本地文件维护 |
| 知识库 | `IMA_KNOWLEDGE_BASE_ID` | 指定 ima 目标知识库 | 可选；也可用非敏感名称配置 |
| 小程序 | `WECHAT_APP_SECRET` | 微信服务端 AppSecret | **待完成（需用户）：恢复小程序发布时填写** |

`AGENT_WEB_ACCESS_TOKEN` 和 `AGENT_SESSION_SECRET` 由部署脚本独立生成，不应放入人工维护文件。非敏感的供应商选择、模型名称、服务地址和启停状态进入 ConfigMap，而不是 Secret。

## 本地同步流程

日常快速入口是仓库根目录的 `sync-local-secrets.cmd`。其内部按以下顺序执行：

1. **规范化**：验证键名、格式、重复项和 UTF-8，保留实际值。
2. **权限保护**：移除继承读取权限，只保留当前用户、SYSTEM和Administrators。
3. **受控同步**：WSL脚本只选择契约允许且非空的键。
4. **Secret更新**：将外部凭证与本地生成的 Web/Session Secret合并后直接流式应用，不落盘生成 YAML。
5. **滚动加载**：重启 Deployment，因为环境变量只在进程启动时读取。
6. **客户端验收**：从 Windows调用状态和Sources接口，确认数据源与LLM目录均可读取。

脚本输出可以包含键名和数量，但不能包含值、Base64 Secret YAML或环境变量转储。

## 替换与回滚

替换第三方凭证时：

1. 先在供应商端创建新凭证，暂不撤销旧凭证。
2. 只修改固定明文文件中对应一行。
3. 运行同步并完成最小只读连通测试。
4. 验收通过后再撤销旧凭证。
5. 若失败，重新填入仍有效的旧凭证并再次同步。

本地 Kind Secret只是运行时副本，不是备份来源；`kubectl rollout undo` 也不会恢复旧 Secret值。

## 服务器迁移边界

服务器环境不得读取上述 Windows文件。迁移时保留相同键名契约，但将权威来源替换为 Vault或云 Secret Manager，并通过 External Secrets、CSI或受控部署流水线注入。

- **待完成（需用户）**：购置服务器后选择 Secret Manager、域名和生产审批策略。
- **待完成（需用户）**：生产启用真实 LLM前选择供应商、配额和付费边界。
- **待完成（需用户）**：任何实际密钥的创建、撤销和供应商侧权限变更。

知识库、日志、Git提交和CI产物只能记录键名、用途、状态和路径，不能记录实际值。
