# Sandbox Action Resolver

## Goal

Ensure every assistant-generated proposal/action object is bound to the correct job, active stage, failed command, sandbox, and checksum before it can become an approval candidate.

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
  - Loads persisted V2 commands.
  - Builds backend-owned subprocess env from command manifests.
  - Emits events with `command_id`, stage, artifacts, sandbox refs.
  - `_result_sandbox_path()` extracts sandbox path from orchestrator result/artifact refs.
- `migration_factory/control_tower/application/v2_approval_mapping.py`
  - `ApprovalDecisionCard`.
  - `ResumeCommand`.
  - `approve()` validates checksum and job id.
- `migration_factory/control_tower/application/v2_repair_flow.py`
  - `RepairProposal` bound to `command_id`.
  - `approve_proposal()` and `apply_patch()` require proposal approval first.
- `migration_factory/control_tower/adapters/fastapi/app.py`
  - Approval endpoints validate card ownership and checksum.
  - Artifact preview resolves stored refs from backend events rather than request paths.
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
  - Approval cards use `request_checksum`.

What already exists:

- Command records.
- Backend-owned manifests.
- Event payloads with command/stage/sandbox data.
- Checksum approval cards.
- Artifact preview resolution from stored refs.

What must not be duplicated:

- Approval mapping.
- Command manifest persistence.
- Event stream.
- Artifact preview resolver.

## Proposed Implementation

Build `V2AssistantActionResolver`.

Responsibilities:

```text
resolve latest failed command
resolve active stage
resolve sandbox from backend state
verify command belongs to job
verify proposal belongs to command
attach checksum
return draft/proposal only
```

Steps:

1. Input: `job_id`, `action_request`, optional `proposal_id`, optional `event_id`.
2. Load job and V2 commands from repositories.
3. Load V2 events and find latest unresolved failed event for the active stage.
4. Extract or resolve sandbox path from backend events/result artifacts.
5. Verify sandbox belongs to the command/job and is not legacy source.
6. Verify proposal `command_id` matches failed command id.
7. Compute checksum over resolved binding and proposal payload.
8. Return a draft/proposal candidate; do not execute.

## Data / Schema Changes

Add binding record or payload:

```text
binding_id
job_id
stage_index
command_id
failed_event_id
sandbox_ref
sandbox_checksum
proposal_id
proposal_checksum
resolved_at
binding_checksum
```

This can start as `sandbox_binding_ref` artifact/metadata and later become explicit DB state.

Technical basis: model/tool outputs must remain application-owned proposals; OpenAI function calling/tool calling lets the model produce structured tool arguments, while the application executes the function: [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling). This matches the repo rule that backend, not browser or chatbot, resolves commands and sandboxes.

## Backend Flow

```text
ActionRequest/RepairProposal
-> V2AssistantActionResolver
-> validate job/command/proposal/sandbox binding
-> attach binding checksum
-> persist draft/proposal
-> later approval card references binding checksum
```

## UI / Cockpit Impact

Approval/proposal cards should show:

- Stage index.
- Command id.
- Sandbox binding status.
- Proposal checksum.
- Binding checksum.

No UI should let the operator pick a sandbox manually.

## Human Supervision Point

The human approves only a backend-resolved proposal/action. They never approve a free-form path from the chatbot.

## Safety / Governance

- Sandbox only: resolver fails closed if sandbox cannot be resolved from backend state.
- No legacy mutation: resolver rejects paths under legacy source.
- Human approval boundary: resolver attaches checksums and can prepare approval candidates, but does not approve.
- Backend-owned action gate: resolver converts LLM intent into bound workflow input without bypassing reviewer, approval, apply, validation, or proof gates.
- Checksum/proof gates: binding checksum guards stale command/sandbox issues.

This prevents:

- wrong sandbox writes
- legacy source mutation
- stale command repair
- proposal-command mismatch
- user/model path injection

## Tests

Targeted tests:

- Extend `tests/control_tower/test_v2_repair_flow.py`.
- Extend `tests/control_tower/test_v2_approval_mapping.py`.
- Extend `tests/control_tower/test_v2_orchestrator_runner.py`.
- Add `test_action_resolver_binds_latest_failed_command`.
- Add `test_action_resolver_rejects_stale_proposal_command`.
- Add `test_action_resolver_rejects_legacy_source_sandbox`.

## Risks

- Attempting to resolve sandbox from model output or browser input.
- Failing open when events lack sandbox refs.
- Confusing active stage with latest stage event after resume.

## Open Questions

- What is the canonical repository method for command lookup by job/stage?
- Should sandbox binding be recomputed on every approval or persisted once?
- UNCERTAIN: resume command ids may differ from original failed command ids; implementation must define canonical failed-command ownership.
