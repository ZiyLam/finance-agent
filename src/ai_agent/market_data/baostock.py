"""Read-only wrapper for BaoStock's documented Python historical K-line API."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from importlib import import_module
from io import StringIO
from time import monotonic
from typing import Any


BAOSTOCK_DAILY_IP_LIMIT = 50_000


class BaoStockError(RuntimeError):
    """Base error for a BaoStock market-data request."""


class BaoStockApiError(BaoStockError):
    """BaoStock returned an unsuccessful result or malformed rows."""


class BaoStockDependencyError(BaoStockError):
    """The official BaoStock Python package is not installed."""


class BaoStockRateLimitError(BaoStockError):
    """The local quota guard rejected a request before it used provider quota."""


class BaoStockSessionError(BaoStockError):
    """The official BaoStock client could not establish its anonymous session."""


@dataclass(frozen=True, slots=True)
class BaoStockLimits:
    """Per-process protection below BaoStock's 50,000 requests/IP/day ceiling."""

    minimum_interval_seconds: float
    max_requests_per_day: int

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if not 1 <= self.max_requests_per_day <= BAOSTOCK_DAILY_IP_LIMIT:
            raise ValueError(
                f"max_requests_per_day must be between 1 and {BAOSTOCK_DAILY_IP_LIMIT}"
            )


# 10% of BaoStock's published daily ceiling leaves headroom for manual research
# and other local applications sharing the same public IP address.
DEFAULT_BAOSTOCK_LIMITS = BaoStockLimits(0.1, 5_000)


@dataclass(frozen=True, slots=True)
class BaoStockCandle:
    """One historical K-line observation from BaoStock."""

    date: str
    code: str
    open_price: Decimal
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal
    previous_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    adjustment_flag: str | None
    turnover_rate_percent: Decimal | None
    trade_status: str | None
    change_percent: Decimal | None
    is_st: str | None


_HISTORY_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,"
    "tradestatus,pctChg,isST"
)
_FREQUENCIES = {"d", "w", "m"}
_ADJUSTMENT_FLAGS = {"1", "2", "3"}


