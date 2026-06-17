# Analysis Gate Runbook — F15-JOB-085

## Overview

The analysis_review gate pauses the workflow after Stage N analysis completes in F15 manual mode. The user must review the analysis output and either accept it (proceeding to planning) or request reanalysis.

## Behavior by Policy

### Old Policy (AUTO_ON_GREEN)
- No analysis_review gate is created
- Planning starts automatically after analysis completes
- No user intervention required

### New Policy (MANUAL / MANUAL_ON_WARNING_OR_FAILURE)
- After analysis completes, an `analysis_review` gate is created
- The gate is in `OPEN` status with `source_artifact_checksum` and `source_artifact_refs`
- Planning is blocked until the gate is resolved

## Available Actions

| Action | Effect |
|--------|--------|
| `continue` (accept_analysis) | Resolves the gate, marks analysis as accepted, queues planning |
| `reanalyze` (request_reanalysis) | Creates draft ArtifactRevision with user feedback, opens new analysis_review gate |

## Artifact Resolution

Gate explanations use `V2GateArtifactResolver` to read gate-bound artifact refs/checksums, not stale previews. Artifacts are redacted and bounded for assistant/UI consumption.

### Evidence Pack Builders
- `EvidencePackBuilder.build_analysis_pack()` — reads analysis_report, dependency_graph, test_inventory, read_only_verification

## Common Failures

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Gate not created | Auto policy active | Check `stage_continuation_policy` in run configuration |
| Analysis artifacts not visible | Gate has no artifact refs | Verify orchestrator produced `artifact_refs` in result JSON |
| "stale_checksum" error | Gate state changed since load | Refresh gate view and retry |
| "no_accepted_analysis" | Draft analysis exists but none accepted | Accept the analysis or request reanalysis |
| Duplicate continue | Already resolved | Returns idempotent result |

## Tests to Run

```bash
# Analysis gate creation
python -m pytest tests/control_tower/test_v2_analysis_review_gate.py -v

# Gate action service (continue_from_gate)
python -m pytest tests/control_tower/test_v2_gate_action_service.py -v

# Reanalysis
python -m pytest tests/control_tower/test_v2_reanalysis_request.py -v

# Planning blocked without accepted analysis
python -m pytest tests/control_tower/test_v2_planning_requires_accepted_analysis.py -v

# End-to-end first slice
python -m pytest tests/control_tower/test_v2_f15_first_slice_e2e.py -v

# Evidence packs
python -m pytest tests/control_tower/test_v2_evidence_packs.py -v

# Artifact resolution
python -m pytest tests/control_tower/test_v2_gate_artifact_resolution.py -v

# Assistant explanation
python -m pytest tests/control_tower/test_v2_gate_assistant.py -v
```

## Sequence

```
Stage 1 (Analysis) completes
  └─ Orchestrator runner
       ├─ AUTO_ON_GREEN  → queues Stage 2 directly
       └─ MANUAL/MANUAL_ON_WARNING_OR_FAILURE
            ├─ Creates analysis_review gate
            └─ Waits for user decision
                 ├─ continue_from_gate() → accept_analysis → queues Stage 2
                 └─ request_reanalysis() → creates draft revision + new gate
```

## No Direct Code Duplication

This runbook describes existing behavior. If you need to modify gate creation logic, edit:
- `v2_orchestrator_runner.py` → `_auto_queue_next_stage()` (gate creation)
- `v2_gate_action_service.py` → `continue_from_gate()` (accept action)
- `v2_gate_action_service.py` → `request_reanalysis()` (reanalysis action)
- `v2_stage_progression.py` → `queue_next_stage()` (stage queuing)
