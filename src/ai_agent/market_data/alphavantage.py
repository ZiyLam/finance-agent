"""Read-only adapter for the documented Alpha Vantage stock endpoints.

The API key is held only in memory.  It is URL encoded for the provider's
documented query-string authentication scheme and is never included in an
exception or return value.
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
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ALPHAVANTAGE_API_BASE = "https://www.alphavantage.co/query"


class AlphaVantageError(RuntimeError):
    """Base error for an Alpha Vantage request; it never contains the API key."""


class AlphaVantageApiError(AlphaVantageError):
    """The provider returned an error payload or an unexpected response shape."""


class AlphaVantageRateLimitError(AlphaVantageError):
    """A local or provider quota guard rejected the request."""


class AlphaVantageTransportError(AlphaVantageError):
    """The provider could not be reached or did not return JSON."""


@dataclass(frozen=True, slots=True)
class AlphaVantageLimits:
    """Conservative local limits for the documented free API-key allowance."""

    minimum_interval_seconds: float
    max_requests_per_day: int

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if self.max_requests_per_day < 1:
            raise ValueError("max_requests_per_day must be at least 1")


# Alpha Vantage documents up to 25 requests per day for the free service.  A
# 15-second spacing is deliberately cautious and prevents bursty use by a model.
FREE_PLAN_LIMITS = AlphaVantageLimits(15.0, 25)


@dataclass(frozen=True, slots=True)
class AlphaVantageCandle:
    """One raw (as-traded), daily global-equity OHLCV observation."""

    date: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class AlphaVantageQuote:
    """A latest-price endpoint observation, normally end-of-day on free access."""

    symbol: str
    latest_trading_day: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    price: Decimal
    volume: Decimal
    previous_close: Decimal
    change: Decimal
    change_percent: Decimal


@dataclass(frozen=True, slots=True)
class AlphaVantageSymbol:
    """A bounded symbol-search match returned by Alpha Vantage."""

    symbol: str
    name: str
    asset_type: str
    region: str
    currency: str
    match_score: Decimal


Transport = Callable[[str], bytes]


class _RateGuard:
    def __init__(
        self,
        limits: AlphaVantageLimits,
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
                raise AlphaVantageRateLimitError(
                    f"Local Alpha Vantage interval limit; retry after {remaining:.1f} seconds"
                )
        today = self._current_date()
        if today != self._date:
            self._date, self._daily_count = today, 0
        if self._daily_count >= self._limits.max_requests_per_day:
            raise AlphaVantageRateLimitError("Local Alpha Vantage daily request limit reached")
        self._last_request = now
        self._daily_count += 1


class AlphaVantageClient:
    """Read Alpha Vantage's daily stock, quote, and symbol-search endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        limits: AlphaVantageLimits = FREE_PLAN_LIMITS,
        timeout_seconds: float = 10.0,
        transport: Transport | None = None,
        clock: Callable[[], float] = monotonic,
        current_date: Callable[[], date] = date.today,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Alpha Vantage API key cannot be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport
        self._guard = _RateGuard(limits, clock, current_date)

    def daily_candles(self, symbol: str) -> tuple[AlphaVantageCandle, ...]:
        """Return up to the latest 100 raw daily OHLCV rows for one global symbol."""

        payload = self._get_json(
            {"function": "TIME_SERIES_DAILY", "symbol": self._validate_symbol(symbol), "outputsize": "compact"}
        )
        time_series = payload.get("Time Series (Daily)")
        if not isinstance(time_series, Mapping):
            raise AlphaVantageApiError("Alpha Vantage returned no daily time series for this symbol")
        candles = [self._to_candle(day, row) for day, row in time_series.items()]
        return tuple(sorted(candles, key=lambda candle: candle.date))

    def global_quote(self, symbol: str) -> AlphaVantageQuote:
        """Return one latest-price response; free access is normally end-of-day."""

        payload = self._get_json(
            {"function": "GLOBAL_QUOTE", "symbol": self._validate_symbol(symbol)}
        )
        quote = payload.get("Global Quote")
        if not isinstance(quote, Mapping) or not quote:
            raise AlphaVantageApiError("Alpha Vantage returned no quote for this symbol")
        return AlphaVantageQuote(
            symbol=self._required_text(quote, "01. symbol"),
            open_price=self._required_decimal(quote, "02. open"),
            high_price=self._required_decimal(quote, "03. high"),
            low_price=self._required_decimal(quote, "04. low"),
            price=self._required_decimal(quote, "05. price"),
            volume=self._required_decimal(quote, "06. volume"),
            latest_trading_day=self._required_date(quote, "07. latest trading day"),
            previous_close=self._required_decimal(quote, "08. previous close"),
            change=self._required_decimal(quote, "09. change"),
            change_percent=self._required_percent(quote, "10. change percent"),
        )

    def symbol_search(self, keywords: str, limit: int = 10) -> tuple[AlphaVantageSymbol, ...]:
        """Search symbols globally and return only the requested leading matches."""

        if not isinstance(keywords, str) or not 1 <= len(keywords.strip()) <= 100:
            raise ValueError("Alpha Vantage search keywords must contain 1 to 100 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("Alpha Vantage search limit must be an integer between 1 and 20")
        payload = self._get_json({"function": "SYMBOL_SEARCH", "keywords": keywords.strip()})
        matches = payload.get("bestMatches")
        if not isinstance(matches, list) or not all(isinstance(item, Mapping) for item in matches):
            raise AlphaVantageApiError("Alpha Vantage returned an unexpected symbol-search response")
        return tuple(self._to_symbol(item) for item in matches[:limit])

    def _get_json(self, parameters: Mapping[str, str]) -> Mapping[str, Any]:
        self._guard.acquire()
        query = urlencode({**parameters, "apikey": self._api_key})
        try:
            raw = self._transport(f"{ALPHAVANTAGE_API_BASE}?{query}")
        except (HTTPError, URLError, TimeoutError, OSError):
            # Request URLs contain the provider-required query-string key.  Do
            # not retain an exception chain that might expose it in diagnostics.
            raise AlphaVantageTransportError("Could not reach Alpha Vantage market-data service") from None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AlphaVantageTransportError("Alpha Vantage returned an invalid JSON response") from error
        if not isinstance(payload, Mapping):
            raise AlphaVantageTransportError("Alpha Vantage returned a non-object JSON response")
        if "Note" in payload or "Information" in payload:
            raise AlphaVantageRateLimitError(
                "Alpha Vantage rejected the request because of a provider rate or plan limit"
            )
        if "Error Message" in payload:
            raise AlphaVantageApiError("Alpha Vantage rejected the requested function or symbol")
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
        if not 1 <= len(normalized) <= 64:
            raise ValueError("Alpha Vantage symbols must contain 1 to 64 characters")
        if any(not (character.isalnum() or character in ".-_") for character in normalized):
            raise ValueError("Alpha Vantage symbols may contain only letters, numbers, dot, hyphen, and underscore")
        return normalized

    @classmethod
    def _to_candle(cls, day: Any, row: Any) -> AlphaVantageCandle:
        if not isinstance(row, Mapping):
            raise AlphaVantageApiError("Alpha Vantage daily row is not an object")
        try:
            normalized_day = datetime.strptime(str(day), "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise AlphaVantageApiError("Alpha Vantage daily row has an invalid date") from error
        return AlphaVantageCandle(
            date=normalized_day,
            open_price=cls._required_decimal(row, "1. open"),
            high_price=cls._required_decimal(row, "2. high"),
            low_price=cls._required_decimal(row, "3. low"),
            close_price=cls._required_decimal(row, "4. close"),
            volume=cls._required_decimal(row, "5. volume"),
        )

    @classmethod
    def _to_symbol(cls, item: Mapping[str, Any]) -> AlphaVantageSymbol:
        return AlphaVantageSymbol(
            symbol=cls._required_text(item, "1. symbol"),
            name=cls._required_text(item, "2. name"),
            asset_type=cls._required_text(item, "3. type"),
            region=cls._required_text(item, "4. region"),
            currency=cls._required_text(item, "8. currency"),
            match_score=cls._required_decimal(item, "9. matchScore"),
        )

    @staticmethod
    def _required_text(item: Mapping[str, Any], key: str) -> str:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AlphaVantageApiError(f"Alpha Vantage response is missing {key}")
        return value.strip()

    @classmethod
    def _required_date(cls, item: Mapping[str, Any], key: str) -> str:
        value = cls._required_text(item, key)
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise AlphaVantageApiError(f"Alpha Vantage response has an invalid {key}") from error

    @classmethod
    def _required_percent(cls, item: Mapping[str, Any], key: str) -> Decimal:
        value = cls._required_text(item, key).removesuffix("%").strip()
        return cls._to_decimal(value, key)

    @classmethod
    def _required_decimal(cls, item: Mapping[str, Any], key: str) -> Decimal:
        return cls._to_decimal(item.get(key), key)

    @staticmethod
    def _to_decimal(value: Any, key: str) -> Decimal:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise AlphaVantageApiError(f"Alpha Vantage response has an invalid {key}") from error
        if not decimal_value.is_finite():
            raise AlphaVantageApiError(f"Alpha Vantage response has a non-finite {key}")
        return decimal_value
