# 共享 LangChain 运行环境

本文是 [项目主说明](../README.md) 的本机运行环境补充，仅说明共享虚拟环境、缓存和资源目录；项目架构、职责与使用路径请以主说明为准。

项目的 Python 和 LangChain 依赖统一安装在 `G:\Program Files\Codex\.venv`，而不是本目录中的独立虚拟环境。完成依赖安装后，从项目根目录执行：

```powershell
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' -m pip install -e .
```

`finance-agent.ps1` 会使用该共享环境。`cache/` 仍只用于可再生的行情数据缓存。

# 数据源资源目录

此目录统一存放本项目的本地数据源运行资源，避免把项目依赖、服务缓存或临时状态混入全局 Python 安装目录 `G:\Program Files\Python314`。

| 路径 | 用途 | Git 策略 |
| --- | --- | --- |
| `data-source-runtime/` | 项目专用 Python 虚拟环境；包含 `finance-agent`、BaoStock、yfinance 与后续数据源 SDK。 | 忽略 |
| `cache/` | 可选的、可重新生成的数据源缓存；例如 yfinance 时区/Cookie 缓存。 | 忽略 |
| 本文件 | 资源布局与维护说明。 | 提交 |

初始化或重新创建运行环境：

```powershell
cd 'G:\Program Files\Codex\finance-agent'
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' -m pip install -e .
```

推荐使用固定启动入口；它会自动将 yfinance 缓存放入本目录：

```powershell
.\resources\finance-agent.ps1
```

也可以直接使用 `data-source-runtime\Scripts\finance-agent.exe`。

数据源令牌继续由当前 Windows 用户的 DPAPI 加密存储管理；它们不放入此目录，也不会写入 Git。
