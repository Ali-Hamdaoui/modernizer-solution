# Governed Repair Workflow

## Overview

Governed repair workflow is backend-owned repair pipeline for failed V2 migration jobs.

Flow:

1. Deterministic diagnosis reads bounded backend artifacts and persists diagnosis with checksums.
2. Model A creates structured `RepairProposal` from persisted diagnosis.
3. Model B creates structured `ReviewerCritique`.
4. Human approval is required and checksum-bound.
5. Backend materializes persisted approved proposal into patch candidate.
6. Patch gate preview evaluates candidate before apply.
7. Backend apply uses persisted patch candidate only.
8. Validation runs in sandbox.
9. Rollback runs automatically on validation failure.
10. Read-only status projection summarizes current state for Control Tower.

## State Machine

### Diagnosis

- Source: deterministic evidence + classifier
- Output: persisted diagnosis record
- Key bindings:
  - `diagnosis_checksum`
  - `evidence_pack_checksum`
  - `context_pack_checksum`

### Proposal

- Source: persisted diagnosis
- Output: draft `RepairProposal`
- Produced by Model A through strict schema validation

### Reviewer Critique

- Source: persisted proposal + diagnosis context
- Output: `ReviewerCritique`
- Reviewer `accept` is not human approval

### Human Approval

- Source: reviewed proposal
- Output: approval decision record
- Approval is checksum-bound and fail-closed on stale bindings

### Patch Candidate

- Source: approved proposal
- Output: persisted patch candidate with unified diff and gate metadata
- Frontend cannot submit raw diff content

### Patch Gate Preview

- Source: persisted patch candidate
- Output: `gate_allowed`, blocked, or unsupported status
- Gate preview must pass before apply

### Apply

- Source: persisted `gate_allowed` patch candidate
- Backend re-runs patch gate immediately before apply
- Apply uses exact persisted unified diff only

### Validation

- Backend-owned sandbox validation runs after apply
- No frontend-supplied commands are executed

### Rollback

- Trigger: validation failure after apply
- Backend restores sandbox automatically

### Status Projection

- Source: persisted diagnosis, proposal, review, approval, patch candidate, apply metadata
- Output: read-only workflow summary + inferred `next_action`

## Key Endpoints

- `POST /v1/v2/jobs/{job_id}/assistant/ask`
  - deterministic failure answer path for failure questions
- `GET /v1/v2/jobs/{job_id}/diagnosis/latest`
  - latest persisted diagnosis summary
- `POST /v1/v2/diagnoses/{diagnosis_id}/repair-proposal`
  - create diagnosis-bound repair proposal
- `POST /v1/v2/repair-proposals/{proposal_id}/review`
  - create reviewer critique
- `POST /v1/v2/repair-proposals/{proposal_id}/approval`
  - record human approval or rejection
- `POST /v1/v2/repair-proposals/{proposal_id}/patch-candidate`
  - create persisted patch candidate
- `POST /v1/v2/patch-candidates/{patch_candidate_id}/apply`
  - apply persisted candidate in sandbox, validate, rollback on failure
- `GET /v1/v2/jobs/{job_id}/governed-repair/status`
  - read-only governed workflow projection

## Safety Invariants

- No legacy source mutation
- Frontend cannot submit raw patch/diff content
- Reviewer `accept` is not human approval
- Approval is checksum-bound
- Apply uses persisted patch candidate only
- Patch gate re-runs before apply
- Rollback runs on validation failure
- No arbitrary frontend commands

## Focused Test Suites

- `python -m pytest tests/control_tower/test_v2_governed_repair_e2e.py -q`
- `python -m pytest tests/control_tower/test_v2_governed_repair_status.py -q`
- `python -m pytest tests/control_tower/test_v2_patch_candidate_apply_service.py -q`
- `python -m pytest tests/control_tower/test_v2_patch_candidate_service.py -q`
- `python -m pytest tests/control_tower/test_v2_repair_proposal_approval.py -q`
- `python -m pytest tests/control_tower/test_v2_diagnosis_proposal_flow.py -q`
- `python -m pytest tests/control_tower/test_v2_failure_diagnosis_persistence.py -q`
- `python -m pytest tests/control_tower/test_v2_assistant_failure_answers.py -q`
- `python -m pytest tests/control_tower/test_v2_f07_f05.py -q`
- `python -m pytest tests/control_tower/test_v2_assistant_adversarial.py -q`
