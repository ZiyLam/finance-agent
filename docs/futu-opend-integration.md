# Futu OpenAPI / FutuOpenD 接入说明（归纳）

本文是项目中原始资料 [Futu-API-Doc-zh-Python.md](../src/Futu-API-Doc-zh-Python.md) 的操作性归纳，面向本项目的金融研究 Agent；原始文档仍是接口细节的参考来源。

## 架构与边界

富途 Python SDK 不是直接访问公共 HTTP API。其通讯链路为：

```text
Finance Agent → futu-api Python SDK → 本机/云端 FutuOpenD → 富途后台
```

本项目只创建 `OpenQuoteContext`，并且只允许读取行情。下列能力不在本项目范围内：交易上下文、账户/持仓读取、交易解锁、交易密码、下单、撤单及任何自动交易。`FUTU_API_TOKEN` 仅为所有数据源统一保留的维护槽位；当前 OpenD 行情接入并不使用该值。

## 一次性准备

1. 安装项目依赖（已包含 `futu-api`）：`python -m pip install -e .`。
2. 按富途官方渠道下载并启动 FutuOpenD。
3. 在 FutuOpenD 内由操作者完成登录；不要向 Agent 提供券商密码、验证码或交易密码。
4. 默认地址为 `127.0.0.1:11111`。若 OpenD 在受操作者控制的其他地址，启动 Agent 前设置：

   ```powershell
   $env:FUTU_OPEND_HOST = '127.0.0.1'
   $env:FUTU_OPEND_PORT = '11111'
   ```

5. 使用 `finance-agent source check futu` 检查 TCP 端口可达。该检查不读取账户、不登录，也不能确认行情权限；实际数据请求才会确认 OpenD 是否可用。

## Agent 已接入的只读动作

`futu_market_data` 提供以下动作：

| 动作 | 输入 | 范围与输出 |
| --- | --- | --- |
| `historical_candles` | `code`、`start_date`、`end_date`、`interval`（`d`/`w`/`m`）、`autype`（`qfq`/`hfq`/`none`） | 日、周、月 K 线；调用单页最多 1,000 根，模型最多显示最近 120 根。若接口提示还有下一页，工具会要求拆分日期范围，绝不静默截断。 |
| `market_snapshot` | 1–20 个 `codes` | 行情快照，包括可用的价格、成交量、成交额、估值和返回时间字段。单次项目限制远低于富途文档的 400 个代码上限。 |

富途代码须带市场前缀，例如 `HK.00700`、`US.AAPL`、`SH.600519`、`SZ.000001`。实际可查询的市场和产品（如港、美、A 股、新加坡、马来西亚、日本、指数、期权、期货等）以 OpenD 所登录账户的权限为准。

## 权限、时效与限流

- 行情时延、摆盘档数与可用品种由账户和行情卡决定。除非返回数据和权限可核验，不能将结果称为实时行情。
- 原始资料列示：分 K 通常限最近 8 年，日 K 限最近 20 年，日 K 以上通常不设该时间限制；具体以接口和账户最终响应为准。
- 历史 K 线官方频率限制为每 30 秒最多 60 次。近 7 天请求一个新标的也可能占用历史 K 线额度；额度按账户资产和交易情况变化，周期不同的同一标的一般不重复占用。
- 本项目本地保护为每进程最小 1 秒间隔、最多 500 次/日。它只是保守的防突发阈值，不能扩大富途官方频率或历史 K 线权限。
- 快照接口的原始资料示例也标示每 30 秒 60 次；本项目使用同一个本地防突发保护。

## 数据使用口径

每次金融分析引用富途返回内容时，都应标注：`Futu OpenAPI (FutuOpenD)`、富途代码、查询动作、周期或快照返回时间、复权口径以及已知的权限/时延限制。K 线最后一根的时间是数据时间，不当然代表当前时刻；价格和成交量数据不能替代公告、财报、监管披露或个性化投资建议。

## 常见故障

| 现象 | 处理 |
| --- | --- |
| 提示缺少 `futu-api` | 在本项目所用 Python 环境执行 `python -m pip install -e .` 或 `python -m pip install futu-api`。 |
| `source check futu` 失败 | 启动 FutuOpenD，核对 `FUTU_OPEND_HOST`、`FUTU_OPEND_PORT`、防火墙和 TCP 端口。 |
| 数据请求提示 OpenD 不可用 | 确认 OpenD 已登录且不是仅端口监听；必要时重启 OpenD 后再次核验。 |
| 请求被拒绝、空数据或权限不足 | 核对富途代码、可用市场、行情卡、历史 K 线额度和账户地区/权限；不得用其他数据源猜测补值。 |
| K 线范围过大 | 按更小日期区间分段请求；本项目不会自动分页，以避免无意消耗历史 K 线额度。 |
| 加密或端口配置不匹配 | 以实际 FutuOpenD 设置为准；本项目默认使用文档所示的本地非加密地址。 |

## 凭证维护

所有数据源均有一致的凭证维护入口：

```powershell
finance-agent source set-token futu
finance-agent source status futu
finance-agent source delete-token futu
```

保存的值使用当前 Windows 用户的 DPAPI 加密。由于当前 Futu 行情接入并不以 API token 鉴权，状态输出会明确显示该槽位为“维护用途，当前适配器不使用”。
