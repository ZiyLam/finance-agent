"""Read-only wrapper for documented 必盈 API沪深 A 股 endpoints."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


BIYING_API_BASE = "https://api.biyingapi.com"


class BiyingError(RuntimeError):
    """Base error whose text never includes the certificate or request URL."""


class BiyingApiError(BiyingError):
    """The API returned a response that does not match the documented payload."""


class BiyingRateLimitError(BiyingError):
    """Local quota protection rejected the request before calling the service."""


class BiyingTransportError(BiyingError):
    """The API could not be reached or returned malformed JSON."""


@dataclass(frozen=True, slots=True)
class BiyingLimits:
    minimum_interval_seconds: float
    max_requests_per_minute: int
    max_requests_per_day: int


# The documentation lists up to 300 calls/minute for an experience certificate,
# while the documentation centre's free tier overview lists 100 calls/day. Keep
# the daily guard conservative until the certificate plan is explicitly known.
FREE_PLAN_LIMITS = BiyingLimits(0.2, 300, 100)


@dataclass(frozen=True, slots=True)
class BiyingStock:
    code: str
    name: str
    exchange: str


@dataclass(frozen=True, slots=True)
class BiyingQuote:
    code: str
    price: Decimal
    updated_at: str | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    previous_close: Decimal | None
    change_percent: Decimal | None
    change_amount: Decimal | None
    volume_lots: Decimal | None
    turnover: Decimal | None
    turnover_rate_percent: Decimal | None
    dynamic_pe: Decimal | None
    pb: Decimal | None
    total_market_value: Decimal | None
    circulating_market_value: Decimal | None


Transport = Callable[[str], bytes]


class _RateGuard:
    def __init__(self, limits: BiyingLimits, clock: Callable[[], float], today: Callable[[], date]) -> None:
        self._limits = limits
        self._clock = clock
        self._today = today
        self._recent: deque[float] = deque()
        self._last: float | None = None
        self._date = today()
        self._daily_count = 0

    def acquire(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._limits.minimum_interval_seconds:
            raise BiyingRateLimitError("Local 必盈 API interval limit reached")
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self._limits.max_requests_per_minute:
            raise BiyingRateLimitError("Local 必盈 API one-minute limit reached")
        current_date = self._today()
        if current_date != self._date:
            self._date, self._daily_count = current_date, 0
        if self._daily_count >= self._limits.max_requests_per_day:
            raise BiyingRateLimitError("Local 必盈 API daily limit reached")
        self._last = now
        self._recent.append(now)
        self._daily_count += 1


class BiyingClient:
    """Fetch stock codes and documented public real-time A-share data."""

    def __init__(
        self,
        licence: str,
        *,
        limits: BiyingLimits = FREE_PLAN_LIMITS,
        timeout_seconds: float = 10.0,
        transport: Transport | None = None,
        clock: Callable[[], float] = monotonic,
        current_date: Callable[[], date] = date.today,
    ) -> None:
        if not licence.strip():
            raise ValueError("必盈 API certificate cannot be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._licence = licence.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport
        self._guard = _RateGuard(limits, clock, current_date)

    def find_stocks(self, query: str, limit: int = 10) -> tuple[BiyingStock, ...]:
        """Search the full documented stock list but return a bounded result set."""

        if not query.strip():
            raise ValueError("Stock search query cannot be blank")
        if not 1 <= limit <= 20:
            raise ValueError("Stock search limit must be between 1 and 20")
        normalized_query = query.strip().lower()
        stocks = self._get_stock_list()
        matches = [
            stock
            for stock in stocks
            if normalized_query in stock.code.lower() or normalized_query in stock.name.lower()
        ]
        return tuple(matches[:limit])

    def realtime_quote(self, code: str) -> BiyingQuote:
        normalized_code = self._validate_code(code)
        payload = self._get_json(f"/hsrl/ssjy/{normalized_code}/{quote(self._licence, safe='')}")
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], Mapping):
            raise BiyingApiError("必盈 API returned an unexpected real-time quote payload")
        return self._to_quote(normalized_code, payload[0])

    def _get_stock_list(self) -> tuple[BiyingStock, ...]:
        payload = self._get_json(f"/hslt/list/{quote(self._licence, safe='')}")
        if not isinstance(payload, list):
            raise BiyingApiError("必盈 API returned an unexpected stock-list payload")
        stocks: list[BiyingStock] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise BiyingApiError("必盈 API stock-list item is invalid")
            code, name, exchange = item.get("dm"), item.get("mc"), item.get("jys")
            if not all(isinstance(value, str) and value for value in (code, name, exchange)):
                raise BiyingApiError("必盈 API stock-list item is incomplete")
            stocks.append(BiyingStock(code=code, name=name, exchange=exchange))
        return tuple(stocks)

    def _get_json(self, path: str) -> Any:
        self._guard.acquire()
        try:
            raw = self._transport(f"{BIYING_API_BASE}{path}")
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            # HTTP errors may retain the URL, whose path carries the certificate.
            del error
            raise BiyingTransportError("Could not reach 必盈 API") from None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BiyingTransportError("必盈 API returned invalid JSON") from error

    def _default_transport(self, url: str) -> bytes:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=self._timeout_seconds) as response:
            return response.read()

    @staticmethod
    def _validate_code(code: str) -> str:
        normalized = code.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("必盈 API A-share codes must be six digits")
        return normalized

    @classmethod
    def _to_quote(cls, code: str, payload: Mapping[str, Any]) -> BiyingQuote:
        price = cls._decimal(payload, "p")
        if price is None:
            raise BiyingApiError("必盈 API quote is missing current price")
        timestamp = payload.get("t")
        return BiyingQuote(
            code=code,
            price=price,
            updated_at=timestamp if isinstance(timestamp, str) else None,
            open_price=cls._decimal(payload, "o"),
            high_price=cls._decimal(payload, "h"),
            low_price=cls._decimal(payload, "l"),
            previous_close=cls._decimal(payload, "yc"),
            change_percent=cls._decimal(payload, "pc"),
            change_amount=cls._decimal(payload, "ud"),
            volume_lots=cls._decimal(payload, "v"),
            turnover=cls._decimal(payload, "cje"),
            turnover_rate_percent=cls._decimal(payload, "hs"),
            dynamic_pe=cls._decimal(payload, "pe"),
            pb=cls._decimal(payload, "sjl"),
            total_market_value=cls._decimal(payload, "sz"),
            circulating_market_value=cls._decimal(payload, "lt"),
        )

    @staticmethod
    def _decimal(payload: Mapping[str, Any], key: str) -> Decimal | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise BiyingApiError(f"必盈 API returned invalid numeric field '{key}'") from error
