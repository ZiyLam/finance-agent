from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app, create_development_components


class ApiDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.components = create_development_components(
            session_secret="test-session-secret-with-at-least-thirty-two-characters",
        )

    def test_configured_origin_can_preflight_credentialed_web_requests(self) -> None:
        app = create_app(
            self.components,
            serve_web=False,
            web_allowed_origins=("http://127.0.0.1:8011",),
        )
        client = TestClient(app)
        response = client.options(
            "/v1/web/status",
            headers={
                "Origin": "http://127.0.0.1:8011",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Finance-Agent-Token",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:8011")
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertIn("x-finance-agent-token", response.headers["access-control-allow-headers"].lower())

        health = client.get("/health", headers={"Origin": "http://127.0.0.1:8011"})
        self.assertEqual(health.headers["access-control-allow-origin"], "http://127.0.0.1:8011")
        self.assertIn("x-request-id", health.headers["access-control-expose-headers"].lower())

    def test_empty_origin_configuration_keeps_cors_disabled(self) -> None:
        app = create_app(self.components, serve_web=False, web_allowed_origins=())
        response = TestClient(app).get("/health", headers={"Origin": "https://web.example.com"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_unlisted_origin_is_not_granted_cors_access(self) -> None:
        app = create_app(
            self.components,
            serve_web=False,
            web_allowed_origins=("https://web.example.com",),
        )
        response = TestClient(app).options(
            "/health",
            headers={"Origin": "https://unlisted.example.com", "Access-Control-Request-Method": "GET"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_wildcard_and_non_origin_cors_values_are_rejected(self) -> None:
        invalid_values = (
            "*",
            "localhost:5173",
            "http://localhost:",
            "http://localhost:5173/",
            "https://example.com/path",
        )
        for value in invalid_values:
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"AGENT_WEB_ALLOWED_ORIGINS": value},
                clear=False,
            ):
                with self.assertRaises(ValueError):
                    create_app(self.components, serve_web=False)

    def test_api_only_mode_does_not_require_or_mount_static_assets(self) -> None:
        with TemporaryDirectory() as directory:
            app = create_app(
                self.components,
                serve_web=False,
                web_directory=Path(directory) / "missing",
                web_allowed_origins=(),
            )
            client = TestClient(app)

            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/v1/tasks/missing").status_code, 401)
            self.assertEqual(client.get("/").status_code, 404)
            self.assertEqual(client.get("/web/").status_code, 404)

    def test_development_default_still_serves_the_web_workspace(self) -> None:
        with patch.dict(os.environ, {"AGENT_SERVE_WEB": ""}, clear=False):
            app = create_app(self.components, web_allowed_origins=())
        client = TestClient(app)

        root = client.get("/", follow_redirects=False)
        self.assertEqual(root.status_code, 307)
        self.assertEqual(root.headers["location"], "/web/")
        self.assertEqual(client.get("/web/").status_code, 200)

    def test_explicit_static_mode_fails_fast_when_assets_are_missing(self) -> None:
        with TemporaryDirectory() as directory:
            missing_directory = Path(directory) / "missing"
            with self.assertRaises(FileNotFoundError):
                create_app(
                    self.components,
                    serve_web=True,
                    web_directory=missing_directory,
                    web_allowed_origins=(),
                )

    def test_invalid_static_mode_flag_is_rejected(self) -> None:
        with patch.dict(os.environ, {"AGENT_SERVE_WEB": "sometimes"}, clear=False):
            with self.assertRaises(ValueError):
                create_app(self.components, web_allowed_origins=())


if __name__ == "__main__":
    unittest.main()
