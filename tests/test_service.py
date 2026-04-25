import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate.models import PatchTarget, PhaseDecision, PhaseDefinition
from cross_agent_phase_gate.service import PhaseGateService, QueuedReviewAdapter


SAMPLE_PLAN = """
# HealthBot Example

## Phase 1 - Foundation

### Verification
- `python3 -m unittest tests.test_service`

## Phase 2 - Follow Through

### Verification
- `python3 -m unittest tests.test_service`
""".strip()


def _write_plan(repo_path: Path) -> Path:
    plan_path = repo_path / "docs" / "plans" / "sample-plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(SAMPLE_PLAN, encoding="utf-8")
    return plan_path


class PhaseGateServiceTests(unittest.TestCase):
    def test_pass_advances_to_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision.pass_decision(
                        phase="1",
                        summary="Looks good.",
                        rationale="Phase matches plan.",
                    )
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )

            current = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            result = service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=current["phase"]["id"],
                packet={
                    "status": "implemented",
                    "summary": "Phase 1 done.",
                    "files_touched": ["src/example.py"],
                    "verification": {
                        "python3 -m unittest tests.test_service": "passed"
                    },
                    "acceptance_results": [
                        {"criterion": "Phase 1 complete", "status": "passed"}
                    ],
                    "known_gaps": [],
                    "shared_gate_status": "green"
                },
            )

            self.assertEqual(result["decision"]["decision"], "PASS")
            status = service.status(repo_path=repo_path, run_id=run.run_id)
            self.assertEqual(status["current_phase"]["id"], "2")
            self.assertEqual(status["run"]["status"], "ready_for_next_phase")

    def test_conditional_pass_carries_forward_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision(
                        decision="CONDITIONAL_PASS",
                        phase="1",
                        summary="Acceptable with carryforwards.",
                        rationale="Need extra wiring next.",
                        carryforwards=("Wire subscriber.",),
                        next_action="Start phase 2 with the carryforward active.",
                        may_start_next_phase=True,
                        next_phase_override=None,
                    )
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )
            phase = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase["phase"]["id"],
                packet={
                    "status": "implemented",
                    "summary": "Phase 1 done.",
                    "files_touched": [],
                    "verification": {},
                    "acceptance_results": [],
                    "known_gaps": [],
                    "shared_gate_status": "green"
                },
            )

            next_phase = service.begin_phase(repo_path=repo_path, run_id=run.run_id)

            self.assertIn("Wire subscriber.", next_phase["active_carryforwards"])

    def test_patch_required_blocks_advancement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision.patch_required(
                        phase="1",
                        summary="Need a patch.",
                        rationale="Verification is incomplete.",
                        carryforwards=("Re-run verification.",),
                    )
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )
            phase = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase["phase"]["id"],
                packet={
                    "status": "implemented",
                    "summary": "Phase 1 done.",
                    "files_touched": [],
                    "verification": {},
                    "acceptance_results": [],
                    "known_gaps": [],
                    "shared_gate_status": "green"
                },
            )

            status = service.status(repo_path=repo_path, run_id=run.run_id)

            self.assertEqual(status["run"]["status"], "patch_required")
            self.assertEqual(status["current_phase"]["id"], "1")

    def test_decision_defaults_to_last_reviewed_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision.pass_decision(
                        phase="1",
                        summary="Approved.",
                        rationale="Phase 1 is good.",
                    )
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )
            phase = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase["phase"]["id"],
                packet={
                    "status": "implemented",
                    "summary": "Phase 1 done.",
                    "files_touched": [],
                    "verification": {},
                    "acceptance_results": [],
                    "known_gaps": [],
                    "shared_gate_status": "green"
                },
            )

            decision = service.decision(repo_path=repo_path, run_id=run.run_id)

            self.assertEqual(decision["phase"], "1")
            self.assertEqual(decision["decision"], "PASS")

    def test_close_run_clears_active_run_and_blocks_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            service = PhaseGateService(
                home_dir=home_dir,
                review_adapter=QueuedReviewAdapter([]),
            )
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )

            service.close_run(repo_path=repo_path, run_id=run.run_id)

            with self.assertRaises(FileNotFoundError):
                service.status(repo_path=repo_path)

    def test_completed_run_decision_uses_phase_id_even_if_reviewer_returns_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision.pass_decision(
                        phase="1",
                        summary="Phase 1 approved.",
                        rationale="Phase 1 matches the plan.",
                    ),
                    PhaseDecision.pass_decision(
                        phase="Phase 2 - Follow Through",
                        summary="Phase 2 approved.",
                        rationale="Phase 2 is acceptable.",
                    ),
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )

            phase_1 = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase_1["phase"]["id"],
                packet={
                    "status": "implemented",
                    "summary": "Phase 1 done.",
                    "files_touched": [],
                    "verification": {},
                    "acceptance_results": [],
                    "known_gaps": [],
                    "shared_gate_status": "green"
                },
            )
            phase_2 = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase_2["phase"]["id"],
                packet={
                    "status": "implemented",
                    "summary": "Phase 2 done.",
                    "files_touched": [],
                    "verification": {},
                    "acceptance_results": [],
                    "known_gaps": [],
                    "shared_gate_status": "green"
                },
            )

            status = service.status(repo_path=repo_path, run_id=run.run_id)
            decision = service.decision(repo_path=repo_path, run_id=run.run_id)

            self.assertEqual(status["run"]["status"], "completed")
            self.assertEqual(status["last_decision_phase_id"], "2")
            self.assertEqual(decision["phase"], "2")
            self.assertEqual(decision["decision"], "PASS")

    def test_status_and_decision_heal_stale_title_based_phase_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            service = PhaseGateService(
                home_dir=home_dir,
                review_adapter=QueuedReviewAdapter([]),
            )
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )

            completed = run.with_updates(
                status="completed",
                current_phase_index=2,
                phases=(
                    replace(run.phases[0], status="passed"),
                    replace(run.phases[1], status="passed"),
                ),
                last_decision_phase_id="Phase 2 - Follow Through",
            )
            service.store.save_run(repo_path, completed)
            service.store.save_decision(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id="2",
                decision=PhaseDecision.pass_decision(
                    phase="Phase 2 - Follow Through",
                    summary="Approved.",
                    rationale="Looks good.",
                ),
            )

            status = service.status(repo_path=repo_path, run_id=run.run_id)
            decision = service.decision(repo_path=repo_path, run_id=run.run_id)

            self.assertEqual(status["run"]["last_decision_phase_id"], "2")
            self.assertEqual(decision["phase"], "2")

    def test_diff_summary_includes_file_preview_for_untracked_allowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            service = PhaseGateService(home_dir=home_dir)
            service._run_git(repo_path, ["init"])
            note_path = repo_path / "notes" / "smoke.txt"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text("bidirectional smoke marker\n", encoding="utf-8")

            diff_summary = service._collect_diff_summary(
                repo_path=repo_path,
                phase=PhaseDefinition(
                    id="1",
                    title="Phase 1",
                    goal="Ship it",
                    allowed_paths=("notes/smoke.txt",),
                ),
            )

            self.assertTrue(diff_summary["git"])
            self.assertIn("?? notes/", diff_summary["status"])
            self.assertEqual(diff_summary["file_evidence"][0]["path"], "notes/smoke.txt")
            self.assertIn(
                "bidirectional smoke marker",
                diff_summary["file_evidence"][0]["content_preview"],
            )


