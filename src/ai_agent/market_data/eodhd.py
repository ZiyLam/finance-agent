"""Read-only adapter for EODHD's documented historical-data and search APIs.

EODHD authenticates with an ``api_token`` query parameter.  This module keeps
the token in memory only and deliberately suppresses exception chains that can
contain the request URL.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


EODHD_API_BASE = "https://eodhd.com/api"
_PERIODS = {"d", "w", "m"}


class EODHDError(RuntimeError):
    """Base error for EODHD data reads; it never includes the API token."""


class EODHDApiError(EODHDError):
    """EODHD rejected a request or returned an unexpected response object."""


class EODHDRateLimitError(EODHDError):
    """A local quota guard rejected a request before it reached EODHD."""


class EODHDTransportError(EODHDError):
    """EODHD could not be reached or did not return valid JSON."""


@dataclass(frozen=True, slots=True)
class EODHDLimits:
    """Conservative protection for EODHD's documented free plan."""

    minimum_interval_seconds: float
    max_requests_per_day: int

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if self.max_requests_per_day < 1:
            raise ValueError("max_requests_per_day must be at least 1")


# EODHD documents 20 API calls/day for its free plan.  Its minute limit is
# plan-specific, so a 3-second spacing is a modest local anti-burst guard.
FREE_PLAN_LIMITS = EODHDLimits(3.0, 20)


@dataclass(frozen=True, slots=True)
class EODHDCandle:
    """One EODHD daily, weekly, or monthly OHLCV record."""

    date: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    adjusted_close: Decimal | None
    volume: Decimal | None


@dataclass(frozen=True, slots=True)
class EODHDSearchMatch:
    """One EODHD active-instrument search result."""

    code: str
    exchange: str
    name: str
    asset_type: str
    country: str | None
    currency: str | None

    @property
    def symbol(self) -> str:
        """The documented ``ticker`` form for EOD historical-data requests."""

        return f"{self.code}.{self.exchange}"


Transport = Callable[[str], bytes]


