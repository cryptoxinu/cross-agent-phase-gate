import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate.role_mode import (
    CLAUDE_BUILDER_CODEX_REVIEWER,
    CODEX_BUILDER_CLAUDE_REVIEWER,
    builder_for_role_mode,
    resolve_role_mode,
    reviewer_for_role_mode,
)


class RoleModeTests(unittest.TestCase):
    def test_resolve_role_mode_uses_claude_default(self) -> None:
        self.assertEqual(
            resolve_role_mode("auto", session_kind="claude"),
            CLAUDE_BUILDER_CODEX_REVIEWER,
        )

    def test_resolve_role_mode_uses_codex_default(self) -> None:
        self.assertEqual(
            resolve_role_mode("auto", session_kind="codex"),
            CODEX_BUILDER_CLAUDE_REVIEWER,
        )

    def test_explicit_role_mode_wins_over_session_default(self) -> None:
        self.assertEqual(
            resolve_role_mode(
                CLAUDE_BUILDER_CODEX_REVIEWER,
                session_kind="codex",
            ),
            CLAUDE_BUILDER_CODEX_REVIEWER,
        )

    def test_role_helpers_match_expected_builder_and_reviewer(self) -> None:
        self.assertEqual(
            builder_for_role_mode(CLAUDE_BUILDER_CODEX_REVIEWER),
            "claude",
        )
        self.assertEqual(
            reviewer_for_role_mode(CLAUDE_BUILDER_CODEX_REVIEWER),
            "codex",
        )
        self.assertEqual(
            builder_for_role_mode(CODEX_BUILDER_CLAUDE_REVIEWER),
            "codex",
        )
        self.assertEqual(
            reviewer_for_role_mode(CODEX_BUILDER_CLAUDE_REVIEWER),
            "claude",
        )

    def test_invalid_role_mode_raises_clear_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_role_mode("broken_mode", session_kind="claude")


if __name__ == "__main__":
    unittest.main()