class PatchRoundCapTests(unittest.TestCase):
    def _patch_target(self) -> PatchTarget:
        return PatchTarget(
            file="src/foo.py",
            line=12,
            defect_class="code_bug",
            evidence="raw SQL string interpolation observed",
        )

    def _packet(self) -> dict:
        return {
            "status": "implemented",
            "summary": "Phase 1 attempt.",
            "files_touched": [],
            "verification": {},
            "acceptance_results": [],
            "known_gaps": [],
            "shared_gate_status": "green",
        }

    def test_patch_round_increments_then_resets_on_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision.patch_required(
                        phase="1",
                        summary="Patch needed.",
                        rationale="Defect.",
                        patch_targets=(self._patch_target(),),
                    ),
                    PhaseDecision.pass_decision(
                        phase="1",
                        summary="Now correct.",
                        rationale="Patch applied.",
                    ),
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )

            phase = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase["phase"]["id"],
                packet=self._packet(),
            )
            after_patch = service.status(repo_path=repo_path, run_id=run.run_id)
            self.assertEqual(after_patch["current_phase"]["patch_round"], 1)

            phase_again = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            self.assertEqual(phase_again["patch_round"], 1)
            self.assertIsNotNone(phase_again["prior_decision"])
            self.assertEqual(
                phase_again["prior_decision"]["patch_targets"][0]["file"], "src/foo.py"
            )
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase_again["phase"]["id"],
                packet=self._packet(),
            )

            after_pass = service.status(repo_path=repo_path, run_id=run.run_id)
            # Phase 1 advanced to phase 2; phase 1's stored patch_round was reset to 0.
            self.assertEqual(after_pass["current_phase"]["id"], "2")
            phase_one = after_pass["run"]["phases"][0]
            self.assertEqual(phase_one["patch_round"], 0)

    def test_patch_round_cap_escalates_to_review_loop_break_hold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision.patch_required(
                        phase="1",
                        summary="Round 1.",
                        rationale="Defect.",
                        patch_targets=(self._patch_target(),),
                    ),
                    PhaseDecision.patch_required(
                        phase="1",
                        summary="Round 2.",
                        rationale="Still bad.",
                        patch_targets=(self._patch_target(),),
                    ),
                    PhaseDecision.patch_required(
                        phase="1",
                        summary="Round 3 — should escalate.",
                        rationale="Reviewer wants to keep bouncing.",
                        patch_targets=(self._patch_target(),),
                    ),
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )

            for _round in range(3):
                phase = service.begin_phase(
                    repo_path=repo_path, run_id=run.run_id
                )
                service.submit_phase(
                    repo_path=repo_path,
                    run_id=run.run_id,
                    phase_id=phase["phase"]["id"],
                    packet=self._packet(),
                )

            status = service.status(repo_path=repo_path, run_id=run.run_id)
            self.assertEqual(status["run"]["status"], "hold")
            decision = service.decision(repo_path=repo_path, run_id=run.run_id)
            self.assertEqual(decision["decision"], "HOLD")
            self.assertIn("REVIEW_LOOP_BREAK", decision["rationale"])
            self.assertTrue(
                any("REVIEW_LOOP_BREAK" in c for c in decision["carryforwards"]),
                decision["carryforwards"],
            )

    def test_max_patch_rounds_is_configurable_via_repo_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = _write_plan(repo_path)
            adapter = QueuedReviewAdapter(
                [
                    PhaseDecision.patch_required(
                        phase="1",
                        summary="Round 1 — should escalate immediately.",
                        rationale="cap=0 means first patch is over budget.",
                        patch_targets=(self._patch_target(),),
                    ),
                ]
            )
            service = PhaseGateService(home_dir=home_dir, review_adapter=adapter)
            run = service.init_run(
                repo_path=repo_path,
                plan_path=plan_path,
                role_mode="claude_builder_codex_reviewer",
                repo_profile_name="healthbot",
            )
            # Override the on-disk repo config to cap patch rounds at zero.
            config_path = service.store.config_path(repo_path)
            existing = config_path.read_text(encoding="utf-8")
            config_path.write_text(
                existing.replace("max_patch_rounds: 2", "max_patch_rounds: 0"),
                encoding="utf-8",
            )

            phase = service.begin_phase(repo_path=repo_path, run_id=run.run_id)
            service.submit_phase(
                repo_path=repo_path,
                run_id=run.run_id,
                phase_id=phase["phase"]["id"],
                packet=self._packet(),
            )

            decision = service.decision(repo_path=repo_path, run_id=run.run_id)
            self.assertEqual(decision["decision"], "HOLD")
            self.assertIn("REVIEW_LOOP_BREAK", decision["rationale"])


if __name__ == "__main__":
    unittest.main()
