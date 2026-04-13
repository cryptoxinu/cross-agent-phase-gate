from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import PhaseDefinition, RunManifest


PHASE_TITLE_RE = re.compile(r"(?i)\b(phase|step|slice)\b|\bP\d+[A-Za-z0-9.-]*\b")
PHASE_ID_RE = re.compile(
    r"(?i)\bphase\s+([A-Za-z0-9.-]+)|\bstep\s+([A-Za-z0-9.-]+)|\b(P\d+[A-Za-z0-9.-]*)\b"
)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
PATH_RE = re.compile(r"`([^`\n]+(?:/[^`\n]+|[.](?:py|md|ts|tsx|js|json|yaml|yml|toml|sh)))`")


@dataclass(frozen=True)
class Section:
    level: int
    title: str
    lines: tuple[str, ...]


def _split_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    current_level = 0
    current_title = "Preamble"
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_lines or current_title != "Preamble":
                sections.append(
                    Section(
                        level=current_level,
                        title=current_title,
                        lines=tuple(current_lines),
                    )
                )
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            current_level = level
            current_title = title
            current_lines = []
            continue
        current_lines.append(line)
    sections.append(
        Section(level=current_level, title=current_title, lines=tuple(current_lines))
    )
    return sections


def _extract_list_items(lines: Iterable[str]) -> tuple[str, ...]:
    items: list[str] = []
    for line in lines:
        match = LIST_ITEM_RE.match(line)
        if match:
            item = match.group(1).strip()
            if item.startswith("`") and item.endswith("`"):
                item = item[1:-1]
            items.append(item)
    return tuple(items)


def _extract_subsections(lines: Iterable[str]) -> dict[str, tuple[str, ...]]:
    sections: dict[str, list[str]] = {}
    current = "body"
    sections[current] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("###") or stripped.startswith("####"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level >= 3:
                current = stripped[level:].strip().lower()
                sections.setdefault(current, [])
                continue
        sections.setdefault(current, []).append(line)
    return {key: tuple(value) for key, value in sections.items()}


def _extract_code_blocks(lines: Iterable[str]) -> tuple[str, ...]:
    commands: list[str] = []
    in_block = False
    buffer: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith("```"):
            if not in_block:
                in_block = True
                buffer = []
            else:
                in_block = False
                for command in buffer:
                    cleaned = command.strip()
                    if cleaned:
                        commands.append(cleaned)
            continue
        if in_block:
            buffer.append(stripped)
    return tuple(commands)


def _extract_goal(subsections: dict[str, tuple[str, ...]], title: str) -> str:
    for key in ("goal", "summary", "objective"):
        if key in subsections:
            bullets = _extract_list_items(subsections[key])
            if bullets:
                return bullets[0]
            text = " ".join(line.strip() for line in subsections[key] if line.strip())
            if text:
                return text
    body_lines = [line.strip() for line in subsections.get("body", ()) if line.strip()]
    if body_lines:
        return body_lines[0]
    return title


def _extract_paths(subsections: dict[str, tuple[str, ...]], lines: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for key in subsections:
        if "file" in key or "path" in key:
            for item in _extract_list_items(subsections[key]):
                if item not in seen:
                    seen.append(item)
    text = "\n".join(lines)
    for match in PATH_RE.findall(text):
        if any(char.isspace() for char in match):
            continue
        if match not in seen:
            seen.append(match)
    return tuple(seen)


def _extract_verification(
    subsections: dict[str, tuple[str, ...]], default_verification: tuple[str, ...]
) -> tuple[str, ...]:
    commands: list[str] = []
    for key, lines in subsections.items():
        if any(token in key for token in ("verification", "validate", "test", "check")):
            for item in _extract_list_items(lines):
                if item not in commands:
                    commands.append(item)
            for command in _extract_code_blocks(lines):
                if command not in commands:
                    commands.append(command)
    if commands:
        return tuple(commands)
    return default_verification


def _extract_non_goals(subsections: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    non_goals: list[str] = []
    for key, lines in subsections.items():
        if any(token in key for token in ("non-goal", "non goal", "defer", "out of scope")):
            for item in _extract_list_items(lines):
                if item not in non_goals:
                    non_goals.append(item)
    return tuple(non_goals)


def _extract_acceptance(subsections: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    acceptance: list[str] = []
    for key, lines in subsections.items():
        if "accept" in key:
            for item in _extract_list_items(lines):
                if item not in acceptance:
                    acceptance.append(item)
    if acceptance:
        return tuple(acceptance)
    body_text = "\n".join(subsections.get("body", ()))
    checklist = re.findall(r"^\s*-\s+\[(?: |x|X)\]\s+(.*)$", body_text, flags=re.M)
    return tuple(item.strip() for item in checklist)


def _phase_id(title: str, index: int) -> str:
    match = PHASE_ID_RE.search(title)
    if match:
        for group in match.groups():
            if group:
                return group.upper() if group.upper().startswith("P") else group
    return str(index)


def normalize_plan(
    repo_path: Path,
    plan_path: Path,
    role_mode: str,
    repo_profile_name: str,
    default_verification: tuple[str, ...],
) -> RunManifest:
    plan_text = plan_path.read_text(encoding="utf-8")
    sections = _split_sections(plan_text)
    candidate_indexes = [
        index
        for index, section in enumerate(sections)
        if section.level >= 2 and PHASE_TITLE_RE.search(section.title)
    ]
    phase_sections: list[Section] = []
    for position, section_index in enumerate(candidate_indexes):
        section = sections[section_index]
        stop_index = len(sections)
        for following_index in candidate_indexes[position + 1 :]:
            if sections[following_index].level <= section.level:
                stop_index = following_index
                break
        combined_lines: list[str] = list(section.lines)
        for nested in sections[section_index + 1 : stop_index]:
            heading = "#" * max(nested.level, section.level + 1)
            combined_lines.append(f"{heading} {nested.title}")
            combined_lines.extend(nested.lines)
        phase_sections.append(
            Section(level=section.level, title=section.title, lines=tuple(combined_lines))
        )
    if not phase_sections:
        phase_sections = [
            Section(
                level=2,
                title="Phase 1 - Execute Plan",
                lines=tuple(plan_text.splitlines()),
            )
        ]
    phases: list[PhaseDefinition] = []
    for index, section in enumerate(phase_sections, start=1):
        subsections = _extract_subsections(section.lines)
        phases.append(
            PhaseDefinition(
                id=_phase_id(section.title, index),
                title=section.title,
                goal=_extract_goal(subsections, section.title),
                allowed_paths=_extract_paths(subsections, section.lines),
                non_goals=_extract_non_goals(subsections),
                acceptance_criteria=_extract_acceptance(subsections),
                verification=_extract_verification(
                    subsections=subsections,
                    default_verification=default_verification,
                ),
            )
        )
    plan_title = next(
        (section.title for section in sections if section.level == 1),
        plan_path.stem,
    )
    return RunManifest(
        run_id=uuid.uuid4().hex[:12],
        repo_path=str(repo_path.resolve()),
        plan_path=str(plan_path.resolve()),
        role_mode=role_mode,
        repo_profile_name=repo_profile_name,
        plan_title=plan_title,
        status="initialized",
        current_phase_index=0,
        active_carryforwards=(),
        phases=tuple(phases),
    )
