from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai_agent.cli import run_source_command
from ai_agent.secrets import (
    EnvironmentSecretStore,
    SecretStoreError,
    TokenStore,
    default_secret_store,
    default_secret_store_path,
    resolve_token,
)


def reversible_protect(value: bytes) -> bytes:
    return value[::-1]


class TokenStoreTests(unittest.TestCase):
    def make_store(self, directory: str) -> TokenStore:
        return TokenStore(
            Path(directory) / "tokens.json",
            protect=reversible_protect,
            unprotect=reversible_protect,
        )

    def test_set_get_and_delete_do_not_store_plaintext(self) -> None:
        with TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.set_token("alltick", "sensitive-test-token")

            self.assertEqual(store.get_token("alltick"), "sensitive-test-token")
            self.assertNotIn("sensitive-test-token", (Path(directory) / "tokens.json").read_text())
            self.assertTrue(store.delete_token("alltick"))
            self.assertIsNone(store.get_token("alltick"))

    def test_environment_token_has_priority_over_stored_token(self) -> None:
        with TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.set_token("alltick", "stored-token")
            with patch.dict("os.environ", {"ALLTICK_API_TOKEN": "temporary-token"}):
                self.assertEqual(resolve_token("alltick", "ALLTICK_API_TOKEN", store), "temporary-token")

    def test_default_store_uses_finance_agent_name(self) -> None:
        with TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"LOCALAPPDATA": directory}, clear=True):
                self.assertEqual(
                    default_secret_store_path(),
                    Path(directory) / "Codex" / "finance-agent" / "tokens.json",
                )

    def test_environment_backend_is_explicitly_read_only(self) -> None:
        store = EnvironmentSecretStore()

        self.assertFalse(store.writable)
        self.assertIsNone(store.get_token("alltick"))
        with self.assertRaisesRegex(SecretStoreError, "deployment environment"):
            store.set_token("alltick", "not-persisted")
        with self.assertRaisesRegex(SecretStoreError, "deployment environment"):
            store.delete_token("alltick")

    def test_explicit_environment_backend_avoids_dpapi(self) -> None:
        with patch.dict("os.environ", {"AGENT_SECRET_BACKEND": "environment"}, clear=True):
            store = default_secret_store()

        self.assertIsInstance(store, EnvironmentSecretStore)

    def test_unknown_backend_fails_without_echoing_configuration(self) -> None:
        with patch.dict("os.environ", {"AGENT_SECRET_BACKEND": "unknown"}, clear=True):
            with self.assertRaisesRegex(SecretStoreError, "must be 'dpapi' or 'environment'"):
                default_secret_store()

    def test_source_command_never_prints_token(self) -> None:
        with TemporaryDirectory() as directory:
            store = self.make_store(directory)
            output: list[str] = []
            result = run_source_command(
                ["set-token", "alltick"],
                store=store,
                secret_input=lambda _: "secret-never-display",
                output=output.append,
            )

            self.assertEqual(result, 0)
            self.assertNotIn("secret-never-display", "\n".join(output))
            self.assertEqual(store.get_token("alltick"), "secret-never-display")

    def test_token_maintenance_is_available_for_a_token_free_source(self) -> None:
        with TemporaryDirectory() as directory:
            store = self.make_store(directory)
            output: list[str] = []

            result = run_source_command(
                ["set-token", "yfinance"],
                store=store,
                secret_input=lambda _: "future-provider-token",
                output=output.append,
            )

            self.assertEqual(result, 0)
            self.assertEqual(store.get_token("yfinance"), "future-provider-token")
            self.assertNotIn("future-provider-token", "\n".join(output))


if __name__ == "__main__":
    unittest.main()
