from __future__ import annotations

from pathlib import Path
from typing import Any

from .role_mode import builder_for_role_mode, reviewer_for_role_mode
from .yaml_config import load_yaml_or_json


def _profiles_root() -> Path:
    return Path(__file__).resolve().parents[2] / "profiles"


def _default_profile(name: str) -> dict[str, Any]:
    if name == "healthbot":
        return {
            "role_mode": "claude_builder_codex_reviewer",
            "repo_profile": "healthbot",
            "plan_roots": ["docs/plans", ".claude/plans"],
            "default_verification": [
                "ruff check src/ tests/",
                "pytest tests/ -q",
            ],
            "review_rules": {
                "reviewer_role": "codex",
                "builder_must_stop": True,
                "must_report_unrelated_gate_failures": True,
                "must_not_claim_dark_work_is_live": True,
                "medical_privacy_guardrails": True,
            },
        }
    return {
        "role_mode": "claude_builder_codex_reviewer",
        "repo_profile": "default",
        "plan_roots": ["docs/plans", ".claude/plans"],
        "default_verification": [],
        "review_rules": {
            "reviewer_role": "codex",
            "builder_must_stop": True,
            "must_report_unrelated_gate_failures": True,
        },
    }


def load_profile(name: str) -> dict[str, Any]:
    profile_path = _profiles_root() / f"{name}.yml"
    if profile_path.exists():
        return load_yaml_or_json(profile_path.read_text(encoding="utf-8"))
    return _default_profile(name)


def apply_role_mode(profile: dict[str, Any], role_mode: str) -> dict[str, Any]:
    review_rules = dict(profile.get("review_rules", {}))
    review_rules["builder_role"] = builder_for_role_mode(role_mode)
    review_rules["reviewer_role"] = reviewer_for_role_mode(role_mode)
    return {
        **profile,
        "role_mode": role_mode,
        "review_rules": review_rules,
    }
