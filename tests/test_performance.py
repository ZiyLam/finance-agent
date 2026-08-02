from __future__ import annotations

import json
import unittest
from datetime import date
from threading import Event
from time import perf_counter

from ai_agent.application.beginner_research import BeginnerResearchService
from ai_agent.application.entity_resolution import KWEICHOW_MOUTAI
from ai_agent.application.index_research import IndexResearchService
from ai_agent.application.web_workspace import WebWorkspaceService
from ai_agent.tools import FunctionTool, ToolRegistry


class PerformanceRegressionTests(unittest.TestCase):
    """Keep the Web's common no-LLM market path within explicit budgets.

    These tests use local, deterministic tools.  They guard application
    overhead and timeout enforcement without making a flaky claim about a
    third-party provider's network latency.
    """

    _FAST_PATH_BUDGET_SECONDS = 0.5
    _TIMEOUT_RETURN_BUDGET_SECONDS = 0.25

    def test_resolved_security_snapshot_returns_within_fast_path_budget(self) -> None:
        def market_data(_arguments: object) -> str:
            return json.dumps(
                {
                    "source": "performance-test source",
                    "candles": [
                        {"date": "2026-07-21", "close": "100", "high": "101", "low": "99"},
                        {"date": "2026-07-22", "close": "101", "high": "102", "low": "100"},
                    ],
                }
            )

        def registry_factory() -> ToolRegistry:
            return ToolRegistry(
                (FunctionTool("yfinance_market_data", "local performance fixture", market_data),)
            )
        beginner_research = BeginnerResearchService(
            tool_registry_factory=registry_factory,
            today=lambda: date(2026, 7, 22),
        )
        workspace = WebWorkspaceService(
            tool_registry_factory=registry_factory,
            agent_factory=lambda: _UnexpectedAgent(),  # type: ignore[arg-type]
            model_provider="echo",
            beginner_research=beginner_research,
        )

        started = perf_counter()
        reply = workspace.chat(conversation_id="performance-fast-path", content="贵州茅台")
        elapsed = perf_counter() - started

        self.assertEqual(reply.response_kind, "beginner_snapshot")
        self.assertGreaterEqual(reply.analysis_duration_ms, 0)
        self.assertLessEqual(reply.analysis_duration_ms / 1_000, elapsed + 0.05)
        self.assertLess(
            elapsed,
            self._FAST_PATH_BUDGET_SECONDS,
            f"resolved-security fast path took {elapsed:.3f}s; budget is {self._FAST_PATH_BUDGET_SECONDS:.3f}s",
        )

    def test_stalled_source_returns_before_timeout_overrun_budget(self) -> None:
        release = Event()

        def blocked_market_data(_arguments: object) -> str:
            release.wait(1)
            return "{}"

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("yfinance_market_data", "blocking performance fixture", blocked_market_data),)
            ),
            today=lambda: date(2026, 7, 22),
            timeout_seconds=0.03,
        )

        started = perf_counter()
        snapshot = service.latest_week(KWEICHOW_MOUTAI).to_dict()
        elapsed = perf_counter() - started
        release.set()

        self.assertEqual(snapshot["market_data"]["status"], "unavailable")
        self.assertLess(
            elapsed,
            self._TIMEOUT_RETURN_BUDGET_SECONDS,
            f"stalled source returned after {elapsed:.3f}s; budget is {self._TIMEOUT_RETURN_BUDGET_SECONDS:.3f}s",
        )

    def test_index_snapshot_is_bounded_and_does_not_call_the_agent(self) -> None:
        def market_data(_arguments: object) -> str:
            return json.dumps(
                {
                    "source": "index performance fixture",
                    "candles": [
                        {"date": "2026-07-21", "close": "5000", "high": "5010", "low": "4990"},
                        {"date": "2026-07-22", "close": "5015", "high": "5020", "low": "5000"},
                    ],
                }
            )

        def registry_factory() -> ToolRegistry:
            return ToolRegistry(
                (FunctionTool("yfinance_market_data", "index performance fixture", market_data),)
            )
        beginner_research = BeginnerResearchService(
            tool_registry_factory=registry_factory,
            today=lambda: date(2026, 7, 22),
        )
        workspace = WebWorkspaceService(
            tool_registry_factory=registry_factory,
            agent_factory=lambda: _UnexpectedAgent(),  # type: ignore[arg-type]
            model_provider="echo",
            beginner_research=beginner_research,
            index_research=IndexResearchService(beginner_research),
        )

        started = perf_counter()
        reply = workspace.chat(conversation_id="performance-index", content="中证500")
        elapsed = perf_counter() - started

        self.assertEqual(reply.response_kind, "index_snapshot")
        self.assertLess(
            elapsed,
            self._FAST_PATH_BUDGET_SECONDS,
            f"index fast path took {elapsed:.3f}s; budget is {self._FAST_PATH_BUDGET_SECONDS:.3f}s",
        )
        self.assertLessEqual(reply.analysis_duration_ms / 1_000, elapsed + 0.05)

    def test_index_snapshot_returns_when_its_single_data_read_times_out(self) -> None:
        release = Event()

        def blocked_market_data(_arguments: object) -> str:
            release.wait(1)
            return "{}"

        def registry_factory() -> ToolRegistry:
            return ToolRegistry(
                (FunctionTool("yfinance_market_data", "blocked index fixture", blocked_market_data),)
            )
        bounded_index_reader = BeginnerResearchService(
            tool_registry_factory=registry_factory,
            today=lambda: date(2026, 7, 22),
            timeout_seconds=0.03,
        )
        workspace = WebWorkspaceService(
            tool_registry_factory=registry_factory,
            agent_factory=lambda: _UnexpectedAgent(),  # type: ignore[arg-type]
            model_provider="echo",
            index_research=IndexResearchService(bounded_index_reader),
        )

        started = perf_counter()
        reply = workspace.chat(conversation_id="performance-index-timeout", content="中证500")
        elapsed = perf_counter() - started
        release.set()

        self.assertEqual(reply.response_kind, "index_snapshot")
        self.assertEqual(reply.snapshot["market_data"]["status"], "unavailable")  # type: ignore[index]
        self.assertLess(
            elapsed,
            self._TIMEOUT_RETURN_BUDGET_SECONDS,
            f"index timeout path returned after {elapsed:.3f}s; budget is {self._TIMEOUT_RETURN_BUDGET_SECONDS:.3f}s",
        )

    def test_market_scan_timeout_returns_without_invoking_the_agent(self) -> None:
        release = Event()

        def blocked_market_scan(_arguments: object) -> str:
            release.wait(1)
            return "{}"

        def registry_factory() -> ToolRegistry:
            return ToolRegistry(
                (FunctionTool("eastmoney_market_scan", "blocked sector fixture", blocked_market_scan),)
            )
        workspace = WebWorkspaceService(
            tool_registry_factory=registry_factory,
            agent_factory=lambda: _UnexpectedAgent(),  # type: ignore[arg-type]
            model_provider="echo",
            market_scan_timeout_seconds=0.03,
        )

        started = perf_counter()
        reply = workspace.chat(
            conversation_id="performance-market-scan-timeout",
            content="我想了解近期哪些板块值得关注",
        )
        elapsed = perf_counter() - started
        release.set()

        self.assertEqual(reply.response_kind, "market_scan")
        self.assertEqual(reply.snapshot["status"], "unavailable")  # type: ignore[index]
        self.assertLess(
            elapsed,
            self._TIMEOUT_RETURN_BUDGET_SECONDS,
            f"market scan timeout returned after {elapsed:.3f}s; budget is {self._TIMEOUT_RETURN_BUDGET_SECONDS:.3f}s",
        )


class _UnexpectedAgent:
    def run(self, *_arguments: object, **_kwargs: object) -> object:
        raise AssertionError("the resolved-security fast path must not call the Agent")


if __name__ == "__main__":
    unittest.main()