class _RateGuard:
    def __init__(
        self,
        limits: EODHDLimits,
        clock: Callable[[], float],
        current_date: Callable[[], date],
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._current_date = current_date
        self._last_request: float | None = None
        self._date = current_date()
        self._daily_count = 0

    def acquire(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            remaining = self._limits.minimum_interval_seconds - (now - self._last_request)
            if remaining > 0:
                raise EODHDRateLimitError(
                    f"Local EODHD interval limit; retry after {remaining:.1f} seconds"
                )
        today = self._current_date()
        if today != self._date:
            self._date, self._daily_count = today, 0
        if self._daily_count >= self._limits.max_requests_per_day:
            raise EODHDRateLimitError("Local EODHD daily request limit reached")
        self._last_request = now
        self._daily_count += 1


class EODHDClient:
    """Read EODHD end-of-day OHLCV history and active-instrument searches."""

    def __init__(
        self,
        api_token: str,
        *,
        limits: EODHDLimits = FREE_PLAN_LIMITS,
        timeout_seconds: float = 10.0,
        transport: Transport | None = None,
        clock: Callable[[], float] = monotonic,
        current_date: Callable[[], date] = date.today,
    ) -> None:
        if not api_token.strip():
            raise ValueError("EODHD API token cannot be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_token = api_token.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport
        self._guard = _RateGuard(limits, clock, current_date)

    def historical_candles(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        period: str = "d",
    ) -> tuple[EODHDCandle, ...]:
        """Read a date-bounded raw or adjusted OHLCV series for one EODHD symbol."""

        normalized_symbol = self._validate_symbol(symbol)
        normalized_period = self._validate_period(period)
        self._validate_dates(start_date, end_date)
        path = f"/eod/{quote(normalized_symbol, safe='.-_')}"
        payload = self._get_json(
            path,
            {"from": start_date, "to": end_date, "period": normalized_period, "fmt": "json"},
        )
        if not isinstance(payload, list):
            raise EODHDApiError("EODHD returned an unexpected historical-data response")
        return tuple(self._to_candle(item) for item in payload)

    def search(self, query: str, limit: int = 10) -> tuple[EODHDSearchMatch, ...]:
        """Search active global instruments and return a bounded result set."""

        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
            raise ValueError("EODHD search query must contain 1 to 100 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("EODHD search limit must be an integer between 1 and 20")
        path = f"/search/{quote(query.strip(), safe='')}"
        payload = self._get_json(path, {"limit": str(limit), "fmt": "json"})
        if not isinstance(payload, list):
            raise EODHDApiError("EODHD returned an unexpected search response")
        return tuple(self._to_search_match(item) for item in payload)

    def _get_json(self, path: str, parameters: Mapping[str, str]) -> Any:
        self._guard.acquire()
        query = urlencode({**parameters, "api_token": self._api_token})
        try:
            raw = self._transport(f"{EODHD_API_BASE}{path}?{query}")
        except (HTTPError, URLError, TimeoutError, OSError):
            # HTTPError includes the request URL, which includes EODHD's token.
            # Do not retain that exception chain in logs or tool responses.
            raise EODHDTransportError("Could not reach EODHD market-data service") from None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EODHDTransportError("EODHD returned an invalid JSON response") from error
        if isinstance(payload, Mapping) and any(key in payload for key in ("error", "message", "errors")):
            raise EODHDApiError("EODHD rejected the requested symbol, date range, or plan")
        return payload

    def _default_transport(self, url: str) -> bytes:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "finance-agent-financial-research/0.1"},
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            return response.read()

    @staticmethod
    def _validate_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
        if not 3 <= len(normalized) <= 64:
            raise ValueError("EODHD symbols must contain 3 to 64 characters")
        if "." not in normalized:
            raise ValueError("EODHD symbols must include an exchange suffix, such as AAPL.US")
        if any(not (character.isalnum() or character in ".-_") for character in normalized):
            raise ValueError("EODHD symbols may contain only letters, numbers, dot, hyphen, and underscore")
        return normalized

    @staticmethod
    def _validate_period(period: str) -> str:
        if not isinstance(period, str) or period not in _PERIODS:
            raise ValueError("EODHD period must be one of d, w, m")
        return period

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> None:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("EODHD dates must use YYYY-MM-DD") from error
        if start > end:
            raise ValueError("EODHD end_date must be on or after start_date")

    @classmethod
    def _to_candle(cls, item: Any) -> EODHDCandle:
        if not isinstance(item, Mapping):
            raise EODHDApiError("EODHD historical-data row is not an object")
        return EODHDCandle(
            date=cls._required_date(item, "date"),
            open_price=cls._required_decimal(item, "open"),
            high_price=cls._required_decimal(item, "high"),
            low_price=cls._required_decimal(item, "low"),
            close_price=cls._required_decimal(item, "close"),
            adjusted_close=cls._optional_decimal(item, "adjusted_close"),
            volume=cls._optional_decimal(item, "volume"),
        )

    @classmethod
    def _to_search_match(cls, item: Any) -> EODHDSearchMatch:
        if not isinstance(item, Mapping):
            raise EODHDApiError("EODHD search item is not an object")
        return EODHDSearchMatch(
            code=cls._required_text(item, "Code"),
            exchange=cls._required_text(item, "Exchange"),
            name=cls._required_text(item, "Name"),
            asset_type=cls._required_text(item, "Type"),
            country=cls._optional_text(item, "Country"),
            currency=cls._optional_text(item, "Currency"),
        )

    @staticmethod
    def _required_text(item: Mapping[str, Any], key: str) -> str:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise EODHDApiError(f"EODHD response is missing {key}")
        return value.strip()

    @staticmethod
    def _optional_text(item: Mapping[str, Any], key: str) -> str | None:
        value = item.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @classmethod
    def _required_date(cls, item: Mapping[str, Any], key: str) -> str:
        value = cls._required_text(item, key)
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise EODHDApiError(f"EODHD response has an invalid {key}") from error

    @classmethod
    def _required_decimal(cls, item: Mapping[str, Any], key: str) -> Decimal:
        value = cls._optional_decimal(item, key)
        if value is None:
            raise EODHDApiError(f"EODHD response is missing {key}")
        return value

    @staticmethod
    def _optional_decimal(item: Mapping[str, Any], key: str) -> Decimal | None:
        value = item.get(key)
        if value is None or str(value).strip().lower() in {"", "null", "none", "nan"}:
            return None
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise EODHDApiError(f"EODHD response has an invalid {key}") from error
        if not decimal_value.is_finite():
            raise EODHDApiError(f"EODHD response has a non-finite {key}")
        return decimal_value
