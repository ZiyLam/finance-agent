from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks
from fastapi import HTTPException

from ai_agent.api.app import (
    ConversationMessagePayload,
    WechatLoginPayload,
    create_app,
    create_development_components,
)
from ai_agent.api.auth import AccessPolicy
from ai_agent.api import main as api_main
from ai_agent.tools import FunctionTool, ToolRegistry


class FakeWechatIdentityProvider:
    def exchange_code(self, code: str) -> str:
        if code != "good-code":
            raise RuntimeError("invalid")
        return "wx_user_1"


def _registry() -> ToolRegistry:
    return ToolRegistry(
        (
            FunctionTool(
                "aktools_market_data",
                "test history",
                lambda _arguments: json.dumps(
                    {"candles": [{"date": "2026-04-01", "close": "10"}, {"date": "2026-07-01", "close": "11"}]}
                ),
            ),
        )
    )


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.components = create_development_components(
            tool_registry_factory=_registry,
            session_secret="test-session-secret-with-at-least-thirty-two-characters",
            wechat=FakeWechatIdentityProvider(),
        )
        self.app = create_app(self.components)

    def endpoint(self, path: str, method: str):  # type: ignore[no-untyped-def]
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route.endpoint
        self.fail(f"endpoint not found: {method} {path}")

    def test_authenticated_user_can_submit_and_read_own_report(self) -> None:
        login = self.endpoint("/v1/auth/wechat/login", "POST")(WechatLoginPayload(code="good-code"))
        identity = self.components.sessions.verify(login["access_token"])
        conversation = self.endpoint("/v1/conversations", "POST")(identity)

        submitted = self.endpoint("/v1/conversations/{conversation_id}/messages", "POST")(
            conversation["id"],
            ConversationMessagePayload(content="600000 最近三个月走势"),
            BackgroundTasks(),
            identity,
        )
        task_id = submitted["task_id"]
        self.components.research.run_next_task()
        task = self.endpoint("/v1/tasks/{task_id}", "GET")(task_id, identity)
        self.assertEqual(task["status"], "completed")
        report = self.endpoint("/v1/reports/{report_id}", "GET")(task["report_id"], identity)
        self.assertEqual(report["report"]["contract_version"], "security-research-report/v1")

    def test_health_discloses_development_storage_not_credentials(self) -> None:
        health = self.endpoint("/health", "GET")()
        self.assertEqual(health["storage"], "in_memory_development_only")
        self.assertTrue(health["wechat_login_configured"])

    def test_personal_mode_denies_unconfigured_or_unlisted_owner(self) -> None:
        components = create_development_components(
            session_secret="test-session-secret-with-at-least-thirty-two-characters",
            wechat=FakeWechatIdentityProvider(),
            access_policy=AccessPolicy(personal_mode=True, allowed_user_ids=frozenset()),
        )
        app = create_app(components)
        login = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/v1/auth/wechat/login")

        with self.assertRaises(HTTPException) as error:
            login(WechatLoginPayload(code="good-code"))

        self.assertEqual(error.exception.status_code, 503)

    def test_personal_api_defaults_narration_to_current_codex_model(self) -> None:
        with patch.dict(os.environ, {"AGENT_API_NARRATOR_PROVIDER": "codex", "AGENT_MODEL": ""}, clear=False):
            api_main.optional_narrator.cache_clear()
            narrator = api_main.optional_narrator()

        assert narrator is not None
        self.assertEqual(narrator.provider_name, "codex")


if __name__ == "__main__":
    unittest.main()
