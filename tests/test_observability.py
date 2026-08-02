from __future__ import annotations

import json
import logging
import unittest
from datetime import date
from io import StringIO

from ai_agent.application.beginner_research import BeginnerResearchService
from ai_agent.application.entity_resolution import KWEICHOW_MOUTAI
from ai_agent.observability import (
    _JsonLineFormatter,
    bind_request_id,
    get_logger,
    log_event,
    reset_request_id,
)
from ai_agent.tools import FunctionTool, ToolRegistry


class ObservabilityTests(unittest.TestCase):
    def test_structured_event_keeps_correlation_metadata_but_drops_sensitive_fields(self) -> None:
        logger = get_logger()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_JsonLineFormatter())
        previous_level = logger.level
        previous_propagate = logger.propagate
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        context_token = bind_request_id("trace-123")
        try:
            log_event(
                "model_completion_failed",
                provider="CodexCliModelClient",
                duration_ms=35,
                prompt="do-not-log-this",
                api_key="do-not-log-this-either",
            )
        finally:
            reset_request_id(context_token)
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
            logger.propagate = previous_propagate

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "model_completion_failed")
        self.assertEqual(payload["request_id"], "trace-123")
        self.assertEqual(payload["provider"], "CodexCliModelClient")
        self.assertEqual(payload["duration_ms"], 35)
        self.assertNotIn("prompt", payload)
        self.assertNotIn("api_key", payload)
        self.assertNotIn("do-not-log-this", stream.getvalue())

    def test_market_reader_propagates_request_id_and_source_latency_class_into_threaded_tool_events(self) -> None:
        logger = get_logger()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_JsonLineFormatter())
        previous_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        def yfinance(_arguments: object) -> str:
            return json.dumps(
                {
                    "source": "test",
                    "candles": [{"date": "2026-07-22", "close": "100", "high": "101", "low": "99"}],
                }
            )

        service = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry((FunctionTool("yfinance_market_data", "test", yfinance),)),
            today=lambda: date(2026, 7, 22),
        )
        context_token = bind_request_id("trace-threaded-market-read")
        try:
            service.latest_week(KWEICHOW_MOUTAI)
        finally:
            reset_request_id(context_token)
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        events = [json.loads(line) for line in stream.getvalue().splitlines()]
        completed = next(event for event in events if event["event"] == "tool_execution_completed")
        self.assertEqual(completed["request_id"], "trace-threaded-market-read")
        self.assertEqual(completed["data_source"], "yfinance")
        self.assertEqual(completed["latency_class"], "high")
        self.assertEqual(completed["routing_priority"], 70)
        self.assertIsInstance(completed["duration_ms"], int)


if __name__ == "__main__":
    unittest.main()
