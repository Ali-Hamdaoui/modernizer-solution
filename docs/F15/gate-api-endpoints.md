# F15 Gate API Endpoints

**Job:** F15-JOB-113
**Area:** API
**Status:** Design complete

## Overview

Expose gate list, detail, and action endpoints. All endpoints require valid authentication. No endpoint accepts `sandbox_path`, `argv`, `env`, or raw filesystem targets from the frontend/chatbot.

## Endpoints

### GET /v1/v2/gates/{gate_id}

Returns gate detail with evidence pack.

**Response:**
```json
{
  "gate": {
    "gate_id": "abc123...",
    "job_id": "job-xyz",
    "gate_phase": "repair_review",
    "stage_index": 1,
    "gate_status": "open",
    "gate_decision": "pending",
    "source_artifact_checksum": "sha256:...",
    "source_artifact_refs": ["build:log-1"],
    "created_at": "2026-06-17T12:00:00Z",
    "resolved_at": null,
    "resolved_by": null,
    "checksum": "sha256:...",
    "available_actions": [...]
  },
  "evidence": {
    "failure_summary": "...",
    "root_cause_hypothesis": "...",
    "patch_summary": "...",
    "affected_paths": [...],
    "reviewer_critique": null,
    "remaining_attempts": 3,
    "max_attempts": 3
  },
  "checksum": "sha256:..."
}
```

### GET /v1/v2/jobs/{job_id}/gates/open

Returns the current open gate for a job, if any.

**Response:**
```json
{
  "gate": { ... } | null
}
```

### POST /v1/v2/gates/{gate_id}/action

Execute a gate action. The action body **must not** contain `sandbox_path`, `argv`, or `env`.

**Request:**
```json
{
  "action": "approve_repair",
  "expected_gate_checksum": "sha256:...",
  "idempotency_key": "unique-key",
  "decided_by": "user-1",
  "proposal_id": "prop-1",
  "proposal_checksum": "sha256:...",
  "context_pack_checksum": "sha256:..."
}
```

**Response:**
```json
{
  "result": {
    "decision_id": "dec-1",
    "gate_id": "gate-1",
    "status": "executed",
    "result_gate_id": null,
    "result_command_id": null,
    "result_revision_id": "prop-1",
    "reason": ""
  }
}
```

## Security

- `sandbox_path`, `argv`, `env` fields are rejected by schema validation.
- Gate checksums must match expected values (stale checksum → rejection).
- Human-only actions (approve, reject) require `actor_type: "human"`.

## Schema validation

See `GateActionRequest` in `contracts.ts` for the full request shape.