class _RateGuard:
    def __init__(
        self,
        limits: BaoStockLimits,
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
                raise BaoStockRateLimitError(
                    f"Local BaoStock interval limit; retry after {remaining:.1f} seconds"
                )
        today = self._current_date()
        if today != self._date:
            self._date, self._daily_count = today, 0
        if self._daily_count >= self._limits.max_requests_per_day:
            raise BaoStockRateLimitError(
                "Local BaoStock daily limit reached before the provider's 50,000 requests/IP/day ceiling"
            )
        self._last_request = now
        self._daily_count += 1


class BaoStockClient:
    """Open a short anonymous BaoStock session for bounded historical K-line reads."""

    def __init__(
        self,
        *,
        limits: BaoStockLimits = DEFAULT_BAOSTOCK_LIMITS,
        api: Any | None = None,
        clock: Callable[[], float] = monotonic,
        current_date: Callable[[], date] = date.today,
    ) -> None:
        self._api = api
        self._guard = _RateGuard(limits, clock, current_date)

    def historical_candles(
        self,
        code: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjustflag: str = "3",
    ) -> tuple[BaoStockCandle, ...]:
        """Fetch A-share daily, weekly, or monthly K lines using BaoStock's API."""

        normalized_code = self._validate_code(code)
        normalized_frequency = self._validate_choice(frequency, _FREQUENCIES, "frequency")
        normalized_adjustflag = self._validate_choice(adjustflag, _ADJUSTMENT_FLAGS, "adjustflag")
        self._validate_dates(start_date, end_date)
        self._guard.acquire()
        api = self._get_api()
        try:
            with redirect_stdout(StringIO()):
                login_result = api.login()
        except Exception as error:
            raise BaoStockSessionError("Could not establish a BaoStock anonymous session") from error
        self._ensure_success(login_result, "login")
        try:
            try:
                with redirect_stdout(StringIO()):
                    result = api.query_history_k_data_plus(
                        normalized_code,
                        _HISTORY_FIELDS,
                        start_date=start_date,
                        end_date=end_date,
                        frequency=normalized_frequency,
                        adjustflag=normalized_adjustflag,
                    )
            except Exception as error:
                raise BaoStockSessionError("BaoStock historical K-line request failed") from error
            self._ensure_success(result, "historical K-line query")
            return tuple(self._to_candle(row) for row in self._rows(result))
        finally:
            try:
                with redirect_stdout(StringIO()):
                    api.logout()
            except Exception:
                # A failed logout must not obscure a completed read or its primary error.
                pass

    def _get_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            self._api = import_module("baostock")
        except ImportError as error:
            raise BaoStockDependencyError(
                "BaoStock support requires the 'baostock' Python package; install the project dependencies first"
            ) from error
        return self._api

    @staticmethod
    def _ensure_success(result: Any, operation: str) -> None:
        error_code = getattr(result, "error_code", None)
        if str(error_code) == "0":
            return
        error_message = getattr(result, "error_msg", "unknown error")
        raise BaoStockApiError(f"BaoStock {operation} failed: {error_message}")

    @staticmethod
    def _rows(result: Any) -> tuple[Mapping[str, str], ...]:
        fields = getattr(result, "fields", None)
        if not isinstance(fields, Sequence) or isinstance(fields, str) or not all(
            isinstance(field, str) and field for field in fields
        ):
            raise BaoStockApiError("BaoStock historical K-line response is missing field names")
        rows: list[Mapping[str, str]] = []
        try:
            while result.next():
                row = result.get_row_data()
                if not isinstance(row, Sequence) or isinstance(row, str) or len(row) != len(fields):
                    raise BaoStockApiError("BaoStock historical K-line row does not match its fields")
                if not all(isinstance(value, str) for value in row):
                    raise BaoStockApiError("BaoStock historical K-line row contains non-text values")
                rows.append(dict(zip(fields, row, strict=True)))
        except BaoStockApiError:
            raise
        except Exception as error:
            raise BaoStockSessionError("Could not read BaoStock historical K-line rows") from error
        return tuple(rows)

    @staticmethod
    def _validate_code(code: str) -> str:
        normalized = code.strip().lower()
        exchange, separator, symbol = normalized.partition(".")
        if separator != "." or exchange not in {"sh", "sz", "bj"} or len(symbol) != 6 or not symbol.isdigit():
            raise ValueError("BaoStock codes must use sh/sz/bj plus a six-digit symbol, for example sh.600000")
        return normalized

    @staticmethod
    def _validate_choice(value: str, allowed: set[str], field_name: str) -> str:
        if not isinstance(value, str) or value not in allowed:
            choices = ", ".join(sorted(allowed))
            raise ValueError(f"BaoStock {field_name} must be one of {choices}")
        return value

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> None:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("BaoStock dates must use YYYY-MM-DD") from error
        if start > end:
            raise ValueError("BaoStock start_date must not be later than end_date")

    @classmethod
    def _to_candle(cls, row: Mapping[str, str]) -> BaoStockCandle:
        return BaoStockCandle(
            date=cls._required_date(row, "date"),
            code=cls._required_text(row, "code"),
            open_price=cls._required_decimal(row, "open"),
            close_price=cls._required_decimal(row, "close"),
            high_price=cls._required_decimal(row, "high"),
            low_price=cls._required_decimal(row, "low"),
            previous_close=cls._optional_decimal(row, "preclose"),
            volume=cls._optional_decimal(row, "volume"),
            amount=cls._optional_decimal(row, "amount"),
            adjustment_flag=cls._optional_text(row, "adjustflag"),
            turnover_rate_percent=cls._optional_decimal(row, "turn"),
            trade_status=cls._optional_text(row, "tradestatus"),
            change_percent=cls._optional_decimal(row, "pctChg"),
            is_st=cls._optional_text(row, "isST"),
        )

    @staticmethod
    def _required_text(row: Mapping[str, str], key: str) -> str:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise BaoStockApiError(f"BaoStock K-line is missing {key}")
        return value

    @staticmethod
    def _optional_text(row: Mapping[str, str], key: str) -> str | None:
        value = row.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise BaoStockApiError(f"BaoStock K-line has an invalid {key}")
        return value

    @classmethod
    def _required_date(cls, row: Mapping[str, str], key: str) -> str:
        value = cls._required_text(row, key)
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise BaoStockApiError(f"BaoStock K-line has an invalid {key}") from error

    @classmethod
    def _required_decimal(cls, row: Mapping[str, str], key: str) -> Decimal:
        value = cls._optional_decimal(row, key)
        if value is None:
            raise BaoStockApiError(f"BaoStock K-line is missing {key}")
        return value

    @staticmethod
    def _optional_decimal(row: Mapping[str, str], key: str) -> Decimal | None:
        value = row.get(key)
        if value is None or value == "":
            return None
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise BaoStockApiError(f"BaoStock K-line has an invalid {key}") from error
