# Cockpit Supervision Panels

## Goal

Expose the governed LLM repair flow in the cockpit using backend records only.

No fake UI-only diagnosis, no hardcoded AI trace, no frontend-only timeline.

## Current State in Repo

Exact files/classes/functions found:

- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
  - Loads job, messages, approvals, stages, events, pipeline, failure summary.
  - Displays Stage Timeline, Pipeline Status, Evidence, Approval Decisions, Failure & Repair, Assistant, Proof & Report.
  - Uses SSE from `v2EventStreamUrl()`.
- `web/control-tower/app/jobs/[jobId]/AssistantPanel.tsx`
  - Shows governed tool/action allowlist and assistant stream.
- `web/control-tower/lib/contracts.ts`
  - `V2PipelineResponse`, `V2FailureSummaryResponse`, `V2ApprovalResponse`, `V2AssistantAskResponse`, `V2ArtifactPreviewResponse`.
- `web/control-tower/lib/controlTowerApi.ts`
  - `getV2JobPipeline()`, `getV2FailureSummary()`, `getV2ArtifactPreview()`, `askV2Assistant()`, `approveV2Card()`, `rejectV2Card()`.
- `migration_factory/control_tower/adapters/fastapi/app.py`
  - Event snapshot/stream endpoints.
  - Pipeline projection.
  - Failure summary endpoint.
  - Approval endpoints.
  - Assistant APIs.
  - Artifact preview API.

What already exists:

- Migration cockpit route.
- Event stream/projection.
- Failure summary endpoint.
- Approval cards.
- Assistant composer.
- Artifact preview API.

What must not be duplicated:

- Event stream.
- Pipeline projection.
- Approval UI.
- Assistant panel.
- Artifact preview API.

## Proposed Implementation

Build panels only after backend records exist:

```text
AI Diagnosis
Evidence Used by AI
POM Analysis
Repair Proposal
Reviewer Verdict
Human Approval
Validation Result
```

Implementation steps:

1. Extend backend projections with persisted AI diagnosis/proposal/reviewer/validation records.
2. Extend `contracts.ts` with typed response fields.
3. Extend `controlTowerApi.ts` to fetch records from backend endpoints or included projection fields.
4. Extend `MigrationCockpit.tsx` panels to render backend state.
5. Drive panel refresh from important SSE events:
   - `ai_diagnosis_created`
   - `repair_proposal_revised`
   - `reviewer_critique_created`
   - `repair_patch_gate_completed`
   - `repair_validation_completed`
6. Keep artifact previews behind existing artifact preview API.

## Data / Schema Changes

Likely frontend contract additions:

- `V2AIDiagnosisResponse`
- `V2RepairProposalResponse`
- `V2ReviewerCritiqueResponse`
- `V2RepairValidationResponse`
- fields on `V2FailureSummaryItem` for `diagnosis_id`, `proposal_id`, `reviewer_critique_id`, `ledger_ref`

Technical basis: Codex `AGENTS.md` guidance is repo-local persistent instruction, but runtime cockpit authority still belongs to this application backend; this plan uses Codex-style documentation for implementation guidance only, not as runtime policy: [OpenAI Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md).

## Backend Flow

```text
backend records/events
-> projection endpoint
-> typed frontend contract
-> cockpit panels
-> SSE triggers refresh
```

## UI / Cockpit Impact

Panel content:

- AI Diagnosis: failure hypothesis, model status, context pack checksum.
- Evidence Used by AI: artifact refs and redaction status.
- POM Analysis: `PomContextSummary`.
- Repair Proposal: affected paths, deterministic rule id, patch summary, proposal checksum.
- Reviewer Verdict: accept/revise/reject and reasoning.
- Human Approval: existing checksum approval card.
- Validation Result: build/test/H2 statuses, rollback status, ledger ref.

## Human Supervision Point

The cockpit is where the human approves, rejects, or asks for revision. Existing approval cards remain the authority point.

## Safety / Governance

- Sandbox only: UI displays backend-resolved sandbox binding; no user path picker.
- No legacy mutation: affected paths are backend-projected.
- Human approval boundary: UI labels reviewer as critique, not approval.
- Backend-owned action gate: assistant panel can request typed drafts/revisions/actions, but backend gates control binding, approval, apply, validation, and proof.
- Checksum/proof gates: approval card shows exact checksum; validation panel shows deterministic results.

## Tests

Targeted tests:

- Extend web tests around `MigrationCockpit`.
- Extend `web/control-tower/tests/controlTowerApi.test.ts`.
- Extend `tests/control_tower/test_v2_cockpit_events.py`.
- Add `shows_ai_diagnosis_from_backend_records`.
- Add `does_not_render_apply_button_for_chatbot_proposal`.
- Add `shows_reviewer_verdict_on_approval_card`.
- Add `refreshes_on_ai_repair_sse_events`.

## Risks

- UI inventing state before backend records exist.
- Exposing raw logs, paths, or model deployment ids.
- Making the cockpit look authoritative before validation rerun/proof.

## Open Questions

- Should AI diagnosis/proposal/reviewer data be included in failure-summary endpoint or a new `/ai-trace` endpoint?
- Should artifact previews be embedded inline or opened on demand to control payload size?
