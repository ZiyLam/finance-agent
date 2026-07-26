from __future__ import annotations

from datetime import date, datetime
import json
from unittest.mock import patch
import unittest

from ai_agent.cli import run_source_command
from ai_agent.market_data.yfinance import (
    YFinanceClient,
    YFinanceLimits,
    YFinanceRateLimitError,
)
from ai_agent.tools import ToolRegistry, create_yfinance_market_data_tool


ROW = {
    "Open": 185.64,
    "High": 187.38,
    "Low": 183.92,
    "Close": 185.85,
    "Adj Close": 184.75,
    "Volume": 82488700,
}


class FakeHistory:
    def __init__(self, rows: list[tuple[object, dict[str, object]]]) -> None:
        self.empty = not rows
        self._rows = rows

    def iterrows(self):
        yield from self._rows


class FakeTicker:
    def __init__(self, history: FakeHistory) -> None:
        self._history = history
        self.calls: list[dict[str, object]] = []

    def history(self, **kwargs: object) -> FakeHistory:
        self.calls.append(kwargs)
        return self._history


class FakeYFinanceApi:
    def __init__(self, history: FakeHistory) -> None:
        self.ticker = FakeTicker(history)
        self.symbols: list[str] = []
        self.cache_locations: list[str] = []

    def Ticker(self, symbol: str) -> FakeTicker:
        self.symbols.append(symbol)
        return self.ticker

    def set_tz_cache_location(self, cache_directory: str) -> None:
        self.cache_locations.append(cache_directory)


class YFinanceClientTests(unittest.TestCase):
    def test_historical_candles_calls_documented_ticker_history(self) -> None:
        api = FakeYFinanceApi(FakeHistory([(datetime(2024, 1, 2), ROW)]))
        client = YFinanceClient(limits=YFinanceLimits(0, 1_000), api=api)

        candles = client.historical_candles(
            "aapl",
            start_date="2024-01-02",
            end_date="2024-01-03",
            interval="1d",
            auto_adjust=False,
        )

        self.assertEqual(api.symbols, ["AAPL"])
        self.assertEqual(
            api.ticker.calls,
            [
                {
                    "start": "2024-01-02",
                    "end": "2024-01-03",
                    "interval": "1d",
                    "auto_adjust": False,
                    "actions": False,
                }
            ],
        )
        self.assertEqual(candles[0].date, "2024-01-02")
        self.assertEqual(str(candles[0].adjusted_close), "184.75")
        self.assertEqual(str(candles[0].volume), "82488700")

    def test_configures_yfinance_cache_when_directory_is_supplied(self) -> None:
        api = FakeYFinanceApi(FakeHistory([(datetime(2024, 1, 2), ROW)]))
        client = YFinanceClient(
            limits=YFinanceLimits(0, 1_000),
            api=api,
            cache_directory="G:/Program Files/Python314/yfinance-cache",
        )

        client.historical_candles("AAPL", start_date="2024-01-02", end_date="2024-01-03")

        self.assertEqual(api.cache_locations, ["G:/Program Files/Python314/yfinance-cache"])

    def test_symbols_dates_and_intervals_are_validated_before_request(self) -> None:
        api = FakeYFinanceApi(FakeHistory([(datetime(2024, 1, 2), ROW)]))
        client = YFinanceClient(limits=YFinanceLimits(0, 1_000), api=api)

        with self.assertRaisesRegex(ValueError, "symbols"):
            client.historical_candles("AAPL/US", start_date="2024-01-02", end_date="2024-01-03")
        with self.assertRaisesRegex(ValueError, "end_date"):
            client.historical_candles("AAPL", start_date="2024-01-03", end_date="2024-01-03")
        with self.assertRaisesRegex(ValueError, "interval"):
            client.historical_candles(
                "AAPL", start_date="2024-01-02", end_date="2024-01-03", interval="1h"
            )
        self.assertEqual(api.symbols, [])

    def test_daily_guard_limits_repeated_requests(self) -> None:
        api = FakeYFinanceApi(FakeHistory([]))
        client = YFinanceClient(
            limits=YFinanceLimits(0, 1),
            api=api,
            clock=lambda: 0,
            current_date=lambda: date(2026, 7, 26),
        )

        self.assertEqual(
            client.historical_candles("AAPL", start_date="2024-01-02", end_date="2024-01-03"), ()
        )
        with self.assertRaises(YFinanceRateLimitError):
            client.historical_candles("AAPL", start_date="2024-01-02", end_date="2024-01-03")
        self.assertEqual(api.symbols, ["AAPL"])


class YFinanceToolTests(unittest.TestCase):
    def test_tool_returns_most_recent_requested_rows(self) -> None:
        api = FakeYFinanceApi(
            FakeHistory(
                [
                    (datetime(2024, 1, 2), ROW),
                    (datetime(2024, 1, 3), {**ROW, "Close": 184.25}),
                ]
            )
        )
        client = YFinanceClient(limits=YFinanceLimits(0, 1_000), api=api)
        registry = ToolRegistry((create_yfinance_market_data_tool(client),))

        result = registry.execute(
            "yfinance_market_data",
            {
                "symbol": "AAPL",
                "start_date": "2024-01-02",
                "end_date": "2024-01-04",
                "limit": 1,
            },
        )

        payload = json.loads(result)
        self.assertEqual(payload["source"], "yfinance (Yahoo Finance)")
        self.assertEqual((payload["returned_rows"], payload["shown_rows"]), (2, 1))
        self.assertEqual(payload["candles"][0]["date"], "2024-01-03")


class YFinanceCliTests(unittest.TestCase):
    def test_source_status_describes_token_free_personal_research_source(self) -> None:
        output: list[str] = []
        with patch.dict("os.environ", {}, clear=True):
            result = run_source_command(["status", "yfinance"], output=output.append)

        self.assertEqual(result, 0)
        self.assertEqual(
            output,
            ["yfinance: no token required; local 1,000 requests/day guard for personal research"],
        )


if __name__ == "__main__":
    unittest.main()
