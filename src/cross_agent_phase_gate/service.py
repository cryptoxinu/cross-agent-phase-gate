from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import PhaseDecision, PhaseDefinition, ReviewRequest, RunManifest, utc_now_iso
from .plan_normalizer import normalize_plan
from .review_adapter import QueuedReviewAdapter, ReviewAdapter, default_review_adapter
from .storage import StateStore


def _dedupe(values: tuple[str, ...], additions: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for item in (*values, *additions):
        if item and item not in ordered:
            ordered.append(item)
    return tuple(ordered)


class PhaseGateService:
    def __init__(
        self,
        home_dir: Path | None = None,
        review_adapter: ReviewAdapter | None = None,
    ) -> None:
        self.store = StateStore(home_dir=home_dir)
        self.review_adapter = review_adapter
        self._default_adapters: dict[str, ReviewAdapter] = {}

    def init_run(
        self,
        repo_path: Path,
        plan_path: Path | None,
        role_mode: str,
        repo_profile_name: str,
    ) -> RunManifest:
        repo_path = repo_path.resolve()
        repo_config = self.store.ensure_repo_config(
            repo_path=repo_path,
            repo_profile_name=repo_profile_name,
            role_mode=role_mode,
        )
        resolved_plan_path = plan_path
        if resolved_plan_path is None:
            discovered = self.store.discover_plan(
                repo_path=repo_path,
                plan_roots=list(repo_config.get("plan_roots", [])),
            )
            if discovered is None:
                raise FileNotFoundError("No plan file found for repository.")
            resolved_plan_path = discovered
        run = normalize_plan(
            repo_path=repo_path,
            plan_path=resolved_plan_path.resolve(),
            role_mode=role_mode,
            repo_profile_name=repo_profile_name,
            default_verification=tuple(repo_config.get("default_verification", [])),
        )
        self.store.save_run(repo_path, run)
        return run

    def begin_phase(self, repo_path: Path, run_id: str | None = None) -> dict[str, Any]:
        repo_path = repo_path.resolve()
        run = self.store.load_run(repo_path, run_id)
        phase = run.current_phase
        if phase is None:
            raise RuntimeError("Run is complete. No current phase remains.")
        if run.status == "hold":
            raise RuntimeError("Run is on HOLD. Resume only after updating the run.")
        if run.status == "closed":
            raise RuntimeError("Run is closed. Initialize a new run to continue work.")
        updated_phase = replace(phase, status="in_progress")
        updated_run = self._replace_phase(run, updated_phase).with_updates(
            status="phase_in_progress"
        )
        self.store.save_run(repo_path, updated_run)
        return {
            "run": updated_run.to_dict(),
            "phase": updated_phase.to_dict(),
            "active_carryforwards": list(updated_run.active_carryforwards),
        }

    def submit_phase(
        self,
        repo_path: Path,
        run_id: str,
        phase_id: str,
        packet: dict[str, Any],
    ) -> dict[str, Any]:
        repo_path = repo_path.resolve()
        run = self.store.load_run(repo_path, run_id)
        phase = run.current_phase
        if phase is None:
            raise RuntimeError("Run is already complete.")
        if phase.id != phase_id:
            raise ValueError(
                f"Cannot submit phase {phase_id}; current phase is {phase.id}."
            )
        repo_config = self.store.ensure_repo_config(
            repo_path=repo_path,
            repo_profile_name=run.repo_profile_name,
            role_mode=run.role_mode,
        )
        self.store.save_packet(repo_path, run.run_id, phase_id, packet)
        diff_summary = self._collect_diff_summary(repo_path=repo_path, phase=phase)
        plan_text = Path(run.plan_path).read_text(encoding="utf-8")
        decision = self._review_adapter_for_run(run).review(
            ReviewRequest(
                run=run,
                phase=phase,
                packet=packet,
                repo_config=repo_config,
                diff_summary=diff_summary,
                plan_text=plan_text,
            )
        )
        decision = self._canonicalize_decision_phase(decision=decision, phase=phase)
        self.store.save_decision(repo_path, run.run_id, phase_id, decision)
        updated_run = self._apply_decision(run, decision)
        self.store.save_run(repo_path, updated_run)
        return {
            "run": updated_run.to_dict(),
            "decision": decision.to_dict(),
            "current_phase": updated_run.current_phase.to_dict()
            if updated_run.current_phase
            else None,
        }

    def decision(
        self, repo_path: Path, run_id: str | None = None, phase_id: str | None = None
    ) -> dict[str, Any]:
        repo_path = repo_path.resolve()
        run = self.store.load_run(repo_path, run_id)
        normalized_run = self._normalize_run_decision_reference(repo_path, run)
        target_phase_id = self._resolve_phase_reference(
            normalized_run, phase_id or normalized_run.last_decision_phase_id
        )
        if target_phase_id is None:
            raise FileNotFoundError("No review decision has been recorded for this run.")
        decision = self.store.load_decision(repo_path, run.run_id, target_phase_id)
        phase = self._phase_by_id(normalized_run, target_phase_id)
        if phase is not None:
            decision = self._canonicalize_decision_phase(decision=decision, phase=phase)
            self.store.save_decision(repo_path, run.run_id, target_phase_id, decision)
        return decision.to_dict()

    def status(self, repo_path: Path, run_id: str | None = None) -> dict[str, Any]:
        repo_path = repo_path.resolve()
        run = self._normalize_run_decision_reference(
            repo_path=repo_path,
            run=self.store.load_run(repo_path, run_id),
        )
        current_phase = run.current_phase.to_dict() if run.current_phase else None
        return {
            "run": run.to_dict(),
            "current_phase": current_phase,
            "active_carryforwards": list(run.active_carryforwards),
            "last_decision_phase_id": run.last_decision_phase_id,
        }

    def resume(self, repo_path: Path) -> dict[str, Any]:
        return self.status(repo_path=repo_path)

    def close_run(self, repo_path: Path, run_id: str | None = None) -> dict[str, Any]:
        repo_path = repo_path.resolve()
        run = self.store.load_run(repo_path, run_id)
        closed = run.with_updates(status="closed", closed_at=utc_now_iso())
        self.store.save_run(repo_path, closed)
        self.store.clear_active_run(repo_path, closed.run_id)
        return {"run": closed.to_dict()}

    def _replace_phase(self, run: RunManifest, updated_phase: PhaseDefinition) -> RunManifest:
        phases = list(run.phases)
        phases[run.current_phase_index] = updated_phase
        return run.with_updates(phases=tuple(phases))

    def _apply_decision(self, run: RunManifest, decision: PhaseDecision) -> RunManifest:
        phase = run.current_phase
        if phase is None:
            return run
        phases = list(run.phases)
        active_carryforwards = _dedupe(run.active_carryforwards, decision.carryforwards)
        new_index = run.current_phase_index
        new_status = run.status
        phase_status = phase.status

        if decision.decision == "PASS":
            phase_status = "passed"
            new_index = run.current_phase_index + 1
            new_status = (
                "completed" if new_index >= len(phases) else "ready_for_next_phase"
            )
        elif decision.decision == "CONDITIONAL_PASS":
            phase_status = "conditional_pass"
            if decision.may_start_next_phase:
                new_index = run.current_phase_index + 1
                new_status = (
                    "completed"
                    if new_index >= len(phases)
                    else "ready_for_next_phase"
                )
            else:
                new_status = "hold"
        elif decision.decision == "PATCH_REQUIRED":
            phase_status = "patch_required"
            new_status = "patch_required"
        elif decision.decision == "HOLD":
            phase_status = "hold"
            new_status = "hold"
        elif decision.decision == "REDIRECT":
            phase_status = "redirected"
            if decision.next_phase_override:
                for index, candidate in enumerate(phases):
                    if candidate.id == decision.next_phase_override:
                        new_index = index
                        break
            new_status = (
                "ready_for_next_phase"
                if decision.may_start_next_phase
                else "redirected"
            )
        phases[run.current_phase_index] = replace(phase, status=phase_status)
        return run.with_updates(
            phases=tuple(phases),
            active_carryforwards=active_carryforwards,
            current_phase_index=new_index,
            status=new_status,
            last_decision_phase_id=decision.phase,
        )

    def _review_adapter_for_run(self, run: RunManifest) -> ReviewAdapter:
        if self.review_adapter is not None:
            return self.review_adapter
        adapter = self._default_adapters.get(run.role_mode)
        if adapter is None:
            adapter = default_review_adapter(run.role_mode)
            self._default_adapters[run.role_mode] = adapter
        return adapter

    def _canonicalize_decision_phase(
        self, decision: PhaseDecision, phase: PhaseDefinition
    ) -> PhaseDecision:
        if decision.phase == phase.id:
            return decision
        return replace(decision, phase=phase.id)

    def _normalize_run_decision_reference(
        self, repo_path: Path, run: RunManifest
    ) -> RunManifest:
        resolved = self._resolve_phase_reference(run, run.last_decision_phase_id)
        if resolved == run.last_decision_phase_id:
            return run
        updated = run.with_updates(last_decision_phase_id=resolved)
        self.store.save_run(repo_path, updated)
        return updated

    def _resolve_phase_reference(
        self, run: RunManifest, phase_ref: str | None
    ) -> str | None:
        if phase_ref is None:
            return None
        for phase in run.phases:
            if phase_ref in {phase.id, phase.title, f"Phase {phase.id}"}:
                return phase.id
        return phase_ref

    def _phase_by_id(
        self, run: RunManifest, phase_id: str
    ) -> PhaseDefinition | None:
        for phase in run.phases:
            if phase.id == phase_id:
                return phase
        return None

    def _collect_diff_summary(
        self, repo_path: Path, phase: PhaseDefinition
    ) -> dict[str, Any]:
        file_evidence = self._collect_file_evidence(repo_path, phase.allowed_paths)
        if not (repo_path / ".git").exists():
            return {
                "git": False,
                "status": [],
                "diffstat": "",
                "file_evidence": file_evidence,
            }
        status_output = self._run_git(repo_path, ["status", "--short"])
        diff_command = ["diff", "--stat"]
        if phase.allowed_paths:
            diff_command.extend(["--", *phase.allowed_paths])
        diffstat_output = self._run_git(repo_path, diff_command)
        return {
            "git": True,
            "status": status_output.splitlines() if status_output else [],
            "diffstat": diffstat_output,
            "file_evidence": file_evidence,
        }

    def _run_git(self, repo_path: Path, args: list[str]) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        return completed.stdout.strip()

    def _collect_file_evidence(
        self, repo_path: Path, allowed_paths: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for relative_path in allowed_paths:
            candidate = repo_path / relative_path
            if candidate.is_dir():
                evidence.append(
                    {"path": relative_path, "exists": True, "kind": "directory"}
                )
                continue
            if not candidate.exists() or not candidate.is_file():
                evidence.append({"path": relative_path, "exists": False})
                continue
            evidence.append(
                {
                    "path": relative_path,
                    "exists": True,
                    "content_preview": self._read_file_preview(candidate),
                    "git_diff": self._git_diff(repo_path, relative_path),
                }
            )
        return evidence

    def _read_file_preview(self, path: Path, limit: int = 2000) -> str:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"

    def _git_diff(self, repo_path: Path, relative_path: str, limit: int = 4000) -> str:
        diff = self._run_git(repo_path, ["diff", "--", relative_path])
        if len(diff) <= limit:
            return diff
        return diff[:limit] + f"\n... [truncated {len(diff) - limit} chars]"


__all__ = ["PhaseGateService", "QueuedReviewAdapter"]
