# F15 Final Merge-Gate Checklist

**Job:** F15-JOB-122
**Area:** Testing/Governance
**Status:** Design complete

## Purpose

Define when F15 can be called done.

## Backend verification

- [ ] All 49 existing phase gate + repair review tests pass.
- [ ] All 28 new repair gate service tests pass.
- [ ] All 66 gate action service tests pass.
- [ ] All 7 repair flow tests pass.
- [ ] All 10 failure diagnosis tests pass.
- [ ] All assistant tests pass (context loader, intent classifier, explanation builders, including failure explanation).
- [ ] `git diff --check` passes with no whitespace errors.

## Security verification

- [ ] No F15 API accepts `sandbox_path`, `argv`, `env`, or raw filesystem targets.
- [ ] Gate action service validates checksum before resolving.
- [ ] `approve_repair` requires reviewer critique gate (F07).
- [ ] Non-human actors cannot perform authoritative actions (approve, reject).
- [ ] Patch preview redacts secrets and absolute paths.
- [ ] Prompt injection sanitizer flags suspicious artifact content.

## Old behavior verification

- [ ] Old auto stage progression endpoint still works (unchanged).
- [ ] F15 manual mode is opt-in (stage continuation policy `AUTO_ON_GREEN` unaffected).
- [ ] Existing V2RepairFlowService still works without gate integration.
- [ ] Existing `test_v2_repair_flow.py` tests pass unchanged.
- [ ] Existing `test_v2_failure_diagnosis.py` tests pass unchanged.

## Live demo proof

- [ ] Fake Stage 1 analysis → completes → analysis_review gate.
- [ ] Assistant explains analysis from gate-bound artifacts.
- [ ] User continues → planning queues.
- [ ] Fake Stage 1 planning → completes → planning_review gate.
- [ ] User continues → approval_review gate created.
- [ ] User approves → transformation runs.
- [ ] Fake build failure → repair_review gate created.
- [ ] Assistant explains failure from gate-bound evidence.
- [ ] User rejects repair → rejection persisted, no patch applied.
- [ ] Or: User approves repair → patch applied in sandbox → validation rerun.

## No duplicate services

- [ ] No duplicate orchestrator runner.
- [ ] No duplicate repair engine.
- [ ] No duplicate plan revision system.
- [ ] No duplicate assistant router.
- [ ] No duplicate artifact resolver.
- [ ] No duplicate repository.
- [ ] No duplicate validation/rollback/ledger.
- [ ] V2RepairGateService composes existing services (does not reimplement them).

## Documentation

- [ ] `docs/F15/repair-gate-runbook.md` documents the repair gate workflow.
- [ ] `docs/F15/f15-developer-index.md` lists all jobs and file locations.
- [ ] `docs/F15/gate-api-endpoints.md` documents API contracts.
- [ ] `docs/F15/e2e-test-plan.md` defines demo acceptance.
- [ ] `docs/F15/security-regression-suite.md` defines security tests.
- [ ] `docs/F15/concurrency-idempotency-suite.md` defines concurrency tests.
- [ ] `docs/F15/repair-ui-card.md` defines frontend UI card design.
