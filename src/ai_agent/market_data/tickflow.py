"""Bounded, read-only adapter for the TickFlow Python SDK.

The SDK owns the HTTP details.  This wrapper keeps the API key in memory,
validates the subset of calls exposed to Finance Agent, and turns SDK errors
into safe provider-neutral failures before they reach an Agent or the Web UI.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,30}\.(?:SH|SZ|BJ|US|HK)$")
_SUPPORTED_ADJUSTMENTS = frozenset({"forward", "backward", "none"})
_MAX_SYMBOLS_PER_QUOTE_REQUEST = 20
_MAX_DAILY_CANDLES = 120
_MAX_HISTORY_DAYS = 3660


class TickFlowError(RuntimeError):
    """Base class for safe TickFlow adapter failures."""


class TickFlowDependencyError(TickFlowError):
    """The optional TickFlow package has not been installed."""


class TickFlowTransportError(TickFlowError):
    """TickFlow could not complete a provider request safely."""


class TickFlowResponseError(TickFlowError):
    """TickFlow returned a payload that does not match the documented shape."""


@dataclass(frozen=True, slots=True)
class TickFlowQuote:
    """One normalized TickFlow quote, retaining only research-safe fields."""

    symbol: str
    timestamp_ms: int
    last_price: Decimal
    previous_close: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    change_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class TickFlowCandle:
    """One normalized daily OHLCV bar."""

    date: str
    timestamp_ms: int
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal | None
    amount: Decimal | None


SdkFactory = Callable[..., object]


class TickFlowClient:
    """Expose a small, date-bounded subset of TickFlow's documented SDK."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 4.0,
        sdk_factory: SdkFactory | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("TickFlow API key cannot be blank")
        if timeout_seconds <= 0:
            raise ValueError("TickFlow timeout_seconds must be positive")
        factory = sdk_factory or _load_sdk_factory()
        try:
            # Disable SDK retries: the caller owns its bounded fallback order and
            # should not spend an unbounded Web request budget on hidden retries.
            self._client = factory(api_key=api_key.strip(), timeout=timeout_seconds, max_retries=0)
        except Exception:
            raise TickFlowTransportError("TickFlow client could not be initialized") from None

    def quotes(self, symbols: Sequence[str]) -> tuple[TickFlowQuote, ...]:
        """Read one bounded batch of real-time quote snapshots."""

        normalized_symbols = self._validate_symbols(symbols)
        try:
            payload = self._client.quotes.get(symbols=list(normalized_symbols))  # type: ignore[attr-defined]
        except Exception:
            raise TickFlowTransportError("TickFlow market-data service is unavailable") from None
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise TickFlowResponseError("TickFlow returned an unexpected quote response")
        return tuple(self._quote(item) for item in payload)

    def daily_candles(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int = _MAX_DAILY_CANDLES,
        adjust: str = "none",
    ) -> tuple[TickFlowCandle, ...]:
        """Read at most 120 daily bars for an explicit inclusive date range."""

        normalized_symbol = self._validate_symbol(symbol)
        start, end = self._validate_dates(start_date, end_date)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_DAILY_CANDLES:
            raise ValueError("TickFlow daily candle limit must be between 1 and 120")
        if adjust not in _SUPPORTED_ADJUSTMENTS:
            raise ValueError("TickFlow adjustment must be forward, backward, or none")
        timezone = _market_timezone(normalized_symbol)
        start_time = _timestamp_milliseconds(start, timezone)
        # TickFlow accepts millisecond timestamps.  Preserve the caller's
        # inclusive end date even when daily bars use a midnight timestamp.
        end_time = _timestamp_milliseconds(end + timedelta(days=1), timezone) - 1
        try:
            payload = self._client.klines.get(  # type: ignore[attr-defined]
                normalized_symbol,
                period="1d",
                count=limit,
                start_time=start_time,
                end_time=end_time,
                adjust=adjust,
            )
        except Exception:
            raise TickFlowTransportError("TickFlow market-data service is unavailable") from None
        if not isinstance(payload, Mapping):
            raise TickFlowResponseError("TickFlow returned an unexpected daily-candle response")
        return self._candles(payload, timezone)

    @staticmethod
    def _validate_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
        if isinstance(symbols, (str, bytes)) or not 1 <= len(symbols) <= _MAX_SYMBOLS_PER_QUOTE_REQUEST:
            raise ValueError("TickFlow quote requests require 1 to 20 symbols")
        normalized = tuple(TickFlowClient._validate_symbol(symbol) for symbol in symbols)
        if len(set(normalized)) != len(normalized):
            raise ValueError("TickFlow quote symbols must not contain duplicates")
        return normalized

    @staticmethod
    def _validate_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
        if not _SYMBOL_PATTERN.fullmatch(normalized):
            raise ValueError("TickFlow symbols must use a supported exchange suffix, such as 600000.SH or AAPL.US")
        return normalized

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> tuple[date, date]:
        try:
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        except (TypeError, ValueError) as error:
            raise ValueError("TickFlow dates must use YYYY-MM-DD") from error
        if start > end:
            raise ValueError("TickFlow end_date must be on or after start_date")
        if (end - start).days > _MAX_HISTORY_DAYS:
            raise ValueError("TickFlow date range must not exceed 3660 days")
        return start, end

    @staticmethod
    def _quote(value: object) -> TickFlowQuote:
        if not isinstance(value, Mapping):
            raise TickFlowResponseError("TickFlow quote row is not an object")
        ext = value.get("ext")
        if ext is not None and not isinstance(ext, Mapping):
            raise TickFlowResponseError("TickFlow quote extension is not an object")
        extension = ext if isinstance(ext, Mapping) else {}
        return TickFlowQuote(
            symbol=TickFlowClient._validate_symbol(_required_text(value, "symbol")),
            timestamp_ms=_required_integer(value, "timestamp"),
            last_price=_required_decimal(value, "last_price"),
            previous_close=_optional_decimal(value, "prev_close"),
            open_price=_optional_decimal(value, "open"),
            high_price=_optional_decimal(value, "high"),
            low_price=_optional_decimal(value, "low"),
            volume=_optional_decimal(value, "volume"),
            amount=_optional_decimal(value, "amount"),
            change_percent=_optional_decimal(extension, "change_pct"),
        )

    @staticmethod
    def _candles(payload: Mapping[str, object], timezone: ZoneInfo) -> tuple[TickFlowCandle, ...]:
        timestamps = _required_sequence(payload, "timestamp")
        opens = _required_sequence(payload, "open")
        highs = _required_sequence(payload, "high")
        lows = _required_sequence(payload, "low")
        closes = _required_sequence(payload, "close")
        volumes = _optional_sequence(payload, "volume", len(timestamps))
        amounts = _optional_sequence(payload, "amount", len(timestamps))
        columns = (opens, highs, lows, closes)
        if any(len(column) != len(timestamps) for column in columns):
            raise TickFlowResponseError("TickFlow daily-candle columns have inconsistent lengths")
        candles: list[TickFlowCandle] = []
        for index, raw_timestamp in enumerate(timestamps):
            timestamp_ms = _integer(raw_timestamp, "timestamp")
            candle_date = datetime.fromtimestamp(timestamp_ms / 1_000, tz=timezone).date().isoformat()
            candles.append(
                TickFlowCandle(
                    date=candle_date,
                    timestamp_ms=timestamp_ms,
                    open_price=_decimal(opens[index], "open"),
                    high_price=_decimal(highs[index], "high"),
                    low_price=_decimal(lows[index], "low"),
                    close_price=_decimal(closes[index], "close"),
                    volume=_decimal(volumes[index], "volume") if volumes is not None else None,
                    amount=_decimal(amounts[index], "amount") if amounts is not None else None,
                )
            )
        return tuple(candles)


