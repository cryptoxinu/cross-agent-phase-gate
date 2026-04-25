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
- `PATCH_REQUIRED`: re-open the same phase, fix the requested slice, and resubmit. See **On `PATCH_REQUIRED`** below — anti-laziness rule applies.
- `HOLD`: stop. If the rationale contains `[REVIEW_LOOP_BREAK]`, the patch-round cap was hit and the human operator must adjudicate.
- `REDIRECT`: follow the redirected next action or phase target.

## On `PATCH_REQUIRED` (anti-laziness rule)

Every `PATCH_REQUIRED` decision carries a structured `patch_targets` array. Each entry has `file`, `line`, `defect_class` (`code_bug` | `verification_failure` | `falsified_packet`), and `evidence`.

You MUST:

1. Read every entry. Do not skim or batch.
2. For each target, decide agree or disagree against the actual file and line.
3. For every agreed target, apply the fix. ALL of them. No half-measures, no "next round". If you agree with five, ship five fixes before resubmitting.
4. For every disagreed target, write an explicit rebuttal in `patch_dispositions[].rebuttal` and surface it in `known_gaps`. Never silently skip. Never claim `applied` without a corresponding diff.
5. Resubmit only after every agreed-with fix is in the diff.

There is no third option — apply, or dispute. Do not negotiate scope.

## Loop Break

The gate caps `PATCH_REQUIRED` at `max_patch_rounds` (default 2). When the cap is hit, further bounces auto-convert to `HOLD` with `[REVIEW_LOOP_BREAK]`. Stop and surface to the user.

## Reviewer Scope (informational)

The reviewer prompt forbids plan-amendment churn, packet-hygiene nits, and stylistic preference as grounds for `PATCH_REQUIRED`. A `PATCH_REQUIRED` without concrete `patch_targets` is auto-downgraded to `CONDITIONAL_PASS` by the gate. Code-only review, no plan loops.
