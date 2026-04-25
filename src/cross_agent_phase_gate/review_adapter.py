from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from .models import PATCH_DEFECT_CLASSES, PhaseDecision, ReviewRequest
from .role_mode import builder_for_role_mode, reviewer_for_role_mode


DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "decision",
        "phase",
        "summary",
        "rationale",
        "carryforwards",
        "next_action",
        "may_start_next_phase",
        "next_phase_override",
        "patch_targets",
    ],
    "properties": {
        "decision": {
            "type": "string",
            "enum": [
                "PASS",
                "CONDITIONAL_PASS",
                "PATCH_REQUIRED",
                "HOLD",
                "REDIRECT",
            ],
        },
        "phase": {"type": "string"},
        "summary": {"type": "string"},
        "rationale": {"type": "string"},
        "carryforwards": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
        "may_start_next_phase": {"type": "boolean"},
        "next_phase_override": {"type": ["string", "null"]},
        "patch_targets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["file", "line", "defect_class", "evidence"],
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "defect_class": {
                        "type": "string",
                        "enum": list(PATCH_DEFECT_CLASSES),
                    },
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


class ReviewAdapter(Protocol):
    def review(self, request: ReviewRequest) -> PhaseDecision: ...


class QueuedReviewAdapter:
    def __init__(self, decisions: list[PhaseDecision]) -> None:
        self._decisions = list(decisions)

    def review(self, request: ReviewRequest) -> PhaseDecision:
        if not self._decisions:
            raise RuntimeError("QueuedReviewAdapter exhausted.")
        return self._decisions.pop(0)


class CodexReviewAdapter:
    def __init__(self, codex_bin: str = "codex", timeout_seconds: int = 900) -> None:
        self.codex_bin = codex_bin
        self.timeout_seconds = timeout_seconds

    def review(self, request: ReviewRequest) -> PhaseDecision:
        prompt = self._build_prompt(request)
        with tempfile.TemporaryDirectory() as tmp_dir:
            schema_path = Path(tmp_dir) / "decision-schema.json"
            output_path = Path(tmp_dir) / "decision.json"
            schema_path.write_text(
                json.dumps(DECISION_SCHEMA, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            command = [
                self.codex_bin,
                "exec",
                "-",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-C",
                request.run.repo_path,
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
            ]
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "Codex review failed: "
                    + (completed.stderr.strip() or completed.stdout.strip() or "unknown error")
                )
            response_text = output_path.read_text(encoding="utf-8").strip()
            return _validated_phase_decision(response_text)

    def _build_prompt(self, request: ReviewRequest) -> str:
        return _build_prompt(request=request, reviewer_name="Codex")


class ClaudeReviewAdapter:
    def __init__(self, claude_bin: str = "claude", timeout_seconds: int = 900) -> None:
        self.claude_bin = claude_bin
        self.timeout_seconds = timeout_seconds

    def review(self, request: ReviewRequest) -> PhaseDecision:
        prompt = self._build_prompt(request)
        schema_text = json.dumps(DECISION_SCHEMA, sort_keys=True)
        command = [
            self.claude_bin,
            "-p",
            "--tools",
            "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--output-format",
            "json",
            "--json-schema",
            schema_text,
        ]
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            cwd=request.run.repo_path,
            check=False,
        )
        response_text = completed.stdout.strip()
        if completed.returncode != 0 or not response_text:
            detail = completed.stderr.strip() or response_text or "unknown error"
            raise RuntimeError(f"Claude review failed: {detail}")
        return _validated_phase_decision(_extract_claude_decision_text(response_text))

    def _build_prompt(self, request: ReviewRequest) -> str:
        return _build_prompt(request=request, reviewer_name="Claude")


def default_review_adapter(role_mode: str) -> ReviewAdapter:
    if reviewer_for_role_mode(role_mode) == "claude":
        return ClaudeReviewAdapter()
    return CodexReviewAdapter()


def _build_prompt(request: ReviewRequest, reviewer_name: str) -> str:
    packet_json = json.dumps(request.packet, indent=2, sort_keys=True)
    phase_json = json.dumps(request.phase.to_dict(), indent=2, sort_keys=True)
    config_json = json.dumps(request.repo_config, indent=2, sort_keys=True)
    diff_json = json.dumps(request.diff_summary, indent=2, sort_keys=True)
    builder_name = builder_for_role_mode(request.run.role_mode).capitalize()
    prior_decision_block = _prior_decision_block(request)
    escalation_block = _escalation_block(request)
    return f"""
You are {reviewer_name} acting as the audit gate for one bounded phase.

SCOPE: CODE ONLY. You are reviewing whether the code in the diff and the
verification evidence in the packet meet the phase's acceptance criteria. You
are NOT a plan editor, packet stylist, or scope architect.

What you MAY block on (PATCH_REQUIRED):
- code_bug: a concrete defect in the diff at a specific file:line that breaks
  behavior or violates an acceptance criterion. Quote the offending line in
  `evidence`.
- verification_failure: a verification command in the packet reports failure,
  was skipped, or was not actually run. Quote the failing output in `evidence`.
- falsified_packet: the packet claims something the diff or file evidence
  contradicts (e.g. claims a file was edited when it was not). Quote both
  sides in `evidence`.

What you MUST NOT block on:
- plan re-interpretation, plan rewording, or plan-amendment requests
- packet hygiene (typos, capitalization, missing-but-harmless fields)
- stylistic preference, naming bikesheds, refactor wishlist
- adjacent improvements outside this phase's allowed_paths
- speculative future work or risks not currently broken

If you have a plan-level concern, put it in `carryforwards` for a future
phase or note it in your rationale and PASS / CONDITIONAL_PASS the current
phase. Plan-level concerns are NEVER grounds for PATCH_REQUIRED.

Every PATCH_REQUIRED MUST include at least one entry in `patch_targets`,
each with a real file, line number, defect_class, and quoted evidence. An
empty or hand-wavy `patch_targets` array will be rejected by the gate and
auto-downgraded to CONDITIONAL_PASS.

Run:
- role_mode: {request.run.role_mode}
- builder: {builder_name}
- reviewer: {reviewer_name}
- repo_profile: {request.run.repo_profile_name}
- plan_title: {request.run.plan_title}
- phase_id: {request.phase.id}
- patch_round: {request.phase.patch_round}
- max_patch_rounds: {request.max_patch_rounds}
{escalation_block}
Repo config:
{config_json}

Current phase:
{phase_json}

Builder packet:
{packet_json}

Diff summary:
{diff_json}

Review hint:
- `file_evidence` may include file content previews for allowed paths, especially when git diff is empty for untracked files.
{prior_decision_block}
Original plan (REFERENCE ONLY — do not bounce on plan-amendment grounds):
{request.plan_text}

Decision rubric:
- PASS: phase is correct and next phase may begin
- CONDITIONAL_PASS: accepted, but carryforwards must remain active
- PATCH_REQUIRED: same phase must be patched — REQUIRES patch_targets with
  file, line, defect_class, evidence. No targets = no patch.
- HOLD: stop and wait (use sparingly; reserved for unrecoverable situations)
- REDIRECT: next work ordering or target phase changes

Output requirement:
- The `phase` field must be exactly `{request.phase.id}`. Do not use the phase title.
- For non-PATCH decisions, `patch_targets` must be `[]`.
- For PATCH_REQUIRED, `patch_targets` must be a non-empty array of objects each with file, line, defect_class (one of: {", ".join(PATCH_DEFECT_CLASSES)}), and evidence.
- Return only a JSON object with exactly these keys:
{_decision_contract_text()}
""".strip()


def _prior_decision_block(request: ReviewRequest) -> str:
    if request.prior_decision is None:
        return ""
    prior_json = json.dumps(request.prior_decision.to_dict(), indent=2, sort_keys=True)
    return (
        "\nPrior decision on this phase (the builder claims to have addressed "
        "these patch_targets — verify each one in the diff before re-bouncing):\n"
        f"{prior_json}\n"
    )


def _escalation_block(request: ReviewRequest) -> str:
    rounds_used = request.phase.patch_round
    rounds_left = max(request.max_patch_rounds - rounds_used, 0)
    if rounds_used == 0:
        return ""
    if rounds_left == 0:
        return (
            "\nESCALATION NOTICE: This phase has already consumed the patch-round "
            "budget. Any further PATCH_REQUIRED will be auto-converted to HOLD "
            "(REVIEW_LOOP_BREAK) and surfaced to the human operator. Only issue "
            "PATCH_REQUIRED now if there is a concrete, evidence-backed defect "
            "the builder failed to fix on the previous round. Otherwise PASS, "
            "CONDITIONAL_PASS with carryforwards, or HOLD with a clear reason.\n"
        )
    return (
        f"\nESCALATION NOTICE: This is patch round {rounds_used + 1} of "
        f"{request.max_patch_rounds}. After the budget is exhausted, further "
        "PATCH_REQUIRED auto-converts to HOLD. Be sure each entry in "
        "patch_targets is a defect that did not exist or was not flagged in "
        "the prior round; do not re-list issues the builder already addressed.\n"
    )


def _decision_contract_text() -> str:
    return json.dumps(
        {
            "decision": "PASS | CONDITIONAL_PASS | PATCH_REQUIRED | HOLD | REDIRECT",
            "phase": "<exact phase id>",
            "summary": "<short summary>",
            "rationale": "<full rationale>",
            "carryforwards": ["<string>", "..."],
            "next_action": "<what the builder should do next>",
            "may_start_next_phase": True,
            "next_phase_override": None,
            "patch_targets": [
                {
                    "file": "<path>",
                    "line": 0,
                    "defect_class": "code_bug | verification_failure | falsified_packet",
                    "evidence": "<quoted code or output proving the defect>",
                }
            ],
        },
        indent=2,
        sort_keys=True,
    )


def _validated_phase_decision(response_text: str) -> PhaseDecision:
    payload = json.loads(response_text)
    if not isinstance(payload, dict):
        raise RuntimeError("Reviewer output must be a JSON object.")
    expected_keys = set(DECISION_SCHEMA["required"])
    payload_keys = set(payload.keys())
    if "patch_targets" not in payload_keys:
        payload["patch_targets"] = []
        payload_keys = set(payload.keys())
    if payload_keys != expected_keys:
        raise RuntimeError(
            "Reviewer output keys did not match the decision contract. "
            f"Expected {sorted(expected_keys)}, got {sorted(payload_keys)}."
        )
    if payload["decision"] not in DECISION_SCHEMA["properties"]["decision"]["enum"]:
        raise RuntimeError("Reviewer output used an invalid decision value.")
    if not isinstance(payload["phase"], str):
        raise RuntimeError("Reviewer output phase must be a string.")
    if not isinstance(payload["summary"], str):
        raise RuntimeError("Reviewer output summary must be a string.")
    if not isinstance(payload["rationale"], str):
        raise RuntimeError("Reviewer output rationale must be a string.")
    if not isinstance(payload["carryforwards"], list) or not all(
        isinstance(item, str) for item in payload["carryforwards"]
    ):
        raise RuntimeError("Reviewer output carryforwards must be a string array.")
    if not isinstance(payload["next_action"], str):
        raise RuntimeError("Reviewer output next_action must be a string.")
    if not isinstance(payload["may_start_next_phase"], bool):
        raise RuntimeError("Reviewer output may_start_next_phase must be a boolean.")
    if payload["next_phase_override"] is not None and not isinstance(
        payload["next_phase_override"], str
    ):
        raise RuntimeError("Reviewer output next_phase_override must be a string or null.")
    if not isinstance(payload["patch_targets"], list):
        raise RuntimeError("Reviewer output patch_targets must be an array.")
    for target in payload["patch_targets"]:
        if not isinstance(target, dict):
            raise RuntimeError("Each patch_targets entry must be an object.")
        for key in ("file", "line", "defect_class", "evidence"):
            if key not in target:
                raise RuntimeError(
                    f"patch_targets entry missing required key: {key}"
                )
        if not isinstance(target["file"], str) or not target["file"].strip():
            raise RuntimeError("patch_targets[].file must be a non-empty string.")
        if not isinstance(target["line"], int):
            raise RuntimeError("patch_targets[].line must be an integer.")
        if target["defect_class"] not in PATCH_DEFECT_CLASSES:
            raise RuntimeError(
                "patch_targets[].defect_class must be one of: "
                f"{', '.join(PATCH_DEFECT_CLASSES)}"
            )
        if not isinstance(target["evidence"], str) or not target["evidence"].strip():
            raise RuntimeError("patch_targets[].evidence must be a non-empty string.")
    if payload["decision"] == "PATCH_REQUIRED" and not payload["patch_targets"]:
        # Code-only review boundary: PATCH_REQUIRED without concrete code
        # evidence is the failure mode we are explicitly preventing. Auto-
        # downgrade to CONDITIONAL_PASS so the loop never spins on plan-level
        # disagreement.
        payload["decision"] = "CONDITIONAL_PASS"
        payload["may_start_next_phase"] = True
        downgrade_note = (
            "[auto-downgrade] PATCH_REQUIRED without patch_targets is not "
            "permitted; converted to CONDITIONAL_PASS. Reviewer should encode "
            "any code defect as a patch_targets entry next time."
        )
        payload["rationale"] = (
            f"{payload['rationale']}\n\n{downgrade_note}"
            if payload.get("rationale")
            else downgrade_note
        )
        existing_carry = payload.get("carryforwards") or []
        payload["carryforwards"] = [*existing_carry, downgrade_note]
        if not payload.get("next_action"):
            payload["next_action"] = (
                "Continue to the next phase; reviewer must cite file:line "
                "evidence for any future code-level concerns."
            )
    if payload["decision"] != "PATCH_REQUIRED" and payload["patch_targets"]:
        # Non-PATCH decisions should never carry patch_targets.
        payload["patch_targets"] = []
    return PhaseDecision.from_dict(payload)


def _extract_claude_decision_text(response_text: str) -> str:
    parsed = json.loads(response_text)
    if isinstance(parsed, dict) and isinstance(parsed.get("structured_output"), dict):
        return json.dumps(parsed["structured_output"])
    if isinstance(parsed, dict):
        return response_text
    raise RuntimeError("Claude reviewer output did not contain a structured JSON decision.")
