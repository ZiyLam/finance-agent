from __future__ import annotations

from datetime import date
import json
from urllib.parse import parse_qs, urlparse
import unittest

from ai_agent.cli import run_source_command
from ai_agent.market_data.alphavantage import (
    AlphaVantageClient,
    AlphaVantageLimits,
    AlphaVantageRateLimitError,
)
from ai_agent.tools import ToolRegistry, create_alphavantage_market_data_tool


DAILY_PAYLOAD = {
    "Meta Data": {"1. Information": "Daily Prices (open, high, low, close) and Volumes"},
    "Time Series (Daily)": {
        "2024-01-03": {
            "1. open": "184.2200",
            "2. high": "185.8800",
            "3. low": "183.4300",
            "4. close": "184.2500",
            "5. volume": "58414460",
        },
        "2024-01-02": {
            "1. open": "187.1500",
            "2. high": "188.4400",
            "3. low": "183.8850",
            "4. close": "185.6400",
            "5. volume": "82488700",
        },
    },
}


class RecordingTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return json.dumps(self.payload).encode("utf-8")


class AlphaVantageClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = AlphaVantageLimits(0, 25)

    def test_daily_candles_use_documented_free_compact_endpoint(self) -> None:
        transport = RecordingTransport(DAILY_PAYLOAD)
        client = AlphaVantageClient("test-key", limits=self.limits, transport=transport)

        candles = client.daily_candles("ibm")

        query = parse_qs(urlparse(transport.urls[0]).query)
        self.assertEqual(query["function"], ["TIME_SERIES_DAILY"])
        self.assertEqual(query["symbol"], ["IBM"])
        self.assertEqual(query["outputsize"], ["compact"])
        self.assertEqual(query["apikey"], ["test-key"])
        self.assertEqual([candle.date for candle in candles], ["2024-01-02", "2024-01-03"])
        self.assertEqual(str(candles[0].volume), "82488700")

    def test_global_quote_and_symbol_search_map_documented_fields(self) -> None:
        quote_transport = RecordingTransport(
            {
                "Global Quote": {
                    "01. symbol": "IBM",
                    "02. open": "170.00",
                    "03. high": "171.00",
                    "04. low": "169.00",
                    "05. price": "170.50",
                    "06. volume": "1000",
                    "07. latest trading day": "2024-01-03",
                    "08. previous close": "169.50",
                    "09. change": "1.00",
                    "10. change percent": "0.5899%",
                }
            }
        )
        quote_client = AlphaVantageClient("test-key", limits=self.limits, transport=quote_transport)
        quote = quote_client.global_quote("IBM")
        self.assertEqual(quote.latest_trading_day, "2024-01-03")
        self.assertEqual(str(quote.change_percent), "0.5899")
        self.assertEqual(parse_qs(urlparse(quote_transport.urls[0]).query)["function"], ["GLOBAL_QUOTE"])

        search_transport = RecordingTransport(
            {
                "bestMatches": [
                    {
                        "1. symbol": "IBM",
                        "2. name": "International Business Machines Corporation",
                        "3. type": "Equity",
                        "4. region": "United States",
                        "8. currency": "USD",
                        "9. matchScore": "1.0000",
                    }
                ]
            }
        )
        search_client = AlphaVantageClient("test-key", limits=self.limits, transport=search_transport)
        matches = search_client.symbol_search("international business")
        self.assertEqual(matches[0].symbol, "IBM")
        self.assertEqual(str(matches[0].match_score), "1.0000")
        self.assertEqual(parse_qs(urlparse(search_transport.urls[0]).query)["function"], ["SYMBOL_SEARCH"])

    def test_provider_note_and_daily_guard_do_not_make_unbounded_requests(self) -> None:
        client = AlphaVantageClient(
            "test-key",
            limits=AlphaVantageLimits(0, 1),
            transport=RecordingTransport({"Note": "provider limit"}),
            clock=lambda: 0,
            current_date=lambda: date(2026, 7, 26),
        )
        with self.assertRaises(AlphaVantageRateLimitError):
            client.daily_candles("IBM")
        with self.assertRaises(AlphaVantageRateLimitError):
            client.daily_candles("IBM")

    def test_invalid_symbols_are_rejected_before_request(self) -> None:
        transport = RecordingTransport(DAILY_PAYLOAD)
        client = AlphaVantageClient("test-key", limits=self.limits, transport=transport)

        with self.assertRaisesRegex(ValueError, "symbols"):
            client.daily_candles("IBM/US")
        self.assertEqual(transport.urls, [])


class AlphaVantageToolTests(unittest.TestCase):
    def test_daily_tool_bounds_rows_and_discloses_raw_compact_series(self) -> None:
        client = AlphaVantageClient(
            "test-key", limits=AlphaVantageLimits(0, 25), transport=RecordingTransport(DAILY_PAYLOAD)
        )
        registry = ToolRegistry((create_alphavantage_market_data_tool(client),))

        result = registry.execute(
            "alphavantage_market_data", {"action": "daily_candles", "symbol": "IBM", "limit": 1}
        )

        payload = json.loads(result)
        self.assertEqual(payload["source"], "Alpha Vantage")
        self.assertEqual((payload["returned_rows"], payload["shown_rows"]), (2, 1))
        self.assertEqual(payload["candles"][0]["date"], "2024-01-03")
        self.assertIn("raw, compact", payload["series"])


class AlphaVantageCliTests(unittest.TestCase):
    def test_source_status_uses_existing_secure_token_maintenance_path(self) -> None:
        output: list[str] = []
        result = run_source_command(["status", "alphavantage"], output=output.append)

        self.assertEqual(result, 0)
        self.assertEqual(len(output), 1)
        self.assertTrue(output[0].startswith("alphavantage: "))


if __name__ == "__main__":
    unittest.main()
