from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ai_agent.cli import run_source_command
from ai_agent.market_data.biying import BiyingClient, BiyingLimits


class RecordingTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return json.dumps(self.response).encode("utf-8")


class BiyingClientTests(unittest.TestCase):
    def test_realtime_quote_uses_documented_certificate_path_and_maps_fields(self) -> None:
        transport = RecordingTransport(
            [{"p": 11.64, "pc": -0.17, "o": 11.69, "h": 11.71, "l": 11.55, "v": 973969, "cje": 113.2, "pe": 4.26, "sjl": 0.54, "t": "2025-02-21 15:29:05"}]
        )
        client = BiyingClient("test-certificate", limits=BiyingLimits(0, 300, 100), transport=transport)

        quote = client.realtime_quote("000001")

        self.assertEqual(str(quote.price), "11.64")
        self.assertEqual(str(quote.dynamic_pe), "4.26")
        self.assertEqual(quote.updated_at, "2025-02-21 15:29:05")
        self.assertEqual(transport.urls, ["https://api.biyingapi.com/hsrl/ssjy/000001/test-certificate"])

    def test_find_stocks_returns_bounded_matching_results(self) -> None:
        transport = RecordingTransport(
            [
                {"dm": "000001", "mc": "平安银行", "jys": "sz"},
                {"dm": "000002", "mc": "万科A", "jys": "sz"},
            ]
        )
        client = BiyingClient("test-certificate", limits=BiyingLimits(0, 300, 100), transport=transport)

        matches = client.find_stocks("平安")

        self.assertEqual([(item.code, item.name) for item in matches], [("000001", "平安银行")])
        self.assertEqual(transport.urls, ["https://api.biyingapi.com/hslt/list/test-certificate"])

    def test_source_status_recognizes_biying_environment_variable(self) -> None:
        output: list[str] = []
        with patch.dict("os.environ", {"BIYING_API_LICENCE": "temporary-test-certificate"}):
            result = run_source_command(["status", "biying"], output=output.append)

        self.assertEqual(result, 0)
        self.assertEqual(output, ["biying: configured via environment variable"])


if __name__ == "__main__":
    unittest.main()
