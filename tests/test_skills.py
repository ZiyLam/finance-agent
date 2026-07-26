from __future__ import annotations

from pathlib import Path
import unittest

from ai_agent.skills import compose_system_prompt, load_skills


class SkillLoadingTests(unittest.TestCase):
    def test_financial_skill_is_discovered_and_rendered(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        skills = load_skills(project_root / "skills")

        self.assertEqual([skill.name for skill in skills], ["financial-investment-analyst"])
        prompt = compose_system_prompt("Base prompt.", skills)
        self.assertIn("金融分析", prompt)
        self.assertIn("security-research-report/v1", prompt)
        self.assertIn("Base prompt.", prompt)


if __name__ == "__main__":
    unittest.main()
