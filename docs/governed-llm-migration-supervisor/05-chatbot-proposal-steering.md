# Chatbot Proposal Steering

## Goal

Let the operator steer LLM proposals through chat as backend-gated migration objects.

The chatbot is a proposal-control surface. It converts operator steering into revised migration proposals. It should feel operational: the user can say "make it POM-only" or "try the dependency fix," and the assistant creates a concrete proposal. The backend still controls binding, approval, apply, and validation.

Example:

```text
User: "Don't touch Java source. Make it POM-only."
Assistant: ActionRequest(action_type="revise_repair_proposal")
Backend: revised RepairProposal draft
```

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/control_tower/application/v2_assistant_service.py`
  - `AssistantMessage`.
  - `PendingActionDraft`.
  - `draft_action()`.
  - `FORBIDDEN_CAPABILITIES`.
  - `ALLOWED_TOOLS`.
- `migration_factory/control_tower/application/v2_model_schemas.py`
  - `ACTION_REQUEST_SCHEMA`.
  - `REPAIR_PROPOSAL_SCHEMA`.
  - `ASSISTANT_ANSWER_SCHEMA`.
- `migration_factory/control_tower/application/v2_repair_flow.py`
  - `V2RepairFlowService.create_proposal()`.
  - `RepairProposal`.
- `migration_factory/control_tower/adapters/fastapi/app.py`
  - `/v1/v2/jobs/{job_id}/assistant/ask`.
  - `/v1/v2/jobs/{job_id}/assistant/actions/draft`.
  - `/v1/v2/commands/{command_id}/repair/flow-proposal`.
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
  - Assistant composer and model status display.
- `web/control-tower/app/jobs/[jobId]/AssistantPanel.tsx`
  - Read-only tool allowlist and guardrail copy.

What already exists:

- Assistant messages.
- Draft actions.
- Read-only guardrails.
- ActionRequest schema validation.
- V2 repair proposal creation.

What must not be duplicated:

- Assistant message store.
- Draft action store.
- Guardrail allowlist.
- Repair proposal schema.

## Proposed Implementation

Allowed chat actions:

```text
explain_failure
diagnose_failure
propose_repair
revise_repair_proposal
propose_pom_patch
request_reviewer_critique
prepare_approval_request
prepare_sandbox_repair
request_validation_rerun_after_apply
```

Forbidden chat actions:

```text
execute_command_directly
write_file_directly
approve_decision
modify_legacy_source
override_failed_proof
choose_random_sandbox
```

Steps:

1. Extend `ActionRequest` validation to allow only the allowed action types above.
2. Add a `revise_repair_proposal` resolver path that requires:
   - existing proposal id
   - failed command id
   - current context pack checksum
   - steering instruction
3. Build a revision prompt from the existing proposal, user steering message, evidence refs, and safety constraints.
4. Validate revised model output as `RepairProposal`.
5. Persist revised proposal as a new draft, not mutation of the approved/applied proposal.
6. Emit an event such as `repair_proposal_revised`.

## Data / Schema Changes

Add fields to action draft/revision payloads:

- `source_proposal_id`
- `revision_instruction`
- `context_pack_checksum`
- `revision_of`
- `revision_number`
- `allowed_scope` such as `pom_only`

If structured outputs are used, keep schemas strict and object `additionalProperties: false`, per OpenAI/Azure guidance: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Azure Structured Outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs). OpenAI tool calling frames tool calls as structured model output that application code executes, which is the boundary this feature uses for proposal actions: [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling).

## Backend Flow

```text
user assistant message
-> /assistant/ask
-> ActionRequest(action_type=revise_repair_proposal)
-> backend resolver validates job/command/proposal binding
-> prompt router asks for revised RepairProposal
-> validate_model_output("RepairProposal")
-> persist revised proposal draft
-> emit repair_proposal_revised
```

## UI / Cockpit Impact

Add proposal steering UI after backend support exists:

- Show current proposal.
- Show user steering instruction.
- Show revised proposal diff/summary.
- Show "request reviewer critique" action.
- Do not show an "apply" button from chat.

Existing components to extend:

- `MigrationCockpit.tsx` assistant and Failure & Repair panel.
- `contracts.ts` `V2DraftActionResponse` and future proposal types.
- `controlTowerApi.ts` `draftV2Action()`.

## Human Supervision Point

The human steers, then reviews the revised proposal. Approval is still an explicit checksum card after reviewer/backend policy gates.

## Safety / Governance

- Sandbox only: revision cannot change sandbox binding.
- No legacy mutation: "POM-only" translates to allowed affected paths; backend still enforces.
- Human approval boundary: revision output can prepare an approval request, but cannot approve itself.
- Backend-owned action gate: chatbot turns steering into typed proposal revisions and action requests, but cannot bypass resolver, reviewer, approval, apply, validation, or proof gates.
- Checksum/proof gates: revised proposal gets a new checksum and must pass review/approval.

## Tests

Targeted tests:

- Extend `tests/control_tower/test_v2_assistant_service.py`.
- Extend `tests/control_tower/test_v2_assistant_adversarial.py`.
- Extend `tests/control_tower/test_v2_assistant_repair_api.py`.
- Add `test_assistant_can_request_repair_revision`.
- Add `test_assistant_rejects_execute_and_write_action_types`.
- Add `test_pom_only_revision_sets_pom_only_scope_without_applying`.

## Risks

- Confusing `prepare_approval_request` with actual approval.
- Revising an already applied proposal.
- Allowing steering text to override safety policy.

## Open Questions

- Should revision instructions be stored as assistant messages only, or as separate immutable instruction records?
- Should the first implementation support only `pom_only` steering?
