from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DesignTokenTests(unittest.TestCase):
    def test_generated_platform_outputs_are_current(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/generate_design_tokens.py", "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_client_styles_import_generated_tokens_instead_of_repeating_values(self) -> None:
        colors = json.loads((PROJECT_ROOT / "frontend" / "design-tokens.json").read_text("utf-8"))["colors"]
        web_styles = (PROJECT_ROOT / "web" / "styles.css").read_text("utf-8")
        miniapp_styles = "\n".join(
            path.read_text("utf-8")
            for path in (PROJECT_ROOT / "miniapp").rglob("*.wxss")
            if path.name != "design-tokens.wxss"
        )

        self.assertTrue(web_styles.startswith('@import url("./design-tokens.css");'))
        self.assertIn('@import "./styles/design-tokens.wxss";', miniapp_styles)
        for name, value in colors.items():
            with self.subTest(name=name):
                self.assertNotIn(value, web_styles, f"Use var(--{name}) instead of repeating {value}")
                self.assertNotIn(value, miniapp_styles, f"Use var(--{name}) instead of repeating {value}")


if __name__ == "__main__":
    unittest.main()
