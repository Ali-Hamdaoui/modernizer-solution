# Approval Runbook — F15-JOB-100

## Overview

The approval_review gate pauses the workflow before transformation runs. After the planning_review gate is accepted with `continue`, an `approval_review` gate is automatically created. The user reviews the combined analysis + plan evidence and either approves transformation or rejects it.

## Approval Semantics

- The approval_review gate is created automatically after `continue_from_gate` on a planning_review gate
- The gate checksum covers **both** accepted analysis and accepted plan artifact checksums
- Approval requires all three preconditions:
  1. Gate exists and is OPEN
  2. Gate checksum is not stale
  3. Accepted analysis + plan revisions exist for the stage
- No transform command is queued until the gate is approved

## Checksum Mismatch

If the analysis or plan content changes between gate creation and approval:

1. The gate checksum (computed at gate creation) won't match the current artifact checksum
2. `approve_from_gate()` returns `stale_checksum`
3. The user must refresh and retry

The rejected gate remains open — no auto-retry. A new gate may be created via the revise cycle.

## Plan Revision After Approval

If a plan revision is needed after approval:

1. The approval_review gate must be rejected (returns `rejected` status)
2. A new planning cycle starts: user requests plan revision via `request_plan_revision`
3. The planning_review gate opens for the revised plan
4. Once accepted, a new approval_review gate is created

**Important:** Changes to the plan or analysis after approval invalidate the approval gate checksum.

## Available Actions

| Action | Effect |
|--------|--------|
| `approve` (approve_transformation) | Validates checksums + revisions, resolves gate, queues transform command |
| `reject` (reject_transformation) | Resolves gate with rejection, persists reason, no command queued |

## Common Failures

| Symptom | Cause | Resolution |
|---------|-------|------------|
| "no_accepted_analysis" | Analysis not accepted before approval | Ensure analysis_review gate was resolved with continue |
| "no_accepted_plan" | Plan not accepted before approval | Ensure planning_review gate was resolved with continue |
| "stale_checksum" | Artifact content changed since gate creation | Refresh gate view, retry, or reject and start new revision cycle |
| "invalid_decision" | Wrong action on approval gate | Use APPROVE or REJECT, not CONTINUE |
| "actor_not_authoritative" | Non-human tried to approve | Only humans can approve |

## Tests to Run

```bash
# Approval gate creation
python -m pytest tests/control_tower/test_v2_approval_gate_creation.py -v

# Approve transformation action
python -m pytest tests/control_tower/test_v2_approval_gate.py -v

# Reject transformation action
python -m pytest tests/control_tower/test_v2_gate_reject.py -v

# Approval blocked without accepted plan
python -m pytest tests/control_tower/test_v2_approval_requires_accepted_plan.py -v

# Gate action service (all actions)
python -m pytest tests/control_tower/test_v2_gate_action_service.py -v

# Phase gate service (approval phase)
python -m pytest tests/control_tower/test_v2_phase_gate_service.py -v

# Assistant explanation
python -m pytest tests/control_tower/test_v2_gate_assistant.py -v
```

## Sequence

```
Stage N analysis completes
  └─ analysis_review gate → continue → Planning phase
       └─ planning_review gate → continue
            └─ approval_review gate created automatically
                 ├─ approve_from_gate() → validates → queues transform
                 └─ reject_from_gate() → persists rejection → blocks
```

## No Direct LLM Approval

LLM/assistant actors cannot perform authoritative actions (approve, reject). Only human actors with `actor_type="human"` can approve transformations. The backend enforces this via the actor authority check in `V2GateActionService._execute_action()`.
