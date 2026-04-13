import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cross_agent_phase_gate.daemon import create_server
from cross_agent_phase_gate.models import PhaseDecision
from cross_agent_phase_gate.service import PhaseGateService, QueuedReviewAdapter


SAMPLE_PLAN = """
# Example Plan

## Phase 1 - First

### Verification
- `python3 -m unittest tests.test_daemon`

## Phase 2 - Second
""".strip()


class DaemonIntegrationTests(unittest.TestCase):
    def test_http_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            repo_path = Path(tmp_dir) / "repo"
            repo_path.mkdir()
            plan_path = repo_path / "docs" / "plans" / "example.md"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(SAMPLE_PLAN, encoding="utf-8")
            service = PhaseGateService(
                home_dir=home_dir,
                review_adapter=QueuedReviewAdapter(
                    [
                        PhaseDecision.pass_decision(
                            phase="1",
                            summary="Approved.",
                            rationale="Looks correct.",
                        )
                    ]
                ),
            )
            server = create_server(host="127.0.0.1", port=0, home_dir=home_dir, service=service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address

            init_payload = self._post(
                host,
                port,
                "/init-run",
                {
                    "repo_path": str(repo_path),
                    "plan_path": str(plan_path),
                    "role_mode": "claude_builder_codex_reviewer",
                    "repo_profile_name": "healthbot",
                },
            )
            run_id = init_payload["run"]["run_id"]

            phase_payload = self._post(
                host,
                port,
                "/begin-phase",
                {"repo_path": str(repo_path), "run_id": run_id},
            )

            self.assertEqual(phase_payload["phase"]["id"], "1")

            submit_payload = self._post(
                host,
                port,
                "/submit-phase",
                {
                    "repo_path": str(repo_path),
                    "run_id": run_id,
                    "phase_id": "1",
                    "packet": {
                        "status": "implemented",
                        "summary": "done",
                        "files_touched": [],
                        "verification": {},
                        "acceptance_results": [],
                        "known_gaps": [],
                        "shared_gate_status": "green",
                    },
                },
            )

            self.assertEqual(submit_payload["decision"]["decision"], "PASS")

            status_payload = self._get(
                host,
                port,
                "/status",
                {"repo": str(repo_path), "run_id": run_id},
            )

            self.assertEqual(status_payload["run"]["status"], "ready_for_next_phase")
            self.assertEqual(status_payload["current_phase"]["id"], "2")

            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_errors_are_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home_dir = Path(tmp_dir) / "home"
            service = PhaseGateService(
                home_dir=home_dir,
                review_adapter=QueuedReviewAdapter([]),
            )
            server = create_server(host="127.0.0.1", port=0, home_dir=home_dir, service=service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address

            with self.assertRaises(urllib.error.HTTPError) as context:
                self._get(host, port, "/decision", {"repo": str(Path(tmp_dir) / "repo")})

            error_payload = json.loads(context.exception.read().decode("utf-8"))
            context.exception.close()
            self.assertIn("error", error_payload)

            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def _post(
        self, host: str, port: int, path: str, payload: dict[str, object]
    ) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://{host}:{port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(
        self, host: str, port: int, path: str, query: dict[str, object]
    ) -> dict[str, object]:
        request = urllib.request.Request(
            f"http://{host}:{port}{path}?{urllib.parse.urlencode(query)}"
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
