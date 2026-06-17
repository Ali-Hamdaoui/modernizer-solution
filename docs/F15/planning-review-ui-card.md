# Planning Review UI Card — F15-JOB-097

## Overview

Frontend component for rendering planning_review gate status and revision request UX in MigrationCockpit.

## UI Card Layout

```
┌─────────────────────────────────────┐
│ 📋 Planning Review — Stage N        │
│─────────────────────────────────────│
│ Status: OPEN / RESOLVED / SUPERSEDED│
│─────────────────────────────────────│
│ 📄 Plan Summary:                    │
│   ✅ Migration Plan                 │
│   ✅ Migration Units (5)            │
│   ✅ Approval Request               │
│─────────────────────────────────────│
│ Actions:                            │
│  [✅ Accept Plan]                   │
│  [📝 Request Revision]              │
│─────────────────────────────────────│
│ Revision Request:                   │
│ ┌─────────────────────────────────┐ │
│ │ Enter feedback...               │ │
│ └─────────────────────────────────┘ │
│ [Send Revision Request]              │
└─────────────────────────────────────┘
```

## Implementation

- Action posts to gate endpoint (not YAML direct edit)
- Text area for plan change request
- Chatbot context is gate-bound
- Submit only: gate_id, job_id, decided_by, expected_gate_checksum, user_feedback
