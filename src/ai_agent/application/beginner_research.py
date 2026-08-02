"""Bounded market-data snapshots for the Web entry's beginner path."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextvars import copy_context
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from threading import Event, RLock, Thread

from ..data_sources import get_data_source
from ..observability import log_event
from ..tools import ToolRegistry
from .entity_resolution import SecurityCandidate


@dataclass(frozen=True, slots=True)
class BeginnerResearchSnapshot:
    """A transparent, bounded result for a selected listed security."""

    security: SecurityCandidate
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return self.payload


@dataclass(slots=True)
class _InFlightMarketRead:
    """One bounded source read shared by identical concurrent callers.

    The result deliberately exists only while the read is in progress. This is
    request coalescing, not a market-data cache: a later user action starts a
    fresh source read and receives fresh evidence.
    """

    completed: Event
    response: str | None = None
    waiting_callers: int = 1


class BeginnerResearchService:
    """Read one short daily-price window without an LLM or unbounded tool loop."""

    def __init__(
        self,
        *,
        tool_registry_factory: Callable[[], ToolRegistry],
        today: Callable[[], date] = date.today,
        timeout_seconds: float = 8.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("beginner market-data timeout_seconds must be positive")
        self._tool_registry_factory = tool_registry_factory
        self._today = today
        self._timeout_seconds = timeout_seconds
        self._inflight_reads: dict[tuple[str, str, str, int], _InFlightMarketRead] = {}
        self._inflight_reads_lock = RLock()

    def latest_week(self, security: SecurityCandidate) -> BeginnerResearchSnapshot:
        """Return the latest available daily bar and up to five recent trading days.

        A configured EODHD account is preferred for these global securities so
        the Web quick path actually uses the data-source credentials that the
        owner has maintained.  Yahoo Finance remains a token-free fallback.
        A ten-calendar-day request is enough to cover a normal five-trading-day
        week without claiming that weekends or market holidays contain prices.
        """

        requested_on = self._today()
        start_date = (requested_on - timedelta(days=10)).isoformat()
        end_date = requested_on.isoformat()
        raw = self._read_market_data(security, start_date, end_date, limit=5)
        market_data = self._market_payload(raw, security, start_date, end_date)
        payload: dict[str, object] = {
            "contract_version": "beginner-market-snapshot/v1",
            "security": security.to_dict(),
            "default_period": {
                "label": "最新可用日线与最近五个交易日",
                "requested_on": requested_on.isoformat(),
                "requested_start_date": start_date,
                "requested_end_date": end_date,
            },
            "market_data": market_data,
            "financial_reports": {
                "status": "not_connected",
                "message": (
                    "当前基础快照已接入行情；财报、监管披露和业绩预告的数据适配器尚未接入，"
                    "因此不会据此生成财报结论。"
                ),
            },
            "limitations": [
                "基础概览优先使用已配置的 EODHD 日线；不可用时才回退至 Yahoo Finance。"
                "两者都可能是收盘后或延迟数据，并非实时成交报价。",
                "港股普通股与美股 ADR 的交易币种、交易时段和存托凭证安排不同，"
                "不能只用价格绝对值直接比较。",
                "本页仅供个人研究与内容整理，不构成投资建议或交易指令。",
            ],
        }
        return BeginnerResearchSnapshot(security=security, payload=payload)

    def period(
        self,
        security: SecurityCandidate,
        *,
        start_date: date,
        end_date: date,
        limit: int = 120,
    ) -> BeginnerResearchSnapshot:
        """Return one exact, bounded daily-price window for professional research."""

        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
            raise ValueError("professional market-data limit must be between 1 and 120")
        start_text = start_date.isoformat()
        end_text = end_date.isoformat()
        raw = self._read_market_data(security, start_text, end_text, limit=limit)
        market_data = self._market_payload(raw, security, start_text, end_text)
        return BeginnerResearchSnapshot(
            security=security,
            payload={
                "contract_version": "professional-market-snapshot/v1",
                "security": security.to_dict(),
                "default_period": {
                    "label": "用户指定的精确日期区间",
                    "requested_start_date": start_text,
                    "requested_end_date": end_text,
                    "maximum_trading_days": limit,
                },
                "market_data": market_data,
                "limitations": [
                    f"单个指数最多读取 {limit} 个交易日；结果会标明实际覆盖的首尾交易日。",
                    "日线可能为收盘后或延迟数据，并非实时可成交报价。",
                    "本页仅供个人研究与内容整理，不构成投资建议或交易指令。",
                ],
            },
        )

    def _read_market_data(
        self,
        security: SecurityCandidate,
        start_date: str,
        end_date: str,
        *,
        limit: int,
    ) -> str:
        """Bound compatible source reads even when a library timeout is ignored.

        A third-party library import, DNS lookup, or upstream socket can
        occasionally outlive its own timeout.  The Web request has a fixed
        outer budget. Identical reads share the same in-flight work so repeat
        clicks cannot multiply source calls while preserving a fresh read for
        any request that starts after the first one has completed.
        """

        read_key = (security.key, start_date, end_date, limit)
        with self._inflight_reads_lock:
            in_flight = self._inflight_reads.get(read_key)
            if in_flight is None:
                in_flight = _InFlightMarketRead(completed=Event())
                self._inflight_reads[read_key] = in_flight
                starts_reader = True
                coalesced_callers = 0
            else:
                in_flight.waiting_callers += 1
                starts_reader = False
                coalesced_callers = in_flight.waiting_callers

        if starts_reader:
            def read() -> None:
                try:
                    registry = self._tool_registry_factory()
                    response = self._read_from_compatible_sources(
                        registry,
                        security,
                        start_date,
                        end_date,
                        limit,
                    )
                except Exception:  # noqa: BLE001 - isolate optional readers from the Web request
                    response = "ERROR: 行情工具暂时不可用。"
                with self._inflight_reads_lock:
                    in_flight.response = response
                    # Existing waiters retain this object. Callers arriving after
                    # completion correctly create a new, fresh source read.
                    in_flight.completed.set()
                    if self._inflight_reads.get(read_key) is in_flight:
                        del self._inflight_reads[read_key]

            # The Web request ID is a ContextVar. Propagate it into the bounded
            # reader so source latency events remain traceable without copying
            # user content or tool payloads into logs.
            request_context = copy_context()
            Thread(
                target=lambda: request_context.run(read),
                name=f"finance-agent-market-{security.key}",
                daemon=True,
            ).start()
        else:
            log_event("market_read_coalesced", waiting_callers=coalesced_callers)

        if not in_flight.completed.wait(timeout=self._timeout_seconds):
            return (
                f"ERROR: 行情数据源在 {self._timeout_seconds:g} 秒内没有响应；已停止等待，"
                "请稍后重试或检查本机网络与数据源状态。"
            )
        return in_flight.response or "ERROR: 行情读取在完成前未返回可用结果。"

    @staticmethod
    def _read_from_compatible_sources(
        registry: ToolRegistry,
        security: SecurityCandidate,
        start_date: str,
        end_date: str,
        limit: int,
    ) -> str:
        """Use compatible sources in the configured low-latency priority order."""

        available = {tool.name for tool in registry.definitions()}
        requests: list[tuple[str, str, dict[str, object]]] = []
        if security.zhitu_index_symbol and "zhitu_market_data" in available:
            requests.append(
                (
                    "zhitu",
                    "zhitu_market_data",
                    {
                        "action": "index_history",
                        "symbol": security.zhitu_index_symbol,
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": limit,
                    },
                )
            )
        if security.tickflow_symbol and "tickflow_market_data" in available:
            requests.append(
                (
                    "tickflow",
                    "tickflow_market_data",
                    {
                        "action": "historical_candles",
                        "symbol": security.tickflow_symbol,
                        "start_date": start_date,
                        "end_date": end_date,
                        "adjust": "none",
                        "limit": limit,
                    },
                )
            )
        if security.eodhd_symbol and "eodhd_market_data" in available:
            requests.append(
                (
                    "eodhd",
                    "eodhd_market_data",
                    {
                        "action": "historical_candles",
                        "symbol": security.eodhd_symbol,
                        "start_date": start_date,
                        # EODHD's end date is inclusive, unlike yfinance.
                        "end_date": end_date,
                        "period": "d",
                        "limit": limit,
                    },
                )
            )
        if "yfinance_market_data" in available:
            requests.append(
                (
                    "yfinance",
                    "yfinance_market_data",
                    {
                        "symbol": security.yahoo_symbol,
                        "start_date": start_date,
                        # yfinance's end date is exclusive, so include today.
                        "end_date": (date.fromisoformat(end_date) + timedelta(days=1)).isoformat(),
                        "interval": "1d",
                        "auto_adjust": True,
                        "limit": limit,
                    },
                )
            )
        if not requests:
            return "ERROR: 没有可用于该证券的行情数据工具。"

        requests.sort(key=lambda request: _source_order(request[0]))
        failures: list[str] = []
        for _source_name, tool_name, arguments in requests:
            response = registry.execute(tool_name, arguments)
            if isinstance(response, str) and _contains_candles(response):
                return response
            if isinstance(response, str) and response.startswith("ERROR:"):
                failures.append(f"{tool_name}: {response.removeprefix('ERROR:').strip()}")
            else:
                failures.append(f"{tool_name}: 未返回可用日线数据")
        return "ERROR: " + "；".join(failures)

    @staticmethod
    def _market_payload(
        raw: str,
        security: SecurityCandidate,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        if raw.startswith("ERROR:"):
            return _unavailable_market_data(str(raw.removeprefix("ERROR:")).strip(), start_date, end_date)
        try:
            source_payload = json.loads(raw)
        except json.JSONDecodeError:
            return _unavailable_market_data("行情工具返回了无法解析的数据。", start_date, end_date)
        if not isinstance(source_payload, Mapping):
            return _unavailable_market_data("行情工具返回了不符合预期的数据结构。", start_date, end_date)
        rows = source_payload.get("candles")
        if not isinstance(rows, list):
            return _unavailable_market_data("行情工具未返回日线数据。", start_date, end_date)

        candles = [_candle(row) for row in rows]
        candles = [row for row in candles if row is not None]
        candles.sort(key=lambda row: str(row["date"]))
        if not candles:
            return _unavailable_market_data("在该请求窗口内没有可用日线数据。", start_date, end_date)
        window = candles[-5:]
        first, latest = window[0], window[-1]
        period_first = candles[0]
        period_change = latest["close"] - period_first["close"]
        period_change_percent = (
            period_change / period_first["close"] * Decimal("100")
            if period_first["close"]
            else None
        )
        change = latest["close"] - first["close"]
        change_percent = (change / first["close"] * Decimal("100")) if first["close"] else None
        volumes = [row["volume"] for row in window if row["volume"] is not None]
        period_volumes = [row["volume"] for row in candles if row["volume"] is not None]
        source = source_payload.get("source")
        return {
            "status": "complete",
            "source": source if isinstance(source, str) else "configured market-data source",
            "freshness": "end_of_day_or_delayed",
            "currency": security.currency,
            "requested_start_date": start_date,
            "requested_end_date": end_date,
            "latest": _presentation_candle(latest),
            "period_performance": {
                "trading_days": len(candles),
                "first_date": period_first["date"],
                "last_date": latest["date"],
                "first_close": _decimal_text(period_first["close"]),
                "last_close": _decimal_text(latest["close"]),
                "change": _decimal_text(period_change, places=2),
                "change_percent": (
                    _decimal_text(period_change_percent, places=2)
                    if period_change_percent is not None
                    else None
                ),
                "highest_high": _decimal_text(max(row["high"] for row in candles)),
                "lowest_low": _decimal_text(min(row["low"] for row in candles)),
                "total_volume": _decimal_text(sum(period_volumes)) if period_volumes else None,
            },
            "recent_week": {
                "trading_days": len(window),
                "first_date": first["date"],
                "last_date": latest["date"],
                "first_close": _decimal_text(first["close"]),
                "last_close": _decimal_text(latest["close"]),
                "change": _decimal_text(change, places=2),
                "change_percent": _decimal_text(change_percent, places=2) if change_percent is not None else None,
                "highest_high": _decimal_text(max(row["high"] for row in window)),
                "lowest_low": _decimal_text(min(row["low"] for row in window)),
                "total_volume": _decimal_text(sum(volumes)) if volumes else None,
            },
        }


def _source_order(source_name: str) -> tuple[int, int, str]:
    """Use the catalog's priority and latency class for beginner fallbacks."""

    definition = get_data_source(source_name)
    if definition is None:
        return (999, 999, source_name)
    return (definition.routing_priority, definition.latency_rank, definition.name)


