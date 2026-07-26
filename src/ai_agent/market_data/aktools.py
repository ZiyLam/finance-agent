"""Read-only client for a locally deployed AkTools service.

AkTools exposes AKShare functions as HTTP endpoints.  It has no API token of
its own, but the service must be started by the operator (locally, in Docker,
or behind an operator-controlled URL) before this client can retrieve data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from os import getenv
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


DEFAULT_AKTOOLS_BASE_URL = "http://127.0.0.1:8080"


class AkToolsError(RuntimeError):
    """Base error for AkTools market-data requests."""


class AkToolsApiError(AkToolsError):
    """AkTools returned data that does not match the documented endpoint."""


class AkToolsRateLimitError(AkToolsError):
    """The local guard rejected a request before it reached AkTools."""


class AkToolsTransportError(AkToolsError):
    """The configured local AkTools service could not be reached."""


@dataclass(frozen=True, slots=True)
class AkToolsLimits:
    """Per-process protection for the local service and its upstream providers."""

    minimum_interval_seconds: float = 0.2

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")


DEFAULT_LIMITS = AkToolsLimits()


@dataclass(frozen=True, slots=True)
class AkToolsCandle:
    """One A-share historical OHLCV observation returned by AkTools."""

    date: str
    open_price: Decimal
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal
    volume: Decimal | None
    turnover: Decimal | None
    amplitude_percent: Decimal | None
    change_percent: Decimal | None
    change_amount: Decimal | None
    turnover_rate_percent: Decimal | None


Transport = Callable[[str], bytes]


class _RateGuard:
    def __init__(self, limits: AkToolsLimits, clock: Callable[[], float]) -> None:
        self._minimum_interval_seconds = limits.minimum_interval_seconds
        self._clock = clock
        self._last_request: float | None = None

    def acquire(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            remaining = self._minimum_interval_seconds - (now - self._last_request)
            if remaining > 0:
                raise AkToolsRateLimitError(
                    f"Local AkTools interval limit; retry after {remaining:.1f} seconds"
                )
        self._last_request = now


class AkToolsClient:
    """Retrieve documented A-share historical K lines from an AkTools service."""

    def __init__(
        self,
        base_url: str = DEFAULT_AKTOOLS_BASE_URL,
        *,
        limits: AkToolsLimits = DEFAULT_LIMITS,
        timeout_seconds: float = 10.0,
        transport: Transport | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = self._validate_base_url(base_url)
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport
        self._guard = _RateGuard(limits, clock)

    @classmethod
    def from_environment(cls, **kwargs: Any) -> "AkToolsClient":
        """Use the configured service, defaulting to the documented local URL."""

        return cls(getenv("AKTOOLS_BASE_URL", DEFAULT_AKTOOLS_BASE_URL), **kwargs)

    def stock_zh_a_hist(
        self,
        symbol: str,
        *,
        period: str = "daily",
        start_date: str,
        end_date: str,
        adjust: str = "",
    ) -> tuple[AkToolsCandle, ...]:
        """Return A-share historical K lines from ``stock_zh_a_hist``.

        AkTools documents ``daily``, ``weekly``, and ``monthly`` periods, and
        an empty, ``qfq``, or ``hfq`` adjustment value.
        """

        normalized_symbol = self._validate_symbol(symbol)
        normalized_period = self._validate_choice(period, {"daily", "weekly", "monthly"}, "period")
        normalized_adjust = self._validate_choice(adjust, {"", "qfq", "hfq"}, "adjust")
        self._validate_dates(start_date, end_date)
        payload = self._get_json(
            "/api/public/stock_zh_a_hist",
            {
                "symbol": normalized_symbol,
                "period": normalized_period,
                "start_date": start_date,
                "end_date": end_date,
                "adjust": normalized_adjust,
            },
        )
        if not isinstance(payload, list) or not all(isinstance(item, Mapping) for item in payload):
            raise AkToolsApiError("AkTools returned an unexpected historical K-line payload")
        return tuple(self._to_candle(item) for item in payload)

    def _get_json(self, path: str, parameters: Mapping[str, str]) -> Any:
        self._guard.acquire()
        url = f"{self._base_url}{path}?{urlencode(parameters)}"
        try:
            raw = self._transport(url)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise AkToolsTransportError(
                "Could not reach the AkTools service. Start it, then retry; "
                "the default address is http://127.0.0.1:8080."
            ) from None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AkToolsTransportError("AkTools returned invalid JSON") from error

    def _default_transport(self, url: str) -> bytes:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=self._timeout_seconds) as response:
            return response.read()

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("AKTOOLS_BASE_URL must be an http(s) base URL without credentials")
        return normalized

    @staticmethod
    def _validate_symbol(symbol: str) -> str:
        normalized = symbol.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("AkTools A-share symbols must be six digits")
        return normalized

    @staticmethod
    def _validate_choice(value: str, allowed: set[str], field_name: str) -> str:
        if not isinstance(value, str) or value not in allowed:
            choices = ", ".join(repr(item) for item in sorted(allowed))
            raise ValueError(f"AkTools {field_name} must be one of {choices}")
        return value

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> None:
        try:
            start = datetime.strptime(start_date, "%Y%m%d").date()
            end = datetime.strptime(end_date, "%Y%m%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("AkTools dates must use YYYYMMDD") from error
        if start > end:
            raise ValueError("AkTools start_date must not be later than end_date")

    @classmethod
    def _to_candle(cls, item: Mapping[str, Any]) -> AkToolsCandle:
        return AkToolsCandle(
            date=cls._required_date(item, "日期"),
            open_price=cls._required_decimal(item, "开盘"),
            close_price=cls._required_decimal(item, "收盘"),
            high_price=cls._required_decimal(item, "最高"),
            low_price=cls._required_decimal(item, "最低"),
            volume=cls._optional_decimal(item, "成交量"),
            turnover=cls._optional_decimal(item, "成交额"),
            amplitude_percent=cls._optional_decimal(item, "振幅"),
            change_percent=cls._optional_decimal(item, "涨跌幅"),
            change_amount=cls._optional_decimal(item, "涨跌额"),
            turnover_rate_percent=cls._optional_decimal(item, "换手率"),
        )

    @staticmethod
    def _required_date(item: Mapping[str, Any], key: str) -> str:
        value = item.get(key)
        if not isinstance(value, str):
            raise AkToolsApiError(f"AkTools K-line is missing {key}")
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise AkToolsApiError(f"AkTools K-line has an invalid {key}") from error

    @staticmethod
    def _required_decimal(item: Mapping[str, Any], key: str) -> Decimal:
        value = AkToolsClient._optional_decimal(item, key)
        if value is None:
            raise AkToolsApiError(f"AkTools K-line is missing {key}")
        return value

    @staticmethod
    def _optional_decimal(item: Mapping[str, Any], key: str) -> Decimal | None:
        value = item.get(key)
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise AkToolsApiError(f"AkTools K-line has an invalid {key}") from error
