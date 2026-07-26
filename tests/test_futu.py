from __future__ import annotations

from datetime import date
import json
import unittest

from ai_agent.cli import run_source_command
from ai_agent.market_data.futu import (
    FutuApiError,
    FutuClient,
    FutuLimits,
    FutuOpenDEndpoint,
    FutuRateLimitError,
)
from ai_agent.tools import ToolRegistry, create_futu_market_data_tool


HISTORY_ROW = {
    "time_key": "2024-01-02 00:00:00",
    "code": "HK.00700",
    "name": "Tencent",
    "open": 280.0,
    "close": 285.0,
    "high": 287.0,
    "low": 279.0,
    "last_close": 278.0,
    "volume": 1200000,
    "turnover": 340000000,
    "turnover_rate": 0.42,
    "change_rate": 2.52,
    "pe_ratio": 18.4,
}

SNAPSHOT_ROW = {
    "code": "US.AAPL",
    "name": "Apple",
    "update_time": "2026-07-26 10:30:00",
    "last_price": 210.25,
    "open_price": 208.0,
    "high_price": 211.0,
    "low_price": 207.5,
    "prev_close_price": 207.9,
    "volume": 1000000,
    "turnover": 209000000,
    "turnover_rate": 0.2,
    "pe_ratio": 31.5,
    "pb_ratio": 45.1,
}


class FakeDataFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row


class FakeQuoteContext:
    def __init__(self) -> None:
        self.history_result: tuple[object, ...] = (0, FakeDataFrame([HISTORY_ROW]), None)
        self.snapshot_result: tuple[object, ...] = (0, FakeDataFrame([SNAPSHOT_ROW]))
        self.history_calls: list[tuple[str, dict[str, object]]] = []
        self.snapshot_calls: list[list[str]] = []
        self.close_calls = 0

    def request_history_kline(self, code: str, **kwargs: object) -> tuple[object, ...]:
        self.history_calls.append((code, kwargs))
        return self.history_result

    def get_market_snapshot(self, codes: list[str]) -> tuple[object, ...]:
        self.snapshot_calls.append(codes)
        return self.snapshot_result

    def close(self) -> None:
        self.close_calls += 1


class FakeFutuApi:
    RET_OK = 0

    def __init__(self, context: FakeQuoteContext) -> None:
        self.context = context
        self.open_context_calls: list[dict[str, object]] = []

    def OpenQuoteContext(self, **kwargs: object) -> FakeQuoteContext:
        self.open_context_calls.append(kwargs)
        return self.context


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class SocketProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, int], float]] = []
        self.sockets: list[FakeSocket] = []

    def __call__(self, address: tuple[str, int], timeout: float) -> FakeSocket:
        self.calls.append((address, timeout))
        connection = FakeSocket()
        self.sockets.append(connection)
        return connection


