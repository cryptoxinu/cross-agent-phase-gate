# HealthBot Setup

Use the built-in `healthbot` profile for a HealthBot-style repository.

That profile defaults to:

- plan roots: `docs/plans`, `.claude/plans`
- verification: `ruff check src/ tests/`, `pytest tests/ -q`
- review rules:
  - builder must stop after each phase
  - unrelated gate failures must be reported honestly
  - dark work must not be described as live
  - medical/privacy guardrails stay active

Initialize from HealthBot root in a Claude session:

```bash
<repo>/bin/claude-phase-gate init-run \
  --repo /path/to/HealthBot \
  --plan /path/to/HealthBot/docs/plans/2026-04-12-outbound-gateway-phase-1.md \
  --repo-profile healthbot \
  --json
```

Initialize from HealthBot root in a Codex session:

```bash
<repo>/bin/codex-phase-gate init-run \
  --repo /path/to/HealthBot \
  --plan /path/to/HealthBot/docs/plans/2026-04-12-outbound-gateway-phase-1.md \
  --repo-profile healthbot \
  --json
```
