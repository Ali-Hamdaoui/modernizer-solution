# F15 Repair Gate Runbook

**Job:** F15-JOB-112
**Area:** Docs
**Status:** Implemented

## Overview

The repair gate (`repair_review`) is an F15 governed-stage gate that pauses the pipeline when a build, test, or transformation fails. It allows the human operator (via the chatbot or UI) to review failure evidence, a repair proposal, and a reviewer critique before approving, rejecting, or requesting a revision.

## Workflow

```text
Stage N build/test/transform failure
  → Failure diagnosis (V2FailureDiagnosisService)
  → Repair proposal created (V2RepairFlowService)
  → repair_review gate created (V2RepairGateService)
  → Human reviews failure evidence via chatbot/UI
  → Human actions:
       • Approve repair → patch applied in sandbox → validation rerun
       • Reject repair → stage remains failed/blocked
       • Request revision → new repair proposal created
  → Validation result:
       • Pass → stage_completion_review gate
       • Fail (attempts remaining) → new repair_review gate
       • Fail (attempts exhausted) → blocked, manual escalation required
```

## Key services

| Service | Location | Responsibility |
|---------|----------|---------------|
| `V2RepairGateService` | `v2_repair_gate_service.py` | Repair gate creation, validation transitions, attempt limits |
| `V2RepairFlowService` | `v2_repair_flow.py` | Repair proposal creation, approval, patch apply, rollback |
| `V2FailureDiagnosisService` | `v2_failure_diagnosis.py` | Automatic failure diagnosis on build/test/transform failure |
| `V2GateActionService` | `v2_gate_action_service.py` | Gate action execution (continue, reject, revise) |
| `V2PhaseGateService` | `v2_phase_gate_service.py` | Gate lifecycle (create, resolve, supersede) |
| `V2ReviewerService` | `v2_reviewer_service.py` | Reviewer critique management |
| `EvidencePackBuilder` | `v2_evidence_pack_builder.py` | Build failure evidence packs for assistant |

## Security rules

- **No auto-apply repair from LLM output.** The chatbot may explain the failure and proposal, but approval must come through `V2GateActionService` with checksum validation.
- **No frontend/chatbot-supplied paths or commands.** All sandbox paths, argv, env are backend-owned.
- **Approval checksum required.** `approve_repair` validates proposal checksum and context pack checksum before resolving the gate.
- **Reviewer critique gate.** Approval is blocked unless an accepted reviewer critique matches the current proposal checksums.
- **Sandbox-only patch application.** Patches are applied in the sandbox only. Legacy source is never mutated.
- **Rollback evidence preserved.** If validation fails after patch apply, the sandbox is rolled back and all evidence (ledger, patch results, validation output) is preserved.

## Attempt limits

The `V2RepairGateService` tracks repair attempts per `(job_id, stage_index)`:

- Default: **3 attempts** per stage.
- Configurable via `max_repair_attempts` constructor parameter.
- Passing validation **resets** the counter.
- When attempts are exhausted, no new repair gate is created and the pipeline must be manually unblocked.

## Gate phases

Repair gates support these decisions:

| Decision | Effect |
|----------|--------|
| `CONTINUE` (via `approve_repair`) | Approves the repair, resolves the gate, queues patch application |
| `REJECT` | Rejects the repair, resolves the gate with rejection reason, stage remains failed |
| `REVISE` (via `request_repair_revision`) | Supersedes the current gate, creates a new open repair gate for revised proposal |
| `REANALYZE` | Re-runs failure diagnosis |

## Tests

| File | What it covers |
|------|---------------|
| `test_v2_repair_review_gate.py` | `approve_repair` action lifecycle (job029) |
| `test_v2_repair_gate_service.py` | Gate creation, reject, revise, validation transitions, attempt limits (jobs 101-108) |
| `test_v2_repair_flow.py` | `V2RepairFlowService` proposal/patch lifecycle |
| `test_v2_failure_diagnosis.py` | `V2FailureDiagnosisService` diagnosis flow |
| `test_v2_gate_action_service.py` | Gate action execution and validation |
| `test_v2_phase_gates.py` | Phase gate model, valid decisions (incl. repair_review) |
| `test_v2_gate_assistant.py` | Assistant Q&A for all gate phases including failure/repair |

## Repair patch preview redaction

The `redact_patch_preview()` function in `redaction.py` provides safe patch preview:

1. **Path redaction**: Sandbox paths, user home, tmp paths are redacted.
2. **Secret redaction**: Passwords, tokens, API keys, secrets are replaced with `[redacted]`.
3. **Size bounding**: Patches are truncated at 10,000 chars by default with an omission marker.

## Repair assistant Q&A

The `GateExplanationBuilder.build_failure_explanation()` method (in `v2_gate_assistant.py`) uses `EvidencePackBuilder.build_failure_pack()` to explain:

- Root cause hypothesis (from failure diagnosis)
- Repair proposal summary
- Patch risk assessment
- Reviewer critique (if available)
- Available actions (approve, reject, revise)

The chatbot may answer repair questions flexibly, but may never execute commands, approve, or write files. All state-changing actions go through `V2GateActionService`.
