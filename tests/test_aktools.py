from __future__ import annotations

import json
from unittest.mock import patch
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from ai_agent.cli import run_source_command
from ai_agent.market_data.aktools import (
    AkToolsClient,
    AkToolsLimits,
    AkToolsTransportError,
    AkToolsServiceVersion,
)
from ai_agent.tools import ToolRegistry, create_aktools_market_data_tool


class RecordingTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return json.dumps(self.response, ensure_ascii=False).encode("utf-8")


SAMPLE_CANDLE = {
    "日期": "2021-11-09",
    "开盘": 3009.83,
    "收盘": 3017.96,
    "最高": 3037.46,
    "最低": 2974.07,
    "成交量": 1240573,
    "成交额": 2163193120,
    "振幅": 2.11,
    "涨跌幅": 0.6,
    "涨跌额": 17.88,
    "换手率": 0.64,
}


class AkToolsClientTests(unittest.TestCase):
    def test_historical_a_share_query_uses_documented_endpoint_and_maps_fields(self) -> None:
        transport = RecordingTransport([SAMPLE_CANDLE])
        client = AkToolsClient(
            "http://localhost:8080/",
            limits=AkToolsLimits(0),
            transport=transport,
        )

        candles = client.stock_zh_a_hist(
            "000001",
            period="weekly",
            start_date="20211109",
            end_date="20211209",
            adjust="hfq",
        )

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].date, "2021-11-09")
        self.assertEqual(str(candles[0].close_price), "3017.96")
        self.assertEqual(str(candles[0].turnover_rate_percent), "0.64")
        parsed_url = urlsplit(transport.urls[0])
        self.assertEqual(parsed_url.path, "/api/public/stock_zh_a_hist")
        self.assertEqual(
            parse_qs(parsed_url.query, keep_blank_values=True),
            {
                "symbol": ["000001"],
                "period": ["weekly"],
                "start_date": ["20211109"],
                "end_date": ["20211209"],
                "adjust": ["hfq"],
            },
        )

    def test_dates_and_choices_are_validated_before_network_access(self) -> None:
        transport = RecordingTransport([SAMPLE_CANDLE])
        client = AkToolsClient(limits=AkToolsLimits(0), transport=transport)

        with self.assertRaisesRegex(ValueError, "YYYYMMDD"):
            client.stock_zh_a_hist("000001", start_date="2021-11-09", end_date="20211209")
        with self.assertRaisesRegex(ValueError, "period"):
            client.stock_zh_a_hist(
                "000001", period="hourly", start_date="20211109", end_date="20211209"
            )
        self.assertEqual(transport.urls, [])

    def test_unreachable_service_has_a_startup_hint(self) -> None:
        def unavailable(_: str) -> bytes:
            raise URLError("connection refused")

        client = AkToolsClient(limits=AkToolsLimits(0), transport=unavailable)

        with self.assertRaisesRegex(AkToolsTransportError, "Start it"):
            client.stock_zh_a_hist("000001", start_date="20211109", end_date="20211209")

    def test_service_version_uses_local_version_endpoint(self) -> None:
        transport = RecordingTransport(
            {
                "at_current_version": "0.0.91",
                "at_latest_version": "0.0.91",
                "ak_current_version": "1.18.78",
                "ak_latest_version": "1.18.78",
            }
        )
        client = AkToolsClient(limits=AkToolsLimits(0), transport=transport)

        report = client.service_version()

        self.assertEqual(report.aktools_current, "0.0.91")
        self.assertEqual(urlsplit(transport.urls[0]).path, "/version")


class AkToolsToolTests(unittest.TestCase):
    def test_tool_limits_context_to_most_recent_requested_rows(self) -> None:
        second_candle = {**SAMPLE_CANDLE, "日期": "2021-11-10", "收盘": 2996.83}
        client = AkToolsClient(
            limits=AkToolsLimits(0), transport=RecordingTransport([SAMPLE_CANDLE, second_candle])
        )
        registry = ToolRegistry((create_aktools_market_data_tool(client),))

        result = registry.execute(
            "aktools_market_data",
            {
                "symbol": "000001",
                "start_date": "20211109",
                "end_date": "20211209",
                "limit": 1,
            },
        )

        payload = json.loads(result)
        self.assertEqual(payload["source"], "AkTools (local AKShare service)")
        self.assertEqual((payload["returned_rows"], payload["shown_rows"]), (2, 1))
        self.assertEqual(payload["candles"][0]["date"], "2021-11-10")

    def test_tool_returns_safe_error_when_local_service_is_not_running(self) -> None:
        def unavailable(_: str) -> bytes:
            raise URLError("connection refused")

        client = AkToolsClient(limits=AkToolsLimits(0), transport=unavailable)
        result = create_aktools_market_data_tool(client).run(
            {"symbol": "000001", "start_date": "20211109", "end_date": "20211209"}
        )

        self.assertTrue(result.startswith("ERROR: Could not reach the AkTools service."))


class AkToolsCliTests(unittest.TestCase):
    def test_source_status_describes_token_free_local_source(self) -> None:
        output: list[str] = []
        with patch.dict("os.environ", {}, clear=True):
            result = run_source_command(["status", "aktools"], output=output.append)

        self.assertEqual(result, 0)
        self.assertEqual(
            output,
            ["aktools: no token required; base URL from default local address (checked on demand)"],
        )

    def test_source_check_reports_current_aktools_service_version(self) -> None:
        output: list[str] = []

        result = run_source_command(
            ["check", "aktools"],
            output=output.append,
            aktools_client_factory=lambda: type(
                "VersionClient",
                (),
                {
                    "service_version": lambda self: AkToolsServiceVersion(
                        aktools_current="0.0.91",
                    )
                },
            )(),
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            output,
            ["aktools: local service version 0.0.91"],
        )


if __name__ == "__main__":
    unittest.main()
