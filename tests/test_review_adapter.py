import json
import tempfile
import textwrap
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate.models import PhaseDefinition, ReviewRequest, RunManifest
from cross_agent_phase_gate.review_adapter import (
    ClaudeReviewAdapter,
    CodexReviewAdapter,
    DECISION_SCHEMA,
    default_review_adapter,
)
from cross_agent_phase_gate.role_mode import (
    CLAUDE_BUILDER_CODEX_REVIEWER,
    CODEX_BUILDER_CLAUDE_REVIEWER,
)


class ReviewAdapterTests(unittest.TestCase):
    def test_decision_schema_is_strict_enough_for_codex_output_schema(self) -> None:
        self.assertEqual(DECISION_SCHEMA["additionalProperties"], False)

    def test_default_review_adapter_selects_by_role_mode(self) -> None:
        self.assertIsInstance(
            default_review_adapter(CLAUDE_BUILDER_CODEX_REVIEWER),
            CodexReviewAdapter,
        )
        self.assertIsInstance(
            default_review_adapter(CODEX_BUILDER_CLAUDE_REVIEWER),
            ClaudeReviewAdapter,
        )

    def test_prompt_requires_exact_phase_id_in_decision_output(self) -> None:
        run = RunManifest(
            run_id="run123",
            repo_path="/tmp/repo",
            plan_path="/tmp/repo/plan.md",
            role_mode="claude_builder_codex_reviewer",
            repo_profile_name="default",
            plan_title="Test Plan",
            status="phase_in_progress",
            current_phase_index=0,
            active_carryforwards=(),
            phases=(
                PhaseDefinition(
                    id="1",
                    title="Phase 1",
                    goal="Ship it",
                    verification=("python3 -m unittest",),
                ),
            ),
        )
        request = ReviewRequest(
            run=run,
            phase=run.phases[0],
            packet={"status": "implemented"},
            repo_config={"repo_profile": "default"},
            diff_summary={"git": False, "status": [], "diffstat": ""},
            plan_text="# Test Plan",
        )

        prompt = CodexReviewAdapter()._build_prompt(request)

        self.assertIn("The `phase` field must be exactly `1`.", prompt)

    def test_codex_adapter_reads_output_last_message_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            repo_path = tmp_path / "repo"
            repo_path.mkdir()
            fake_codex = tmp_path / "fake-codex"
            fake_codex.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import sys
                    from pathlib import Path

                    args = sys.argv[1:]
                    output_path = None
                    for index, arg in enumerate(args):
                        if arg == "--output-last-message":
                            output_path = Path(args[index + 1])
                    if output_path is None:
                        raise SystemExit("missing output path")
                    output_path.write_text(json.dumps({
                        "decision": "PASS",
                        "phase": "1",
                        "summary": "Approved.",
                        "rationale": "Looks good.",
                        "carryforwards": [],
                        "next_action": "Proceed.",
                        "may_start_next_phase": True,
                        "next_phase_override": None
                    }))
                    """
                ),
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            run = RunManifest(
                run_id="run123",
                repo_path=str(repo_path),
                plan_path=str(repo_path / "plan.md"),
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="default",
                plan_title="Test Plan",
                status="phase_in_progress",
                current_phase_index=0,
                active_carryforwards=(),
                phases=(
                    PhaseDefinition(
                        id="1",
                        title="Phase 1",
                        goal="Ship it",
                        verification=("python3 -m unittest",),
                    ),
                ),
            )
            request = ReviewRequest(
                run=run,
                phase=run.phases[0],
                packet={"status": "implemented"},
                repo_config={"repo_profile": "default"},
                diff_summary={"git": False, "status": [], "diffstat": ""},
                plan_text="# Test Plan",
            )

            adapter = CodexReviewAdapter(codex_bin=str(fake_codex), timeout_seconds=5)
            decision = adapter.review(request)

            self.assertEqual(decision.decision, "PASS")
            self.assertEqual(decision.phase, "1")

    def test_claude_adapter_reads_structured_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            repo_path = tmp_path / "repo"
            repo_path.mkdir()
            fake_claude = tmp_path / "fake-claude"
            fake_claude.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    print(json.dumps({
                        "structured_output": {
                            "decision": "PASS",
                            "phase": "1",
                            "summary": "Approved by Claude.",
                            "rationale": "Looks good.",
                            "carryforwards": [],
                            "next_action": "Proceed.",
                            "may_start_next_phase": True,
                            "next_phase_override": None
                        }
                    }))
                    """
                ),
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            run = RunManifest(
                run_id="run123",
                repo_path=str(repo_path),
                plan_path=str(repo_path / "plan.md"),
                role_mode=CODEX_BUILDER_CLAUDE_REVIEWER,
                repo_profile_name="default",
                plan_title="Test Plan",
                status="phase_in_progress",
                current_phase_index=0,
                active_carryforwards=(),
                phases=(
                    PhaseDefinition(
                        id="1",
                        title="Phase 1",
                        goal="Ship it",
                        verification=("python3 -m unittest",),
                    ),
                ),
            )
            request = ReviewRequest(
                run=run,
                phase=run.phases[0],
                packet={"status": "implemented"},
                repo_config={"repo_profile": "default"},
                diff_summary={"git": False, "status": [], "diffstat": ""},
                plan_text="# Test Plan",
            )

            adapter = ClaudeReviewAdapter(claude_bin=str(fake_claude), timeout_seconds=5)
            decision = adapter.review(request)

            self.assertEqual(decision.decision, "PASS")
            self.assertEqual(decision.phase, "1")

    def test_claude_adapter_accepts_direct_decision_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            repo_path = tmp_path / "repo"
            repo_path.mkdir()
            fake_claude = tmp_path / "fake-claude"
            fake_claude.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    print(json.dumps({
                        "decision": "PASS",
                        "phase": "1",
                        "summary": "Approved by Claude.",
                        "rationale": "Looks good.",
                        "carryforwards": [],
                        "next_action": "Proceed.",
                        "may_start_next_phase": True,
                        "next_phase_override": None
                    }))
                    """
                ),
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            run = RunManifest(
                run_id="run123",
                repo_path=str(repo_path),
                plan_path=str(repo_path / "plan.md"),
                role_mode=CODEX_BUILDER_CLAUDE_REVIEWER,
                repo_profile_name="default",
                plan_title="Test Plan",
                status="phase_in_progress",
                current_phase_index=0,
                active_carryforwards=(),
                phases=(
                    PhaseDefinition(
                        id="1",
                        title="Phase 1",
                        goal="Ship it",
                        verification=("python3 -m unittest",),
                    ),
                ),
            )
            request = ReviewRequest(
                run=run,
                phase=run.phases[0],
                packet={"status": "implemented"},
                repo_config={"repo_profile": "default"},
                diff_summary={"git": False, "status": [], "diffstat": ""},
                plan_text="# Test Plan",
            )

            adapter = ClaudeReviewAdapter(claude_bin=str(fake_claude), timeout_seconds=5)
            decision = adapter.review(request)

            self.assertEqual(decision.decision, "PASS")
            self.assertEqual(decision.phase, "1")


if __name__ == "__main__":
    unittest.main()
