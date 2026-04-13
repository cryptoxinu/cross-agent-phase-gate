from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _tupled(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, tuple):
        return values
    return tuple(str(value) for value in values)


@dataclass(frozen=True)
class PhaseDefinition:
    id: str
    title: str
    goal: str
    allowed_paths: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    stop_condition: str = (
        "Stop after implementation, verification, and packet submission."
    )
    carryforwards: tuple[str, ...] = ()
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "allowed_paths": list(self.allowed_paths),
            "non_goals": list(self.non_goals),
            "acceptance_criteria": list(self.acceptance_criteria),
            "verification": list(self.verification),
            "stop_condition": self.stop_condition,
            "carryforwards": list(self.carryforwards),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseDefinition":
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            goal=str(data.get("goal", data["title"])),
            allowed_paths=_tupled(data.get("allowed_paths")),
            non_goals=_tupled(data.get("non_goals")),
            acceptance_criteria=_tupled(data.get("acceptance_criteria")),
            verification=_tupled(data.get("verification")),
            stop_condition=str(
                data.get(
                    "stop_condition",
                    "Stop after implementation, verification, and packet submission.",
                )
            ),
            carryforwards=_tupled(data.get("carryforwards")),
            status=str(data.get("status", "pending")),
        )


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    repo_path: str
    plan_path: str
    role_mode: str
    repo_profile_name: str
    plan_title: str
    status: str
    current_phase_index: int
    active_carryforwards: tuple[str, ...]
    phases: tuple[PhaseDefinition, ...]
    last_decision_phase_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    closed_at: str | None = None

    @property
    def current_phase(self) -> PhaseDefinition | None:
        if self.current_phase_index < 0 or self.current_phase_index >= len(self.phases):
            return None
        return self.phases[self.current_phase_index]

    def with_updates(self, **changes: Any) -> "RunManifest":
        next_changes = {"updated_at": utc_now_iso(), **changes}
        return replace(self, **next_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "repo_path": self.repo_path,
            "plan_path": self.plan_path,
            "role_mode": self.role_mode,
            "repo_profile_name": self.repo_profile_name,
            "plan_title": self.plan_title,
            "status": self.status,
            "current_phase_index": self.current_phase_index,
            "active_carryforwards": list(self.active_carryforwards),
            "phases": [phase.to_dict() for phase in self.phases],
            "last_decision_phase_id": self.last_decision_phase_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunManifest":
        return cls(
            run_id=str(data["run_id"]),
            repo_path=str(data["repo_path"]),
            plan_path=str(data["plan_path"]),
            role_mode=str(data["role_mode"]),
            repo_profile_name=str(data.get("repo_profile_name", "default")),
            plan_title=str(data.get("plan_title", "Plan")),
            status=str(data.get("status", "initialized")),
            current_phase_index=int(data.get("current_phase_index", 0)),
            active_carryforwards=_tupled(data.get("active_carryforwards")),
            phases=tuple(
                PhaseDefinition.from_dict(item) for item in data.get("phases", [])
            ),
            last_decision_phase_id=data.get("last_decision_phase_id"),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
            closed_at=data.get("closed_at"),
        )


@dataclass(frozen=True)
class PhaseDecision:
    decision: str
    phase: str
    summary: str
    rationale: str
    carryforwards: tuple[str, ...] = ()
    next_action: str = ""
    may_start_next_phase: bool = False
    next_phase_override: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "phase": self.phase,
            "summary": self.summary,
            "rationale": self.rationale,
            "carryforwards": list(self.carryforwards),
            "next_action": self.next_action,
            "may_start_next_phase": self.may_start_next_phase,
            "next_phase_override": self.next_phase_override,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseDecision":
        return cls(
            decision=str(data["decision"]).upper(),
            phase=str(data["phase"]),
            summary=str(data.get("summary", "")),
            rationale=str(data.get("rationale", "")),
            carryforwards=_tupled(data.get("carryforwards")),
            next_action=str(data.get("next_action", "")),
            may_start_next_phase=bool(data.get("may_start_next_phase", False)),
            next_phase_override=data.get("next_phase_override"),
            created_at=str(data.get("created_at", utc_now_iso())),
        )

    @classmethod
    def pass_decision(
        cls, phase: str, summary: str, rationale: str
    ) -> "PhaseDecision":
        return cls(
            decision="PASS",
            phase=phase,
            summary=summary,
            rationale=rationale,
            carryforwards=(),
            next_action="Proceed to the next phase.",
            may_start_next_phase=True,
        )

    @classmethod
    def patch_required(
        cls,
        phase: str,
        summary: str,
        rationale: str,
        carryforwards: tuple[str, ...] | list[str] = (),
    ) -> "PhaseDecision":
        return cls(
            decision="PATCH_REQUIRED",
            phase=phase,
            summary=summary,
            rationale=rationale,
            carryforwards=_tupled(carryforwards),
            next_action="Apply the requested patch slice and resubmit the same phase.",
            may_start_next_phase=False,
        )


@dataclass(frozen=True)
class ReviewRequest:
    run: RunManifest
    phase: PhaseDefinition
    packet: dict[str, Any]
    repo_config: dict[str, Any]
    diff_summary: dict[str, Any]
    plan_text: str
