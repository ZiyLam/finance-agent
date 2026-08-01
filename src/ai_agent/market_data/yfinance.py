"""Read-only adapter for yfinance historical market data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from importlib import import_module
from io import StringIO
from math import isnan
from os import getenv
from time import monotonic
from typing import Any


class YFinanceError(RuntimeError):
    """Base error for a yfinance market-data request."""


class YFinanceApiError(YFinanceError):
    """yfinance returned a dataframe whose rows do not match expected OHLCV data."""


class YFinanceDependencyError(YFinanceError):
    """The yfinance Python package is not installed."""


class YFinanceRateLimitError(YFinanceError):
    """The local guard rejected a request before it reached Yahoo Finance."""


class YFinanceTransportError(YFinanceError):
    """Yahoo Finance could not be reached through yfinance."""


@dataclass(frozen=True, slots=True)
class YFinanceLimits:
    """Conservative per-process guard for Yahoo's personal-use data service."""

    minimum_interval_seconds: float
    max_requests_per_day: int

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if self.max_requests_per_day < 1:
            raise ValueError("max_requests_per_day must be at least 1")


DEFAULT_YFINANCE_LIMITS = YFinanceLimits(0.5, 1_000)


@dataclass(frozen=True, slots=True)
class YFinanceCandle:
    """One Yahoo Finance historical OHLCV observation."""

    date: str
    open_price: Decimal
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal
    adjusted_close: Decimal | None
    volume: Decimal | None


_INTERVALS = {"1d", "1wk", "1mo"}


class _RateGuard:
    def __init__(
        self,
        limits: YFinanceLimits,
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
                raise YFinanceRateLimitError(
                    f"Local yfinance interval limit; retry after {remaining:.1f} seconds"
                )
        today = self._current_date()
        if today != self._date:
            self._date, self._daily_count = today, 0
        if self._daily_count >= self._limits.max_requests_per_day:
            raise YFinanceRateLimitError("Local yfinance daily request limit reached")
        self._last_request = now
        self._daily_count += 1


class YFinanceClient:
    """Retrieve a bounded single-symbol history through ``yfinance.Ticker.history``."""

    def __init__(
        self,
        *,
        limits: YFinanceLimits = DEFAULT_YFINANCE_LIMITS,
        api: Any | None = None,
        cache_directory: str | None = None,
        timeout_seconds: float = 8.0,
        clock: Callable[[], float] = monotonic,
        current_date: Callable[[], date] = date.today,
    ) -> None:
        self._api = api
        self._cache_directory = cache_directory or getenv("YFINANCE_CACHE_DIR")
        if timeout_seconds <= 0:
            raise ValueError("yfinance timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._guard = _RateGuard(limits, clock, current_date)

    def historical_candles(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        auto_adjust: bool = True,
    ) -> tuple[YFinanceCandle, ...]:
        """Fetch historical daily, weekly, or monthly OHLCV data for a Yahoo symbol.

        yfinance follows Yahoo Finance's ``end`` convention: ``end_date`` is
        exclusive. The caller should supply the day after the final daily bar
        desired when querying daily history.
        """

        normalized_symbol = self._validate_symbol(symbol)
        normalized_interval = self._validate_interval(interval)
        self._validate_dates(start_date, end_date)
        if not isinstance(auto_adjust, bool):
            raise ValueError("yfinance auto_adjust must be a boolean")
        self._guard.acquire()
        try:
            api = self._get_api()
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                if self._cache_directory:
                    api.set_tz_cache_location(self._cache_directory)
                history = api.Ticker(normalized_symbol).history(
                    start=start_date,
                    end=end_date,
                    interval=normalized_interval,
                    auto_adjust=auto_adjust,
                    actions=False,
                    timeout=self._timeout_seconds,
                )
        except Exception as error:
            raise YFinanceTransportError("Could not retrieve Yahoo Finance historical data") from error
        if not hasattr(history, "empty") or not hasattr(history, "iterrows"):
            raise YFinanceApiError("yfinance returned an unexpected historical-data object")
        if bool(history.empty):
            return ()
        try:
            return tuple(self._to_candle(index, row) for index, row in history.iterrows())
        except YFinanceError:
            raise
        except Exception as error:
            raise YFinanceApiError("Could not parse yfinance historical-data rows") from error

    def _get_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            self._api = import_module("yfinance")
        except ImportError as error:
            raise YFinanceDependencyError(
                "yfinance support requires the 'yfinance' Python package; install the project dependencies first"
            ) from error
        return self._api

    @staticmethod
    def _validate_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^=")
        if not 1 <= len(normalized) <= 32 or any(character not in allowed for character in normalized):
            raise ValueError(
                "yfinance symbols may contain only letters, numbers, dot, hyphen, caret, and equals"
            )
        return normalized

    @staticmethod
    def _validate_interval(interval: str) -> str:
        if not isinstance(interval, str) or interval not in _INTERVALS:
            raise ValueError("yfinance interval must be one of 1d, 1wk, 1mo")
        return interval

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> None:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("yfinance dates must use YYYY-MM-DD") from error
        if start >= end:
            raise ValueError("yfinance end_date must be later than start_date")

    @classmethod
    def _to_candle(cls, index: Any, row: Any) -> YFinanceCandle:
        if not hasattr(row, "get"):
            raise YFinanceApiError("yfinance historical-data row is not column-addressable")
        return YFinanceCandle(
            date=cls._to_date(index),
            open_price=cls._required_decimal(row, "Open"),
            close_price=cls._required_decimal(row, "Close"),
            high_price=cls._required_decimal(row, "High"),
            low_price=cls._required_decimal(row, "Low"),
            adjusted_close=cls._optional_decimal(row, "Adj Close"),
            volume=cls._optional_decimal(row, "Volume"),
        )

    @staticmethod
    def _to_date(index: Any) -> str:
        candidate = index.date() if hasattr(index, "date") else str(index)[:10]
        if isinstance(candidate, date):
            return candidate.isoformat()
        try:
            return datetime.strptime(str(candidate), "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise YFinanceApiError("yfinance historical-data row has an invalid date index") from error

    @classmethod
    def _required_decimal(cls, row: Any, key: str) -> Decimal:
        value = cls._optional_decimal(row, key)
        if value is None:
            raise YFinanceApiError(f"yfinance historical-data row is missing {key}")
        return value

    @staticmethod
    def _optional_decimal(row: Any, key: str) -> Decimal | None:
        value = row.get(key)
        if value is None or (isinstance(value, float) and isnan(value)):
            return None
        text = str(value)
        if text.lower() in {"", "nan", "nat", "none"}:
            return None
        try:
            decimal_value = Decimal(text)
        except (InvalidOperation, ValueError) as error:
            raise YFinanceApiError(f"yfinance historical-data row has an invalid {key}") from error
        if not decimal_value.is_finite():
            raise YFinanceApiError(f"yfinance historical-data row has a non-finite {key}")
        return decimal_value
