from __future__ import annotations

import json
from typing import Any


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith(("[", "{")) and value.endswith(("]", "}")):
        return json.loads(value)
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() == "null":
        return None
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_yaml_or_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        return json.loads(stripped)
    lines = [line.rstrip() for line in text.splitlines()]
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any, str | None]] = [(-1, root, None)]

    for original_line in lines:
        if not original_line.strip() or original_line.lstrip().startswith("#"):
            continue
        indent = len(original_line) - len(original_line.lstrip(" "))
        line = original_line.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        parent_key = stack[-1][2]
        if line.startswith("- "):
            item = _parse_scalar(line[2:])
            if not isinstance(parent, list):
                if not isinstance(stack[-2][1], dict) or parent_key is None:
                    raise ValueError("Invalid YAML list structure.")
                new_list: list[Any] = []
                stack[-2][1][parent_key] = new_list
                stack[-1] = (stack[-1][0], new_list, parent_key)
                parent = new_list
            parent.append(item)
            continue
        if ":" not in line:
            raise ValueError(f"Unsupported YAML line: {original_line}")
        key, remainder = line.split(":", 1)
        key = key.strip()
        remainder = remainder.strip()
        if remainder:
            assert isinstance(parent, dict)
            parent[key] = _parse_scalar(remainder)
            continue
        assert isinstance(parent, dict)
        parent[key] = {}
        stack.append((indent, parent[key], key))
    return root


def _dump_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text or ":" in text or text.strip() != text:
        return json.dumps(text)
    return text


def dump_yaml(data: dict[str, Any], indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            if not value:
                lines.append(f"{prefix}{key}: {{}}")
                continue
            lines.append(f"{prefix}{key}:")
            lines.append(dump_yaml(value, indent + 2))
            continue
        if isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
                continue
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{prefix}  -")
                    lines.append(dump_yaml(item, indent + 4))
                else:
                    lines.append(f"{prefix}  - {_dump_scalar(item)}")
            continue
        lines.append(f"{prefix}{key}: {_dump_scalar(value)}")
    return "\n".join(line for line in lines if line != "")
