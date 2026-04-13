---
name: cross-agent-phase-gate
description: Use when Codex should execute a written multi-phase implementation plan one bounded phase at a time while Claude acts as PM, design architect, and audit gate. In Codex, this skill defaults to `codex_builder_claude_reviewer`. The same shared system also supports the reverse direction from Claude terminals.
---

# Cross-Agent Phase Gate

Use the shared runtime in this repository:

```bash
<repo>/bin/codex-phase-gate
```

## Core Contract

- Codex is the implementer by default in this skill.
- Claude is review-only unless the user explicitly asks for the reverse direction.
- Implement only one bounded phase at a time.
- Stop after every phase.
- Run verification before claiming completion.
- Submit a structured phase packet.
- Do not start the next phase until the stored decision allows it.

## Start A Run

```bash
<repo>/bin/codex-phase-gate init-run \
  --repo "$PWD" \
  --plan /absolute/path/to/plan.md \
  --repo-profile default \
  --json
```

Then begin the current phase:

```bash
<repo>/bin/codex-phase-gate begin-phase \
  --repo "$PWD" \
  --json
```

## Direction Override

- If the user explicitly wants Claude to build, initialize with:

```bash
<repo>/bin/codex-phase-gate init-run \
  --repo "$PWD" \
  --plan /absolute/path/to/plan.md \
  --role-mode claude_builder_codex_reviewer \
  --json
```

## Packet And Review

- Create the shared structured packet with:
  - `status`
  - `summary`
  - `files_touched`
  - `verification`
  - `acceptance_results`
  - `known_gaps`
  - `shared_gate_status`
- Submit with:

```bash
<repo>/bin/codex-phase-gate submit-phase \
  --repo "$PWD" \
  --run-id <run-id> \
  --phase-id <phase-id> \
  --packet /absolute/path/to/packet.json \
  --json
```

## Decision Handling

- `PASS`: begin the next phase.
- `CONDITIONAL_PASS`: begin the next phase with carryforwards active.
- `PATCH_REQUIRED`: re-open the same phase, fix only the requested slice, and resubmit.
- `HOLD`: stop.
- `REDIRECT`: follow the redirected next action or phase target.
