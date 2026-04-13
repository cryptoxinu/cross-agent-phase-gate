# Contributing

## Development Loop

1. Keep changes scoped.
2. Prefer test-first when changing runtime behavior.
3. Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

4. If you touch the Claude plugin surface, also run:

```bash
claude plugins validate .claude-plugin/plugin.json
```

## Release Notes

- Bump the version in:
  - `package.json`
  - `.claude-plugin/plugin.json`
  - `.claude-plugin/marketplace.json`
  - `src/cross_agent_phase_gate/__init__.py`
- If you use an installed Claude plugin copy locally, update it after publishing:

```bash
claude plugins update cross-agent-phase-gate@cross-agent-phase-gate --scope user
```

## Codex Skill Sync

The Codex-facing skill shipped in this repo lives at:

```text
codex-skill/SKILL.md
```

If you keep a local installed copy under `~/.codex/skills/cross-agent-phase-gate/`,
sync or relink that file after making changes.
