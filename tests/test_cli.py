import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate import cli


class CliTests(unittest.TestCase):
    def test_submit_phase_uses_extended_http_timeout(self) -> None:
        self.assertEqual(cli._request_timeout("/submit-phase"), 1200)
        self.assertEqual(cli._request_timeout("/status"), 30)

    def test_main_returns_clean_error_for_runtime_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stderr = io.StringIO()
            stdout = io.StringIO()
            with (
                patch.object(cli, "ensure_daemon_running"),
                patch.object(cli, "read_daemon_metadata", return_value={"host": "127.0.0.1", "port": 47474}),
                patch.object(cli, "_get", side_effect=RuntimeError("No review decision has been recorded for this run.")),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = cli.main(["decision", "--repo", tmp_dir])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("No review decision has been recorded for this run.", stderr.getvalue())

    def test_main_falls_back_to_local_execution_when_daemon_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            (repo / "docs" / "plans").mkdir(parents=True)
            (repo / "docs" / "plans" / "plan.md").write_text(
                "# Plan\n\n## Phase 1 - First\n", encoding="utf-8"
            )
            stderr = io.StringIO()
            stdout = io.StringIO()
            with (
                patch.object(cli, "ensure_daemon_running", side_effect=RuntimeError("bind failed")),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = cli.main(
                    [
                        "init-run",
                        "--repo",
                        tmp_dir,
                        "--plan",
                        str(repo / "docs" / "plans" / "plan.md"),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["run"]["plan_title"], "Plan")
            self.assertEqual(stderr.getvalue(), "")

    def test_main_uses_codex_session_default_role_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            (repo / "docs" / "plans").mkdir(parents=True)
            (repo / "docs" / "plans" / "plan.md").write_text(
                "# Plan\n\n## Phase 1 - First\n", encoding="utf-8"
            )
            stderr = io.StringIO()
            stdout = io.StringIO()
            with (
                patch.object(cli, "ensure_daemon_running", side_effect=RuntimeError("bind failed")),
                patch.dict(os.environ, {"PHASE_GATE_SESSION_KIND": "codex"}, clear=False),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = cli.main(
                    [
                        "init-run",
                        "--repo",
                        tmp_dir,
                        "--plan",
                        str(repo / "docs" / "plans" / "plan.md"),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                payload["run"]["role_mode"],
                "codex_builder_claude_reviewer",
            )
            self.assertEqual(stderr.getvalue(), "")

    def test_doctor_reports_auth_block_for_trigger_check(self) -> None:
        with patch.object(
            cli,
            "_command_status",
            side_effect=[
                {"status": "ok", "detail": "codex 1"},
                {"status": "ok", "detail": "claude 1"},
            ],
        ), patch.object(
            cli,
            "_claude_auth_status",
            return_value={"status": "not_logged_in", "detail": {}, "logged_in": False},
        ), patch.object(
            cli,
            "_plugin_manifest_status",
            return_value={"status": "ok", "detail": "valid"},
        ):
            payload = cli._doctor(check_trigger=True)

        self.assertEqual(payload["trigger_check"]["status"], "blocked_auth")


if __name__ == "__main__":
    unittest.main()
