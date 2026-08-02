from __future__ import annotations

import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from ai_agent.market_data.tickflow import TickFlowClient, TickFlowTransportError
from ai_agent.tools import ToolRegistry, create_tickflow_market_data_tool


def _timestamp(year: int, month: int, day: int, timezone: str = "Asia/Shanghai") -> int:
    return int(datetime(year, month, day, tzinfo=ZoneInfo(timezone)).timestamp() * 1_000)


class _FakeKlines:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def get(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        return self.payload


class _FakeQuotes:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def get(self, **_kwargs: object) -> object:
        return self.payload


class _FakeSdk:
    def __init__(self, klines_payload: object, quotes_payload: object) -> None:
        self.klines = _FakeKlines(klines_payload)
        self.quotes = _FakeQuotes(quotes_payload)


class TickFlowClientTests(unittest.TestCase):
    def test_daily_candles_are_date_bounded_and_normalized(self) -> None:
        sdk = _FakeSdk(
            {
                "timestamp": [_timestamp(2026, 7, 27), _timestamp(2026, 7, 28)],
                "open": [100, 101],
                "high": [102, 103],
                "low": [99, 100],
                "close": [101, 102],
                "volume": [10, 20],
                "amount": [1000, 2000],
            },
            [],
        )
        constructor_kwargs: dict[str, object] = {}

        def factory(**kwargs: object) -> _FakeSdk:
            constructor_kwargs.update(kwargs)
            return sdk

        client = TickFlowClient("test-key", timeout_seconds=2, sdk_factory=factory)
        candles = client.daily_candles(
            "600000.SH",
            start_date="2026-07-27",
            end_date="2026-07-28",
            limit=5,
            adjust="none",
        )

        self.assertEqual(constructor_kwargs["timeout"], 2)
        self.assertEqual(constructor_kwargs["max_retries"], 0)
        self.assertEqual([candle.date for candle in candles], ["2026-07-27", "2026-07-28"])
        self.assertEqual(str(candles[-1].close_price), "102")
        _arguments, request = sdk.klines.calls[0]
        self.assertEqual(request["period"], "1d")
        self.assertEqual(request["adjust"], "none")
        self.assertLess(request["start_time"], request["end_time"])

    def test_tool_returns_safe_json_for_quotes_and_candles(self) -> None:
        sdk = _FakeSdk(
            {
                "timestamp": [_timestamp(2026, 7, 28)],
                "open": [100],
                "high": [102],
                "low": [99],
                "close": [101],
            },
            [
                {
                    "symbol": "600000.SH",
                    "timestamp": _timestamp(2026, 7, 28),
                    "last_price": 101,
                    "prev_close": 100,
                    "open": 100,
                    "high": 102,
                    "low": 99,
                    "volume": 10,
                    "amount": 1000,
                    "ext": {"change_pct": 0.01},
                }
            ],
        )
        client = TickFlowClient("test-key", sdk_factory=lambda **_kwargs: sdk)
        registry = ToolRegistry((create_tickflow_market_data_tool(client),))

        quote = json.loads(registry.execute("tickflow_market_data", {"action": "quote", "symbols": ["600000.SH"]}))
        candles = json.loads(
            registry.execute(
                "tickflow_market_data",
                {
                    "action": "historical_candles",
                    "symbol": "600000.SH",
                    "start_date": "2026-07-28",
                    "end_date": "2026-07-28",
                    "limit": 1,
                },
            )
        )

        self.assertEqual(quote["source"], "TickFlow")
        self.assertEqual(quote["quotes"][0]["change_percent"], "0.01")
        self.assertEqual(candles["source"], "TickFlow")
        self.assertEqual(candles["candles"][0]["date"], "2026-07-28")

    def test_provider_exception_is_sanitized(self) -> None:
        class BrokenSdk:
            class quotes:
                @staticmethod
                def get(**_kwargs: object) -> object:
                    raise RuntimeError("provider-secret-must-not-escape")

        client = TickFlowClient("test-key", sdk_factory=lambda **_kwargs: BrokenSdk())

        with self.assertRaises(TickFlowTransportError) as error:
            client.quotes(["600000.SH"])

        self.assertNotIn("provider-secret-must-not-escape", str(error.exception))


if __name__ == "__main__":
    unittest.main()
