from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import perf_counter
from unittest.mock import patch

from ai_agent.application.source_connectivity import SourceConnectivityService
from ai_agent.data_sources import ordered_data_sources
from ai_agent.provider_activation import ProviderActivationStore
from ai_agent.secrets import TokenStore


class SourceConnectivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.store = TokenStore(
            Path(self.temporary_directory.name) / "tokens.json",
            protect=lambda value: value[::-1],
            unprotect=lambda value: value[::-1],
        )
        self.activation = ProviderActivationStore(
            Path(self.temporary_directory.name) / "provider-settings.json"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_snapshot_is_passive_and_required_token_is_reported_without_calling_probe(self) -> None:
        calls: list[str | None] = []
        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={"alltick": calls.append},
            now=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

        with patch.dict(os.environ, {}, clear=True):
            initial = service.snapshot("alltick")
            checked = service.check("alltick")

        self.assertEqual(initial["status"], "untested")
        self.assertEqual(checked["status"], "not_configured")
        self.assertEqual(calls, [])

    def test_configured_probe_reports_healthy_without_returning_the_token(self) -> None:
        sensitive_token = "private-connectivity-token"
        observed: list[str | None] = []
        self.store.set_token("alltick", sensitive_token)
        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={"alltick": observed.append},
            now=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

        with patch.dict(os.environ, {}, clear=True):
            result = service.check("alltick")

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["message"], "已完成最小只读请求，服务连接正常。")
        self.assertEqual(observed, [sensitive_token])
        self.assertNotIn(sensitive_token, str(result))
        self.assertEqual(result["checked_at"], "2026-08-01T00:00:00+00:00")

    def test_remote_failure_is_red_status_and_does_not_expose_provider_details(self) -> None:
        def fail(_token: str | None) -> None:
            raise RuntimeError("private URL and response body must not leave the service")

        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={"eastmoney": fail},
        )

        result = service.check("eastmoney")

        self.assertEqual(result["status"], "remote_failure")
        self.assertEqual(result["category"], "remote_connection")
        self.assertNotIn("private URL", str(result))
        self.assertNotIn("response body", str(result))

    def test_local_service_failure_is_distinct_from_remote_failure(self) -> None:
        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={"aktools": lambda _token: (_ for _ in ()).throw(RuntimeError("local detail"))},
        )

        result = service.check("aktools")

        self.assertEqual(result["status"], "local_unavailable")
        self.assertEqual(result["category"], "local_runtime")
        self.assertNotIn("local detail", str(result))

    def test_stalled_probe_returns_within_the_explicit_timeout_budget(self) -> None:
        release = Event()
        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={"eastmoney": lambda _token: release.wait(1)},
            timeout_seconds=0.03,
        )

        started = perf_counter()
        result = service.check("eastmoney")
        elapsed = perf_counter() - started
        release.set()

        self.assertEqual(result["status"], "remote_failure")
        self.assertEqual(result["category"], "remote_timeout")
        self.assertLess(elapsed, 0.25)

    def test_batch_result_retains_catalog_routing_order(self) -> None:
        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={},
            max_parallel_checks=2,
        )

        with patch.dict(os.environ, {}, clear=True):
            results = service.check_all()

        self.assertEqual(
            [result["name"] for result in results],
            [definition.name for definition in ordered_data_sources()],
        )

    def test_batch_can_be_limited_to_the_llm_settings_module(self) -> None:
        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={},
        )

        with patch.dict(os.environ, {}, clear=True):
            results = service.check_all("llm")

        self.assertEqual([result["name"] for result in results], ["qianfan"])
        self.assertEqual(results[0]["status"], "not_configured")

    def test_disabled_provider_does_not_read_credential_or_call_probe(self) -> None:
        sensitive_token = "disabled-provider-token"
        observed: list[str | None] = []
        self.store.set_token("alltick", sensitive_token)
        self.activation.set_enabled("alltick", False)
        service = SourceConnectivityService(
            self.store,
            activation=self.activation,
            probes={"alltick": observed.append},
        )

        with patch.object(self.store, "get_token", side_effect=AssertionError("credential was read")):
            snapshot = service.snapshot("alltick")
            result = service.check("alltick")

        self.assertEqual(snapshot["status"], "disabled")
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["category"], "disabled")
        self.assertEqual(observed, [])


if __name__ == "__main__":
    unittest.main()
