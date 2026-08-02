from __future__ import annotations

import unittest
from pathlib import Path

from ai_agent.api.app import create_app, create_development_components

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_OPERATIONS = (
    ("get", "/v1/web/status", "app.js", '"/v1/web/status"'),
    ("post", "/v1/web/chat", "app.js", '"/v1/web/chat"'),
    ("post", "/v1/web/professional-research", "app.js", '"/v1/web/professional-research"'),
    ("get", "/v1/web/sources", "sources.js", '"/v1/web/sources"'),
    ("post", "/v1/web/sources/connectivity", "sources.js", "/v1/web/sources/connectivity?"),
    ("post", "/v1/web/sources/{source}/connectivity", "sources.js", "/connectivity`"),
    ("put", "/v1/web/sources/{source}/enabled", "sources.js", "/enabled`"),
    ("put", "/v1/web/sources/{source}/token", "sources.js", "/token`"),
    ("delete", "/v1/web/sources/{source}/token", "sources.js", 'method: "DELETE"'),
)
MINIAPP_OPERATIONS = (
    ("post", "/v1/auth/wechat/login", '"POST", "/v1/auth/wechat/login"'),
    ("post", "/v1/conversations", '"POST", "/v1/conversations"'),
    ("post", "/v1/conversations/{conversation_id}/messages", "`/v1/conversations/${"),
    ("get", "/v1/tasks/{task_id}", "`/v1/tasks/${"),
    ("get", "/v1/reports/{report_id}", "`/v1/reports/${"),
)


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        components = create_development_components(session_secret="frontend-contract-test-session-secret")
        cls.openapi_paths = create_app(
            components,
            serve_web=False,
            web_allowed_origins=(),
        ).openapi()["paths"]

    def test_web_calls_are_present_in_the_openapi_contract(self) -> None:
        sources = {
            name: (PROJECT_ROOT / "web" / name).read_text("utf-8")
            for name in {operation[2] for operation in WEB_OPERATIONS}
        }
        for method, path, source_name, marker in WEB_OPERATIONS:
            with self.subTest(method=method, path=path):
                self.assertIn(method, self.openapi_paths[path])
                self.assertIn(marker, sources[source_name])

    def test_paused_miniapp_calls_remain_in_the_openapi_contract(self) -> None:
        source = (PROJECT_ROOT / "miniapp" / "utils" / "api.ts").read_text("utf-8")
        for method, path, marker in MINIAPP_OPERATIONS:
            with self.subTest(method=method, path=path):
                self.assertIn(method, self.openapi_paths[path])
                self.assertIn(marker, source)

    def test_each_client_keeps_one_network_gateway(self) -> None:
        web_network_files = [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in (PROJECT_ROOT / "web").glob("*.js")
            if "fetch(" in path.read_text("utf-8")
        ]
        miniapp_network_files = [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in (PROJECT_ROOT / "miniapp").rglob("*.ts")
            if "wx.request(" in path.read_text("utf-8")
        ]

        self.assertEqual(web_network_files, ["web/api-client.js"])
        self.assertEqual(miniapp_network_files, ["miniapp/utils/api.ts"])


if __name__ == "__main__":
    unittest.main()
