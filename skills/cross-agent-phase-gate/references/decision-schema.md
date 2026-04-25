# Decision Schema

The reviewer returns one of five decisions. The same schema is used whether the reviewer is Codex or Claude:

- `PASS`
- `CONDITIONAL_PASS`
- `PATCH_REQUIRED`
- `HOLD`
- `REDIRECT`

JSON shape:

```json
{
  "decision": "CONDITIONAL_PASS",
  "phase": "1A",
  "summary": "Accepted with one carryforward.",
  "rationale": "The phase is correct, but the next slice must preserve wiring work.",
  "carryforwards": [
    "Wire the subscriber before claiming the feature is live."
  ],
  "next_action": "Start phase 1B with the carryforward active.",
  "may_start_next_phase": true,
  "next_phase_override": null,
  "patch_targets": []
}
```

For `PATCH_REQUIRED`, `patch_targets` MUST be a non-empty array of evidence objects:

```json
{
  "decision": "PATCH_REQUIRED",
  "phase": "1A",
  "summary": "Two concrete defects.",
  "rationale": "See patch_targets for file-level evidence.",
  "carryforwards": [],
  "next_action": "Apply both fixes and resubmit.",
  "may_start_next_phase": false,
  "next_phase_override": null,
  "patch_targets": [
    {
      "file": "src/example.py",
      "line": 42,
      "defect_class": "code_bug",
      "evidence": "f-string interpolates `user_input` directly into raw SQL"
    },
    {
      "file": "tests/test_example.py",
      "line": 17,
      "defect_class": "verification_failure",
      "evidence": "pytest reports `AssertionError: expected 200, got 500`"
    }
  ]
}
```

`defect_class` is restricted to:

- `code_bug` — concrete defect in the diff at a specific file:line that breaks behavior or violates an acceptance criterion.
- `verification_failure` — a verification command failed, was skipped, or was not actually run.
- `falsified_packet` — the packet claims something the diff or file evidence contradicts.

Plan-level concerns, packet hygiene, and stylistic preference are NOT defect classes and MUST NOT be used as grounds for `PATCH_REQUIRED`. The gate auto-downgrades `PATCH_REQUIRED` with empty `patch_targets` to `CONDITIONAL_PASS`.

Rules:

- `carryforwards` must remain active until explicitly cleared by a later decision.
- `PATCH_REQUIRED` always keeps work on the same phase and increments the phase's `patch_round` counter.
- `HOLD` blocks progress.
- `REDIRECT` may change next-phase ordering through `next_phase_override`.

## Loop Break (`REVIEW_LOOP_BREAK`)

The gate caps `PATCH_REQUIRED` rounds at `max_patch_rounds` (default 2; configurable in the repo profile under `review_rules.max_patch_rounds`).

When the cap is reached and the reviewer issues another `PATCH_REQUIRED`, the gate auto-converts the decision to `HOLD` with `[REVIEW_LOOP_BREAK]` prepended to the rationale and the loop-break note appended to `carryforwards`. The builder must stop and surface the situation to the human operator. Resume only after the operator accepts the remaining patch_targets as carryforwards, updates the plan, or explicitly authorizes one more patch round.

A successful `PASS`, `CONDITIONAL_PASS`, or `REDIRECT` resets the phase's `patch_round` counter to zero.
