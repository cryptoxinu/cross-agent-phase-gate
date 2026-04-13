# Cross-Agent Phase Gate Plugin

This plugin exposes the `cross-agent-phase-gate` skill to Claude Code and relies on the local
service wrapper at:

```bash
~/.claude/plugins/cross-agent-phase-gate/bin/phase-gate
```

The Claude-facing default is:

- builder: Claude
- reviewer: Codex

The shared runtime also supports the reverse direction from Codex terminals.

The manifest intentionally keeps the surface small:

- one plugin metadata file
- one skill directory
- no explicit `hooks` declaration

The service itself is reusable outside Claude because the daemon and CLI live in the same project.
For the full repo documentation, see the top-level `README.md`.
