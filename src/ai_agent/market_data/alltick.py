"""Small, dependency-free HTTP client for the documented AllTick quote APIs.

The token is deliberately read from ``ALLTICK_API_TOKEN`` at runtime only.  It
is never written to a file, included in exceptions, or emitted by this module.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import IntEnum, StrEnum
import json
from os import getenv
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


STOCK_API_BASE = "https://quote.alltick.co/quote-stock-b-api"
OTHER_API_BASE = "https://quote.alltick.co/quote-b-api"


class AllTickError(RuntimeError):
    """Base error for a failed market-data request."""


class AllTickApiError(AllTickError):
    """An API response whose documented ``ret`` field is not 200."""

    def __init__(self, status: int, message: str, trace: str | None) -> None:
        self.status = status
        self.message = message
        self.trace = trace
        detail = f"AllTick API returned {status}: {message}"
        if trace:
            detail += f" (trace: {trace})"
        super().__init__(detail)


class AllTickRateLimitError(AllTickError):
    """The local guard rejected a request before it consumed provider quota."""


class AllTickTransportError(AllTickError):
    """The provider could not be reached or returned invalid JSON."""


class AllTickAssetClass(StrEnum):
    """AllTick uses one API family for stocks and another for other assets."""

    STOCK = "stock"
    OTHER = "other"


class AllTickKlineType(IntEnum):
    MINUTE_1 = 1
    MINUTE_5 = 2
    MINUTE_15 = 3
    MINUTE_30 = 4
    HOUR_1 = 5
    HOUR_2 = 6
    HOUR_4 = 7
    DAY_1 = 8
    WEEK_1 = 9
    MONTH_1 = 10


@dataclass(frozen=True, slots=True)
class AllTickLimits:
    """Quota protection values for one process; configure a higher plan explicitly."""

    minimum_interval_seconds: float
    max_requests_per_minute: int
    max_requests_per_day: int
    max_symbols_per_latest_quote: int

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if min(
            self.max_requests_per_minute,
            self.max_requests_per_day,
            self.max_symbols_per_latest_quote,
        ) < 1:
            raise ValueError("AllTick limit counts must be at least 1")


# Conservative default from the documented free HTTP limits. A trial token may
# grant more capacity, but it must be opted into only after verifying its plan.
FREE_PLAN_LIMITS = AllTickLimits(
    minimum_interval_seconds=10.0,
    max_requests_per_minute=10,
    max_requests_per_day=1_000,
    max_symbols_per_latest_quote=5,
)


@dataclass(frozen=True, slots=True)
class AllTickQuote:
    code: str
    sequence: str
    timestamp_ms: int
    price: Decimal
    volume: Decimal
    turnover: Decimal
    trade_direction: int


@dataclass(frozen=True, slots=True)
class AllTickCandle:
    timestamp_seconds: int
    open_price: Decimal
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal
    volume: Decimal
    turnover: Decimal


Transport = Callable[[str], bytes]


class _RequestLimiter:
    def __init__(
        self,
        limits: AllTickLimits,
        clock: Callable[[], float],
        current_date: Callable[[], date],
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._current_date = current_date
        self._recent: deque[float] = deque()
        self._last_request: float | None = None
        self._day = current_date()
        self._daily_count = 0

    def acquire(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            remaining = self._limits.minimum_interval_seconds - (now - self._last_request)
            if remaining > 0:
                raise AllTickRateLimitError(
                    f"Local AllTick interval limit; retry after {remaining:.1f} seconds"
                )

        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self._limits.max_requests_per_minute:
            raise AllTickRateLimitError("Local AllTick one-minute request limit reached")

        today = self._current_date()
        if today != self._day:
            self._day = today
            self._daily_count = 0
        if self._daily_count >= self._limits.max_requests_per_day:
            raise AllTickRateLimitError("Local AllTick daily request limit reached")

        self._last_request = now
        self._recent.append(now)
        self._daily_count += 1


class AllTickClient:
    """Read latest trades and historical candles using documented HTTP endpoints."""

    def __init__(
        self,
        api_token: str,
        *,
        limits: AllTickLimits = FREE_PLAN_LIMITS,
        timeout_seconds: float = 10.0,
        transport: Transport | None = None,
        clock: Callable[[], float] = monotonic,
        current_date: Callable[[], date] = date.today,
    ) -> None:
        if not api_token.strip():
            raise ValueError("AllTick API token cannot be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_token = api_token.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport
        self._limiter = _RequestLimiter(limits, clock, current_date)
        self._limits = limits

    @classmethod
    def from_environment(cls, **kwargs: Any) -> "AllTickClient":
        token = getenv("ALLTICK_API_TOKEN")
        if not token:
            raise ValueError("Set ALLTICK_API_TOKEN before enabling AllTick market data")
        return cls(token, **kwargs)

    def latest_quotes(
        self,
        codes: Sequence[str],
        *,
        asset_class: AllTickAssetClass = AllTickAssetClass.STOCK,
    ) -> tuple[AllTickQuote, ...]:
        normalized_codes = self._validate_codes(codes)
        if len(normalized_codes) > self._limits.max_symbols_per_latest_quote:
            raise ValueError(
                "Too many symbols for this AllTick plan; "
                f"maximum is {self._limits.max_symbols_per_latest_quote}"
            )

        payload = {
            "trace": str(uuid4()),
            "data": {"symbol_list": [{"code": code} for code in normalized_codes]},
        }
        data = self._get(asset_class, "/trade-tick", payload)
        tick_list = self._required_list(data, "tick_list")
        return tuple(self._to_quote(item) for item in tick_list)

    def historical_candles(
        self,
        code: str,
        *,
        asset_class: AllTickAssetClass = AllTickAssetClass.STOCK,
        kline_type: AllTickKlineType = AllTickKlineType.DAY_1,
        count: int = 30,
        timestamp_end: int = 0,
        adjust_type: int = 0,
    ) -> tuple[AllTickCandle, ...]:
        normalized_code = self._validate_codes((code,))[0]
        if not 1 <= count <= 500:
            raise ValueError("AllTick kline count must be between 1 and 500")
        if timestamp_end < 0:
            raise ValueError("timestamp_end cannot be negative")
        if adjust_type != 0:
            raise ValueError("AllTick currently documents only adjust_type=0")
        if asset_class is AllTickAssetClass.STOCK and kline_type in {
            AllTickKlineType.HOUR_2,
            AllTickKlineType.HOUR_4,
        }:
            raise ValueError("AllTick does not support 2-hour or 4-hour stock candles")
        if asset_class is AllTickAssetClass.STOCK and timestamp_end != 0:
            raise ValueError("AllTick documents timestamp_end only for non-stock candles")

        payload = {
            "trace": str(uuid4()),
            "data": {
                "code": normalized_code,
                "kline_type": int(kline_type),
                "kline_timestamp_end": timestamp_end,
                "query_kline_num": count,
                "adjust_type": adjust_type,
            },
        }
        data = self._get(asset_class, "/kline", payload)
        candle_list = self._required_list(data, "kline_list")
        return tuple(self._to_candle(item) for item in candle_list)

    def _get(
        self,
        asset_class: AllTickAssetClass,
        path: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._limiter.acquire()
        base_url = STOCK_API_BASE if asset_class is AllTickAssetClass.STOCK else OTHER_API_BASE
        query = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        url = f"{base_url}{path}?{urlencode({'token': self._api_token, 'query': query})}"
        try:
            raw = self._transport(url)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            # HTTPError can embed the request URL, which contains the token by
            # AllTick's documented design. Do not retain it in an exception chain.
            del error
            raise AllTickTransportError("Could not reach AllTick market-data service") from None

        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AllTickTransportError("AllTick returned an invalid JSON response") from error
        if not isinstance(response, Mapping):
            raise AllTickTransportError("AllTick returned a non-object JSON response")

        status = response.get("ret")
        message = response.get("msg", "unknown error")
        trace = response.get("trace")
        if not isinstance(status, int):
            raise AllTickTransportError("AllTick response is missing its integer ret field")
        if status != 200:
            raise AllTickApiError(status, str(message), str(trace) if trace else None)
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise AllTickTransportError("AllTick successful response is missing data")
        return data

    def _default_transport(self, url: str) -> bytes:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=self._timeout_seconds) as response:
            return response.read()

    @staticmethod
    def _validate_codes(codes: Sequence[str]) -> tuple[str, ...]:
        if not codes:
            raise ValueError("At least one AllTick product code is required")
        normalized = tuple(code.strip() for code in codes)
        if any(not code for code in normalized):
            raise ValueError("AllTick product codes cannot be blank")
        return normalized

    @staticmethod
    def _required_list(data: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
        value = data.get(key)
        if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
            raise AllTickTransportError(f"AllTick response is missing its {key} list")
        return value

    @classmethod
    def _to_quote(cls, item: Mapping[str, Any]) -> AllTickQuote:
        return AllTickQuote(
            code=cls._required_text(item, "code"),
            sequence=cls._required_text(item, "seq"),
            timestamp_ms=cls._required_int(item, "tick_time"),
            price=cls._required_decimal(item, "price"),
            volume=cls._required_decimal(item, "volume"),
            turnover=cls._required_decimal(item, "turnover"),
            trade_direction=cls._required_int(item, "trade_direction"),
        )

    @classmethod
    def _to_candle(cls, item: Mapping[str, Any]) -> AllTickCandle:
        return AllTickCandle(
            timestamp_seconds=cls._required_int(item, "timestamp"),
            open_price=cls._required_decimal(item, "open_price"),
            close_price=cls._required_decimal(item, "close_price"),
            high_price=cls._required_decimal(item, "high_price"),
            low_price=cls._required_decimal(item, "low_price"),
            volume=cls._required_decimal(item, "volume"),
            turnover=cls._required_decimal(item, "turnover"),
        )

    @staticmethod
    def _required_text(item: Mapping[str, Any], key: str) -> str:
        value = item.get(key)
        if not isinstance(value, str) or not value:
            raise AllTickTransportError(f"AllTick item is missing {key}")
        return value

    @staticmethod
    def _required_int(item: Mapping[str, Any], key: str) -> int:
        value = item.get(key)
        try:
            return int(str(value))
        except (TypeError, ValueError) as error:
            raise AllTickTransportError(f"AllTick item has an invalid {key}") from error

    @staticmethod
    def _required_decimal(item: Mapping[str, Any], key: str) -> Decimal:
        value = item.get(key)
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise AllTickTransportError(f"AllTick item has an invalid {key}") from error
