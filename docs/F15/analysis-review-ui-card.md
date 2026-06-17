# Analysis Review UI Card — F15-JOB-084

## Overview

Frontend component for rendering analysis_review gate status and actions in MigrationCockpit.

## UI Card Layout

```
┌─────────────────────────────────────┐
│ 🔍 Analysis Review — Stage N        │
│─────────────────────────────────────│
│ Status: OPEN / RESOLVED / SUPERSEDED│
│ Checksum: a1b2c3d4...               │
│─────────────────────────────────────│
│ 📄 Artifacts:                       │
│   ✅ Analysis Report                │
│   ✅ Dependency Graph               │
│   ✅ Test Inventory                 │
│─────────────────────────────────────│
│ Actions:                            │
│  [✅ Accept Analysis]               │
│  [📝 Request Reanalysis]            │
│─────────────────────────────────────│
│ Chatbot context includes: gate_id   │
└─────────────────────────────────────┘
```

## Implementation

- File: `web/control-tower/app/migrations/[jobId]/components/AnalysisReviewGateCard.tsx`
- Props: `gateId`, `jobId`, `onAction`
- No sandbox_path sent in any action payload
- Actions call existing gate API endpoint
- Artifact summary shown from evidence pack

## No sandbox_path

The UI card never sends `sandbox_path`, `argv`, `env`, or raw commands to the backend. All action payloads contain only:
- `gate_id`
- `job_id`
- `decided_by`
- `expected_gate_checksum`
- `user_feedback` (for reanalysis)