class FutuClientTests(unittest.TestCase):
    def make_client(
        self,
        *,
        limits: FutuLimits = FutuLimits(0, 500),
        clock=lambda: 0,
    ) -> tuple[FutuClient, FakeQuoteContext, FakeFutuApi, SocketProbe]:
        context = FakeQuoteContext()
        api = FakeFutuApi(context)
        probe = SocketProbe()
        return (
            FutuClient(
                api=api,
                limits=limits,
                socket_factory=probe,
                clock=clock,
                current_date=lambda: date(2026, 7, 26),
            ),
            context,
            api,
            probe,
        )

    def test_historical_candles_calls_open_quote_context_and_maps_rows(self) -> None:
        client, context, api, probe = self.make_client()

        candles = client.historical_candles(
            "hk.00700",
            start_date="2024-01-02",
            end_date="2024-01-03",
            interval="d",
            autype="qfq",
        )

        self.assertEqual(probe.calls, [(("127.0.0.1", 11111), 1.0)])
        self.assertTrue(probe.sockets[0].closed)
        self.assertEqual(api.open_context_calls, [{"host": "127.0.0.1", "port": 11111}])
        self.assertEqual(
            context.history_calls,
            [
                (
                    "HK.00700",
                    {
                        "start": "2024-01-02",
                        "end": "2024-01-03",
                        "ktype": "K_DAY",
                        "autype": "qfq",
                        "max_count": 1000,
                    },
                )
            ],
        )
        self.assertEqual(candles[0].time_key, "2024-01-02 00:00:00")
        self.assertEqual(str(candles[0].close_price), "285.0")
        self.assertEqual(str(candles[0].turnover_rate_percent), "0.42")
        self.assertEqual(context.close_calls, 1)

    def test_snapshot_is_bounded_and_maps_provider_time(self) -> None:
        client, context, _, _ = self.make_client()

        snapshots = client.market_snapshot(["us.aapl"])

        self.assertEqual(context.snapshot_calls, [["US.AAPL"]])
        self.assertEqual(snapshots[0].update_time, "2026-07-26 10:30:00")
        self.assertEqual(str(snapshots[0].last_price), "210.25")
        with self.assertRaisesRegex(ValueError, "1 to 50"):
            client.market_snapshot([])

    def test_rejects_unpaged_history_that_has_more_rows(self) -> None:
        client, context, _, _ = self.make_client()
        context.history_result = (0, FakeDataFrame([HISTORY_ROW]), "next-page")

        with self.assertRaisesRegex(FutuApiError, "more than 1,000"):
            client.historical_candles(
                "HK.00700", start_date="2024-01-02", end_date="2024-01-03"
            )
        self.assertEqual(context.close_calls, 1)

    def test_validates_code_dates_and_options_before_connecting(self) -> None:
        client, context, _, probe = self.make_client()

        with self.assertRaisesRegex(ValueError, "market prefix"):
            client.historical_candles(
                "AAPL", start_date="2024-01-02", end_date="2024-01-03"
            )
        with self.assertRaisesRegex(ValueError, "start_date"):
            client.historical_candles(
                "US.AAPL", start_date="2024-01-04", end_date="2024-01-03"
            )
        with self.assertRaisesRegex(ValueError, "interval"):
            client.historical_candles(
                "US.AAPL", start_date="2024-01-02", end_date="2024-01-03", interval="1m"
            )
        self.assertEqual(probe.calls, [])
        self.assertEqual(context.history_calls, [])

    def test_daily_guard_rejects_repeated_requests(self) -> None:
        client, _, _, _ = self.make_client(limits=FutuLimits(0, 1))

        client.market_snapshot(["US.AAPL"])
        with self.assertRaises(FutuRateLimitError):
            client.market_snapshot(["US.AAPL"])


class FutuToolTests(unittest.TestCase):
    def test_tool_returns_bounded_recent_candles(self) -> None:
        client, context, _, _ = FutuClientTests().make_client()
        context.history_result = (
            0,
            FakeDataFrame([HISTORY_ROW, {**HISTORY_ROW, "time_key": "2024-01-03 00:00:00"}]),
            None,
        )
        registry = ToolRegistry((create_futu_market_data_tool(client),))

        result = registry.execute(
            "futu_market_data",
            {
                "action": "historical_candles",
                "code": "HK.00700",
                "start_date": "2024-01-02",
                "end_date": "2024-01-03",
                "limit": 1,
            },
        )

        payload = json.loads(result)
        self.assertEqual(payload["source"], "Futu OpenAPI (FutuOpenD)")
        self.assertEqual((payload["returned_rows"], payload["shown_rows"]), (2, 1))
        self.assertEqual(payload["candles"][0]["time_key"], "2024-01-03 00:00:00")

    def test_tool_returns_snapshots_without_trading_fields(self) -> None:
        client, _, _, _ = FutuClientTests().make_client()
        registry = ToolRegistry((create_futu_market_data_tool(client),))

        result = registry.execute(
            "futu_market_data", {"action": "market_snapshot", "codes": ["US.AAPL"]}
        )

        payload = json.loads(result)
        self.assertEqual(payload["snapshots"][0]["code"], "US.AAPL")
        self.assertNotIn("account", payload)


class FutuCliTests(unittest.TestCase):
    def test_source_check_reports_reachable_local_gateway_without_claiming_permissions(self) -> None:
        output: list[str] = []

        class ReachableClient:
            def check_opend(self) -> FutuOpenDEndpoint:
                return FutuOpenDEndpoint("127.0.0.1", 11111)

        result = run_source_command(
            ["check", "futu"],
            futu_client_factory=ReachableClient,
            output=output.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            output,
            [
                "futu: FutuOpenD TCP port reachable at 127.0.0.1:11111; "
                "login and market-data permissions are checked when data is requested"
            ],
        )


if __name__ == "__main__":
    unittest.main()
