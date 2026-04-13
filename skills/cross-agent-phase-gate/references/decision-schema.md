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
  "next_phase_override": null
}
```

Rules:

- `carryforwards` must remain active until explicitly cleared by a later decision.
- `PATCH_REQUIRED` always keeps work on the same phase.
- `HOLD` blocks progress.
- `REDIRECT` may change next-phase ordering through `next_phase_override`.
