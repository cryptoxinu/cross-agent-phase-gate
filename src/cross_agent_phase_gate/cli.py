from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .daemon import DEFAULT_HOST, DEFAULT_PORT, ensure_daemon_running, read_daemon_metadata, serve
from .role_mode import (
    CLAUDE_BUILDER_CODEX_REVIEWER,
    CODEX_BUILDER_CLAUDE_REVIEWER,
    resolve_role_mode,
)
from .service import PhaseGateService


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    home_dir = Path(os.environ.get("PHASE_GATE_HOME", Path.home() / ".phase-gate"))

    try:
        if args.command == "serve":
            serve(host=args.host, port=args.port, home_dir=home_dir)
            return 0
        if args.command == "doctor":
            response = _doctor(check_trigger=args.check_trigger)
            if args.json:
                print(json.dumps(response, indent=2, sort_keys=True))
            else:
                print(_human_output(args.command, response))
            return 0

        response = _execute_command(args, home_dir)

        if args.json:
            print(json.dumps(response, indent=2, sort_keys=True))
        else:
            print(_human_output(args.command, response))
        return 0
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _execute_command(args: argparse.Namespace, home_dir: Path) -> dict[str, Any]:
    try:
        ensure_daemon_running(home_dir)
        metadata = read_daemon_metadata(home_dir)
        if metadata is None:
            raise RuntimeError("Phase-gate daemon metadata missing after startup.")
    except RuntimeError:
        return _execute_locally(args, home_dir)
    return _execute_via_http(args, metadata)


def _execute_via_http(args: argparse.Namespace, metadata: dict[str, Any]) -> dict[str, Any]:
    if args.command == "init-run":
        payload = {
            "repo_path": str(Path(args.repo).resolve()),
            "plan_path": str(Path(args.plan).resolve()) if args.plan else None,
            "role_mode": _resolved_role_mode(args.role_mode),
            "repo_profile_name": args.repo_profile,
        }
        return _post(metadata, "/init-run", payload)
    if args.command == "begin-phase":
        payload = {
            "repo_path": str(Path(args.repo).resolve()),
            "run_id": args.run_id,
        }
        return _post(metadata, "/begin-phase", payload)
    if args.command == "submit-phase":
        payload = {
            "repo_path": str(Path(args.repo).resolve()),
            "run_id": args.run_id,
            "phase_id": args.phase_id,
            "packet": json.loads(Path(args.packet).read_text(encoding="utf-8")),
        }
        return _post(metadata, "/submit-phase", payload)
    if args.command == "decision":
        return _get(
            metadata,
            "/decision",
            {
                "repo": str(Path(args.repo).resolve()),
                "run_id": args.run_id,
                "phase_id": args.phase_id,
            },
        )
    if args.command == "status":
        return _get(
            metadata,
            "/status",
            {"repo": str(Path(args.repo).resolve()), "run_id": args.run_id},
        )
    if args.command == "resume":
        return _post(
            metadata,
            "/resume",
            {"repo_path": str(Path(args.repo).resolve())},
        )
    if args.command == "close-run":
        return _post(
            metadata,
            "/close-run",
            {
                "repo_path": str(Path(args.repo).resolve()),
                "run_id": args.run_id,
            },
        )
    raise RuntimeError(f"Unknown command: {args.command}")


