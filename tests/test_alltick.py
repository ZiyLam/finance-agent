from __future__ import annotations

import json
import unittest
from datetime import date
from urllib.parse import parse_qs, urlparse

from ai_agent.market_data.alltick import (
    AllTickAssetClass,
    AllTickClient,
    AllTickKlineType,
    AllTickLimits,
    AllTickRateLimitError,
)


class RecordingTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return json.dumps(self.payload).encode("utf-8")


class AllTickClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = AllTickLimits(0, 10, 100, 5)

    def test_latest_quotes_encodes_query_and_parses_decimal_values(self) -> None:
        transport = RecordingTransport(
            {
                "ret": 200,
                "msg": "ok",
                "trace": "server-trace",
                "data": {
                    "tick_list": [
                        {
                            "code": "UNH.US",
                            "seq": "12",
                            "tick_time": "1677831545217",
                            "price": "136.302",
                            "volume": "0",
                            "turnover": "0",
                            "trade_direction": 1,
                        }
                    ]
                },
            }
        )
        client = AllTickClient("test-token", limits=self.limits, transport=transport)

        quotes = client.latest_quotes(["UNH.US"])

        self.assertEqual(str(quotes[0].price), "136.302")
        parsed = urlparse(transport.urls[0])
        self.assertEqual(parsed.path, "/quote-stock-b-api/trade-tick")
        query = parse_qs(parsed.query)
        self.assertEqual(query["token"], ["test-token"])
        self.assertEqual(json.loads(query["query"][0])["data"]["symbol_list"], [{"code": "UNH.US"}])

    def test_historical_candles_uses_other_asset_path_and_documented_payload(self) -> None:
        transport = RecordingTransport(
            {
                "ret": 200,
                "msg": "ok",
                "trace": "server-trace",
                "data": {
                    "kline_list": [
                        {
                            "timestamp": "1677829200",
                            "open_price": "1.01",
                            "close_price": "1.02",
                            "high_price": "1.03",
                            "low_price": "1.00",
                            "volume": "10",
                            "turnover": "10.2",
                        }
                    ]
                },
            }
        )
        client = AllTickClient("test-token", limits=self.limits, transport=transport)

        candles = client.historical_candles(
            "EURUSD",
            asset_class=AllTickAssetClass.OTHER,
            kline_type=AllTickKlineType.HOUR_1,
            count=2,
            timestamp_end=123,
        )

        self.assertEqual(str(candles[0].close_price), "1.02")
        parsed = urlparse(transport.urls[0])
        self.assertEqual(parsed.path, "/quote-b-api/kline")
        data = json.loads(parse_qs(parsed.query)["query"][0])["data"]
        self.assertEqual(data["kline_timestamp_end"], 123)
        self.assertEqual(data["query_kline_num"], 2)

    def test_local_interval_guard_rejects_second_request_without_calling_transport(self) -> None:
        transport = RecordingTransport({"ret": 200, "msg": "ok", "data": {"tick_list": []}})
        client = AllTickClient(
            "test-token",
            limits=AllTickLimits(10, 10, 100, 5),
            transport=transport,
            clock=lambda: 100.0,
            current_date=lambda: date(2026, 7, 26),
        )

        client.latest_quotes(["UNH.US"])
        with self.assertRaises(AllTickRateLimitError):
            client.latest_quotes(["UNH.US"])
        self.assertEqual(len(transport.urls), 1)


if __name__ == "__main__":
    unittest.main()
