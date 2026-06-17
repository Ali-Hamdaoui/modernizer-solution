# F15 End-to-End First-Slice Test Plan

**Job:** F15-JOB-118
**Area:** Testing
**Status:** Design complete

## Purpose

Define the first demo acceptance from analysis stop through repair gate to planning continue.

## Test scenario

1. Fake Stage 1 analysis completes.
2. Pipeline stops at `analysis_review` gate (manual mode).
3. Assistant explains analysis from gate-bound artifacts.
4. User continues → planning queues.
5. Stage 1 planning completes.
6. Pipeline stops at `planning_review` gate.
7. Assistant explains plan.
8. User continues → approval gate created.
9. User approves → transformation starts.
10. Fake build failure.
11. Failure diagnosis runs → repair_review gate created.
12. Assistant explains failure from gate-bound evidence.
13. User rejects repair or requests revision.
14. Pipeline state is consistent throughout.

## Verification

- [ ] Manual mode stops after analysis.
- [ ] Assistant explains from gate artifacts (not stale previews).
- [ ] Planning queues after continue.
- [ ] Approval gate created after planning acceptance.
- [ ] Repair_review gate created on build failure.
- [ ] Assistant explains failure from gate-bound evidence.
- [ ] Reject repair persists decision without patch apply.
- [ ] No sandbox_path in API calls.

## Suggested test file

`test_v2_f15_first_slice_e2e.py` — focused integration test using fake runner.