def _contains_candles(response: str) -> bool:
    """Reject successful-looking empty payloads so the fallback can still help."""

    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, Mapping) and isinstance(payload.get("candles"), list) and bool(payload["candles"])


def _unavailable_market_data(reason: str, start_date: str, end_date: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "reason": reason or "行情工具暂时不可用。",
        "freshness": "unknown",
        "requested_start_date": start_date,
        "requested_end_date": end_date,
    }


def _candle(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    observation_date = value.get("date")
    if not isinstance(observation_date, str):
        return None
    try:
        close = _decimal(value.get("close"))
        high = _decimal(value.get("high"))
        low = _decimal(value.get("low"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    volume_value = value.get("volume")
    try:
        volume = _decimal(volume_value) if volume_value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        volume = None
    return {"date": observation_date, "close": close, "high": high, "low": low, "volume": volume}


def _decimal(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite number")
    return result


def _presentation_candle(candle: Mapping[str, object]) -> dict[str, object]:
    return {
        "date": candle["date"],
        "close": _decimal_text(candle["close"]),
        "high": _decimal_text(candle["high"]),
        "low": _decimal_text(candle["low"]),
        "volume": _decimal_text(candle["volume"]) if candle["volume"] is not None else None,
    }


def _decimal_text(value: object, *, places: int | None = None) -> str:
    decimal_value = value if isinstance(value, Decimal) else _decimal(value)
    if places is not None:
        decimal_value = decimal_value.quantize(Decimal("1." + "0" * places), rounding=ROUND_HALF_UP)
    return format(decimal_value, "f")
