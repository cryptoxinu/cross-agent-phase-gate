# Cross Agent Phase Gate

Bidirectional phase-gated delivery loops for Claude Code and Codex.

This repo packages one shared runtime with two front-ends:

- Claude front-end: Claude plugin + Claude skill
- Codex front-end: Codex skill
- Shared core: local daemon, CLI, plan parser, packet store, review adapters

The default direction depends on the terminal you are using:

- In Claude, Claude builds and Codex reviews.
- In Codex, Codex builds and Claude reviews.
- In either terminal, you can override the direction explicitly.

## Why This Exists

This project automates a disciplined two-agent delivery loop:

1. Start from a written implementation plan.
2. Normalize that plan into bounded phases.
3. Build exactly one phase.
4. Stop and submit a structured packet.
5. Ask the other model to review the phase.
6. Advance only if the review decision allows it.

Instead of maintaining separate Claude-only and Codex-only systems, this repo keeps one shared state machine and switches reviewer behavior from `role_mode`.

## What It Ships

- `bin/phase-gate`: neutral CLI wrapper
- `bin/claude-phase-gate`: Claude-session wrapper
- `bin/codex-phase-gate`: Codex-session wrapper
- `.claude-plugin/`: Claude plugin manifest
- `skills/cross-agent-phase-gate/`: Claude skill
- `codex-skill/SKILL.md`: repo-contained Codex skill definition
- `src/cross_agent_phase_gate/`: runtime, parser, adapters, daemon, storage
- `profiles/`: built-in repo profiles
- `examples/`: example config and phase packet
- `tests/`: unit and integration tests

## Status

Current version: `0.2.1`

Verified locally with:

- Claude Code `2.1.104`
- Codex CLI `0.120.0`
- Python unit suite: `33/33` passing

Live checks already passed:

- Claude installed-plugin trigger probe
- Codex skill-selection probe
- Claude builder -> Codex reviewer flow
- Codex builder -> Claude reviewer flow

## Installation

### Prerequisites

- Claude Code installed and authenticated
- Codex CLI installed and authenticated
- Python 3.10+ available locally

### Use In Claude

For ad hoc local use:

```bash
claude --plugin-dir /absolute/path/to/cross-agent-phase-gate
```

To install it into your Claude plugins directory:

```bash
mkdir -p ~/.claude/plugins
ln -s /absolute/path/to/cross-agent-phase-gate ~/.claude/plugins/cross-agent-phase-gate
```

Then trigger it with a prompt such as:

```text
Use cross-agent-phase-gate to execute this plan one phase at a time with the other model reviewing each phase.
```

### Use In Codex

Copy or symlink the repo-contained skill into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills/cross-agent-phase-gate
ln -s /absolute/path/to/cross-agent-phase-gate/codex-skill/SKILL.md \
  ~/.codex/skills/cross-agent-phase-gate/SKILL.md
```

Then prompt Codex with something like:

```text
Use cross-agent-phase-gate for this plan. The current terminal should build one phase at a time and wait for the other model to review before continuing.
```

## Quick Start

### Claude Session

```bash
/absolute/path/to/cross-agent-phase-gate/bin/claude-phase-gate init-run \
  --repo /path/to/repo \
  --plan /path/to/plan.md \
  --repo-profile default \
  --json

/absolute/path/to/cross-agent-phase-gate/bin/claude-phase-gate begin-phase \
  --repo /path/to/repo \
  --json
```

### Codex Session

```bash
/absolute/path/to/cross-agent-phase-gate/bin/codex-phase-gate init-run \
  --repo /path/to/repo \
  --plan /path/to/plan.md \
  --repo-profile default \
  --json

/absolute/path/to/cross-agent-phase-gate/bin/codex-phase-gate begin-phase \
  --repo /path/to/repo \
  --json
```

### Explicit Direction Override

Force Claude to build from either terminal:

```bash
/absolute/path/to/cross-agent-phase-gate/bin/phase-gate init-run \
  --repo /path/to/repo \
  --plan /path/to/plan.md \
  --role-mode claude_builder_codex_reviewer \
  --json
```

Force Codex to build from either terminal:

```bash
/absolute/path/to/cross-agent-phase-gate/bin/phase-gate init-run \
  --repo /path/to/repo \
  --plan /path/to/plan.md \
  --role-mode codex_builder_claude_reviewer \
  --json
```

## Plan Format

Plans are written in Markdown with bounded phases:

```md
# Delivery Plan

## Phase 1 - Build The Foundation

### Goal
Ship the minimal foundation.

### Files
- `src/example.py`
- `tests/test_example.py`

### Verification
- `python3 -m unittest tests.test_example`

### Acceptance Criteria
- Core behavior exists
- Tests prove it works

### Non-Goals
- No adjacent refactors
```

The parser normalizes those sections into machine state under `.phase-gate/runs/<run-id>/run.json`.

## Packet Format

Phase packets are JSON. See [examples/phase-packet.json](./examples/phase-packet.json).

Required top-level fields:

- `status`
- `summary`
- `files_touched`
- `verification`
- `acceptance_results`
- `known_gaps`
- `shared_gate_status`

## Decisions

Reviewers return one of:

- `PASS`
- `CONDITIONAL_PASS`
- `PATCH_REQUIRED`
- `HOLD`
- `REDIRECT`

The decision contract is shared between Claude and Codex reviewers.

## Runtime Artifacts

Each repo using the workflow gets a local `.phase-gate/` directory:

- `.phase-gate/config.yml`
- `.phase-gate/runs/<run-id>/run.json`
- `.phase-gate/runs/<run-id>/phase-<id>-packet.json`
- `.phase-gate/runs/<run-id>/phase-<id>-decision.json`

This keeps the workflow auditable and resumable.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Validate the Claude plugin manifest:

```bash
claude plugins validate .claude-plugin/plugin.json
```

Run the local doctor command:

```bash
bin/phase-gate doctor --check-trigger --json
```

## Limitations

- This is a local-first workflow, not a hosted service.
- Reviewer quality depends on the local Claude and Codex CLIs being authenticated and functional.
- Very large diffs will still need phase discipline; the system helps, but it cannot rescue a bad plan.
- The strongest proof so far is live smoke coverage and unit coverage, not a long-running production workload across many repos.

## Repo Name

The recommended GitHub repository name for this project is:

`cross-agent-phase-gate`

It matches the current runtime/package/plugin names and avoids a risky rename across the working implementation.
