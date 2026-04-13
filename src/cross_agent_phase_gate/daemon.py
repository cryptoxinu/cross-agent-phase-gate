from __future__ import annotations

import json
import os
import socket
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from .service import PhaseGateService


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47474


def daemon_home(home_dir: Path | None = None) -> Path:
    resolved = Path(home_dir or Path.home() / ".phase-gate").expanduser()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def daemon_metadata_path(home_dir: Path | None = None) -> Path:
    return daemon_home(home_dir) / "daemon.json"


def read_daemon_metadata(home_dir: Path | None = None) -> dict[str, Any] | None:
    metadata_path = daemon_metadata_path(home_dir)
    if not metadata_path.exists():
        return None
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def write_daemon_metadata(
    host: str,
    port: int,
    home_dir: Path | None = None,
) -> None:
    daemon_metadata_path(home_dir).write_text(
        json.dumps(
            {
                "host": host,
                "port": port,
                "pid": os.getpid(),
                "version": __version__,
                "updated_at": time.time(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _pick_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


class PhaseGateRequestHandler(BaseHTTPRequestHandler):
    server: "PhaseGateHTTPServer"

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            if parsed.path == "/status":
                payload = self.server.service.status(
                    repo_path=Path(self._require_query(query, "repo")),
                    run_id=self._optional_query(query, "run_id"),
                )
                self._send_json(200, payload)
                return
            if parsed.path == "/decision":
                payload = self.server.service.decision(
                    repo_path=Path(self._require_query(query, "repo")),
                    run_id=self._optional_query(query, "run_id"),
                    phase_id=self._optional_query(query, "phase_id"),
                )
                self._send_json(200, payload)
                return
            self._send_json(404, {"error": f"Unknown path: {parsed.path}"})
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(409, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urllib.parse.urlparse(self.path)
            payload = self._read_json()
            if parsed.path == "/init-run":
                run = self.server.service.init_run(
                    repo_path=Path(payload["repo_path"]),
                    plan_path=Path(payload["plan_path"]) if payload.get("plan_path") else None,
                    role_mode=payload.get(
                        "role_mode", "claude_builder_codex_reviewer"
                    ),
                    repo_profile_name=payload.get("repo_profile_name", "default"),
                )
                self._send_json(200, {"run": run.to_dict()})
                return
            if parsed.path == "/begin-phase":
                result = self.server.service.begin_phase(
                    repo_path=Path(payload["repo_path"]),
                    run_id=payload.get("run_id"),
                )
                self._send_json(200, result)
                return
            if parsed.path == "/submit-phase":
                result = self.server.service.submit_phase(
                    repo_path=Path(payload["repo_path"]),
                    run_id=payload["run_id"],
                    phase_id=payload["phase_id"],
                    packet=payload["packet"],
                )
                self._send_json(200, result)
                return
            if parsed.path == "/resume":
                result = self.server.service.resume(repo_path=Path(payload["repo_path"]))
                self._send_json(200, result)
                return
            if parsed.path == "/close-run":
                result = self.server.service.close_run(
                    repo_path=Path(payload["repo_path"]),
                    run_id=payload.get("run_id"),
                )
                self._send_json(200, result)
                return
            self._send_json(404, {"error": f"Unknown path: {parsed.path}"})
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(409, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw or "{}")

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_query(self, query: dict[str, list[str]], key: str) -> str:
        values = query.get(key)
        if not values:
            raise ValueError(f"Missing query parameter: {key}")
        return values[0]

    def _optional_query(self, query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key)
        return values[0] if values else None


class PhaseGateHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        service: PhaseGateService,
        bind_and_activate: bool = True,
    ) -> None:
        self.service = service
        super().__init__(address, PhaseGateRequestHandler, bind_and_activate=bind_and_activate)


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    home_dir: Path | None = None,
    service: PhaseGateService | None = None,
) -> PhaseGateHTTPServer:
    resolved_port = DEFAULT_PORT if port is None else port
    return PhaseGateHTTPServer(
        (host, resolved_port),
        service=service or PhaseGateService(home_dir=home_dir),
    )


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    home_dir: Path | None = None,
) -> None:
    server = create_server(host=host, port=port, home_dir=home_dir)
    actual_host, actual_port = server.server_address
    write_daemon_metadata(actual_host, int(actual_port), home_dir=home_dir)
    server.serve_forever(poll_interval=0.5)


def daemon_is_healthy(home_dir: Path | None = None) -> bool:
    metadata = read_daemon_metadata(home_dir)
    if not metadata:
        return False
    if metadata.get("version") != __version__:
        return False
    try:
        request = urllib.request.Request(
            f"http://{metadata['host']}:{metadata['port']}/health"
        )
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("status") == "ok"
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def ensure_daemon_running(home_dir: Path | None = None) -> dict[str, Any]:
    metadata = read_daemon_metadata(home_dir)
    if metadata and metadata.get("version") != __version__:
        _stop_daemon(metadata)
    if daemon_is_healthy(home_dir):
        metadata = read_daemon_metadata(home_dir)
        assert metadata is not None
        return metadata
    resolved_home = daemon_home(home_dir)
    wrapper = Path(__file__).resolve().parents[2] / "bin" / "phase-gate"
    logs_dir = resolved_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "daemon.log"
    err_path = logs_dir / "daemon.err.log"
    chosen_port = DEFAULT_PORT
    metadata = read_daemon_metadata(home_dir)
    if metadata and isinstance(metadata.get("port"), int):
        chosen_port = int(metadata["port"])
    if _port_in_use(DEFAULT_HOST, chosen_port):
        chosen_port = _pick_port(DEFAULT_HOST)
    env = dict(os.environ)
    env["PHASE_GATE_HOME"] = str(resolved_home)
    with log_path.open("ab") as stdout_handle, err_path.open("ab") as stderr_handle:
        subprocess.Popen(  # noqa: S603
            [str(wrapper), "serve", "--host", DEFAULT_HOST, "--port", str(chosen_port)],
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    deadline = time.time() + 10
    while time.time() < deadline:
        if daemon_is_healthy(home_dir):
            metadata = read_daemon_metadata(home_dir)
            assert metadata is not None
            return metadata
        time.sleep(0.2)
    raise RuntimeError("Failed to start phase-gate daemon.")


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def _stop_daemon(metadata: dict[str, Any]) -> None:
    pid = metadata.get("pid")
    if not isinstance(pid, int):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
