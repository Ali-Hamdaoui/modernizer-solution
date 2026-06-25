# Feature 12 Tasks — Backend Policy Validator

## Task F12-T01 — Compose pre-approval lineage and review validation

### Goal

Reject candidates whose immutable governance bindings are incomplete or stale.

### Scope

- Validate attempt/checkpoint/evidence/classification/retrieval/mode bindings.
- Validate candidate baseline checksums and exact accepted review.
- Return a persisted pre-approval policy result that Feature 13 can bind to.

### Likely future modified files

- `migration_factory/control_tower/application/v2_repair_gate_service.py` — expose exact review/approval state.
- `migration_factory/control_tower/application/v2_repair_flow.py` — call composed validator before execution.

### Likely future new files

- `migration_factory/control_tower/application/v2_backend_policy_validator.py` — composed result.
- `tests/control_tower/test_v2_backend_policy_validator.py` — stale/unreviewed/unapproved matrix.

### Implementation notes

- Generic validation does not decide whether the proposed fix is semantically correct.
- Backend owns the decision; model output cannot waive checks.

### Acceptance criteria

- Any missing/stale binding yields a persisted fail-closed result before approval.

### Focused tests

- Stale checkpoint/file/candidate, wrong attempt, missing review/approval.

### Out of scope

- Filesystem apply.

### Dependencies

- Features 09–11.

## Task F12-T02 — Validate patch, dependency, and configuration safety

### Goal

Apply the selected envelope to exact candidate content.

### Scope

- Enforce traversal, symlink, forbidden path, legacy source, file count, diff size, and touched-path rules.
- Add generic dependency and config policy checks.
- Re-check actual touched paths at apply boundary.

### Likely future modified files

- `migration_factory/repair_loop/patch_gate.py` — parameterize/enhance generic limits.
- `migration_factory/repair_loop/patch_apply.py` — pre-apply revalidation hook.
- `migration_factory/control_tower/application/pom_dependency_policy.py` — reuse dependency checks; exact integration needs verification.

### Likely future new files

- `migration_factory/control_tower/application/v2_patch_validator.py` — candidate-level patch validation.
- `migration_factory/control_tower/application/v2_dependency_policy_validator.py` — dependency envelope.
- `migration_factory/control_tower/application/v2_config_policy_validator.py` — config envelope.
- `tests/control_tower/test_v2_patch_validator.py` — path/limit cases.

### Implementation notes

- Reuse current path and symlink protections.
- Do not add fixture-specific exact repair logic.

### Acceptance criteria

- Unsafe or out-of-envelope candidates cannot reach executor.

### Focused tests

- Traversal, symlink, forbidden files, count/size, disallowed dependency/config.

### Out of scope

- Compile/test validation.

### Dependencies

- F12-T01.

## Task F12-T03 — Revalidate policy immediately before execution

### Goal

Prevent an approved candidate from executing after any relevant state has changed.

### Scope

- Re-run lineage, baseline, review, envelope, path, dependency, and configuration checks.
- Require exact human approval and pre-approval policy-result checksum.
- Persist the pre-execution result used by the executor.

### Likely future modified files

- `migration_factory/control_tower/application/v2_repair_flow.py` — invoke revalidation after approval.
- `migration_factory/control_tower/application/v2_repair_gate_service.py` — resolve exact approval decision.

### Likely future new files

- `tests/control_tower/test_v2_backend_policy_revalidation.py` — approval/stale-state matrix.
- `migration_factory/control_tower/application/v2_backend_policy_validator.py` — add pre-execution mode.

### Implementation notes

- This is the point that rejects unapproved candidates.
- Reuse the same generic validator and policy versions; do not create separate repair knowledge.

### Acceptance criteria

- Any post-approval change to candidate, files, checkpoint, review, policy, or approval blocks execution.

### Focused tests

- Missing approval, stale baseline, revised candidate, changed policy, duplicate execution.

### Out of scope

- Applying the candidate.

### Dependencies

- F12-T01, F12-T02, and Feature 13.
