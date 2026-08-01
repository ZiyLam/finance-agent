from __future__ import annotations

import json
from datetime import date
from threading import Event, Thread
from time import monotonic
import unittest

from ai_agent.application.beginner_research import BeginnerResearchService
from ai_agent.application.entity_resolution import HSBC_HK
from ai_agent.tools import FunctionTool, ToolRegistry


class BeginnerResearchServiceTests(unittest.TestCase):
    def test_returns_latest_available_bar_and_a_five_trading_day_window(self) -> None:
        def market_data(_arguments: object) -> str:
            return json.dumps(
                {
                    "source": "yfinance (Yahoo Finance)",
                    "candles": [
                        {"date": "2026-07-21", "close": "100", "high": "101", "low": "99", "volume": "10"},
                        {"date": "2026-07-22", "close": "101", "high": "102", "low": "100", "volume": "11"},
                        {"date": "2026-07-23", "close": "99", "high": "102", "low": "98", "volume": "12"},
                        {"date": "2026-07-24", "close": "103", "high": "104", "low": "99", "volume": "13"},
                        {"date": "2026-07-27", "close": "105", "high": "106", "low": "102", "volume": "14"},
                    ],
                }
            )

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("yfinance_market_data", "test", market_data),)
            ),
            today=lambda: date(2026, 7, 27),
        )

        snapshot = service.latest_week(HSBC_HK).to_dict()

        market = snapshot["market_data"]
        self.assertEqual(market["status"], "complete")
        self.assertEqual(market["latest"]["date"], "2026-07-27")
        self.assertEqual(market["recent_week"]["trading_days"], 5)
        self.assertEqual(market["recent_week"]["change_percent"], "5.00")
        self.assertEqual(market["recent_week"]["total_volume"], "60")
        self.assertEqual(snapshot["financial_reports"]["status"], "not_connected")

    def test_tool_failure_is_presented_as_unavailable_not_fabricated_data(self) -> None:
        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(),
            today=lambda: date(2026, 7, 27),
        )

        snapshot = service.latest_week(HSBC_HK).to_dict()

        self.assertEqual(snapshot["market_data"]["status"], "unavailable")
        self.assertEqual(snapshot["financial_reports"]["status"], "not_connected")

    def test_professional_period_uses_exact_dates_and_reports_full_window_performance(self) -> None:
        calls: list[dict[str, object]] = []

        def market_data(arguments: dict[str, object]) -> str:
            calls.append(arguments)
            return json.dumps(
                {
                    "source": "professional fixture",
                    "candles": [
                        {"date": "2026-06-01", "close": "100", "high": "102", "low": "99"},
                        {"date": "2026-06-15", "close": "108", "high": "110", "low": "104"},
                        {"date": "2026-06-30", "close": "120", "high": "121", "low": "118"},
                    ],
                }
            )

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("yfinance_market_data", "test", market_data),)
            )
        )

        snapshot = service.period(
            HSBC_HK,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
        ).to_dict()

        self.assertEqual(calls[0]["start_date"], "2026-06-01")
        self.assertEqual(calls[0]["end_date"], "2026-07-01")
        self.assertEqual(calls[0]["limit"], 120)
        performance = snapshot["market_data"]["period_performance"]
        self.assertEqual(performance["first_date"], "2026-06-01")
        self.assertEqual(performance["last_date"], "2026-06-30")
        self.assertEqual(performance["change_percent"], "20.00")
        self.assertEqual(snapshot["default_period"]["requested_end_date"], "2026-06-30")

    def test_prefers_configured_eodhd_for_a_known_global_listing(self) -> None:
        calls: list[tuple[str, object]] = []

        def eodhd_market_data(arguments: object) -> str:
            calls.append(("eodhd", arguments))
            return json.dumps(
                {
                    "source": "EOD Historical Data (EODHD)",
                    "candles": [
                        {"date": "2026-07-27", "close": "100", "high": "101", "low": "99", "volume": "10"},
                        {"date": "2026-07-28", "close": "101", "high": "102", "low": "100", "volume": "11"},
                    ],
                }
            )

        def unexpected_yfinance(arguments: object) -> str:
            calls.append(("yfinance", arguments))
            return "ERROR: fallback should not run"

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (
                    FunctionTool("eodhd_market_data", "test", eodhd_market_data),
                    FunctionTool("yfinance_market_data", "test", unexpected_yfinance),
                )
            ),
            today=lambda: date(2026, 7, 29),
        )

        snapshot = service.latest_week(HSBC_HK).to_dict()

        self.assertEqual(snapshot["market_data"]["source"], "EOD Historical Data (EODHD)")
        self.assertEqual(calls[0][0], "eodhd")
        self.assertEqual(calls[0][1]["symbol"], "0005.HK")
        self.assertEqual(calls[0][1]["end_date"], "2026-07-29")
        self.assertEqual(len(calls), 1)

    def test_prefers_configured_low_latency_tickflow_before_other_compatible_sources(self) -> None:
        calls: list[str] = []

        def tickflow_market_data(arguments: object) -> str:
            calls.append("tickflow")
            self.assertEqual(arguments["symbol"], "0005.HK")
            return json.dumps(
                {
                    "source": "TickFlow",
                    "candles": [
                        {"date": "2026-07-29", "close": "100", "high": "101", "low": "99", "volume": "10"},
                    ],
                }
            )

        def unexpected_eodhd(_arguments: object) -> str:
            calls.append("eodhd")
            return "ERROR: should not run"

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (
                    FunctionTool("tickflow_market_data", "test", tickflow_market_data),
                    FunctionTool("eodhd_market_data", "test", unexpected_eodhd),
                )
            ),
            today=lambda: date(2026, 7, 29),
        )

        snapshot = service.latest_week(HSBC_HK).to_dict()

        self.assertEqual(snapshot["market_data"]["source"], "TickFlow")
        self.assertEqual(calls, ["tickflow"])

    def test_falls_back_to_yfinance_when_eodhd_has_no_usable_candles(self) -> None:
        calls: list[str] = []

        def eodhd_market_data(_arguments: object) -> str:
            calls.append("eodhd")
            return "ERROR: source unavailable"

        def yfinance_market_data(_arguments: object) -> str:
            calls.append("yfinance")
            return json.dumps(
                {
                    "source": "yfinance (Yahoo Finance)",
                    "candles": [
                        {"date": "2026-07-27", "close": "100", "high": "101", "low": "99", "volume": "10"},
                    ],
                }
            )

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (
                    FunctionTool("eodhd_market_data", "test", eodhd_market_data),
                    FunctionTool("yfinance_market_data", "test", yfinance_market_data),
                )
            ),
            today=lambda: date(2026, 7, 27),
        )

        snapshot = service.latest_week(HSBC_HK).to_dict()

        self.assertEqual(calls, ["eodhd", "yfinance"])
        self.assertEqual(snapshot["market_data"]["source"], "yfinance (Yahoo Finance)")

    def test_stalled_source_returns_within_the_web_budget(self) -> None:
        release = Event()

        def blocked_market_data(_arguments: object) -> str:
            release.wait(1)
            return "{}"

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("yfinance_market_data", "test", blocked_market_data),)
            ),
            today=lambda: date(2026, 7, 27),
            timeout_seconds=0.01,
        )

        snapshot = service.latest_week(HSBC_HK).to_dict()
        release.set()

        self.assertEqual(snapshot["market_data"]["status"], "unavailable")
        self.assertIn("没有响应", snapshot["market_data"]["reason"])

    def test_identical_concurrent_reads_share_one_in_flight_source_call(self) -> None:
        started = Event()
        release = Event()
        calls = 0

        def blocked_market_data(_arguments: object) -> str:
            nonlocal calls
            calls += 1
            started.set()
            release.wait(1)
            return json.dumps(
                {
                    "source": "coalescing fixture",
                    "candles": [{"date": "2026-07-27", "close": "100", "high": "101", "low": "99"}],
                }
            )

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("yfinance_market_data", "test", blocked_market_data),)
            ),
            today=lambda: date(2026, 7, 27),
            timeout_seconds=1,
        )
        snapshots: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def request_snapshot() -> None:
            try:
                snapshots.append(service.latest_week(HSBC_HK).to_dict())
            except BaseException as error:  # noqa: BLE001 - preserve thread failure for the assertion below
                errors.append(error)

        first = Thread(target=request_snapshot)
        second = Thread(target=request_snapshot)
        first.start()
        self.assertTrue(started.wait(0.5))
        second.start()
        deadline = monotonic() + 0.5
        while monotonic() < deadline:
            with service._inflight_reads_lock:
                in_flight = next(iter(service._inflight_reads.values()), None)
                if in_flight is not None and in_flight.waiting_callers == 2:
                    break
            Event().wait(0.001)
        else:
            release.set()
            first.join(1)
            second.join(1)
            self.fail("the second identical request did not join the in-flight read")

        release.set()
        first.join(1)
        second.join(1)

        self.assertFalse(errors)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(calls, 1)
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(all(snapshot["market_data"]["status"] == "complete" for snapshot in snapshots))


if __name__ == "__main__":
    unittest.main()
