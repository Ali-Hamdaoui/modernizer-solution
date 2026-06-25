# Feature 13 Tasks — Human Approval Gate

## Task F13-T01 — Bind approval to exact reviewed revision

### Goal

Record a human decision that cannot drift across candidate revisions.

### Scope

- Resolve exact candidate and accepted critique.
- Bind actor, decision, checksums, feedback, timestamp, and idempotency.
- Reject stale, missing, same-model-failed, or policy-invalid review state.

### Likely future modified files

- `migration_factory/control_tower/application/v2_gate_action_service.py` — exact revision approval validation.
- `migration_factory/control_tower/application/v2_repair_gate_service.py` — DEMO3 gate adapter.

### Likely future new files

- `migration_factory/control_tower/application/v2_repair_approval_service.py` — approval coordinator.
- `tests/control_tower/test_v2_human_repair_approval.py` — authority/checksum tests.

### Implementation notes

- Reuse F15 immutable decisions and stale-checksum protection.
- Human decides; reviewer only critiques; backend validates.

### Acceptance criteria

- Any candidate revision invalidates prior approval for execution.

### Focused tests

- Approve/reject/revise, stale checksum, wrong actor, duplicate/conflict.

### Out of scope

- Apply and validation.

### Dependencies

- Features 10–11 and F12-T01/F12-T02.

## Task F13-T02 — Expose safe approval actions

### Goal

Let the cockpit submit typed human decisions without execution details.

### Scope

- Add strict request/response mapping.
- Return IDs, statuses, checksums, and safe reasons.
- Keep sandbox/path/argv/env/commands absent.

### Likely future modified files

- `migration_factory/control_tower/adapters/fastapi/app.py` — approval endpoints.
- `web/control-tower/lib/controlTowerApi.ts` — typed action call.
- `web/control-tower/lib/contracts.ts` — safe DTOs.

### Likely future new files

- `tests/control_tower/test_v2_human_repair_approval.py` — API cases.
- `web/control-tower/tests/recoveryApiSecurity.test.ts` — request/redaction checks.

### Implementation notes

- Chatbot may draft the action; only authenticated human submission executes it.

### Acceptance criteria

- Public contract is strict, idempotent, checksum-bound, and redacted.

### Focused tests

- Extra fields, actor mapping, response leakage.

### Out of scope

- Cockpit visual design.

### Dependencies

- F13-T01 and Feature 02.
