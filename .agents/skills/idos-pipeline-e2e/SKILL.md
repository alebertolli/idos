---
name: idos-pipeline-e2e
description: Plan and verify IDOS investment research workflows end to end, including safe branch-scoped GitHub Actions runs, public dashboard checks, and private portfolio boundaries. Use for pipeline releases or strategy rollout validation.
---

# IDOS pipeline E2E validation

Use this workflow when validating an IDOS discovery, research, risk, decision, portfolio, or dashboard pipeline. Reuse the domain checks in other investment systems only after mapping their data contracts and deployment boundaries.

## Establish scope and boundaries

- Read the project `AGENTS.md`, relevant SDD, workflow definitions, strategy configuration, and recent test plan before changing code or dispatching Actions.
- Inspect the current branch, worktree status, workflow enabled state, write targets, and deployment triggers. Preserve existing local edits and unrelated temporary files.
- Use a non-production branch for E2E writes. Never let test dispatches commit to `main`; pause production event paths for the test window and restore workflow state after the run.
- Keep live holdings, transactions, account identifiers, and portfolio snapshots out of public dashboard artifacts. Public opportunity flow may extend through Buy List only when explicitly in scope.
- Do not enable a strategy, promote a buy decision, or simulate real capital as a side effect of testing. Keep strategy enablement and universe membership governed by SDD.

## Validate the workflow

1. Map each stage to its workflow, input, persistent outputs, and downstream trigger. Identify automatic `workflow_run`, dispatch, schedule, and Pages publication behavior.
2. Run focused tests for changed boundaries, including data provenance, idempotency, strategy isolation, human approval gates, and public/private serialization where applicable.
3. Execute remote Actions in dependency order on the test branch. Use the least expansive inputs; do not set force/reprocess or portfolio simulation without an explicit test requirement.
4. Inspect job logs, artifacts, generated journal records, and commit destination. Treat a green job with warnings, red log fragments, empty output, or hidden errors as an anomaly until reconciled with structured results.
5. Before Pages deployment, build and inspect the public payload. Assert private position, ledger, and portfolio fields are empty; inspect what Buy List and opportunity reports expose.
6. Verify the deployed page itself, including decision state, thesis, evidence, risks, timestamps, data quality, provenance, and missing/stale indicators. A successful build alone is not deployment verification.
7. Restore the workflows' original enabled/disabled state. Record run IDs, commit SHAs, findings, failed or skipped stages, and remaining manager review in SDD and the test plan.

## Completion criteria

Report each stage as passed, failed, skipped, or blocked by a concrete prerequisite. Do not call an E2E complete if the remote page was not checked, if there are unexplained errors, or if expected outputs were not produced. Separate technical validation from the manager's final investment judgment and from any portfolio-connected assessment.
