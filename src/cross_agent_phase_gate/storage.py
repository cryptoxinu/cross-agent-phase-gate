from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PhaseDecision, RunManifest
from .profiles import apply_role_mode, load_profile
from .yaml_config import dump_yaml, load_yaml_or_json


class StateStore:
    def __init__(self, home_dir: Path | None = None) -> None:
        self.home_dir = Path(home_dir or Path.home() / ".phase-gate").expanduser()
        self.home_dir.mkdir(parents=True, exist_ok=True)

    def repo_root(self, repo_path: Path) -> Path:
        return repo_path.resolve() / ".phase-gate"

    def config_path(self, repo_path: Path) -> Path:
        return self.repo_root(repo_path) / "config.yml"

    def run_dir(self, repo_path: Path, run_id: str) -> Path:
        return self.repo_root(repo_path) / "runs" / run_id

    def manifest_path(self, repo_path: Path, run_id: str) -> Path:
        return self.run_dir(repo_path, run_id) / "run.json"

    def packet_path(self, repo_path: Path, run_id: str, phase_id: str) -> Path:
        return self.run_dir(repo_path, run_id) / f"phase-{phase_id}-packet.json"

    def decision_path(self, repo_path: Path, run_id: str, phase_id: str) -> Path:
        return self.run_dir(repo_path, run_id) / f"phase-{phase_id}-decision.json"

    def active_index_path(self) -> Path:
        return self.home_dir / "active-runs.json"

    def ensure_repo_config(
        self, repo_path: Path, repo_profile_name: str, role_mode: str | None = None
    ) -> dict[str, Any]:
        config_path = self.config_path(repo_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            config = load_yaml_or_json(config_path.read_text(encoding="utf-8"))
        else:
            config = load_profile(repo_profile_name)
            if role_mode:
                config = apply_role_mode(config, role_mode)
            config_path.write_text(dump_yaml(config) + "\n", encoding="utf-8")
        if role_mode:
            updated = apply_role_mode(config, role_mode)
            if updated != config:
                config_path.write_text(dump_yaml(updated) + "\n", encoding="utf-8")
                return updated
        return config

    def discover_plan(self, repo_path: Path, plan_roots: list[str]) -> Path | None:
        candidates: list[Path] = []
        for root in plan_roots:
            plan_root = repo_path / root
            if not plan_root.exists():
                continue
            candidates.extend(
                path for path in plan_root.rglob("*.md") if path.is_file()
            )
        if not candidates:
            return None
        return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]

    def save_run(self, repo_path: Path, run: RunManifest) -> None:
        manifest_path = self.manifest_path(repo_path, run.run_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(run.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._update_active_run(repo_path, run.run_id)

    def load_run(self, repo_path: Path, run_id: str | None = None) -> RunManifest:
        resolved_run_id = run_id or self.get_active_run_id(repo_path)
        if resolved_run_id is None:
            raise FileNotFoundError("No active run for repository.")
        manifest_path = self.manifest_path(repo_path, resolved_run_id)
        return RunManifest.from_dict(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )

    def save_packet(
        self, repo_path: Path, run_id: str, phase_id: str, packet: dict[str, Any]
    ) -> Path:
        packet_path = self.packet_path(repo_path, run_id, phase_id)
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        packet_path.write_text(
            json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return packet_path

    def save_decision(
        self, repo_path: Path, run_id: str, phase_id: str, decision: PhaseDecision
    ) -> Path:
        decision_path = self.decision_path(repo_path, run_id, phase_id)
        decision_path.parent.mkdir(parents=True, exist_ok=True)
        decision_path.write_text(
            json.dumps(decision.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return decision_path

    def load_decision(
        self, repo_path: Path, run_id: str, phase_id: str
    ) -> PhaseDecision:
        decision_path = self.decision_path(repo_path, run_id, phase_id)
        return PhaseDecision.from_dict(
            json.loads(decision_path.read_text(encoding="utf-8"))
        )

    def get_active_run_id(self, repo_path: Path) -> str | None:
        index_path = self.active_index_path()
        if not index_path.exists():
            return None
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        repo_key = str(repo_path.resolve())
        return payload.get("repos", {}).get(repo_key, {}).get("active_run_id")

    def clear_active_run(self, repo_path: Path, run_id: str) -> None:
        index_path = self.active_index_path()
        if not index_path.exists():
            return
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        repo_key = str(repo_path.resolve())
        repos = dict(payload.get("repos", {}))
        active = repos.get(repo_key, {})
        if active.get("active_run_id") == run_id:
            repos.pop(repo_key, None)
            index_path.write_text(
                json.dumps({"repos": repos}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    def _update_active_run(self, repo_path: Path, run_id: str) -> None:
        index_path = self.active_index_path()
        if index_path.exists():
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            payload = {"repos": {}}
        repo_key = str(repo_path.resolve())
        repos = dict(payload.get("repos", {}))
        repos[repo_key] = {"active_run_id": run_id}
        index_path.write_text(
            json.dumps({"repos": repos}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
