import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate.plan_normalizer import normalize_plan


SAMPLE_PLAN = """
# Delivery Plan

## Summary
- Build the workflow.

## Phase 1A - Normalize Plan

### Goal
- Convert the plan into bounded phases.

### Files
- `src/phase_gate/plan.py`
- `tests/test_plan.py`

### Verification
```bash
python3 -m unittest tests.test_plan_normalizer
```

### Acceptance Criteria
- Produces at least one normalized phase
- Keeps non-goals explicit

## Phase 1B - Review Loop

### Goal
- Submit a packet and wait for review.

### Non-Goals
- No automatic merging

### Verification
- `python3 -m unittest tests.test_service`
""".strip()


class PlanNormalizerTests(unittest.TestCase):
    def test_extracts_multiple_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plan_path = Path(tmp_dir) / "plan.md"
            plan_path.write_text(SAMPLE_PLAN, encoding="utf-8")

            run_manifest = normalize_plan(
                repo_path=Path(tmp_dir),
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
                default_verification=("ruff check src/ tests/",),
            )

        self.assertEqual(len(run_manifest.phases), 2)
        self.assertEqual(run_manifest.phases[0].id, "1A")
        self.assertIn("src/phase_gate/plan.py", run_manifest.phases[0].allowed_paths)
        self.assertIn(
            "python3 -m unittest tests.test_plan_normalizer",
            run_manifest.phases[0].verification,
        )
        self.assertIn(
            "No automatic merging",
            run_manifest.phases[1].non_goals,
        )

    def test_falls_back_to_single_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plan_path = Path(tmp_dir) / "plan.md"
            plan_path.write_text("# Tiny Plan\nShip it carefully.\n", encoding="utf-8")

            run_manifest = normalize_plan(
                repo_path=Path(tmp_dir),
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="default",
                default_verification=("python3 -m unittest",),
            )

        self.assertEqual(len(run_manifest.phases), 1)
        self.assertEqual(run_manifest.phases[0].verification, ("python3 -m unittest",))

    def test_verification_commands_are_not_treated_as_allowed_paths(self) -> None:
        plan_text = """
# Smoke

## Phase 1 - Add Note

### Files
- `notes/smoke.txt`

### Verification
- `test -f notes/smoke.txt`
""".strip()
        with tempfile.TemporaryDirectory() as tmp_dir:
            plan_path = Path(tmp_dir) / "plan.md"
            plan_path.write_text(plan_text, encoding="utf-8")

            run_manifest = normalize_plan(
                repo_path=Path(tmp_dir),
                plan_path=plan_path,
                role_mode="codex_builder_claude_reviewer",
                repo_profile_name="default",
                default_verification=(),
            )

        self.assertEqual(run_manifest.phases[0].allowed_paths, ("notes/smoke.txt",))
        self.assertEqual(run_manifest.phases[0].verification, ("test -f notes/smoke.txt",))


if __name__ == "__main__":
    unittest.main()
