from __future__ import annotations

import json
import unittest
from urllib.error import URLError

from ai_agent.market_data.zhitu import ZhituClient, ZhituLimits, ZhituTransportError
from ai_agent.tools import ToolRegistry, create_zhitu_market_data_tool


def _history_payload() -> bytes:
    return json.dumps(
        [
            {"t": "2026年07月20日", "o": 100, "h": 102, "l": 99, "c": 101, "pc": 98, "v": 10, "a": 1000},
            {"t": "2026年07月21日", "o": 101, "h": 103, "l": 100, "c": 102, "pc": 101, "v": 20, "a": 2000},
        ]
    ).encode("utf-8")


class ZhituClientTests(unittest.TestCase):
    def test_index_history_uses_documented_path_and_normalizes_rows(self) -> None:
        requests: list[str] = []
        client = ZhituClient(
            "test-token",
            limits=ZhituLimits(0, 300),
            transport=lambda url: requests.append(url) or _history_payload(),
        )

        candles = client.index_daily_candles(
            "000905.SH",
            start_date="2026-07-20",
            end_date="2026-07-21",
            limit=1,
        )

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].date, "2026-07-21")
        self.assertEqual(str(candles[0].close_price), "102")
        self.assertIn("/hz/history/fsjy/000905.SH/d?", requests[0])
        self.assertIn("st=20260720", requests[0])
        self.assertIn("et=20260721", requests[0])

    def test_stock_quote_uses_documented_code_only_path(self) -> None:
        requests: list[str] = []
        payload = json.dumps(
            {"p": 101, "pc": 100, "o": 100, "h": 102, "l": 99, "v": 10, "cje": 1000, "ud": 1, "zf": 1}
        ).encode("utf-8")
        client = ZhituClient(
            "test-token",
            limits=ZhituLimits(0, 300),
            transport=lambda url: requests.append(url) or payload,
        )

        quote = client.stock_quote("600000.SH")

        self.assertEqual(quote.symbol, "600000.SH")
        self.assertEqual(str(quote.last_price), "101")
        self.assertIn("/hs/real/ssjy/600000?", requests[0])

    def test_transport_failure_never_exposes_a_token_bearing_url(self) -> None:
        client = ZhituClient(
            "private-token",
            limits=ZhituLimits(0, 300),
            transport=lambda _url: (_ for _ in ()).throw(URLError("network unavailable")),
        )

        with self.assertRaises(ZhituTransportError) as error:
            client.index_quote("000905.SH")

        self.assertNotIn("private-token", str(error.exception))

    def test_tool_returns_normalized_candles_without_the_api_key(self) -> None:
        client = ZhituClient(
            "test-token",
            limits=ZhituLimits(0, 300),
            transport=lambda _url: _history_payload(),
        )
        registry = ToolRegistry((create_zhitu_market_data_tool(client),))

        response = registry.execute(
            "zhitu_market_data",
            {
                "action": "index_history",
                "symbol": "000905.SH",
                "start_date": "2026-07-20",
                "end_date": "2026-07-21",
                "limit": 2,
            },
        )
        payload = json.loads(response)

        self.assertEqual(payload["source"], "智兔数服")
        self.assertEqual(payload["candles"][0]["date"], "2026-07-20")
        self.assertNotIn("test-token", response)


if __name__ == "__main__":
    unittest.main()
