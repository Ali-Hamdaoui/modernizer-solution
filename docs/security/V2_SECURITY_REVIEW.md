# V2 Security Review — AI Migration Control Tower

**Agent:** A15 Security Review Agent  
**Date:** 2026-06-13  
**Branch inspected:** `V2IMPROVMENT` (all A1-A14 merged)  

## Scope

Review all V2 changes for trust boundaries, redaction, approval, worker, model, and frontend secret exposure.

## Findings

### 1. Frontend Secret Exposure: CLEAN

- No `NEXT_PUBLIC_*` Azure/OpenAI secrets found.
- Azure env refs use backend-only pattern; frontend receives only env ref NAMEs.

### 2. Backend Secret Redaction: CLEAN

- `/v1/settings/ai` returns env ref projections only (never endpoint URLs, API keys, deployment IDs).
- `redaction.py` includes comprehensive redaction: absolute paths, env assignments, secret keys, deployment IDs, raw prompts.
- `v2_settings.py` uses env ref projection pattern: var NAMEs only.

### 3. Worker Manifest Security: CLEAN

- `v2_worker_stage.py` builds argv from setup data only. No browser-supplied argv/env.
- All paths come from setup, not from request payload.
- Stage 1 uses fixed profile and mode.

### 4. Approval Checksum Gating: CLEAN

- `v2_approval_mapping.py` requires exact checksum match for approve/reject.
- Stale checksum rejected. Duplicate approve/reject rejected.
- LLM cannot approve — only exact checksum match works.

### 5. Assistant Authority: CLEAN

- `v2_assistant_service.py` has FORBIDDEN_CAPABILITIES list:
  - `execute_command`, `approve_decision`, `write_file`
  - `change_route`, `change_stage`, `override_proof`
- Assistant can only draft pending actions (status: "draft"), never execute.

### 6. Repair Flow Security: CLEAN

- Proposals require approval before patch application.
- Patch application bounded to sandbox (target_path in sandbox).
- Cannot approve or apply twice.

### 7. Append-Only Tables: CLEAN

- All V2 migrations include no-update and no-delete triggers:
  - `v2_migration_setups`
  - `v2_preflight_results`
  - `v2_model_health_checks`

### 8. Pipeline Route Authority: CLEAN

- Pipeline is hardcoded: `springboot-216-to-356-java21-three-stage`
- Stage inputs are fixed by code: Stage 1 = legacy, Stage 2 = Stage 1 sandbox, Stage 3 = Stage 2 sandbox.
- No Boot 4 path. No user-selected stage inputs.
- Browser cannot choose commands, Maven goals, working dirs, model deployments, or Stage 2/3 inputs.

### 9. Azure Health Non-Blocking: CLEAN

- Azure BLOCKED/DEGRADED does not prevent deterministic migration start.
- Health checks are stored with redacted error classifications.
- No secrets, prompts, or raw responses persist in health records.

### 10. Frontend Controls: CLEAN

- `/migrations/new` form has no Azure secret fields.
- No Maven goals, deployment IDs, or model name fields.
- Start button gated on deterministic readiness (Azure not required).
- Cockpit (`/migrations/[jobId]`) has no stage-start or execution buttons.

## Residual Risks

1. **SQLite single-instance**: Designed for local operator mode only. No multi-user access control.
2. **Path validation**: Preflight checks path existence but does not enforce strict containment beyond self-check. Production deployments should add stricter path validation.
3. **No authentication**: API is local-only (127.0.0.1 binding). No user auth layer.

## Verdict

**CLEAN** — No high or critical security findings. All V2 non-negotiable security rules are enforced.
