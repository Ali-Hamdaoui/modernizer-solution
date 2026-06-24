# Feature 17 Tasks — Cockpit Recovery UX

## Task F17-T01 — Render checkpoint and attempt lineage

### Goal

Make accepted inputs and every stage attempt understandable without exposing storage details.

### Scope

- Render checkpoint chain, attempt causes/statuses, parent/fork relations, artifacts, and validation summaries.
- Highlight preserved checkpoint after failure.
- Consume backend-safe projections only; no provider endpoint, credential, SDK, or direct model call.

### Likely future modified files

- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` — compose recovery views.
- `web/control-tower/lib/contracts.ts` — checkpoint/attempt projection types.

### Likely future new files

- `web/control-tower/app/migrations/[jobId]/components/CheckpointPanel.tsx` — checkpoint details.
- `web/control-tower/app/migrations/[jobId]/components/AttemptTimeline.tsx` — attempt history.
- `web/control-tower/tests/recoveryCockpit.test.tsx` — lineage rendering.

### Implementation notes

- Artifacts/checksums are display truth.
- Do not display paths, argv, env, commands, raw logs, or Azure AI Foundry credentials/configuration.

### Acceptance criteria

- Failed Stage 4 clearly retains accepted Stage 3 checkpoint and all attempts.

### Focused tests

- Empty/loading/failure/multiple-attempt/fork states and redaction.

### Out of scope

- Recovery action submission.

### Dependencies

- Features 02, 03, 04.

## Task F17-T02 — Add governed recovery and repair controls

### Goal

Let humans review and submit backend-advertised actions.

### Scope

- Render retry/resume/fork/restart options, exact candidate diff, critique, approval, and validation proof.
- Submit user intent plus IDs/checksums/idempotency only; never submit provider, endpoint, deployment, credential, or fallback selection.
- Refresh on stale/conflict responses.

### Likely future modified files

- `web/control-tower/lib/controlTowerApi.ts` — safe action calls.
- `web/control-tower/lib/contracts.ts` — action/candidate/review/proof types.
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` — composition.

### Likely future new files

- `components/RepairReviewPanel.tsx` — exact candidate/review/approval.
- `components/RecoveryActionsPanel.tsx` — backend-advertised actions.
- `web/control-tower/tests/recoveryCockpit.test.tsx` — interaction/security tests.

### Implementation notes

- Human is decision owner; UI does not infer or auto-submit approval.
- Backend controls available actions and validates all requests.
- The Control Tower assistant response is generated through the backend Azure AI Foundry integration; the frontend does not call Foundry.

### Acceptance criteria

- Actions carry no execution fields and stale state requires refresh.

### Focused tests

- Approval/reject/revise/retry payloads, disabled states, accessibility.

### Out of scope

- Live frontend model calls, provider selection, Copilot integration, and advanced fork comparison.

### Dependencies

- F17-T01 and Features 05, 13, 16.
