"""Bounded, read-only adapter for the documented 智兔数服 market APIs.

智兔数服 authenticates with a ``token`` query parameter.  The token is kept
only in memory and is never included in an exception, tool result, or log
event.  The public documentation exposes no pagination or row-limit parameter
for historical requests, so this adapter deliberately constrains the requested
date window before making a network call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re
from threading import RLock
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ZHITU_API_BASE = "https://api.zhituapi.com"
_SYMBOL_PATTERN = re.compile(r"^\d{6}\.(?:SH|SZ)$")
_MAX_HISTORY_DAYS = 366


class ZhituError(RuntimeError):
    """Base safe error for 智兔数服 data reads."""


class ZhituApiError(ZhituError):
    """智兔数服 rejected a request or returned an unexpected payload."""


class ZhituRateLimitError(ZhituError):
    """A local guard rejected an unsafe request burst."""


class ZhituTransportError(ZhituError):
    """智兔数服 could not be reached or did not return JSON."""


@dataclass(frozen=True, slots=True)
class ZhituLimits:
    """Conservative local guard for the lowest documented provider plan."""

    minimum_interval_seconds: float
    max_requests_per_minute: int

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if self.max_requests_per_minute < 1:
            raise ValueError("max_requests_per_minute must be at least 1")


# 官网各已发布接口页面均标注包量版为 300 次/分钟；用户套餐未知时，
# 以此作为不会主动超额的本地上限。
DOCUMENTED_MINIMUM_PLAN_LIMITS = ZhituLimits(0.2, 300)


@dataclass(frozen=True, slots=True)
class ZhituCandle:
    """One normalized daily OHLCV record from 智兔数服."""

    date: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    previous_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None


@dataclass(frozen=True, slots=True)
class ZhituQuote:
    """One normalized provider quote snapshot."""

    symbol: str
    timestamp: str | None
    last_price: Decimal
    previous_close: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None


Transport = Callable[[str], bytes]


class _RateGuard:
    """Reject locally unsafe bursts without sleeping a Web request thread."""

    def __init__(self, limits: ZhituLimits, clock: Callable[[], float]) -> None:
        self._limits = limits
        self._clock = clock
        self._last_request: float | None = None
        self._minute_started_at: float | None = None
        self._minute_count = 0
        self._lock = RLock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request is not None:
                remaining = self._limits.minimum_interval_seconds - (now - self._last_request)
                if remaining > 0:
                    raise ZhituRateLimitError("Local 智兔数服 interval limit reached")
            if self._minute_started_at is None or now - self._minute_started_at >= 60:
                self._minute_started_at, self._minute_count = now, 0
            if self._minute_count >= self._limits.max_requests_per_minute:
                raise ZhituRateLimitError("Local 智兔数服 one-minute request limit reached")
            self._last_request = now
            self._minute_count += 1


class ZhituClient:
    """Read documented A-share and index quote or daily-history endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        limits: ZhituLimits = DOCUMENTED_MINIMUM_PLAN_LIMITS,
        timeout_seconds: float = 4.0,
        transport: Transport | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("智兔数服 API key cannot be blank")
        if timeout_seconds <= 0:
            raise ValueError("智兔数服 timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport
        self._guard = _RateGuard(limits, clock)

    def index_daily_candles(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int = 120,
    ) -> tuple[ZhituCandle, ...]:
        """Read a bounded daily series from ``/hz/history/fsjy``."""

        return self._daily_candles(
            "/hz/history/fsjy/{symbol}/d",
            symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    def stock_daily_candles(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int = 120,
    ) -> tuple[ZhituCandle, ...]:
        """Read a bounded unadjusted daily A-share series from ``/hs/history``."""

        return self._daily_candles(
            "/hs/history/{symbol}/d/n",
            symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    def index_quote(self, symbol: str) -> ZhituQuote:
        """Read one documented 沪深指数 real-time quote snapshot."""

        normalized = self._validate_symbol(symbol)
        payload = self._get_json(f"/hz/real/ssjy/{quote(normalized, safe='.')}")
        return self._to_quote(normalized, payload)

    def stock_quote(self, symbol: str) -> ZhituQuote:
        """Read one documented 沪深A股 real-time quote snapshot."""

        normalized = self._validate_symbol(symbol)
        code = normalized.split(".", 1)[0]
        payload = self._get_json(f"/hs/real/ssjy/{quote(code, safe='')}")
        return self._to_quote(normalized, payload)

    def _daily_candles(
        self,
        route: str,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int,
    ) -> tuple[ZhituCandle, ...]:
        normalized = self._validate_symbol(symbol)
        start, end = self._validate_dates(start_date, end_date)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
            raise ValueError("智兔数服 candle limit must be an integer between 1 and 120")
        path = route.format(symbol=quote(normalized, safe="."))
        payload = self._get_json(
            path,
            {"st": start.strftime("%Y%m%d"), "et": end.strftime("%Y%m%d")},
        )
        if not isinstance(payload, list):
            raise ZhituApiError("智兔数服 returned an unexpected historical-data response")
        candles = sorted((self._to_candle(row) for row in payload), key=lambda candle: candle.date)
        return tuple(candles[-limit:])

    def _get_json(self, path: str, parameters: Mapping[str, str] | None = None) -> Any:
        self._guard.acquire()
        query = urlencode({**(parameters or {}), "token": self._api_key})
        try:
            raw = self._transport(f"{ZHITU_API_BASE}{path}?{query}")
        except (HTTPError, URLError, TimeoutError, OSError):
            # HTTPError can include the full token-bearing URL.  Never retain it.
            raise ZhituTransportError("Could not reach 智兔数服 market-data service") from None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ZhituTransportError("智兔数服 returned an invalid JSON response") from None
        if isinstance(payload, Mapping) and any(key in payload for key in ("error", "message", "msg", "code")):
            raise ZhituApiError("智兔数服 rejected the requested symbol, date range, or plan")
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
        if not _SYMBOL_PATTERN.fullmatch(normalized):
            raise ValueError("智兔数服 symbols must use six digits plus .SH or .SZ, such as 000905.SH")
        return normalized

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> tuple[date, date]:
        try:
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        except (TypeError, ValueError) as error:
            raise ValueError("智兔数服 dates must use YYYY-MM-DD") from error
        if start > end:
            raise ValueError("智兔数服 end_date must be on or after start_date")
        if (end - start).days > _MAX_HISTORY_DAYS:
            raise ValueError("智兔数服 history range must not exceed 366 days")
        return start, end

    @classmethod
    def _to_candle(cls, value: object) -> ZhituCandle:
        if not isinstance(value, Mapping):
            raise ZhituApiError("智兔数服 historical-data row is not an object")
        return ZhituCandle(
            date=cls._date(value, "t"),
            open_price=cls._required_decimal(value, "o"),
            high_price=cls._required_decimal(value, "h"),
            low_price=cls._required_decimal(value, "l"),
            close_price=cls._required_decimal(value, "c"),
            previous_close=cls._optional_decimal(value, "pc"),
            volume=cls._optional_decimal(value, "v"),
            amount=cls._optional_decimal(value, "a"),
        )

    @classmethod
    def _to_quote(cls, symbol: str, value: object) -> ZhituQuote:
        if not isinstance(value, Mapping):
            raise ZhituApiError("智兔数服 quote response is not an object")
        timestamp = value.get("t")
        return ZhituQuote(
            symbol=symbol,
            timestamp=timestamp.strip() if isinstance(timestamp, str) and timestamp.strip() else None,
            last_price=cls._required_decimal(value, "p"),
            previous_close=cls._optional_decimal(value, "pc"),
            open_price=cls._optional_decimal(value, "o"),
            high_price=cls._optional_decimal(value, "h"),
            low_price=cls._optional_decimal(value, "l"),
            volume=cls._optional_decimal(value, "v"),
            amount=cls._optional_decimal(value, "cje"),
            change=cls._optional_decimal(value, "ud"),
            change_percent=cls._optional_decimal(value, "zf"),
        )

    @staticmethod
    def _date(value: Mapping[str, object], key: str) -> str:
        raw = value.get(key)
        if not isinstance(raw, str):
            raise ZhituApiError(f"智兔数服 response is missing {key}")
        digits = "".join(re.findall(r"\d", raw))
        if len(digits) < 8:
            raise ZhituApiError(f"智兔数服 response has an invalid {key}")
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()
        except ValueError as error:
            raise ZhituApiError(f"智兔数服 response has an invalid {key}") from error

    @classmethod
    def _required_decimal(cls, value: Mapping[str, object], key: str) -> Decimal:
        result = cls._optional_decimal(value, key)
        if result is None:
            raise ZhituApiError(f"智兔数服 response is missing {key}")
        return result

    @staticmethod
    def _optional_decimal(value: Mapping[str, object], key: str) -> Decimal | None:
        raw = value.get(key)
        if raw is None or str(raw).strip().lower() in {"", "null", "none", "nan"}:
            return None
        try:
            result = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            raise ZhituApiError(f"智兔数服 response has an invalid {key}") from None
        if not result.is_finite():
            raise ZhituApiError(f"智兔数服 response has an invalid {key}")
        return result
