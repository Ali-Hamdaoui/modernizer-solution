# Feature 01 Tasks — Stage 4 Reconciliation

## Task F01-T01 — Reconcile historical Stage 4 behavior

### Goal

Produce a behavior-level port plan against the current F15 implementation.

### Scope

- Compare the four named historical commits with current progression, runner, API, repository, and tests.
- Keep only behavior still compatible with current gates and artifact revisions.
- Verify whether migration `0046` can be adapted or must be replaced by the next append-only migration.

### Likely future modified files

- `migration_factory/control_tower/application/v2_stage_progression.py` — add Stage 4 profile/order rules.
- `migration_factory/control_tower/application/v2_job_service.py` — expose four-stage job state.
- `migration_factory/control_tower/application/v2_orchestrator_runner.py` — persist/resolve Stage 3 output before Stage 4.

### Likely future new files

- `tests/control_tower/test_v2_stage4_progression.py` — Stage 3→4 behavior.
- `tests/control_tower/test_v2_stage4_schema.py` — schema compatibility.

### Implementation notes

- Reuse current F15 progression and artifact revisions.
- Do not cherry-pick blindly or duplicate the runner.
- Backend remains owner of stage order, artifact resolution, paths, and commands.

### Acceptance criteria

- A reviewed map explains every retained or rejected historical change.
- No applied migration is edited.

### Focused tests

- Existing progression/job tests plus new Stage 4 tests.

### Out of scope

- Checkpoint persistence and recovery APIs.

### Dependencies

- None.

## Task F01-T02 — Add governed Stage 4 continuation

### Goal

Extend the existing execution spine so accepted Stage 3 output can launch Stage 4.

### Scope

- Add Stage 4 schemas/contracts and runner wiring.
- Bind continuation to accepted Stage 3 artifacts and F15 gate state.
- Update safe cockpit projection.

### Likely future modified files

- `migration_factory/control_tower/adapters/fastapi/app.py` — Stage 4 endpoint/projection wiring.
- `migration_factory/control_tower/schemas/` — governed Stage 4 schema.
- `web/control-tower/lib/contracts.ts` and `MigrationCockpit.tsx` — safe Stage 4 display.
- `tests/control_tower/test_v2_stage_progression.py` and `test_v2_orchestrator_runner.py` — affected behavior.

### Likely future new files

- `tests/control_tower/test_v2_stage4_progression.py` — direct-jump and artifact-binding cases.
- `tests/control_tower/test_v2_stage4_schema.py` — strict public contract.

### Implementation notes

- Persist output artifact revision before continuation.
- Do not expose sandbox paths or command details as part of the new API.
- Human/F15 gate decisions remain required where policy says so.

### Acceptance criteria

- Direct Stage 4 entry without accepted Stage 3 output fails.
- Successful continuation is backend-derived and checksum-bound.

### Focused tests

- Gate, artifact, profile, and Stage 4 launch tests only.

### Out of scope

- Retry, repair generation, and checkpoint promotion.

### Dependencies

- F01-T01.
