from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_agent.provider_activation import ProviderActivationError, ProviderActivationStore


class ProviderActivationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "provider-settings.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_known_providers_default_to_enabled_without_creating_a_file(self) -> None:
        store = ProviderActivationStore(self.path)

        self.assertTrue(store.is_enabled("eastmoney"))
        self.assertTrue(store.is_enabled("qianfan"))
        self.assertFalse(self.path.exists())

    def test_disabled_choice_is_persisted_and_read_by_a_new_instance(self) -> None:
        store = ProviderActivationStore(self.path)

        self.assertFalse(store.set_enabled("eastmoney", False))

        reloaded = ProviderActivationStore(self.path)
        self.assertFalse(reloaded.is_enabled("eastmoney"))
        self.assertTrue(reloaded.is_enabled("qianfan"))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload, {"version": 1, "enabled": {"eastmoney": False}})

    def test_invalid_settings_file_fails_closed_instead_of_enabling_a_provider(self) -> None:
        self.path.write_text('{"enabled":{"eastmoney":"yes"}}', encoding="utf-8")

        with self.assertRaisesRegex(ProviderActivationError, "invalid format"):
            ProviderActivationStore(self.path).is_enabled("eastmoney")

    def test_unknown_provider_cannot_be_persisted(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown provider"):
            ProviderActivationStore(self.path).set_enabled("not-a-provider", False)


if __name__ == "__main__":
    unittest.main()
