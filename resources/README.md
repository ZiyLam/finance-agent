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
& 'G:\Program Files\Python314\python.exe' -m venv 'resources\data-source-runtime'
.\resources\data-source-runtime\Scripts\Activate.ps1
$env:PIP_CACHE_DIR = 'G:\Program Files\Codex\finance-agent\resources\cache\pip'
python -m pip install --upgrade pip
python -m pip install -e .
```

推荐使用固定启动入口；它会自动将 yfinance 缓存放入本目录：

```powershell
.\resources\finance-agent.ps1
```

也可以直接使用 `data-source-runtime\Scripts\finance-agent.exe`。

数据源令牌继续由当前 Windows 用户的 DPAPI 加密存储管理；它们不放入此目录，也不会写入 Git。
