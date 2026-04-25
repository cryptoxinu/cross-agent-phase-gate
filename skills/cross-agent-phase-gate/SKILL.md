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
- `PATCH_REQUIRED`: re-open the same phase, apply the requested patch slice, and resubmit. See **On `PATCH_REQUIRED`** below — there is a strict anti-laziness rule.
- `HOLD`: stop. If the rationale contains `[REVIEW_LOOP_BREAK]`, the patch-round cap was hit and the human operator must adjudicate before resuming.
- `REDIRECT`: follow the redirected next action or phase target.

## On `PATCH_REQUIRED` (anti-laziness rule — read in full)

Every `PATCH_REQUIRED` decision now carries a structured `patch_targets` array. Each entry has `file`, `line`, `defect_class` (one of `code_bug`, `verification_failure`, `falsified_packet`), and `evidence` (a quoted snippet proving the defect).

When you re-enter a phase after a `PATCH_REQUIRED`, the `begin-phase` response includes `prior_decision`. You MUST:

1. **Read every entry in `patch_targets`.** Do not skim. Do not skip. Do not collapse multiple targets into "the gist". Each one is a discrete defect claim.
2. **Decide agree or disagree per target.** Use your own judgement against the cited file, line, and evidence. The reviewer is not always right — but your default stance is to take the claim seriously and verify it against the actual code.
3. **For every target you AGREE with: apply the fix.** All of them. Not "the easy ones now and the rest next round". Not "the most important one and a TODO for the others". If you agree with five targets, the next packet contains five fixes. No half-measures.
4. **For every target you DISAGREE with: dispute it explicitly.** Add the same line item to the next packet's `patch_dispositions[]` field with `target_index`, `disposition: "disputed"`, and a concrete `rebuttal` string. Also reflect the dispute in `known_gaps` so it surfaces if it ends up wrong. Do NOT silently skip. Do NOT pretend the patch was applied. Do NOT mark `disposition: "applied"` when no diff exists for that file:line.
5. **Resubmit only after every agreed-with patch is in the diff.** The reviewer will see your `patch_dispositions` next to the actual diff. A claim of `applied` with no corresponding code change is a `falsified_packet` and earns an immediate re-bounce.

There is no third option. Apply, or dispute. Do not negotiate scope. Do not propose deferring an agreed defect to the next phase. Do not respond by editing the plan to make the defect not-a-defect.

Sample `patch_dispositions` shape for the resubmitted packet:

```json
"patch_dispositions": [
  {
    "target_index": 0,
    "disposition": "applied",
    "note": "Fixed at src/foo.py:42 — switched to parameterized query."
  },
  {
    "target_index": 1,
    "disposition": "disputed",
    "rebuttal": "The cited line is dead code reachable only from a removed branch; verified with grep. Adding to known_gaps for the next reviewer."
  }
]
```

## Loop Break

The gate caps PATCH_REQUIRED at `max_patch_rounds` (default 2; configurable per profile in `review_rules.max_patch_rounds`). When the cap is hit and the reviewer still wants to bounce, the gate auto-converts the decision to `HOLD` with `[REVIEW_LOOP_BREAK]` in the rationale. Stop and surface to the user. Do not attempt to bypass.

## Reviewer Scope (informational)

The reviewer prompt explicitly forbids plan-amendment churn, packet-hygiene nits, and stylistic preference as grounds for `PATCH_REQUIRED`. If the reviewer ever returns `PATCH_REQUIRED` without `patch_targets`, the gate auto-downgrades it to `CONDITIONAL_PASS` and you may continue. This is by design — code-only review, no plan loops.

## Forbidden Behaviors

- Do not self-approve the next phase.
- Do not claim user-visible completion for dark or unreachable work.
- Do not hide unrelated failing checks.
- Do not silently drop carryforwards.
- Do not expand scope without updating the plan and re-running the gate.
- Do not skip an agreed `patch_target`. Apply or dispute — never both, never neither.
- Do not mark a `patch_disposition` as `applied` without a corresponding code diff for that file:line.
