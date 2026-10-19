---
name: investment-platform-e2e
description: Plan and verify bounded end-to-end investment-platform workflows across discovery, research, decisions, dashboards, and portfolio boundaries. Use when changing or validating a multi-strategy investment pipeline; not for standalone market research or trading advice.
---

# Investment platform E2E

Use this skill to turn a pipeline change into reviewable, bounded validation and report what the evidence proves. Adapt names and controls to the repository; do not assume every project uses GitHub Actions, a public dashboard, or the same stages.

## Establish the contract

1. Read repository instructions, relevant SDD/requirements, workflow definitions, and current tests before changing code.
2. Map the path from eligible instrument to persisted result and user-visible output. Record which strategy/profile owns each rule.
3. Separate the eligible-instrument registry from data providers and market screeners. For IDOS, `idos-config/universe/operable.yml` is the broker-operability registry; do not replace it with an exchange or CEDEAR catalogue. A strategy may intersect it with its configured universe and supported asset types before fetching data.
4. Keep strategy rules behind profile/factory boundaries. Share infrastructure and contracts, not investment criteria. Preserve the default strategy and keep incomplete strategies disabled.
5. List decisions that affect investment meaning, such as benchmark, score normalization, freshness, and missing-data policy. Do not silently invent these rules. Continue independent work and surface unresolved decisions with evidence.

## Protect data and execution scope

- Determine the exact branch/ref, workflow triggers, write targets, external dispatches, API calls, and public/private outputs before a remote run.
- Use an isolated test branch and the smallest useful candidate set. Validate every manual ticker against the operable registry and respect repository limits.
- Keep portfolio simulation, order execution, production dispatches, and publication disabled unless the user explicitly authorized those effects.
- Treat public dashboard artifacts as public. Check generated JSON and pages for secrets, account identifiers, positions, balances, and private portfolio details before publishing.
- Estimate provider calls, latency, and Actions usage. Prefer one focused remote run after local checks; do not repeat a wide run just to obtain a green check.

## Validate the pipeline

1. Run narrow unit and integration tests for changed contracts, followed by relevant regression tests.
2. Run one bounded remote workflow on the authorized test ref when workflow behavior or persistence changed. Verify the run's input ref and commit before interpreting its status.
3. Inspect logs and persisted artifacts, not just the green status. Check candidate, fetched, rejected, skipped, and created counts; source fallback; per-field provenance; data-quality gates; and expected state transitions.
4. Distinguish a successful no-op from a completed business E2E. A run that creates no valid opportunity cannot prove Research, Assessment, Buy List, dashboard thesis quality, or portfolio integration.
5. For investment metrics, retain source, as-of date, period, currency/unit, freshness, and field-level provenance. Missing or conflicting critical evidence must fail closed; a global source count does not prove coverage for each metric.
6. Verify dashboard content in its rendered form and confirm the public/private boundary. A generated file alone does not prove the user-facing view is correct.

## Record and hand off

- Update relevant SDD/README files with decisions, impact, migration/rollback, exact test evidence, run links, and unresolved gates.
- Commit and push only to the authorized branch; verify local and remote refs afterward. Never merge or deploy to production without explicit authorization.
- State what was proven, what was not, and what the investment manager still needs to validate. Do not describe a screen result as a buy/sell recommendation unless the specified decision gates and human review are complete.

## IDOS project references

In IDOS, use `SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md` for current E2E evidence and outstanding gates, plus the applicable strategy SDD for profile-specific rules. These files are project state and can change; re-read them instead of treating this skill as the current run ledger.
