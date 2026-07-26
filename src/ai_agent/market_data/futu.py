"""Read-only Futu OpenAPI adapter backed by an operator-managed FutuOpenD.

Futu's Python SDK speaks TCP to FutuOpenD rather than calling a public HTTP
endpoint.  This adapter deliberately exposes market-data reads only: it never
creates a trading context, unlocks trading, reads account data, or places an
order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from importlib import import_module
from io import StringIO
from os import getenv
import re
import socket
from time import monotonic
from typing import Any


DEFAULT_FUTU_OPEND_HOST = "127.0.0.1"
DEFAULT_FUTU_OPEND_PORT = 11111
_CODE_PATTERN = re.compile(r"^[A-Z]{2,5}\.[A-Z0-9._-]{1,40}$")
_KTYPES = {"d": "K_DAY", "w": "K_WEEK", "m": "K_MON"}
_AUTYPES = {"qfq", "hfq", "none"}


class FutuError(RuntimeError):
    """Base error for a read-only Futu market-data request."""


class FutuApiError(FutuError):
    """FutuOpenD rejected a request or returned malformed market data."""


class FutuDependencyError(FutuError):
    """The ``futu-api`` Python package is not installed."""


class FutuOpenDError(FutuError):
    """The operator-managed local FutuOpenD cannot be reached or used."""


class FutuRateLimitError(FutuError):
    """The local Futu request guard rejected a request before OpenD was used."""


@dataclass(frozen=True, slots=True)
class FutuLimits:
    """Conservative per-process guard for read-only Futu OpenD requests."""

    minimum_interval_seconds: float
    max_requests_per_day: int

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if self.max_requests_per_day < 1:
            raise ValueError("max_requests_per_day must be at least 1")


# Futu documents a 60 calls / 30 seconds historical-K-line ceiling.  One
# second between requests leaves headroom for the same OpenD account to be
# used manually.  The daily guard is a project-side protection, not a Futu
# entitlement or a replacement for account-specific historical-K-line quotas.
DEFAULT_FUTU_LIMITS = FutuLimits(1.0, 500)


@dataclass(frozen=True, slots=True)
class FutuCandle:
    """One daily, weekly, or monthly K-line returned by FutuOpenD."""

    time_key: str
    code: str
    name: str | None
    open_price: Decimal
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal
    previous_close: Decimal | None
    volume: Decimal | None
    turnover: Decimal | None
    turnover_rate_percent: Decimal | None
    change_percent: Decimal | None
    pe_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class FutuSnapshot:
    """One read-only market snapshot returned by FutuOpenD."""

    code: str
    name: str | None
    update_time: str | None
    last_price: Decimal
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    previous_close: Decimal | None
    volume: Decimal | None
    turnover: Decimal | None
    turnover_rate_percent: Decimal | None
    pe_ratio: Decimal | None
    pb_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class FutuOpenDEndpoint:
    """The local gateway endpoint whose TCP port accepted a short probe."""

    host: str
    port: int


SocketFactory = Callable[[tuple[str, int], float], Any]


class _RateGuard:
    def __init__(
        self,
        limits: FutuLimits,
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
                raise FutuRateLimitError(
                    f"Local Futu interval limit; retry after {remaining:.1f} seconds"
                )
        today = self._current_date()
        if today != self._date:
            self._date, self._daily_count = today, 0
        if self._daily_count >= self._limits.max_requests_per_day:
            raise FutuRateLimitError("Local Futu daily request limit reached")
        self._last_request = now
        self._daily_count += 1


class FutuClient:
    """Read bounded market data via a local, logged-in FutuOpenD gateway."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_FUTU_OPEND_HOST,
        port: int = DEFAULT_FUTU_OPEND_PORT,
        limits: FutuLimits = DEFAULT_FUTU_LIMITS,
        api: Any | None = None,
        socket_factory: SocketFactory = socket.create_connection,
        connection_timeout_seconds: float = 1.0,
        clock: Callable[[], float] = monotonic,
        current_date: Callable[[], date] = date.today,
    ) -> None:
        normalized_host = host.strip() if isinstance(host, str) else ""
        if not normalized_host or len(normalized_host) > 255:
            raise ValueError("FutuOpenD host must be a non-empty hostname or IP address")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("FutuOpenD port must be an integer between 1 and 65535")
        if connection_timeout_seconds <= 0:
            raise ValueError("FutuOpenD connection_timeout_seconds must be positive")
        self._host = normalized_host
        self._port = port
        self._api = api
        self._socket_factory = socket_factory
        self._connection_timeout_seconds = connection_timeout_seconds
        self._guard = _RateGuard(limits, clock, current_date)

    @classmethod
    def from_environment(cls) -> "FutuClient":
        """Build a client from optional local OpenD host and port settings."""

        host = getenv("FUTU_OPEND_HOST", DEFAULT_FUTU_OPEND_HOST)
        raw_port = getenv("FUTU_OPEND_PORT", str(DEFAULT_FUTU_OPEND_PORT))
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ValueError("FUTU_OPEND_PORT must be an integer between 1 and 65535") from error
        return cls(host=host, port=port)

    def check_opend(self) -> FutuOpenDEndpoint:
        """Perform a short TCP reachability probe without logging into an account.

        A reachable port only establishes that something is listening at the
        configured address.  Market-data permissions and OpenD login status are
        verified later by an actual read request.
        """

        connection: Any | None = None
        try:
            connection = self._socket_factory(
                (self._host, self._port), self._connection_timeout_seconds
            )
        except (OSError, TimeoutError, ValueError) as error:
            raise FutuOpenDError(
                "FutuOpenD is not reachable; start and log into FutuOpenD, then verify "
                "FUTU_OPEND_HOST and FUTU_OPEND_PORT"
            ) from error
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        return FutuOpenDEndpoint(self._host, self._port)

    def historical_candles(
        self,
        code: str,
        *,
        start_date: str,
        end_date: str,
        interval: str = "d",
        autype: str = "qfq",
    ) -> tuple[FutuCandle, ...]:
        """Read up to one unpaged daily, weekly, or monthly Futu K-line page."""

        normalized_code = self._validate_code(code)
        normalized_interval = self._validate_choice(interval, _KTYPES, "interval")
        normalized_autype = self._validate_choice(autype, _AUTYPES, "autype")
        self._validate_dates(start_date, end_date)
        api = self._get_api()
        self._guard.acquire()
        self.check_opend()
        context = self._open_quote_context(api)
        try:
            try:
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    result = context.request_history_kline(
                        normalized_code,
                        start=start_date,
                        end=end_date,
                        ktype=_KTYPES[normalized_interval],
                        autype=normalized_autype,
                        max_count=1000,
                    )
            except Exception as error:
                raise FutuOpenDError(
                    "FutuOpenD could not complete the historical K-line request; verify its login "
                    "state, market-data permissions, and TCP configuration"
                ) from error
            payload, page_request_key = self._successful_result(api, result, "historical K-line request")
            if page_request_key is not None:
                raise FutuApiError(
                    "Futu returned more than 1,000 K-line rows; split the date range before retrying"
                )
            return tuple(self._to_candle(row) for row in self._rows(payload, "historical K-line"))
        finally:
            self._close_context(context)

    def market_snapshot(self, codes: Sequence[str]) -> tuple[FutuSnapshot, ...]:
        """Read a bounded set of Futu market snapshots through OpenD."""

        normalized_codes = self._validate_codes(codes)
        api = self._get_api()
        self._guard.acquire()
        self.check_opend()
        context = self._open_quote_context(api)
        try:
            try:
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    result = context.get_market_snapshot(list(normalized_codes))
            except Exception as error:
                raise FutuOpenDError(
                    "FutuOpenD could not complete the market-snapshot request; verify its login "
                    "state, market-data permissions, and TCP configuration"
                ) from error
            payload, _ = self._successful_result(api, result, "market-snapshot request")
            return tuple(self._to_snapshot(row) for row in self._rows(payload, "market snapshot"))
        finally:
            self._close_context(context)

    def _get_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            self._api = import_module("futu")
        except ImportError as error:
            raise FutuDependencyError(
                "Futu support requires the 'futu-api' Python package; install the project dependencies first"
            ) from error
        return self._api

    def _open_quote_context(self, api: Any) -> Any:
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                return api.OpenQuoteContext(host=self._host, port=self._port)
        except Exception as error:
            raise FutuOpenDError(
                "FutuOpenD did not accept a quote connection; verify that it is running and logged in"
            ) from error

    @staticmethod
    def _close_context(context: Any) -> None:
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                context.close()
        except Exception:
            # Cleanup errors must not hide the primary market-data result.
            pass

    @staticmethod
    def _successful_result(api: Any, result: Any, operation: str) -> tuple[Any, Any | None]:
        if not isinstance(result, tuple) or len(result) not in {2, 3}:
            raise FutuApiError(f"Futu {operation} returned an unexpected response")
        return_code, payload = result[0], result[1]
        if return_code != getattr(api, "RET_OK", 0):
            raise FutuApiError(
                f"Futu {operation} was rejected; verify the code, OpenD login, permissions, and quota"
            )
        return payload, result[2] if len(result) == 3 else None

    @staticmethod
    def _rows(payload: Any, operation: str) -> Iterable[Any]:
        if not hasattr(payload, "iterrows"):
            raise FutuApiError(f"Futu {operation} response is missing tabular rows")
        try:
            return tuple(row for _, row in payload.iterrows())
        except Exception as error:
            raise FutuApiError(f"Could not read Futu {operation} rows") from error

    @staticmethod
    def _validate_code(code: str) -> str:
        normalized = code.strip().upper() if isinstance(code, str) else ""
        if not _CODE_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Futu codes must include a market prefix, for example HK.00700, US.AAPL, or SH.600519"
            )
        return normalized

    @classmethod
    def _validate_codes(cls, codes: Sequence[str]) -> tuple[str, ...]:
        if isinstance(codes, str) or not isinstance(codes, Sequence) or not 1 <= len(codes) <= 50:
            raise ValueError("Futu market snapshots require 1 to 50 code strings")
        normalized = tuple(cls._validate_code(code) for code in codes)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Futu market snapshot codes must be unique")
        return normalized

    @staticmethod
    def _validate_choice(value: str, allowed: Mapping[str, str] | set[str], field_name: str) -> str:
        normalized = value.lower() if isinstance(value, str) else ""
        if normalized not in allowed:
            choices = ", ".join(sorted(allowed))
            raise ValueError(f"Futu {field_name} must be one of {choices}")
        return normalized

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> None:
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except (TypeError, ValueError) as error:
            raise ValueError("Futu start_date and end_date must use YYYY-MM-DD") from error
        if start > end:
            raise ValueError("Futu start_date must not be later than end_date")

    @classmethod
    def _to_candle(cls, row: Any) -> FutuCandle:
        return FutuCandle(
            time_key=cls._required_text(row, "time_key"),
            code=cls._required_text(row, "code"),
            name=cls._optional_text(row, "name"),
            open_price=cls._required_decimal(row, "open"),
            close_price=cls._required_decimal(row, "close"),
            high_price=cls._required_decimal(row, "high"),
            low_price=cls._required_decimal(row, "low"),
            previous_close=cls._optional_decimal(row, "last_close"),
            volume=cls._optional_decimal(row, "volume"),
            turnover=cls._optional_decimal(row, "turnover"),
            turnover_rate_percent=cls._optional_decimal(row, "turnover_rate"),
            change_percent=cls._optional_decimal(row, "change_rate"),
            pe_ratio=cls._optional_decimal(row, "pe_ratio"),
        )

    @classmethod
    def _to_snapshot(cls, row: Any) -> FutuSnapshot:
        return FutuSnapshot(
            code=cls._required_text(row, "code"),
            name=cls._optional_text(row, "name"),
            update_time=cls._optional_text(row, "update_time"),
            last_price=cls._required_decimal(row, "last_price"),
            open_price=cls._optional_decimal(row, "open_price"),
            high_price=cls._optional_decimal(row, "high_price"),
            low_price=cls._optional_decimal(row, "low_price"),
            previous_close=cls._optional_decimal(row, "prev_close_price"),
            volume=cls._optional_decimal(row, "volume"),
            turnover=cls._optional_decimal(row, "turnover"),
            turnover_rate_percent=cls._optional_decimal(row, "turnover_rate"),
            pe_ratio=cls._optional_decimal(row, "pe_ratio"),
            pb_ratio=cls._optional_decimal(row, "pb_ratio"),
        )

    @staticmethod
    def _value(row: Any, key: str) -> Any:
        getter = getattr(row, "get", None)
        if not callable(getter):
            raise FutuApiError(f"Futu response row does not support field {key}")
        return getter(key)

    @classmethod
    def _required_text(cls, row: Any, key: str) -> str:
        value = cls._optional_text(row, key)
        if value is None:
            raise FutuApiError(f"Futu response row is missing {key}")
        return value

    @classmethod
    def _optional_text(cls, row: Any, key: str) -> str | None:
        value = cls._value(row, key)
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "nat", "none"}:
            return None
        return text

    @classmethod
    def _required_decimal(cls, row: Any, key: str) -> Decimal:
        value = cls._optional_decimal(row, key)
        if value is None:
            raise FutuApiError(f"Futu response row is missing {key}")
        return value

    @classmethod
    def _optional_decimal(cls, row: Any, key: str) -> Decimal | None:
        value = cls._value(row, key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise FutuApiError(f"Futu response row has an invalid {key}") from error
        if not decimal.is_finite():
            return None
        return decimal
