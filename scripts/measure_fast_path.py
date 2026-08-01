"""Measure deterministic local latency and in-flight request coalescing.

This is intentionally an offline fixture benchmark. It measures Finance Agent
application overhead, not a third-party market-data provider or an LLM. Run
from the project root with ``PYTHONPATH=src`` so the result is reproducible.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from math import ceil
from threading import Event, Thread
from time import monotonic

from ai_agent.application.beginner_research import BeginnerResearchService
from ai_agent.application.entity_resolution import KWEICHOW_MOUTAI
from ai_agent.application.web_workspace import WebWorkspaceService
from ai_agent.tools import FunctionTool, ToolRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure deterministic Finance Agent fast-path behavior.")
    parser.add_argument("--iterations", type=int, default=50, help="Number of sequential fast-path samples (default: 50).")
    arguments = parser.parse_args()
    if arguments.iterations < 5:
        parser.error("--iterations must be at least 5")

    timings = _fast_path_timings(arguments.iterations)
    coalescing = _coalescing_measurement()
    print(
        json.dumps(
            {
                "benchmark": "deterministic_fast_path_fixture/v1",
                "iterations": arguments.iterations,
                "fast_path_ms": {
                    "min": round(min(timings), 3),
                    "p50": _percentile(timings, 50),
                    "p95": _percentile(timings, 95),
                    "max": round(max(timings), 3),
                },
                "identical_in_flight_pair": coalescing,
                "scope": "offline fixture; excludes network and model-provider latency",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _fast_path_timings(iterations: int) -> list[float]:
    def market_data(_arguments: object) -> str:
        return json.dumps(
            {
                "source": "benchmark fixture",
                "candles": [
                    {"date": "2026-07-21", "close": "100", "high": "101", "low": "99"},
                    {"date": "2026-07-22", "close": "101", "high": "102", "low": "100"},
                ],
            }
        )

    registry_factory = lambda: ToolRegistry((FunctionTool("yfinance_market_data", "benchmark fixture", market_data),))
    workspace = WebWorkspaceService(
        tool_registry_factory=registry_factory,
        agent_factory=_UnexpectedAgent,
        model_provider="echo",
        beginner_research=BeginnerResearchService(
            tool_registry_factory=registry_factory,
            today=lambda: date(2026, 7, 22),
        ),
    )
    timings: list[float] = []
    for sample in range(iterations):
        started = monotonic()
        reply = workspace.chat(conversation_id=f"benchmark-{sample}", content="贵州茅台")
        elapsed_ms = (monotonic() - started) * 1_000
        if reply.response_kind != "beginner_snapshot":
            raise RuntimeError(f"unexpected benchmark response kind: {reply.response_kind}")
        timings.append(elapsed_ms)
    return timings


def _coalescing_measurement() -> dict[str, int | float]:
    source_started = Event()
    release_source = Event()
    calls = 0

    def blocked_market_data(_arguments: object) -> str:
        nonlocal calls
        calls += 1
        source_started.set()
        if not release_source.wait(1):
            raise RuntimeError("benchmark source release timed out")
        return json.dumps(
            {
                "source": "coalescing fixture",
                "candles": [{"date": "2026-07-22", "close": "100", "high": "101", "low": "99"}],
            }
        )

    service = BeginnerResearchService(
        tool_registry_factory=lambda: ToolRegistry(
            (FunctionTool("yfinance_market_data", "coalescing fixture", blocked_market_data),)
        ),
        today=lambda: date(2026, 7, 22),
        timeout_seconds=1,
    )
    errors: list[BaseException] = []

    def request_snapshot() -> None:
        try:
            service.latest_week(KWEICHOW_MOUTAI)
        except BaseException as error:  # noqa: BLE001 - report the fixture failure after joining both callers
            errors.append(error)

    first = Thread(target=request_snapshot)
    second = Thread(target=request_snapshot)
    first.start()
    if not source_started.wait(0.5):
        raise RuntimeError("first fixture request did not start")
    second.start()
    deadline = monotonic() + 0.5
    while monotonic() < deadline:
        with service._inflight_reads_lock:
            read = next(iter(service._inflight_reads.values()), None)
            if read is not None and read.waiting_callers == 2:
                break
        Event().wait(0.001)
    else:
        release_source.set()
        first.join(1)
        second.join(1)
        raise RuntimeError("identical fixture calls did not coalesce")

    release_source.set()
    first.join(1)
    second.join(1)
    if errors or first.is_alive() or second.is_alive():
        raise RuntimeError("coalescing fixture callers did not complete")
    logical_requests = 2
    return {
        "logical_requests": logical_requests,
        "source_calls": calls,
        "source_calls_avoided": logical_requests - calls,
        "source_call_reduction_percent": round((logical_requests - calls) / logical_requests * 100, 1),
    }


def _percentile(samples: list[float], percentile: int) -> float:
    ordered = sorted(samples)
    index = ceil(len(ordered) * percentile / 100) - 1
    return round(ordered[index], 3)


class _UnexpectedAgent:
    def run(self, *_arguments: object, **_kwargs: object) -> object:
        raise AssertionError("the deterministic fast path must not call an Agent")


if __name__ == "__main__":
    main()
