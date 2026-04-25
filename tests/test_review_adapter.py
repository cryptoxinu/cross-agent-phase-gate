import json
import tempfile
import textwrap
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate.models import (
    PatchTarget,
    PhaseDecision,
    PhaseDefinition,
    ReviewRequest,
    RunManifest,
)
from cross_agent_phase_gate.review_adapter import (
    ClaudeReviewAdapter,
    CodexReviewAdapter,
    DECISION_SCHEMA,
    _validated_phase_decision,
    default_review_adapter,
)
from cross_agent_phase_gate.role_mode import (
    CLAUDE_BUILDER_CODEX_REVIEWER,
    CODEX_BUILDER_CLAUDE_REVIEWER,
)


def _decision_payload(**overrides: object) -> dict[str, object]:
    base = {
        "decision": "PASS",
        "phase": "1",
        "summary": "Approved.",
        "rationale": "Looks good.",
        "carryforwards": [],
        "next_action": "Proceed.",
        "may_start_next_phase": True,
        "next_phase_override": None,
        "patch_targets": [],
    }
    base.update(overrides)
    return base


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


class ReviewerScopeAndEvidenceTests(unittest.TestCase):
    def _make_request(self, *, patch_round: int = 0) -> ReviewRequest:
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
                    patch_round=patch_round,
                ),
            ),
        )
        return ReviewRequest(
            run=run,
            phase=run.phases[0],
            packet={"status": "implemented"},
            repo_config={"repo_profile": "default"},
            diff_summary={"git": False, "status": [], "diffstat": ""},
            plan_text="# Test Plan",
            prior_decision=None,
            max_patch_rounds=2,
        )

    def test_prompt_declares_code_only_scope(self) -> None:
        prompt = CodexReviewAdapter()._build_prompt(self._make_request())
        self.assertIn("SCOPE: CODE ONLY", prompt)
        self.assertIn("Plan-level concerns are NEVER grounds for PATCH_REQUIRED", prompt)
        self.assertIn("patch_targets", prompt)
        self.assertIn("code_bug", prompt)
        self.assertIn("verification_failure", prompt)
        self.assertIn("falsified_packet", prompt)

    def test_prompt_surfaces_escalation_when_rounds_consumed(self) -> None:
        request = self._make_request(patch_round=2)
        prompt = CodexReviewAdapter()._build_prompt(request)
        self.assertIn("ESCALATION NOTICE", prompt)
        self.assertIn("REVIEW_LOOP_BREAK", prompt)

    def test_prompt_includes_prior_decision_when_resubmitting(self) -> None:
        request = self._make_request(patch_round=1)
        prior = PhaseDecision.patch_required(
            phase="1",
            summary="Needs fix.",
            rationale="See targets.",
            patch_targets=[
                PatchTarget(
                    file="src/foo.py",
                    line=10,
                    defect_class="code_bug",
                    evidence="raw SQL string interpolation",
                )
            ],
        )
        request_with_prior = ReviewRequest(
            run=request.run,
            phase=request.phase,
            packet=request.packet,
            repo_config=request.repo_config,
            diff_summary=request.diff_summary,
            plan_text=request.plan_text,
            prior_decision=prior,
            max_patch_rounds=2,
        )
        prompt = CodexReviewAdapter()._build_prompt(request_with_prior)
        self.assertIn("Prior decision on this phase", prompt)
        self.assertIn("src/foo.py", prompt)

    def test_decision_schema_includes_patch_targets(self) -> None:
        self.assertIn("patch_targets", DECISION_SCHEMA["required"])
        targets = DECISION_SCHEMA["properties"]["patch_targets"]
        self.assertEqual(targets["type"], "array")
        item_schema = targets["items"]
        self.assertEqual(
            sorted(item_schema["required"]),
            sorted(["file", "line", "defect_class", "evidence"]),
        )

    def test_patch_required_without_targets_is_auto_downgraded(self) -> None:
        payload = _decision_payload(
            decision="PATCH_REQUIRED",
            rationale="Plan does not say enough.",
            may_start_next_phase=False,
            patch_targets=[],
        )
        decision = _validated_phase_decision(json.dumps(payload))
        self.assertEqual(decision.decision, "CONDITIONAL_PASS")
        self.assertTrue(decision.may_start_next_phase)
        self.assertIn("auto-downgrade", decision.rationale)
        self.assertTrue(
            any("auto-downgrade" in c for c in decision.carryforwards),
            decision.carryforwards,
        )

    def test_patch_required_with_targets_is_kept(self) -> None:
        payload = _decision_payload(
            decision="PATCH_REQUIRED",
            rationale="Concrete defect found.",
            may_start_next_phase=False,
            patch_targets=[
                {
                    "file": "src/foo.py",
                    "line": 42,
                    "defect_class": "code_bug",
                    "evidence": "uses eval() on untrusted input",
                }
            ],
        )
        decision = _validated_phase_decision(json.dumps(payload))
        self.assertEqual(decision.decision, "PATCH_REQUIRED")
        self.assertEqual(len(decision.patch_targets), 1)
        self.assertEqual(decision.patch_targets[0].file, "src/foo.py")
        self.assertEqual(decision.patch_targets[0].defect_class, "code_bug")

    def test_validation_rejects_invalid_defect_class(self) -> None:
        payload = _decision_payload(
            decision="PATCH_REQUIRED",
            may_start_next_phase=False,
            patch_targets=[
                {
                    "file": "src/foo.py",
                    "line": 42,
                    "defect_class": "plan_amendment",
                    "evidence": "the plan should mention X",
                }
            ],
        )
        with self.assertRaises(RuntimeError) as ctx:
            _validated_phase_decision(json.dumps(payload))
        self.assertIn("defect_class", str(ctx.exception))

    def test_validation_rejects_empty_evidence(self) -> None:
        payload = _decision_payload(
            decision="PATCH_REQUIRED",
            may_start_next_phase=False,
            patch_targets=[
                {
                    "file": "src/foo.py",
                    "line": 42,
                    "defect_class": "code_bug",
                    "evidence": "",
                }
            ],
        )
        with self.assertRaises(RuntimeError):
            _validated_phase_decision(json.dumps(payload))

    def test_non_patch_decisions_strip_patch_targets(self) -> None:
        payload = _decision_payload(
            decision="PASS",
            patch_targets=[
                {
                    "file": "src/foo.py",
                    "line": 1,
                    "defect_class": "code_bug",
                    "evidence": "stray",
                }
            ],
        )
        decision = _validated_phase_decision(json.dumps(payload))
        self.assertEqual(decision.patch_targets, ())

    def test_legacy_decision_without_patch_targets_field_is_accepted(self) -> None:
        payload = {
            "decision": "PASS",
            "phase": "1",
            "summary": "Approved.",
            "rationale": "Looks good.",
            "carryforwards": [],
            "next_action": "Proceed.",
            "may_start_next_phase": True,
            "next_phase_override": None,
        }
        decision = _validated_phase_decision(json.dumps(payload))
        self.assertEqual(decision.decision, "PASS")
        self.assertEqual(decision.patch_targets, ())


if __name__ == "__main__":
    unittest.main()
