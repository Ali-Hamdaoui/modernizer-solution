# Feature 15 Tasks — Validation Runner

## Task F15-T01 — Define versioned validation policies

### Goal

Select deterministic checks from profile, stage, mode, and candidate type.

### Scope

- Define required operations, order, timeout, success criteria, artifacts, and rollback rule.
- Map deterministic and generative modes without caller/model commands.
- Define unsupported-policy failure.

### Likely future modified files

- `migration_factory/repair_loop/validation_runner.py` — consume policy operations.
- `migration_factory/control_tower/application/v2_orchestrator_runner.py` — backend operation launch.

### Likely future new files

- `migration_factory/control_tower/application/v2_validation_policy.py` — policy registry/selection.
- `tests/control_tower/test_v2_validation_policy.py` — selection and fail-closed cases.

### Implementation notes

- Reuse typed backend launchers and existing validation.
- Backend constructs argv/env.

### Acceptance criteria

- Every executable mode resolves an explicit versioned validation policy.

### Focused tests

- Mode/profile mapping, unknown policy, timeout settings.

### Out of scope

- Full repository test suite.

### Dependencies

- Features 09 and 14.

## Task F15-T02 — Persist proof and rollback on failure

### Goal

Make validation outcome the only promotion signal.

### Scope

- Run configured checks against repaired sandbox.
- Persist logs/reports/status/checksums in bounded artifacts.
- Trigger existing rollback on failure and record result.

### Likely future modified files

- `migration_factory/repair_loop/validation_runner.py` — structured proof result.
- `migration_factory/control_tower/application/v2_repair_flow.py` — pass/fail transition.
- `migration_factory/control_tower/application/v2_orchestrator_runner.py` — operation result integration.

### Likely future new files

- `tests/control_tower/test_v2_validation_policy.py` — proof/rollback tests.
- `tests/control_tower/test_v2_validation_runner_demo3.py` — suggested integration test; needs verification.

### Implementation notes

- Reuse rollback and repair ledger.
- A model statement cannot alter result.

### Acceptance criteria

- Failed validation leaves no accepted checkpoint and records rollback; pass exposes immutable proof refs.

### Focused tests

- Build fail, test fail, success, timeout, rollback failure.

### Out of scope

- Checkpoint creation.

### Dependencies

- F15-T01.
