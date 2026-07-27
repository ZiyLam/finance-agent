from __future__ import annotations

import json
import unittest

from ai_agent.application.input_parser import ResearchIntentParser
from ai_agent.application.research_service import ResearchService
from ai_agent.infrastructure.store import InMemoryApplicationStore
from ai_agent.infrastructure.task_queue import InMemoryTaskQueue
from ai_agent.tools import FunctionTool, ToolRegistry


def _registry() -> ToolRegistry:
    def history(_arguments):
        return json.dumps(
            {
                "candles": [
                    {"date": "2026-04-27", "close": "100", "high": "101", "low": "99"},
                    {"date": "2026-07-27", "close": "110", "high": "111", "low": "109"},
                ]
            }
        )

    return ToolRegistry((FunctionTool("aktools_market_data", "test history", history),))


class ResearchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryApplicationStore()
        self.service = ResearchService(
            store=self.store,
            queue=InMemoryTaskQueue(),
            parser=ResearchIntentParser(),
            tool_registry_factory=_registry,
        )

    def test_ready_request_creates_user_owned_task_and_report(self) -> None:
        conversation = self.service.create_conversation("user-a")

        submission = self.service.submit_message("user-a", conversation.id, "600000 最近三个月走势")
        completed = self.service.run_next_task()

        self.assertEqual(submission.status, "queued")
        assert completed is not None
        self.assertEqual(completed.status, "completed")
        assert completed.report_id is not None
        report = self.service.get_report("user-a", completed.report_id)
        assert report is not None
        self.assertEqual(report.payload["contract_version"], "security-research-report/v1")
        self.assertIsNone(self.service.get_task("user-b", completed.id))
        self.assertIsNone(self.service.get_report("user-b", completed.report_id))

    def test_ambiguous_request_never_enqueues_work(self) -> None:
        conversation = self.service.create_conversation("user-a")

        submission = self.service.submit_message("user-a", conversation.id, "分析贵州茅台")

        self.assertEqual(submission.status, "needs_clarification")
        self.assertIsNone(submission.task_id)
        self.assertIsNone(self.service.run_next_task())

    def test_blank_request_is_rejected_without_persisting_or_queueing(self) -> None:
        conversation = self.service.create_conversation("user-a")

        with self.assertRaisesRegex(ValueError, "cannot be blank"):
            self.service.submit_message("user-a", conversation.id, "   ")

        self.assertIsNone(self.service.run_next_task())

    def test_model_narration_is_optional_and_evidence_report_remains_primary(self) -> None:
        class FakeNarrator:
            provider_name = "qianfan"

            def narrate(self, report):  # type: ignore[no-untyped-def]
                self.report_status = report["report_status"]
                return "基于证据的千帆摘要。"

        narrator = FakeNarrator()
        service = ResearchService(
            store=InMemoryApplicationStore(),
            queue=InMemoryTaskQueue(),
            parser=ResearchIntentParser(),
            tool_registry_factory=_registry,
            narrator=narrator,
        )
        conversation = service.create_conversation("user-a")
        submission = service.submit_message("user-a", conversation.id, "600000 最近三个月走势")
        assert submission.task_id is not None
        completed = service.run_next_task()
        assert completed is not None and completed.report_id is not None
        report = service.get_report("user-a", completed.report_id)
        assert report is not None

        self.assertEqual(report.payload["model_narrative"], "基于证据的千帆摘要。")
        self.assertEqual(report.payload["narration_provider"], "qianfan")
        self.assertEqual(narrator.report_status, "complete")


if __name__ == "__main__":
    unittest.main()
