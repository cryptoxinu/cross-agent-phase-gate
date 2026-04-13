import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate.yaml_config import dump_yaml, load_yaml_or_json


class YamlConfigTests(unittest.TestCase):
    def test_loads_nested_yaml_with_lists(self) -> None:
        payload = """
role_mode: claude_builder_codex_reviewer
repo_profile: healthbot
plan_roots:
  - docs/plans
  - .claude/plans
review_rules:
  builder_must_stop: true
  reviewer_role: codex
""".strip()

        parsed = load_yaml_or_json(payload)

        self.assertEqual(parsed["role_mode"], "claude_builder_codex_reviewer")
        self.assertEqual(parsed["plan_roots"], ["docs/plans", ".claude/plans"])
        self.assertEqual(parsed["review_rules"]["builder_must_stop"], True)
        self.assertEqual(parsed["review_rules"]["reviewer_role"], "codex")

    def test_dump_round_trips_supported_shape(self) -> None:
        data = {
            "role_mode": "claude_builder_codex_reviewer",
            "repo_profile": "healthbot",
            "default_verification": ["ruff check src/ tests/", "pytest tests/ -q"],
            "review_rules": {
                "reviewer_role": "codex",
                "builder_must_stop": True,
            },
        }

        dumped = dump_yaml(data)
        parsed = load_yaml_or_json(dumped)

        self.assertEqual(parsed, data)

    def test_loads_json_compatibly(self) -> None:
        parsed = load_yaml_or_json('{"role_mode":"codex_builder_claude_reviewer"}')
        self.assertEqual(parsed["role_mode"], "codex_builder_claude_reviewer")

    def test_loads_empty_list_inline(self) -> None:
        parsed = load_yaml_or_json("default_verification: []")
        self.assertEqual(parsed["default_verification"], [])


if __name__ == "__main__":
    unittest.main()
