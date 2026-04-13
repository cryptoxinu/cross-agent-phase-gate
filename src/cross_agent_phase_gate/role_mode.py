from __future__ import annotations


CLAUDE_BUILDER_CODEX_REVIEWER = "claude_builder_codex_reviewer"
CODEX_BUILDER_CLAUDE_REVIEWER = "codex_builder_claude_reviewer"

VALID_ROLE_MODES = frozenset(
    {
        CLAUDE_BUILDER_CODEX_REVIEWER,
        CODEX_BUILDER_CLAUDE_REVIEWER,
    }
)


def default_role_mode(session_kind: str | None = None) -> str:
    resolved_kind = (session_kind or "").strip().lower()
    if resolved_kind == "codex":
        return CODEX_BUILDER_CLAUDE_REVIEWER
    return CLAUDE_BUILDER_CODEX_REVIEWER


def resolve_role_mode(role_mode: str | None, session_kind: str | None = None) -> str:
    requested = (role_mode or "auto").strip().lower()
    if requested == "auto":
        return default_role_mode(session_kind=session_kind)
    if requested in VALID_ROLE_MODES:
        return requested
    raise ValueError(
        "Invalid role mode. Expected one of: "
        f"{', '.join(sorted(VALID_ROLE_MODES))}, auto."
    )


def builder_for_role_mode(role_mode: str) -> str:
    resolved = resolve_role_mode(role_mode)
    if resolved == CODEX_BUILDER_CLAUDE_REVIEWER:
        return "codex"
    return "claude"


def reviewer_for_role_mode(role_mode: str) -> str:
    resolved = resolve_role_mode(role_mode)
    if resolved == CODEX_BUILDER_CLAUDE_REVIEWER:
        return "claude"
    return "codex"

