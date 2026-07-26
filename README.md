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
  cli.py            # 本地交互入口
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

## 接入真实模型

1. 在 `src/ai_agent/providers/` 新建供应商适配器，并实现 `ModelClient.complete()`。
2. 将适配器注入 `Agent`，或在后续的应用组合层中按 `AGENT_PROVIDER` 选择适配器。
3. 通过实现 `Tool` 协议添加业务工具；工具应在自己的边界内完成鉴权、输入校验和审计。

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
