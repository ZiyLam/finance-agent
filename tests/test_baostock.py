from __future__ import annotations

from datetime import date
import json
from unittest.mock import patch
import unittest

from ai_agent.cli import run_source_command
from ai_agent.market_data.baostock import (
    BaoStockClient,
    BaoStockLimits,
    BaoStockRateLimitError,
)
from ai_agent.tools import ToolRegistry, create_baostock_market_data_tool


FIELDS = [
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "adjustflag",
    "turn",
    "tradestatus",
    "pctChg",
    "isST",
]
ROW = [
    "2024-01-02",
    "sh.600000",
    "7.10",
    "7.24",
    "7.08",
    "7.20",
    "7.10",
    "3000000",
    "21500000",
    "3",
    "0.50",
    "1",
    "1.41",
    "0",
]


class Result:
    def __init__(self, rows: list[list[str]], *, error_code: str = "0", error_msg: str = "") -> None:
        self.error_code = error_code
        self.error_msg = error_msg
        self.fields = FIELDS
        self._rows = rows
        self._index = 0

    def next(self) -> bool:
        if self._index >= len(self._rows):
            return False
        self._index += 1
        return True

    def get_row_data(self) -> list[str]:
        return self._rows[self._index - 1]


class FakeBaoStockApi:
    def __init__(self, *, login_result: Result | None = None, query_result: Result | None = None) -> None:
        self.login_result = login_result or Result([])
        self.query_result = query_result or Result([ROW])
        self.query_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.login_calls = 0
        self.logout_calls = 0

    def login(self) -> Result:
        self.login_calls += 1
        return self.login_result

    def query_history_k_data_plus(self, *args: object, **kwargs: object) -> Result:
        self.query_calls.append((args, kwargs))
        return self.query_result

    def logout(self) -> None:
        self.logout_calls += 1


class BaoStockClientTests(unittest.TestCase):
    def test_historical_candles_uses_documented_anonymous_session_and_parameters(self) -> None:
        api = FakeBaoStockApi()
        client = BaoStockClient(limits=BaoStockLimits(0, 5_000), api=api)

        candles = client.historical_candles(
            "SH.600000",
            start_date="2024-01-02",
            end_date="2024-01-03",
            frequency="d",
            adjustflag="3",
        )

        self.assertEqual(api.login_calls, 1)
        self.assertEqual(api.logout_calls, 1)
        self.assertEqual(api.query_calls[0][0][0], "sh.600000")
        self.assertEqual(
            api.query_calls[0][1],
            {
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
                "frequency": "d",
                "adjustflag": "3",
            },
        )
        self.assertEqual(len(candles), 1)
        self.assertEqual(str(candles[0].close_price), "7.20")
        self.assertEqual(str(candles[0].change_percent), "1.41")

    def test_failed_login_does_not_query_or_logout(self) -> None:
        api = FakeBaoStockApi(login_result=Result([], error_code="100", error_msg="login rejected"))
        client = BaoStockClient(limits=BaoStockLimits(0, 5_000), api=api)

        with self.assertRaisesRegex(Exception, "login rejected"):
            client.historical_candles(
                "sh.600000", start_date="2024-01-02", end_date="2024-01-03"
            )

        self.assertEqual(api.query_calls, [])
        self.assertEqual(api.logout_calls, 0)

    def test_daily_guard_stays_below_documented_ip_ceiling(self) -> None:
        api = FakeBaoStockApi()
        client = BaoStockClient(
            limits=BaoStockLimits(0, 1),
            api=api,
            clock=lambda: 0,
            current_date=lambda: date(2026, 7, 26),
        )

        client.historical_candles("sh.600000", start_date="2024-01-02", end_date="2024-01-03")
        with self.assertRaises(BaoStockRateLimitError):
            client.historical_candles("sh.600000", start_date="2024-01-02", end_date="2024-01-03")
        self.assertEqual(api.login_calls, 1)


class BaoStockToolTests(unittest.TestCase):
    def test_tool_returns_bounded_recent_rows(self) -> None:
        api = FakeBaoStockApi(query_result=Result([ROW, ["2024-01-03", *ROW[1:]]]))
        client = BaoStockClient(limits=BaoStockLimits(0, 5_000), api=api)
        registry = ToolRegistry((create_baostock_market_data_tool(client),))

        result = registry.execute(
            "baostock_market_data",
            {
                "code": "sh.600000",
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
                "limit": 1,
            },
        )

        payload = json.loads(result)
        self.assertEqual((payload["returned_rows"], payload["shown_rows"]), (2, 1))
        self.assertEqual(payload["candles"][0]["date"], "2024-01-03")


class BaoStockCliTests(unittest.TestCase):
    def test_source_status_describes_token_free_quota_guard(self) -> None:
        output: list[str] = []
        with patch.dict("os.environ", {}, clear=True):
            result = run_source_command(["status", "baostock"], output=output.append)

        self.assertEqual(result, 0)
        self.assertEqual(
            output,
            ["baostock: no token required; anonymous sessions use a local 5,000 requests/day guard"],
        )


if __name__ == "__main__":
    unittest.main()