def _execute_locally(args: argparse.Namespace, home_dir: Path) -> dict[str, Any]:
    service = PhaseGateService(home_dir=home_dir)
    repo_path = Path(args.repo).resolve()
    if args.command == "init-run":
        run = service.init_run(
            repo_path=repo_path,
            plan_path=Path(args.plan).resolve() if args.plan else None,
            role_mode=_resolved_role_mode(args.role_mode),
            repo_profile_name=args.repo_profile,
        )
        return {"run": run.to_dict()}
    if args.command == "begin-phase":
        return service.begin_phase(repo_path=repo_path, run_id=args.run_id)
    if args.command == "submit-phase":
        return service.submit_phase(
            repo_path=repo_path,
            run_id=args.run_id,
            phase_id=args.phase_id,
            packet=json.loads(Path(args.packet).read_text(encoding="utf-8")),
        )
    if args.command == "decision":
        return service.decision(
            repo_path=repo_path,
            run_id=args.run_id,
            phase_id=args.phase_id,
        )
    if args.command == "status":
        return service.status(repo_path=repo_path, run_id=args.run_id)
    if args.command == "resume":
        return service.resume(repo_path=repo_path)
    if args.command == "close-run":
        return service.close_run(repo_path=repo_path, run_id=args.run_id)
    raise RuntimeError(f"Unknown command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phase-gate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default=DEFAULT_HOST)
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--check-trigger", action="store_true")
    doctor_parser.add_argument("--json", action="store_true")

    init_parser = subparsers.add_parser("init-run")
    init_parser.add_argument("--repo", required=True)
    init_parser.add_argument("--plan")
    init_parser.add_argument(
        "--role-mode", default="auto"
    )
    init_parser.add_argument("--repo-profile", default="default")
    init_parser.add_argument("--json", action="store_true")

    begin_parser = subparsers.add_parser("begin-phase")
    begin_parser.add_argument("--repo", required=True)
    begin_parser.add_argument("--run-id")
    begin_parser.add_argument("--json", action="store_true")

    submit_parser = subparsers.add_parser("submit-phase")
    submit_parser.add_argument("--repo", required=True)
    submit_parser.add_argument("--run-id", required=True)
    submit_parser.add_argument("--phase-id", required=True)
    submit_parser.add_argument("--packet", required=True)
    submit_parser.add_argument("--json", action="store_true")

    decision_parser = subparsers.add_parser("decision")
    decision_parser.add_argument("--repo", required=True)
    decision_parser.add_argument("--run-id")
    decision_parser.add_argument("--phase-id")
    decision_parser.add_argument("--json", action="store_true")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--repo", required=True)
    status_parser.add_argument("--run-id")
    status_parser.add_argument("--json", action="store_true")

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--repo", required=True)
    resume_parser.add_argument("--json", action="store_true")

    close_parser = subparsers.add_parser("close-run")
    close_parser.add_argument("--repo", required=True)
    close_parser.add_argument("--run-id")
    close_parser.add_argument("--json", action="store_true")

    return parser


def _post(metadata: dict[str, Any], path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://{metadata['host']}:{metadata['port']}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_request_timeout(path)) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_read_http_error(exc)) from exc


def _get(metadata: dict[str, Any], path: str, query: dict[str, Any]) -> dict[str, Any]:
    filtered = {key: value for key, value in query.items() if value is not None}
    request = urllib.request.Request(
        f"http://{metadata['host']}:{metadata['port']}{path}"
        f"?{urllib.parse.urlencode(filtered)}"
    )
    try:
        with urllib.request.urlopen(request, timeout=_request_timeout(path)) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_read_http_error(exc)) from exc


def _read_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
        if not raw:
            return f"Phase-gate request failed with HTTP {exc.code}."
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return f"Phase-gate request failed with HTTP {exc.code}."
    error = payload.get("error")
    if isinstance(error, str) and error:
        return error
    return f"Phase-gate request failed with HTTP {exc.code}."


def _request_timeout(path: str) -> int:
    if path == "/submit-phase":
        return 1200
    return 30


def _human_output(command: str, response: dict[str, Any]) -> str:
    if command == "init-run":
        run = response["run"]
        return (
            f"Run {run['run_id']} initialized for {run['plan_title']} "
            f"with {len(run['phases'])} phase(s)."
        )
    if command == "begin-phase":
        phase = response["phase"]
        return f"Begin phase {phase['id']}: {phase['title']}"
    if command == "submit-phase":
        decision = response["decision"]
        return (
            f"{decision['decision']} for phase {decision['phase']}: "
            f"{decision['summary']}"
        )
    if command == "decision":
        return json.dumps(response, indent=2, sort_keys=True)
    if command in {"status", "resume"}:
        run = response["run"]
        phase = response.get("current_phase")
        if phase is None:
            return f"Run {run['run_id']} is {run['status']}."
        return (
            f"Run {run['run_id']} is {run['status']}; "
            f"current phase is {phase['id']}."
        )
    if command == "close-run":
        return f"Run {response['run']['run_id']} closed."
    if command == "doctor":
        lines = [
            f"phase-gate version: {response['phase_gate_version']}",
            f"codex: {response['codex']['status']}",
            f"claude auth: {response['claude_auth']['status']}",
            f"plugin manifest: {response['plugin_manifest']['status']}",
            f"codex skill: {response['codex_skill']['status']}",
        ]
        trigger = response.get("trigger_check")
        if trigger:
            lines.append(f"trigger check: {trigger['status']}")
        return "\n".join(lines)
    return json.dumps(response, indent=2, sort_keys=True)


def _doctor(check_trigger: bool) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[2]
    plugin_manifest = project_root / ".claude-plugin" / "plugin.json"
    payload = {
        "phase_gate_version": _package_version(),
        "project_root": str(project_root),
        "codex": _command_status(["codex", "--version"]),
        "claude": _command_status(["claude", "--version"]),
        "claude_auth": _claude_auth_status(),
        "plugin_manifest": _plugin_manifest_status(plugin_manifest),
        "codex_skill": _codex_skill_status(),
        "session_defaults": {
            "claude": CLAUDE_BUILDER_CODEX_REVIEWER,
            "codex": CODEX_BUILDER_CLAUDE_REVIEWER,
        },
    }
    if check_trigger:
        payload["trigger_check"] = _trigger_check(project_root, payload["claude_auth"])
    return payload


def _package_version() -> str:
    project_root = Path(__file__).resolve().parents[2]
    package_json = json.loads((project_root / "package.json").read_text(encoding="utf-8"))
    return str(package_json["version"])


def _command_status(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except Exception as exc:
        return {"status": "unavailable", "detail": str(exc)}
    detail = completed.stdout.strip() or completed.stderr.strip()
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "detail": detail,
        "returncode": completed.returncode,
    }


def _claude_auth_status() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["claude", "auth", "status"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except Exception as exc:
        return {"status": "unavailable", "detail": str(exc), "logged_in": False}
    raw = completed.stdout.strip() or completed.stderr.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "status": "error" if completed.returncode else "ok",
            "detail": raw,
            "logged_in": False,
        }
    logged_in = bool(parsed.get("loggedIn"))
    return {
        "status": "ok" if logged_in else "not_logged_in",
        "detail": parsed,
        "logged_in": logged_in,
    }


def _plugin_manifest_status(plugin_manifest: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["claude", "plugins", "validate", str(plugin_manifest)],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except Exception as exc:
        return {"status": "unavailable", "detail": str(exc)}
    detail = completed.stdout.strip() or completed.stderr.strip()
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "detail": detail,
        "returncode": completed.returncode,
    }


def _codex_skill_status() -> dict[str, Any]:
    skill_path = (
        Path.home()
        / ".codex"
        / "skills"
        / "cross-agent-phase-gate"
        / "SKILL.md"
    )
    if skill_path.exists():
        return {"status": "ok", "detail": str(skill_path)}
    return {"status": "missing", "detail": str(skill_path)}


def _trigger_check(project_root: Path, auth_status: dict[str, Any]) -> dict[str, Any]:
    if not auth_status.get("logged_in"):
        return {
            "status": "blocked_auth",
            "detail": "Claude CLI is not logged in.",
        }
    prompt = (
        "You have a written multi-phase implementation plan. Claude should build "
        "one bounded phase at a time and wait for Codex review before continuing. "
        "Which skill should you use? Reply with only the skill name."
    )
    try:
        completed = subprocess.run(
            ["claude", "-p", prompt],
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
    output = completed.stdout.strip() or completed.stderr.strip()
    status = (
        "ok"
        if completed.returncode == 0 and "cross-agent-phase-gate" in output
        else "unexpected"
    )
    return {
        "status": status,
        "detail": output,
        "returncode": completed.returncode,
    }


def _resolved_role_mode(requested_role_mode: str | None) -> str:
    return resolve_role_mode(
        requested_role_mode,
        session_kind=os.environ.get("PHASE_GATE_SESSION_KIND"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
