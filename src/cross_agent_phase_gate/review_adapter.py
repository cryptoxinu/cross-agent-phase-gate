from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from .models import PhaseDecision, ReviewRequest
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
    def __init__(self, codex_bin: str = "codex", timeout_seconds: int = 180) -> None:
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
    def __init__(self, claude_bin: str = "claude", timeout_seconds: int = 180) -> None:
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
    return f"""
You are {reviewer_name} acting as PM, design architect, and audit gate.

Rules:
- Review only. Do not propose editing the repository directly.
- Decide whether the builder may continue.
- Be strict about plan adherence, scope honesty, verification honesty, and carryforwards.
- Output only JSON matching the schema.

Run:
- role_mode: {request.run.role_mode}
- builder: {builder_name}
- reviewer: {reviewer_name}
- repo_profile: {request.run.repo_profile_name}
- plan_title: {request.run.plan_title}
- phase_id: {request.phase.id}

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

Original plan:
{request.plan_text}

Decision rubric:
- PASS: phase is correct and next phase may begin
- CONDITIONAL_PASS: accepted, but carryforwards must remain active
- PATCH_REQUIRED: same phase must be patched before moving on
- HOLD: stop and wait
- REDIRECT: next work ordering or target phase changes

Output requirement:
- The `phase` field must be exactly `{request.phase.id}`. Do not use the phase title.
- Return only a JSON object with exactly these keys:
{_decision_contract_text()}
""".strip()


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
    return PhaseDecision.from_dict(payload)


def _extract_claude_decision_text(response_text: str) -> str:
    parsed = json.loads(response_text)
    if isinstance(parsed, dict) and isinstance(parsed.get("structured_output"), dict):
        return json.dumps(parsed["structured_output"])
    if isinstance(parsed, dict):
        return response_text
    raise RuntimeError("Claude reviewer output did not contain a structured JSON decision.")
