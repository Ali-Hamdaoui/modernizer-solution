# F15 Repair UI Card

**Job:** F15-JOB-110
**Area:** Frontend
**Status:** Design complete

## Purpose

Render failure diagnosis and repair approval/revision actions in the MigrationCockpit. The repair UI card is shown when the pipeline stops at a `repair_review` gate.

## Card layout

```
┌─────────────────────────────────────────────────┐
│ 🔧 Repair Required — Stage 1                    │
│                                                 │
│ Failure Summary:                                 │
│ Build failed: compilation error in Foo.java      │
│ stderr: .../Foo.java:42: cannot find symbol      │
│                                                 │
│ Root Cause Hypothesis:                           │
│ Missing dependency declaration                   │
│                                                 │
│ Proposed Patch:                                  │
│ ┌─────────────────────────────────────────────┐ │
│ │ +    <dependency>                           │ │
│ │ +      <groupId>com.example</groupId>       │ │
│ │ +      <artifactId>example-lib</artifactId> │ │
│ │ +    </dependency>                          │ │
│ │ [... patch preview truncated ...]           │ │
│ └─────────────────────────────────────────────┘ │
│                                                 │
│ Reviewer Critique:                               │
│ ✅ Accepted — Proposal looks correct             │
│                                                 │
│ Attempts: 1/3 remaining                          │
│                                                 │
│ [Approve] [Revise] [Reject]                     │
└─────────────────────────────────────────────────┘
```

## Components

### RepairGateCard
- **Props**: `gate`, `evidence`, `proposal`, `critique`, `remainingAttempts`, `maxAttempts`
- **Sections**:
  - Failure summary (from evidence pack)
  - Root cause hypothesis (from diagnosis)
  - Patch preview (redacted)
  - Reviewer critique status
  - Attempt count indicator
  - Action buttons (Approve/Revise/Reject)

### Actions
- **Approve**: Calls `POST /gate/{gateId}/action` with `action=approve_repair`, `proposalId`, `proposalChecksum`, `contextPackChecksum`
- **Revise**: Opens a feedback dialog, then calls `POST /gate/{gateId}/action` with `action=request_repair_revision`
- **Reject**: Opens a confirmation dialog with reason input, then calls `POST /gate/{gateId}/action` with `action=reject_gate`

## Security

- No patch apply without gate action (approve via backend).
- No raw sandbox paths sent to frontend.
- Patch preview is redacted server-side before sending to frontend.
- Action buttons are disabled when gate is resolved or superseded.

## TypeScript contracts

See `contracts.ts` for:
- `GatePhase` enum
- `GateDecision` enum
- `GateRepresentation`
- `GateActionRequest` (no `sandbox_path`, `argv`, `env` fields)
- `GateActionResult`
- `RepairGateEvidence`
- `RepairGateProposal`