def _load_sdk_factory() -> SdkFactory:
    try:
        from tickflow import TickFlow
    except ImportError:
        raise TickFlowDependencyError("TickFlow SDK is not installed") from None
    return TickFlow


def _market_timezone(symbol: str) -> ZoneInfo:
    suffix = symbol.rsplit(".", 1)[1]
    return ZoneInfo("America/New_York") if suffix == "US" else ZoneInfo("Asia/Shanghai")


def _timestamp_milliseconds(day: date, timezone: ZoneInfo) -> int:
    return int(datetime.combine(day, time.min, tzinfo=timezone).timestamp() * 1_000)


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TickFlowResponseError(f"TickFlow response is missing {key}")
    return value.strip()


def _required_integer(payload: Mapping[str, object], key: str) -> int:
    if key not in payload:
        raise TickFlowResponseError(f"TickFlow response is missing {key}")
    return _integer(payload[key], key)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise TickFlowResponseError(f"TickFlow response has an invalid {field}")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        raise TickFlowResponseError(f"TickFlow response has an invalid {field}") from None
    if result < 0:
        raise TickFlowResponseError(f"TickFlow response has an invalid {field}")
    return result


def _required_decimal(payload: Mapping[str, object], key: str) -> Decimal:
    if key not in payload:
        raise TickFlowResponseError(f"TickFlow response is missing {key}")
    return _decimal(payload[key], key)


def _optional_decimal(payload: Mapping[str, object], key: str) -> Decimal | None:
    value = payload.get(key)
    return None if value is None else _decimal(value, key)


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise TickFlowResponseError(f"TickFlow response has an invalid {field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise TickFlowResponseError(f"TickFlow response has an invalid {field}") from None
    if not result.is_finite():
        raise TickFlowResponseError(f"TickFlow response has an invalid {field}")
    return result


def _required_sequence(payload: Mapping[str, object], key: str) -> Sequence[object]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TickFlowResponseError(f"TickFlow response is missing {key}")
    return value


def _optional_sequence(payload: Mapping[str, object], key: str, expected_length: int) -> Sequence[object] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != expected_length:
        raise TickFlowResponseError(f"TickFlow response has an invalid {key}")
    return value
