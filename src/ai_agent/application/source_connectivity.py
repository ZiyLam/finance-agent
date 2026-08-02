"""Bounded, read-only connectivity checks for configured external sources."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import BoundedSemaphore, RLock, Thread
from time import monotonic

from ..data_sources import (
    DataSourceDefinition,
    SourceConfigurationGroup,
    configurations_in_group,
    get_data_source,
    ordered_data_sources,
)
from ..messages import ChatMessage, MessageRole
from ..observability import log_event
from ..provider_activation import ProviderActivationError, ProviderActivationStore
from ..secrets import SecretStore, SecretStoreError, default_secret_store, resolve_token

SourceProbe = Callable[[str | None], None]


@dataclass(frozen=True, slots=True)
class SourceConnectivityResult:
    """A browser-safe connectivity result with no provider response details."""

    name: str
    status: str
    checked_at: str | None
    duration_ms: int | None
    category: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "checked_at": self.checked_at,
            "duration_ms": self.duration_ms,
            "category": self.category,
            "message": self.message,
        }


class SourceConnectivityService:
    """Run explicit smoke tests under per-call timeout and concurrency limits.

    Checks are never triggered by listing the settings page. Each probe performs
    one minimal read using the same adapter as the research runtime. Results are
    cached only in this process so the page can retain the latest observation.
    """

    def __init__(
        self,
        store: SecretStore | None = None,
        *,
        activation: ProviderActivationStore | None = None,
        probes: Mapping[str, SourceProbe] | None = None,
        timeout_seconds: float = 4.0,
        max_parallel_checks: int = 4,
        clock: Callable[[], float] = monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("source connectivity timeout_seconds must be positive")
        if max_parallel_checks < 1:
            raise ValueError("max_parallel_checks must be at least 1")
        self._store = store or default_secret_store()
        self._activation = activation or ProviderActivationStore()
        self._probes = dict(_default_probes() if probes is None else probes)
        self._timeout_seconds = timeout_seconds
        self._max_parallel_checks = max_parallel_checks
        self._clock = clock
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._slots = BoundedSemaphore(max_parallel_checks)
        self._lock = RLock()
        self._results: dict[str, SourceConnectivityResult] = {}

    def snapshot(self, source: str) -> dict[str, object]:
        """Return the latest in-memory state without initiating a network call."""

        definition = self._definition(source)
        if not self._is_enabled(definition):
            return self._disabled(definition).to_dict()
        with self._lock:
            result = self._results.get(definition.name)
        return (result or self._untested(definition)).to_dict()

    def invalidate(self, source: str) -> None:
        """Discard a stale result after its credential changes."""

        definition = self._definition(source)
        with self._lock:
            self._results.pop(definition.name, None)

    def check(self, source: str) -> dict[str, object]:
        """Run one bounded connectivity check and retain its safe result."""

        definition = self._definition(source)
        started_at = self._clock()
        checked_at = self._now().astimezone(timezone.utc).isoformat()
        if not self._is_enabled(definition):
            return self._remember(
                SourceConnectivityResult(
                    name=definition.name,
                    status="disabled",
                    checked_at=checked_at,
                    duration_ms=max(0, round((self._clock() - started_at) * 1_000)),
                    category="disabled",
                    message="此提供方已停用，未发出连接请求。",
                )
            )
        try:
            token = resolve_token(
                definition.name,
                definition.token_environment_variable,
                self._store,
            )
        except (OSError, SecretStoreError):
            result = self._result(
                definition,
                "local_unavailable",
                checked_at,
                started_at,
                "local_credentials",
                "本地安全凭据暂时无法读取。",
            )
            return self._remember(result)

        if definition.token_required_by_adapter and not token:
            result = self._result(
                definition,
                "not_configured",
                checked_at,
                started_at,
                "credential",
                "尚未配置此适配器所需的令牌。",
            )
            return self._remember(result)

        probe = self._probes.get(definition.name)
        if probe is None:
            result = self._result(
                definition,
                "unsupported",
                checked_at,
                started_at,
                "unsupported",
                "当前版本尚未定义此来源的安全只读探测。",
            )
            return self._remember(result)

        if not self._slots.acquire(timeout=self._timeout_seconds):
            result = self._result(
                definition,
                "local_unavailable",
                checked_at,
                started_at,
                "local_capacity",
                "连通性测试并发已满，请稍后重试。",
            )
            return self._remember(result)
        try:
            outcome, error = self._run_probe(probe, token)
        finally:
            self._slots.release()

        if outcome == "healthy":
            result = self._result(
                definition,
                "healthy",
                checked_at,
                started_at,
                "connectivity",
                "已完成最小只读请求，服务连接正常。",
            )
        elif outcome == "timeout":
            result = self._result(
                definition,
                "remote_failure",
                checked_at,
                started_at,
                "remote_timeout",
                "远端服务未在测试时限内响应。",
            )
        elif _is_local_failure(definition.name, error):
            result = self._result(
                definition,
                "local_unavailable",
                checked_at,
                started_at,
                "local_runtime",
                "本地服务或可选依赖当前不可用。",
            )
        else:
            result = self._result(
                definition,
                "remote_failure",
                checked_at,
                started_at,
                "remote_connection",
                "远端服务未能完成连接测试。",
            )
        return self._remember(result, error_type=type(error).__name__ if error is not None else None)

    def check_all(
        self,
        configuration_group: SourceConfigurationGroup | str | None = None,
    ) -> list[dict[str, object]]:
        """Check one settings module, or the full catalog, in routing order."""

        definitions = (
            ordered_data_sources()
            if configuration_group is None
            else configurations_in_group(configuration_group)
        )
        if not definitions:
            return []
        with ThreadPoolExecutor(
            max_workers=min(self._max_parallel_checks, len(definitions)),
            thread_name_prefix="source-connectivity",
        ) as executor:
            futures = {definition.name: executor.submit(self.check, definition.name) for definition in definitions}
            return [futures[definition.name].result() for definition in definitions]

    def _run_probe(self, probe: SourceProbe, token: str | None) -> tuple[str, BaseException | None]:
        output: Queue[tuple[str, BaseException | None]] = Queue(maxsize=1)

        def invoke() -> None:
            try:
                probe(token)
            except Exception as error:  # Keep provider details inside this process.
                output.put(("failed", error))
            else:
                output.put(("healthy", None))

        worker = Thread(target=invoke, daemon=True, name="source-smoke-test")
        worker.start()
        worker.join(self._timeout_seconds)
        if worker.is_alive():
            return "timeout", None
        try:
            return output.get_nowait()
        except Empty:
            return "failed", RuntimeError("source probe ended without a result")

    def _result(
        self,
        definition: DataSourceDefinition,
        status: str,
        checked_at: str,
        started_at: float,
        category: str,
        message: str,
    ) -> SourceConnectivityResult:
        return SourceConnectivityResult(
            name=definition.name,
            status=status,
            checked_at=checked_at,
            duration_ms=max(0, round((self._clock() - started_at) * 1_000)),
            category=category,
            message=message,
        )

    def _remember(
        self,
        result: SourceConnectivityResult,
        *,
        error_type: str | None = None,
    ) -> dict[str, object]:
        with self._lock:
            self._results[result.name] = result
        fields: dict[str, object] = {
            "provider_name": result.name,
            "configuration_group": self._definition(result.name).configuration_group.value,
            "connectivity_status": result.status,
            "category": result.category,
            "duration_ms": result.duration_ms,
        }
        if error_type:
            fields["error_type"] = error_type
        log_event("source_connectivity_check_completed", **fields)
        return result.to_dict()

    @staticmethod
    def _definition(source: str) -> DataSourceDefinition:
        definition = get_data_source(source)
        if definition is None:
            raise ValueError("Unknown data source")
        return definition

    @staticmethod
    def _untested(definition: DataSourceDefinition) -> SourceConnectivityResult:
        return SourceConnectivityResult(
            name=definition.name,
            status="untested",
            checked_at=None,
            duration_ms=None,
            category="not_tested",
            message="尚未执行连通性测试。",
        )

    @staticmethod
    def _disabled(definition: DataSourceDefinition) -> SourceConnectivityResult:
        return SourceConnectivityResult(
            name=definition.name,
            status="disabled",
            checked_at=None,
            duration_ms=None,
            category="disabled",
            message="此提供方已停用，不会被调用。",
        )

    def _is_enabled(self, definition: DataSourceDefinition) -> bool:
        try:
            return self._activation.is_enabled(definition.name)
        except (OSError, ProviderActivationError):
            # Fail closed: an unreadable local policy must never broaden access.
            return False


def _is_local_failure(source: str, error: BaseException | None) -> bool:
    if source == "aktools":
        return True
    return error is not None and type(error).__name__.endswith("DependencyError")


def _default_probes() -> dict[str, SourceProbe]:
    """Build lazy probes so importing the settings service performs no I/O."""

    timeout_seconds = 4.0

    def alltick(token: str | None) -> None:
        from ..market_data.alltick import AllTickClient

        AllTickClient(token or "", timeout_seconds=timeout_seconds).latest_quotes(("UNH.US",))

    def alphavantage(token: str | None) -> None:
        from ..market_data.alphavantage import AlphaVantageClient

        AlphaVantageClient(token or "", timeout_seconds=timeout_seconds).global_quote("IBM")

    def biying(token: str | None) -> None:
        from ..market_data.biying import BiyingClient

        BiyingClient(token or "", timeout_seconds=timeout_seconds).realtime_quote("000001")

    def eodhd(token: str | None) -> None:
        from ..market_data.eodhd import EODHDClient

        EODHDClient(token or "", timeout_seconds=timeout_seconds).search("Apple", limit=1)

    def eastmoney(_token: str | None) -> None:
        from ..market_data.eastmoney import EastmoneySecuritySearchClient

        EastmoneySecuritySearchClient(timeout_seconds=timeout_seconds).leading_industries(limit=1)

    def zhitu(token: str | None) -> None:
        from ..market_data.zhitu import ZhituClient

        ZhituClient(token or "", timeout_seconds=timeout_seconds).stock_quote("600000.SH")

    def qianfan(token: str | None) -> None:
        from ..providers.qianfan import QianfanModelClient

        QianfanModelClient(token or "", timeout_seconds=timeout_seconds).complete(
            (ChatMessage(MessageRole.USER, "请仅确认服务可用。"),),
            (),
        )

    def aktools(_token: str | None) -> None:
        from ..market_data.aktools import AkToolsClient

        AkToolsClient.from_environment(timeout_seconds=timeout_seconds).service_version()

    def baostock(_token: str | None) -> None:
        from ..market_data.baostock import BaoStockClient

        BaoStockClient().historical_candles(
            "sh.600000",
            start_date="2024-01-02",
            end_date="2024-01-03",
        )

    def yfinance(_token: str | None) -> None:
        from ..market_data.yfinance import YFinanceClient

        YFinanceClient(timeout_seconds=timeout_seconds).historical_candles(
            "AAPL",
            start_date="2024-01-02",
            end_date="2024-01-04",
        )

    def tickflow(token: str | None) -> None:
        from ..market_data.tickflow import TickFlowClient

        TickFlowClient(token or "", timeout_seconds=timeout_seconds).quotes(("600000.SH",))

    return {
        "alltick": alltick,
        "alphavantage": alphavantage,
        "biying": biying,
        "eodhd": eodhd,
        "eastmoney": eastmoney,
        "zhitu": zhitu,
        "qianfan": qianfan,
        "aktools": aktools,
        "baostock": baostock,
        "yfinance": yfinance,
        "tickflow": tickflow,
    }
