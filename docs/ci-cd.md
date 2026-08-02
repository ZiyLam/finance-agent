# CI/CD 运行说明

当前仓库已准备好 GitHub Actions 的持续集成和容器制品发布流程。它们只使用
测试数据和 `AGENT_PROVIDER=echo`，不会读取行情、模型、IMA 或微信凭据。

## CI

每个 Pull Request、推送到 `main` 以及手动运行都会执行：

1. Python 3.11 和 3.13 矩阵测试；
2. `uv.lock` 锁定依赖同步；
3. Ruff 检查；
4. 完整 Python `unittest` 测试；
5. OpenAPI 和设计令牌契约检查；
6. Web 客户端 Node 测试；
7. 带哈希的生产依赖漏洞审计；
8. Python wheel/sdist 构建和 Docker 镜像构建。

本地等价命令：

```powershell
$env:PYTHONPATH = 'src'
uv sync --locked --group dev
uv run ruff check src tests scripts
uv run python -m unittest discover -s tests -v
uv run python scripts/generate_design_tokens.py --check
node --test tests/test_web_api_client.js
uv export --locked --no-dev --no-emit-project --format requirements-txt `
  --output-file .venv\audit-requirements.txt
uv run pip-audit --require-hashes --disable-pip `
  --requirement .venv\audit-requirements.txt
uv build
```

## 容器制品发布

推送形如 `v0.1.0` 的 Git tag，或手动运行 `Publish container`，会先重复发布前检查，
再将镜像推送到 GitHub Container Registry。镜像默认：

- 监听 `0.0.0.0:8000`；
- 使用 `AGENT_PROVIDER=echo`，避免意外调用外部模型；
- 以非 root 用户运行；
- 通过 `/health` 提供容器健康检查。

正式部署前必须在部署平台覆盖这些默认值，并配置服务端凭据。当前 API 的存储、
队列、缓存和限流仍是单进程内存实现，镜像只能用于个人或单实例受限 Staging，不能
直接作为公网多实例生产服务。

## 尚未自动化的 Staging/Production 部署

部署目标（例如腾讯云、AWS、Azure、Render 或自有服务器）、域名、HTTPS 证书、持久化
数据库/Redis 和 Secret Manager 尚未选定，因此仓库暂不自动执行云端部署。确定目标后，
再为 `staging` 和 `production` GitHub Environment 配置 OIDC、密钥、批准规则、冒烟测试
和回滚策略。

## WSL2 + kind 本地 Staging

Windows 个人机器可以直接使用 WSL2 内的 Docker、kubectl 和 kind。日常启动使用：

```powershell
.\scripts\start_local_staging.ps1

# 不再使用时缩容应用并停止 keepalive
.\scripts\stop_local_staging.ps1
```

脚本会创建独立的 `finance-agent` kind 集群、构建并导入本地镜像，然后部署到
`finance-agent-staging` 命名空间。Windows 通过
`http://localhost:18080/web/` 访问；页面需要的随机访问令牌保存在被 Git 忽略的
`.local/kind-web-access-token`。重新运行脚本会复用集群和本地令牌并发布新镜像。

启动脚本会创建隐藏的 `wsl.exe sleep infinity` keepalive。否则，当最后一个 Windows WSL
客户端退出时，WSL 可能回收虚拟机并停止 Docker/kind；PID 会写入被 Git 忽略的
`.local/wsl-keepalive.pid`，停止脚本会清理它。

仓库也包含 `Deploy local staging` 工作流。它只在 `main` 的 CI 成功后运行，且只派发到
带 `finance-agent-local` 标签的 Linux 自托管 Runner，不会在 Pull Request 上执行本机代码。
在 GitHub 仓库设置中注册 WSL 自托管 Runner 并创建 `local-staging` Environment 后，即可
让个人机器通过出站连接接收部署任务，无需开放家庭网络入站端口。

Runner 安装在 WSL 的 `/opt/actions-runner`，以独立的 `github-runner` 非 root 用户运行，
并只授予 Docker 组与当前 kind kubeconfig。注册令牌是一次性的，不写入仓库或本地配置。

本地机器关机或 WSL/Docker 停止时服务会离线，因此它适合 CI/CD 学习和个人 Staging，
不适合作为需要持续在线的生产服务。
