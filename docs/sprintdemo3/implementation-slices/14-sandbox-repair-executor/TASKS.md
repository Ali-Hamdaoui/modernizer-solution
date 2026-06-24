# Feature 14 Tasks — Sandbox Repair Executor

## Task F14-T01 — Resolve and revalidate backend-owned execution

### Goal

Create an executor entry point that accepts only governed IDs.

### Scope

- Resolve attempt, checkpoint, candidate, review, approval, mode, and sandbox internally.
- Re-run policy/baseline checks immediately before apply.
- Select backend-known adapter without model/client commands.

### Likely future modified files

- `migration_factory/control_tower/application/v2_repair_flow.py` — call executor after approval.
- `migration_factory/repair_loop/patch_apply.py` — expose safe adapter primitives.

### Likely future new files

- `migration_factory/control_tower/application/v2_sandbox_repair_executor.py` — governed coordinator.
- `tests/control_tower/test_v2_sandbox_repair_executor.py` — resolution and authority tests.

### Implementation notes

- Reuse current patch application; do not create a second repair loop.
- Backend owns all paths, argv, env, and commands.

### Acceptance criteria

- Executor cannot be invoked with caller-supplied filesystem or command data.

### Focused tests

- Missing/stale bindings, wrong sandbox, forbidden input fields.

### Out of scope

- Validation policy.

### Dependencies

- Features 02 and 13, plus F12-T03.

## Task F14-T02 — Record proposed and actual sandbox changes

### Goal

Prove what the model proposed and what the sandbox contains after apply.

### Scope

- Persist exact proposed bytes/checksum.
- Snapshot baseline, apply, compute actual diff/touched paths/hashes.
- Verify original source remains unchanged and rollback data exists.

### Likely future modified files

- `migration_factory/repair_loop/patch_apply.py` — actual diff and hash capture.
- `migration_factory/repair_loop/validation_runner.py` — consume execution artifact refs.

### Likely future new files

- `tests/control_tower/test_v2_sandbox_repair_executor.py` — exact-byte and source-integrity tests.
- `tests/fixtures/demo3/` — proposed/actual diff fixtures.

### Implementation notes

- Proposed model diff and actual sandbox diff are distinct artifacts.
- Unexpected actual paths fail before validation.

### Acceptance criteria

- Audit can compare approved candidate bytes to applied result and prove original source unchanged.

### Focused tests

- Created/deleted files, apply failure, actual path drift, rollback snapshot.

### Out of scope

- Success determination.

### Dependencies

- F14-T01.
