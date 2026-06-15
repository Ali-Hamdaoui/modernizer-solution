# Event-Based Prompt Router

## Goal

Map backend migration events to prompt templates and strict output schemas so the LLM creates typed, bounded migration objects for the current event.

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/control_tower/application/v2_model_schemas.py`
  - Schema registry: `SCHEMA_REGISTRY`.
  - Required schemas: `PlanProposal`, `RepairProposal`, `ReviewerCritique`, `ActionRequest`, `AssistantAnswer`.
  - Validation entry points: `validate_against_schema()` and `validate_model_output()`.
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
  - `V2AssistantModelClient.answer()` and `smoke()`.
  - System prompt already enforces bounded assistant behavior and forbidden capabilities.
- `migration_factory/control_tower/application/v2_assistant_service.py`
  - Assistant message persistence and draft actions.
- `migration_factory/control_tower/adapters/fastapi/app.py`
  - `/assistant/ask` builds a bounded prompt from job, pipeline, events, approvals, failure summary, and artifacts.
  - `/assistant/actions/draft` validates `ActionRequest`.
  - `/repair/flow-proposal` validates `RepairProposal`.

What already exists:

- Strict schema definitions.
- Model invocation client.
- Assistant prompt building.
- Schema validation at service/API boundaries.

What must not be duplicated:

- Schema registry.
- Assistant model client.
- Assistant message service.
- Existing model audit/redaction behavior.

## Proposed Implementation

Add a small router beside the model schema/client layer, for example `v2_prompt_router.py`, with no execution authority.

Initial routing table:

```text
build_failed -> repair_diagnosis_prompt -> RepairProposal
test_failed -> repair_diagnosis_prompt -> RepairProposal
transform_failed -> repair_diagnosis_prompt -> RepairProposal
pom_issue_detected -> pom_repair_prompt -> RepairProposal
review_requested -> reviewer_prompt -> ReviewerCritique
```

Delay:

```text
analysis_completed
planning_completed
final_report_requested
```

Router responsibilities:

1. Accept `event_type`, `ContextPack`, and bounded event payload.
2. Select prompt template id.
3. Select schema name.
4. Select token budget from existing `TOKEN_BUDGETS`.
5. Return a model-call request object only.
6. Validate model output with `validate_model_output()`.

The router turns events into typed model-call requests. It can prepare diagnosis/proposal/review/action objects, but backend services still create approvals, choose commands, resolve sandboxes, apply patches, and validate proof.

## Data / Schema Changes

Add prompt metadata fields to model invocation/audit or context pack metadata:

- `prompt_template_id`
- `event_type`
- `output_schema_name`
- `context_pack_checksum`
- `token_budget_input`
- `token_budget_output`

No new output schema is required for the first slice because `RepairProposal` and `ReviewerCritique` already exist.

OpenAI and Azure both support schema-constrained outputs; Azure documents a JSON Schema subset and `additionalProperties: false`, matching the repo's strict schemas: [Azure Structured Outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs), [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Backend Flow

```text
event_type + ContextPack
-> PromptRouter.route()
-> prompt template id + schema name
-> model client structured call
-> validate_model_output(schema_name, output)
-> persist proposal/review/answer
```

## UI / Cockpit Impact

Show prompt routing as trace metadata only after persisted:

- Event type.
- Prompt template id.
- Output schema.
- Context pack checksum.
- Model status.

Do not add a UI-only router visualization.

## Human Supervision Point

Human sees the typed output and its evidence refs. They do not approve the router result until it becomes a proposal/reviewer/approval card.

## Safety / Governance

- Sandbox only: router cannot resolve paths or apply.
- No legacy mutation: prompt selection creates migration intents without file authority.
- Human approval boundary: router output schema can prepare an approval request, but cannot approve.
- Backend-owned action gate: tools/actions from router output must pass resolver, reviewer, approval, apply, validation, and proof gates.
- Checksum/proof gates: context pack checksum and model output checksum are carried forward.

## Tests

Targeted tests:

- Extend `tests/control_tower/test_v2_model_schemas.py`.
- Extend `tests/control_tower/test_v2_assistant_model_backing.py`.
- Add `test_prompt_router_maps_failure_events_to_repair_proposal`.
- Add `test_prompt_router_rejects_unknown_event_type`.
- Add `test_prompt_router_does_not_return_execution_fields`.

## Risks

- Router becoming a hidden command dispatcher.
- Adding too many event types before failure repair is stable.
- Letting model choose output schema.

## Open Questions

- Should prompt templates be inline Python constants, YAML files in AI Hub, or DB records?
- Should router failures be persisted as `model_invocation_failed` or a separate prompt-route failure event?
