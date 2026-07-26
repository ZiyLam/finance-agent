from __future__ import annotations

from datetime import date
import json
from urllib.parse import parse_qs, unquote, urlparse
import unittest

from ai_agent.cli import run_source_command
from ai_agent.market_data.eodhd import EODHDApiError, EODHDClient, EODHDLimits, EODHDRateLimitError
from ai_agent.tools import ToolRegistry, create_eodhd_market_data_tool


HISTORY_PAYLOAD = [
    {
        "date": "2024-01-02",
        "open": 187.15,
        "high": 188.44,
        "low": 183.885,
        "close": 185.64,
        "adjusted_close": 183.76,
        "volume": 82488700,
    },
    {
        "date": "2024-01-03",
        "open": 184.22,
        "high": 185.88,
        "low": 183.43,
        "close": 184.25,
        "adjusted_close": 182.39,
        "volume": 58414460,
    },
]


class RecordingTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return json.dumps(self.payload).encode("utf-8")


class EODHDClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = EODHDLimits(0, 20)

    def test_historical_candles_use_documented_eod_path_and_parameters(self) -> None:
        transport = RecordingTransport(HISTORY_PAYLOAD)
        client = EODHDClient("test-token", limits=self.limits, transport=transport)

        candles = client.historical_candles(
            "aapl.us", start_date="2024-01-02", end_date="2024-01-03", period="d"
        )

        parsed = urlparse(transport.urls[0])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/eod/AAPL.US")
        self.assertEqual(query["api_token"], ["test-token"])
        self.assertEqual(query["from"], ["2024-01-02"])
        self.assertEqual(query["to"], ["2024-01-03"])
        self.assertEqual(query["period"], ["d"])
        self.assertEqual(query["fmt"], ["json"])
        self.assertEqual(candles[0].date, "2024-01-02")
        self.assertEqual(str(candles[0].adjusted_close), "183.76")
        self.assertEqual(str(candles[0].volume), "82488700")

    def test_search_returns_eod_symbol_form_and_uses_bounded_limit(self) -> None:
        transport = RecordingTransport(
            [
                {
                    "Code": "AAPL",
                    "Exchange": "US",
                    "Name": "Apple Inc",
                    "Type": "Common Stock",
                    "Country": "USA",
                    "Currency": "USD",
                }
            ]
        )
        client = EODHDClient("test-token", limits=self.limits, transport=transport)

        matches = client.search("Apple Inc", limit=1)

        parsed = urlparse(transport.urls[0])
        self.assertEqual(unquote(parsed.path), "/api/search/Apple Inc")
        self.assertEqual(parse_qs(parsed.query)["limit"], ["1"])
        self.assertEqual(matches[0].symbol, "AAPL.US")
        self.assertEqual(matches[0].currency, "USD")

    def test_daily_guard_rejects_second_request_after_provider_rejection(self) -> None:
        client = EODHDClient(
            "test-token",
            limits=EODHDLimits(0, 1),
            transport=RecordingTransport({"error": "provider limit"}),
            clock=lambda: 0,
            current_date=lambda: date(2026, 7, 26),
        )

        with self.assertRaises(EODHDApiError):
            client.historical_candles("AAPL.US", start_date="2024-01-02", end_date="2024-01-03")
        with self.assertRaises(EODHDRateLimitError):
            client.historical_candles("AAPL.US", start_date="2024-01-02", end_date="2024-01-03")

    def test_symbol_dates_and_period_are_validated_before_request(self) -> None:
        transport = RecordingTransport(HISTORY_PAYLOAD)
        client = EODHDClient("test-token", limits=self.limits, transport=transport)

        with self.assertRaisesRegex(ValueError, "exchange suffix"):
            client.historical_candles("AAPL", start_date="2024-01-02", end_date="2024-01-03")
        with self.assertRaisesRegex(ValueError, "end_date"):
            client.historical_candles("AAPL.US", start_date="2024-01-03", end_date="2024-01-02")
        with self.assertRaisesRegex(ValueError, "period"):
            client.historical_candles(
                "AAPL.US", start_date="2024-01-02", end_date="2024-01-03", period="1d"
            )
        self.assertEqual(transport.urls, [])


class EODHDToolTests(unittest.TestCase):
    def test_historical_tool_bounds_rows_and_includes_adjusted_close(self) -> None:
        client = EODHDClient(
            "test-token", limits=EODHDLimits(0, 20), transport=RecordingTransport(HISTORY_PAYLOAD)
        )
        registry = ToolRegistry((create_eodhd_market_data_tool(client),))

        result = registry.execute(
            "eodhd_market_data",
            {
                "action": "historical_candles",
                "symbol": "AAPL.US",
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
                "limit": 1,
            },
        )

        payload = json.loads(result)
        self.assertEqual(payload["source"], "EOD Historical Data (EODHD)")
        self.assertEqual((payload["returned_rows"], payload["shown_rows"]), (2, 1))
        self.assertEqual(payload["candles"][0]["date"], "2024-01-03")
        self.assertEqual(payload["candles"][0]["adjusted_close"], "182.39")


class EODHDCliTests(unittest.TestCase):
    def test_source_status_uses_existing_secure_token_maintenance_path(self) -> None:
        output: list[str] = []
        result = run_source_command(["status", "eodhd"], output=output.append)

        self.assertEqual(result, 0)
        self.assertEqual(len(output), 1)
        self.assertTrue(output[0].startswith("eodhd: "))


if __name__ == "__main__":
    unittest.main()
