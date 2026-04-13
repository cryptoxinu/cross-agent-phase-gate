---
name: cross-agent-phase-gate
description: >
  Execute a written multi-phase implementation plan through the shared phase-gate
  daemon. In Claude, this skill defaults to `claude_builder_codex_reviewer`:
  Claude builds one bounded phase at a time and Codex acts as PM, design
  architect, and audit gate. The same shared system also supports the reverse
  direction from Codex terminals.
---

# Cross-Agent Phase Gate

Use the local wrapper:

```bash
<repo>/bin/phase-gate
```

## Core Contract

- In this Claude skill, Claude is the implementer by default.
- Codex is review-only unless the user explicitly asks for the reverse direction.
- Implement only one bounded phase at a time.
- Stop after every phase.
- Run verification before claiming completion.
- Submit a structured phase packet.
- Do not start the next phase until the stored decision allows it.

## Start A Run

1. Identify the plan file.
2. Choose the repo profile:
   - `healthbot` for HealthBot-style repos
   - `default` otherwise
3. Initialize the run:

```bash
<repo>/bin/claude-phase-gate init-run \
  --repo "$PWD" \
  --plan /absolute/path/to/plan.md \
  --repo-profile healthbot \
  --json
```

4. Begin the current phase:

```bash
<repo>/bin/claude-phase-gate begin-phase \
  --repo "$PWD" \
  --json
```

Read the returned phase data and active carryforwards before coding.

## During Implementation

- Keep scope inside the current phase.
- Do not start adjacent refactors.
- Do not self-advance after tests pass.
- If the current phase is a patch loop, fix only the requested patch slice.
- If unrelated repo failures exist, record them honestly in the packet.

## Direction Override

- If the user explicitly wants Codex to build and Claude to review, initialize the run with:

```bash
<repo>/bin/claude-phase-gate init-run \
  --repo "$PWD" \
  --plan /absolute/path/to/plan.md \
  --role-mode codex_builder_claude_reviewer \
  --json
```

## Packet Requirements

Create a JSON packet matching [phase-packet-template.json](./references/phase-packet-template.json).

Required fields:

- `status`
- `summary`
- `files_touched`
- `verification`
- `acceptance_results`
- `known_gaps`
- `shared_gate_status`

Use the template as the default shape and keep the contents factual.

## Submit For Review

```bash
<repo>/bin/claude-phase-gate submit-phase \
  --repo "$PWD" \
  --run-id <run-id> \
  --phase-id <phase-id> \
  --packet /absolute/path/to/packet.json \
  --json
```

Interpret the decision using [decision-schema.md](./references/decision-schema.md).

## Decision Handling

- `PASS`: begin the next phase.
- `CONDITIONAL_PASS`: begin the next phase with carryforwards active.
- `PATCH_REQUIRED`: re-open the same phase, apply only the requested patch slice, and resubmit.
- `HOLD`: stop.
- `REDIRECT`: follow the redirected next action or phase target.

## Forbidden Behaviors

- Do not self-approve the next phase.
- Do not claim user-visible completion for dark or unreachable work.
- Do not hide unrelated failing checks.
- Do not silently drop carryforwards.
- Do not expand scope without updating the plan and re-running the gate.
