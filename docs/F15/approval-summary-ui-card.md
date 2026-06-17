# Approval Summary UI Card — F15-JOB-096

## Overview

Frontend component for rendering approval_review gate status and checksum-bound approval button in MigrationCockpit.

## UI Card Layout

```
┌─────────────────────────────────────┐
│ ✅ Approval Review — Stage N        │
│─────────────────────────────────────│
│ Status: OPEN / RESOLVED / REJECTED  │
│─────────────────────────────────────│
│ Approved Scope:                     │
│   ✅ Analysis Revision (checksum)    │
│   ✅ Plan Revision (checksum)        │
│   📋 Migration Units: 5             │
│   ⚠ Risks: Medium (3 findings)      │
│   📋 Validation Plan: Ready         │
│─────────────────────────────────────│
│ Actions:                            │
│  [👍 Approve Transformation]        │
│  [👎 Reject]                        │
│─────────────────────────────────────│
│ Checksum: a1b2c3d4...               │
└─────────────────────────────────────┘
```

## Implementation

- No approval without checksum
- No sandbox_path sent in any action payload
- Rejection path must be visible in UI
- Actions call gate API endpoint
- Submit only: gate_id, job_id, decided_by, expected_gate_checksum
