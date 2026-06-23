# Feature 09 Tasks — Repair Mode Registry

## Task F09-T01 — Define repair modes and safety envelopes

### Goal

Describe what kind of candidate may be authored and its generic limits.

### Scope

- Define all required deterministic, generative, and manual modes.
- Define candidate type, allowed path classes, file/diff limits, dependency/config permissions, review add-ons, executor, and validation policy.
- Version and checksum entries.

### Likely future modified files

- `migration_factory/repair_loop/rule_registry.py` — adapt deterministic rules as mode implementations.
- `migration_factory/control_tower/application/v2_repair_flow.py` — consume selected mode.

### Likely future new files

- `migration_factory/control_tower/domain/v2_repair_mode.py` — mode/envelope contract.
- `migration_factory/control_tower/application/v2_repair_mode_registry.py` — registry.
- `tests/control_tower/test_v2_repair_mode_registry.py` — mode matrix.

### Implementation notes

- Registry governs form and limits, not exact generative patch content.
- Backend selects only allowlisted entries; model cannot enlarge limits.

### Acceptance criteria

- All required modes have explicit compatibility and fail-closed defaults.

### Focused tests

- Unknown, disabled, profile mismatch, envelope checksum.

### Out of scope

- Candidate generation and execution.

### Dependencies

- Feature 08.

## Task F09-T02 — Adapt deterministic rules without constraining generative modes

### Goal

Retain existing fixed-rule value as implementations under the generic registry.

### Scope

- Map existing rule IDs to compatible deterministic modes.
- Seed Jackson/OpenRewrite as one registry entry.
- Add a generative non-Jackson mode with no fixture-specific backend fix.

### Likely future modified files

- `migration_factory/repair_loop/rule_registry.py` — deterministic adapter.
- `migration_factory/control_tower/application/v2_repair_gate_service.py` — persist selected mode/envelope.

### Likely future new files

- `tests/control_tower/test_v2_repair_mode_registry.py` — deterministic/generative parity.
- `tests/control_tower/test_v2_repair_mode_selection.py` — suggested selection tests; needs verification.

### Implementation notes

- No Jackson branch in recovery orchestration.
- Existing rules may perform mode-specific validation; generic validators still run.

### Acceptance criteria

- Adding a generative fixture requires registry data/policy, not a core-engine branch or exact backend repair rule.

### Focused tests

- Jackson recipe selection and non-Jackson LLM patch selection.

### Out of scope

- Model invocation.

### Dependencies

- F09-T01.
