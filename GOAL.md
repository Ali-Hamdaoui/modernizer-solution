# FINAL AMF-252 Coding Agent Brief — True Reviewer JSON Schema Route + Diagnostics

## Objective

Implement **AMF-252** on branch:

```text
amf-237-reviewed-repair-gate
```

The product goal is the reviewed repair chain below:

```text
failure evidence
→ main/proposer LLM proposes repair
→ reviewer LLM returns schema-valid RepairReviewerOutput through strict json_schema response_format
→ backend validates/materializes final reviewed diff
→ git apply --check proves applicability
→ patch policy proves governance
→ repair proposal appears
→ approve action appears
```

AMF-252 is **not** the auto-rebuild/test continuation issue.

Do **not** implement automatic rebuild/test continuation in AMF-252 unless it is already wired and only needs a tiny reconnection. Auto rebuild/test continuation belongs to **AMF-253**.

---

## Web-Verified Structured Output Rule

Official OpenAI and Azure documentation agree on the important distinction:

```text
JSON mode / response_format={"type":"json_object"}
  → guarantees valid JSON only
  → does not guarantee the JSON matches RepairReviewerOutput

Structured Outputs / response_format={"type":"json_schema", ... strict=true ...}
  → constrains the model to the supplied JSON Schema
  → is the correct mechanism for governed reviewer output
```

Provider-safe strict schemas must follow these rules:

```text
root type = object
root anyOf = not used
every object has additionalProperties=false
every property in properties is listed in required
conditional/optional values are represented as nullable types, for example ["string", "null"]
avoid unsupported provider keywords in the outbound provider schema
```

This matters because the reviewer output is a governance boundary, not a convenience parser.

---

## ZIP Reanalysis Verdict

The uploaded ZIP is architecturally close. It already has the right big pieces:

```text
main/proposer role
reviewer role
RepairPrimaryOutput schema
RepairReviewerOutput schema
repair_review_chain producer
review_chain.json artifact
reviewer_repair_llm_output.json artifact
reviewer_repair_schema_failure.json artifact
final_reviewed_repair.diff artifact
backend import replacement materializer
/repair/proposals/current projection
/llm/activity projection
repair gate service
patch applicability and policy path
```

But AMF-252 is still blocked because the implementation still treats **JSON object support** as if it were enough for governed reviewer structured output.

Current bad behavior in the ZIP:

```text
supports_json_object=true
→ route is allowed
→ client may send response_format={"type":"json_object"}
→ reviewer output is only JSON-mode/prompt-mode governed
→ backend may later fail with confusing schema/materialization diagnostics
```

Correct AMF-252 behavior:

```text
reviewer + require_schema + output_schema_name=RepairReviewerOutput
→ requires AI_MIGRATION_REVIEWER_SUPPORTS_JSON_SCHEMA=true
→ requires AI_MIGRATION_REVIEWER_RESPONSE_FORMAT=json_schema
→ sends response_format.type=json_schema
→ sends json_schema.name=RepairReviewerOutput
→ sends json_schema.strict=true
→ sends provider-safe RepairReviewerOutput schema
```

If those requirements are not met, the backend must fail closed **before trusting reviewer output**.

---

## Non-Negotiable Product Rules

Keep these rules exactly:

```text
Backend is authority.
Frontend is display/approval only.
Main/proposer and reviewer are mandatory.
No schema-valid reviewer output => no proposal.
No final reviewed diff => no proposal.
No backend import fallback from main-only output.
No auto-apply.
No frontend patch text.
No weak Git flags:
  no git apply --reject
  no git apply --unidiff-zero
  no git apply --recount
git apply --check remains the applicability proof.
Patch policy remains the governance proof.
Approve action appears only after proposal exists.
```

---

## Root Problem

The current backend has a lot of fail-closed behavior already, but the reviewer route is not truly schema-capable.

Bad route:

```text
supports_json_object
→ treated like schema capability
→ response_format={"type":"json_object"}
→ not enough for RepairReviewerOutput
```

Correct route:

```text
supports_json_schema=true
response_format=json_schema
→ response_format.type=json_schema
→ strict RepairReviewerOutput schema
→ backend validates returned JSON again
```

`json_object` must **never** satisfy governed reviewer output.

---

## Current ZIP Findings

### Finding 1 — Reviewer schema capability default is unsafe

File:

```text
migration_factory/control_tower/application/v2_model_role_config.py
```

Current behavior in ZIP:

```python
"supports_json_schema": _get_env_bool(
    f"{prefix}_SUPPORTS_JSON_SCHEMA", True
),
```

Problem:

```text
Reviewer schema support defaults to true.
That means the backend may believe a reviewer deployment is schema-capable even when no runtime proof or explicit config exists.
```

Required AMF-252 behavior:

```text
For reviewer:
  AI_MIGRATION_REVIEWER_SUPPORTS_JSON_SCHEMA default = false

For governed reviewer RepairReviewerOutput:
  AI_MIGRATION_REVIEWER_SUPPORTS_JSON_SCHEMA must equal true
  AI_MIGRATION_REVIEWER_RESPONSE_FORMAT must equal json_schema
```

`AI_MIGRATION_REVIEWER_SUPPORTS_JSON_OBJECT=true` must not pass the reviewer `RepairReviewerOutput` gate.

---

### Finding 2 — Reviewer route gate is backwards

File:

```text
migration_factory/control_tower/application/v2_model_role_router.py
```

Current bad condition in ZIP:

```python
if role_config is None or role_config.supports_json_object:
    return None
```

Why this is wrong:

```text
If reviewer supports json_object only, route continues.
But json_object is exactly the mode that does not prove RepairReviewerOutput schema adherence.
```

Required logic:

```python
if (
    request.role == V2ModelRole.REVIEWER
    and request.require_schema
    and request.output_schema_name == "RepairReviewerOutput"
):
    role_config = ModelRoleConfigLoader.try_load_role("reviewer")

    if role_config is None:
        return reviewer_schema_capability_issue()

    if not role_config.supports_json_schema:
        return reviewer_schema_capability_issue()

    if role_config.response_format != "json_schema":
        return reviewer_schema_capability_issue()
```

Failure payload must include:

```text
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
schema_name=RepairReviewerOutput
role=reviewer
stage=reviewer
parse_failure_category=unsupported_response_format
response_format_requested=true
response_format_used=false
schema_repair_attempted=false
schema_repair_succeeded=false
schema_repair_failure_reason=schema_capability_unavailable
```

Required behavior:

```text
No reviewer freeform call.
No json_object call.
No prompt-only JSON fallback.
No schema repair attempt.
No final diff.
No proposal.
No approve action.
```

---

### Finding 3 — Model client still emits json_object for schema-required calls

File:

```text
migration_factory/control_tower/application/v2_assistant_model_client.py
```

Current behavior in ZIP:

```python
if require_schema and supports_json_object:
    payload["response_format"] = {"type": "json_object"}
```

And another provider path uses:

```python
if require_schema:
    response_format = {"type": "json_object"}
```

AMF-252 rule:

```text
json_object may remain for non-governed routes if existing tests need it.
json_object must never be used for reviewer RepairReviewerOutput.
```

Required helper or equivalent:

```python
def _build_response_format(
    *,
    role: V2ModelRole,
    role_config: ModelRoleConfig | None,
    require_schema: bool,
    output_schema_name: str | None,
) -> dict | None:
    ...
```

For reviewer `RepairReviewerOutput`, send exactly:

```python
{
    "type": "json_schema",
    "json_schema": {
        "name": "RepairReviewerOutput",
        "strict": True,
        "schema": structured_response_schema("RepairReviewerOutput"),
    },
}
```

Do not duplicate the schema manually inside the model client. The client must import/use:

```python
structured_response_schema("RepairReviewerOutput")
```

Provider rejection handling must also change.

Current summary in ZIP is still json_object-centered:

```text
Azure rejected response_format=json_object.
```

Required AMF-252 behavior for reviewer `json_schema` rejection:

```text
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
parse_failure_category=unsupported_response_format
response_format_requested=true
response_format_used=false
schema_repair_failure_reason=schema_capability_unavailable
redacted_summary=Reviewer model route does not support required structured output.
```

---

### Finding 4 — RepairReviewerOutput schema is not provider-safe yet

File:

```text
migration_factory/control_tower/application/v2_model_schemas.py
```

Current ZIP schema issue:

```text
reason_for_rejection is optional and type=string
revision_request is optional and type=string
provider helper structured_response_schema(schema_name) does not exist
provider schema still risks optional/internal fields leaking into strict mode
```

Required change:

```python
def structured_response_schema(schema_name: str) -> dict:
    ...
```

For `RepairReviewerOutput`, return a provider-safe strict schema:

```text
root type = object
root anyOf = not used
additionalProperties = false
every property listed in required
nullable type used for conditional fields
nested objects, if any, also additionalProperties=false
no unsupported provider-only keywords
```

Minimum required provider schema fields:

```text
decision
review_summary
main_patch_findings
changed_files_verified
reviewed_diff
diff_changed_by_reviewer
risks
policy_concerns
main_diff_diagnostics_acknowledged
diff_parseable
reviewed_context_checksum
reviewed_primary_output_checksum
reason_for_rejection
revision_request
```

Required nullable fields:

```json
"reason_for_rejection": { "type": ["string", "null"] },
"revision_request": { "type": ["string", "null"] }
```

Important internal-schema nuance:

```text
The internal REPAIR_REVIEWER_OUTPUT_SCHEMA must also accept the provider output.
If provider schema requires reason_for_rejection=null or revision_request=null,
internal validation must not reject null.
```

So update internal schema too:

```python
"required": [
    "decision",
    "review_summary",
    "main_patch_findings",
    "changed_files_verified",
    "reviewed_diff",
    "diff_changed_by_reviewer",
    "risks",
    "policy_concerns",
    "main_diff_diagnostics_acknowledged",
    "diff_parseable",
    "reviewed_context_checksum",
    "reviewed_primary_output_checksum",
    "reason_for_rejection",
    "revision_request",
],
"properties": {
    ...
    "reason_for_rejection": {"type": ["string", "null"]},
    "revision_request": {"type": ["string", "null"]},
}
```

Provider schema should not include optional/internal fields unless they are required and provider-compatible. Keep these out of the provider schema unless there is a strong reason and full tests:

```text
notes
confidence
model_claimed_diff_parseable
reviewed_diff_checksum
review_dimensions
```

---

### Finding 5 — Repair review chain is close; keep the governance order

File:

```text
migration_factory/orchestrator/repair_review_chain.py
```

The chain is broadly correct and must not be redesigned.

Keep this order:

```text
main output exists
→ reviewer schema capability confirmed
→ reviewer RepairReviewerOutput validates
→ reviewer diff accepted or backend import replacement fallback runs
→ final reviewed diff is promoted only after backend validation
```

Hard rule:

```text
backend import fallback must not run from main-only output
```

Allowed fallback:

```text
reviewer returned schema-valid RepairReviewerOutput
reviewer decision permits/accepts repair path
reviewer diff is malformed or not materializable
backend import replacement fallback can materialize deterministic import-only replacement
backend validates generated diff before promotion
```

Required prompt update:

```text
Return only JSON matching RepairReviewerOutput.
No markdown.
No prose outside JSON.
No extra keys.
Every required key must be present.
If accepting, set decision=accept and reason_for_rejection=null and revision_request=null.
If rejecting, set decision=reject, reviewed_diff="", reason_for_rejection=<reason>, revision_request=null.
If requesting revision, set decision=needs_revision, reason_for_rejection=null, revision_request=<specific request>.
If more context is needed, set decision=needs_more_context, reviewed_diff="", reason_for_rejection=<reason>, revision_request=<specific request or null>.
```

When route/client returns `REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE`, the chain must preserve that reason code exactly.

---

### Finding 6 — Repair gate events need truthful terminal diagnostics

File:

```text
migration_factory/control_tower/application/v2_repair_gate_service.py
```

Current code knows about `REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE`, but the event payloads must be made deterministic and complete.

When reviewer schema capability fails, both unavailable/materialization events must carry:

```text
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
schema_name=RepairReviewerOutput
parse_failure_category=unsupported_response_format
response_format_requested=true
response_format_used=false
schema_repair_attempted=false
schema_repair_succeeded=false
schema_repair_failure_reason=schema_capability_unavailable
reviewer_schema_failure_ref=<safe artifact ref>
final_diff_exists=false
policy_ran=false
gate_created=false
proposal_created=false
```

Suppress, demote, or guard against confusing duplicate-main events after terminal reviewer capability failure.

Confusing message to avoid:

```text
duplicate_main_blocked
Reviewed repair unavailable because the latest reviewed diff failed structural validation.
schema_name=RepairPrimaryOutput
```

Why:

```text
There was no reviewed diff in reviewer schema capability failure.
The terminal truth is reviewer schema capability unavailable.
```

---

### Finding 7 — /repair/proposals/current needs stronger diagnostic merge

File:

```text
migration_factory/control_tower/adapters/fastapi/app.py
```

Projection must merge diagnostics from:

```text
event.payload.schema_diagnostics
event.payload top-level diagnostic fields
reviewer_repair_schema_failure.json safe fields, if reviewer_schema_failure_ref exists
```

Expected safe-fail projection:

```text
kind=materialization_failed
title=Reviewer Schema Capability Unavailable
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
schema_name=RepairReviewerOutput
parse_failure_category=unsupported_response_format
response_format_requested=true
response_format_used=false
schema_repair_attempted=false
schema_repair_succeeded=false
schema_repair_failure_reason=schema_capability_unavailable
reviewer_schema_failure_ref=<safe artifact ref>
final_diff_exists=false
policy_ran=false
gate_created=false
proposal_created=false
next_action=Retry after reviewer/schema contract fix
```

Approve must be absent in this state.

---

### Finding 8 — /llm/activity ledger status can persist invalid durable status

File:

```text
migration_factory/control_tower/application/v2_llm_invocation_ledger.py
```

Current ZIP risk:

```python
failure_status = "schema_invalid"
```

But the durable DB status set is expected to be:

```text
started
completed
failed
fallback
```

Required minimum fix:

```text
Do not persist schema_invalid unless a migration explicitly allows it.
Use failed or fallback as durable status.
Expose schema/reason diagnostics separately in API projection.
```

Expected `/llm/activity` for reviewer capability failure:

```text
role=reviewer
status=fallback
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
schema_name=RepairReviewerOutput
response_format_requested=true
response_format_used=false
parse_failure_category=unsupported_response_format
schema_repair_failure_reason=schema_capability_unavailable
redacted_summary=Reviewer model route does not support required structured output.
```

Optional durable improvement:

```text
Add migration columns:
reason_code
schema_diagnostics_json
response_format_requested
response_format_used
parse_failure_category
schema_repair_failure_reason
finish_reason
```

Only add DB migration if tests cover it end-to-end.

---

### Finding 9 — Import replacement materializer should not be rewritten

File:

```text
migration_factory/repair_loop/import_replacement_materializer.py
```

Current ZIP uses:

```python
difflib.unified_diff(..., lineterm="")
```

Keep this.

Regression required:

```text
backend_import_replacement.diff must not contain:

--- a/file

+++ b/file
```

It must contain:

```text
--- a/file
+++ b/file
```

Do not rewrite AMF-250B logic in AMF-252.

---

## Backend Launcher Script Changes

File:

```text
run-control-tower-backend.ps1
```

Current ZIP launcher issue:

```text
Reviewer is configured as:
AI_MIGRATION_REVIEWER_RESPONSE_FORMAT=json_instruction_only
AI_MIGRATION_REVIEWER_SUPPORTS_JSON_OBJECT=false

The live smoke test only proves prompt JSON / json_object behavior.
It does not prove strict json_schema support.
```

That can let the backend start even though governed repair can never create proposals.

Add vars to clear list and runtime printout:

```text
AI_MIGRATION_MAIN_SUPPORTS_JSON_SCHEMA
AI_MIGRATION_REVIEWER_SUPPORTS_JSON_SCHEMA
AI_MIGRATION_FALLBACK_SUPPORTS_JSON_SCHEMA
AI_MIGRATION_MAIN_SUPPORTS_STRUCTURED_OUTPUTS
AI_MIGRATION_REVIEWER_SUPPORTS_STRUCTURED_OUTPUTS
AI_MIGRATION_FALLBACK_SUPPORTS_STRUCTURED_OUTPUTS
```

For product-success reviewer config, use only after strict smoke passes:

```powershell
Set-EnvValue "AI_MIGRATION_REVIEWER_RESPONSE_FORMAT" "json_schema"
Set-EnvValue "AI_MIGRATION_REVIEWER_SUPPORTS_JSON_SCHEMA" "true"
```

Add a reviewer strict schema smoke test with a very small schema:

```powershell
$response_format = @{
  type = "json_schema"
  json_schema = @{
    name = "ReviewerSchemaSmoke"
    strict = $true
    schema = @{
      type = "object"
      additionalProperties = $false
      required = @("ok", "role")
      properties = @{
        ok = @{ type = "boolean" }
        role = @{ type = "string"; enum = @("reviewer") }
      }
    }
  }
}
```

If reviewer deployment fails this smoke, stop launcher:

```text
Reviewer deployment is not schema-capable. Repair automation cannot create proposals.
```

Important model-selection rule:

```text
Do not assume Llama-3.3-70B-Instruct is schema-capable on this exact Azure/Foundry route.
Prove it with the strict json_schema smoke test.
If it fails, route reviewer to a deployment that supports json_schema.
```

Do not print secrets, endpoint credentials, raw prompts, or full provider error bodies.

---

## Required Code Changes by File

### 1. `migration_factory/control_tower/application/v2_model_role_config.py`

Implement reviewer-safe schema support default:

```python
supports_json_schema_default = False if role == "reviewer" else True

"supports_json_schema": _get_env_bool(
    f"{prefix}_SUPPORTS_JSON_SCHEMA",
    supports_json_schema_default,
),
```

Add/update tests:

```text
reviewer defaults supports_json_schema=false
main/proposer existing default behavior preserved unless intentionally changed
explicit AI_MIGRATION_REVIEWER_SUPPORTS_JSON_SCHEMA=true is honored
explicit AI_MIGRATION_REVIEWER_RESPONSE_FORMAT=json_schema is honored
```

---

### 2. `migration_factory/control_tower/application/v2_model_role_router.py`

Replace the current reviewer schema capability check.

Required helper behavior:

```python
def _schema_required_route_capability_issue(...):
    if not reviewer RepairReviewerOutput schema-required request:
        return None

    role_config = ModelRoleConfigLoader.try_load_role("reviewer")
    if role_config is None:
        return reviewer_schema_capability_issue()
    if not role_config.supports_json_schema:
        return reviewer_schema_capability_issue()
    if role_config.response_format != "json_schema":
        return reviewer_schema_capability_issue()
    return None
```

Make sure `supports_json_object` is irrelevant for reviewer RepairReviewerOutput.

Add/update tests:

```text
supports_json_object=true + supports_json_schema=false → fail closed
supports_json_object=true + response_format=json_object → fail closed
supports_json_schema=true + response_format=json_schema → route allowed
missing reviewer config → fail closed with REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
no reviewer invoke occurs when capability unavailable
```

---

### 3. `migration_factory/control_tower/application/v2_model_schemas.py`

Add:

```python
def structured_response_schema(schema_name: str) -> dict[str, Any]:
    ...
```

For `RepairReviewerOutput`, return a strict provider-safe schema. Do not manually duplicate the schema in `v2_assistant_model_client.py`.

Tests must verify:

```text
root type is object
root anyOf absent
root additionalProperties=false
every top-level property is listed in required
required includes reason_for_rejection and revision_request
reason_for_rejection accepts string/null
revision_request accepts string/null
all object schemas have additionalProperties=false
provider schema omits non-required/internal optional fields
```

Also update internal validation to accept nullable fields that provider will emit.

---

### 4. `migration_factory/control_tower/application/v2_assistant_model_client.py`

Add centralized response-format selection:

```python
def _build_response_format(
    *,
    role: V2ModelRole,
    role_config: ModelRoleConfig | None,
    require_schema: bool,
    output_schema_name: str | None,
) -> dict | None:
    if not require_schema:
        return None

    if role == V2ModelRole.REVIEWER and output_schema_name == "RepairReviewerOutput":
        if role_config is None:
            return None
        if not role_config.supports_json_schema:
            return None
        if role_config.response_format != "json_schema":
            return None
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "RepairReviewerOutput",
                "strict": True,
                "schema": structured_response_schema("RepairReviewerOutput"),
            },
        }

    # Existing non-governed routes may keep json_object if already intended.
    if role_config and role_config.supports_json_object:
        return {"type": "json_object"}
    return None
```

For reviewer `RepairReviewerOutput`:

```text
no json_object downgrade
no prompt-only JSON downgrade
no freeform retry
```

Provider 400 rejection of `json_schema` must become:

```text
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
failure_reason=reviewer_schema_capability_unavailable or equivalent mapped reason
parse_failure_category=unsupported_response_format
response_format_requested=true
response_format_used=false
```

Tests must inspect the actual request body and assert:

```text
response_format.type=json_schema
response_format.json_schema.name=RepairReviewerOutput
response_format.json_schema.strict=true
response_format.json_schema.schema == structured_response_schema("RepairReviewerOutput")
```

---

### 5. `migration_factory/orchestrator/repair_review_chain.py`

Keep the chain; do not redesign it.

Update the reviewer prompt contract to match the strict schema exactly.

Preserve schema capability failure diagnostics:

```text
REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE must not be rewritten to reviewer_schema_invalid.
REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE must not be rewritten to main_schema_invalid.
REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE must not be rewritten to duplicate_main_blocked.
```

Backend import replacement fallback is allowed only after schema-valid reviewer output exists.

Tests must cover:

```text
main-only output cannot trigger backend fallback
schema-capability unavailable stops before final diff
schema-valid reviewer + malformed reviewed_diff can trigger backend import fallback
schema-valid reviewer + valid diff continues to materialization
```

---

### 6. `migration_factory/control_tower/application/v2_repair_gate_service.py`

Normalize terminal reviewer capability failure events.

Required event names may stay as existing service design, but payload truth must include:

```text
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
schema_name=RepairReviewerOutput
parse_failure_category=unsupported_response_format
response_format_requested=true
response_format_used=false
schema_repair_attempted=false
schema_repair_succeeded=false
schema_repair_failure_reason=schema_capability_unavailable
final_diff_exists=false
policy_ran=false
gate_created=false
proposal_created=false
```

Add tests proving duplicate-main unavailable event is not emitted after this terminal reviewer capability failure.

---

### 7. `migration_factory/control_tower/adapters/fastapi/app.py`

Fix `/repair/proposals/current` safe-fail projection.

Projection merge order should be deterministic:

```text
base event payload
+ event.payload.schema_diagnostics
+ event.payload top-level diagnostic fields
+ safe fields from reviewer_schema_failure_ref artifact
```

Safe fail must show:

```text
kind=materialization_failed
title=Reviewer Schema Capability Unavailable
next_action=Retry after reviewer/schema contract fix
allowed_actions=[] or no approve action
```

Tests must call the API/projection and assert all diagnostic fields are visible.

---

### 8. `migration_factory/control_tower/application/v2_llm_invocation_ledger.py`

Do not persist invalid status values.

Minimum implementation:

```text
schema capability failures persist status=fallback or failed
reason_code is derived/exposed separately
schema diagnostics are exposed separately
```

Do not store `schema_invalid` as durable DB status unless you also add a migration and tests.

Tests:

```text
fail_invocation with schema text stores failed/fallback, not schema_invalid
record_to_dto exposes deterministic reason_code
reviewer capability unavailable appears as fallback with diagnostics
```

---

### 9. `migration_factory/repair_loop/import_replacement_materializer.py`

Keep existing diff generation behavior.

Add only regression coverage:

```text
no blank line between --- and +++ headers
```

---

### 10. `run-control-tower-backend.ps1`

Add strict reviewer schema smoke.

Recommended split:

```text
Invoke-RoleSmoke
  generic JSON smoke for non-governed roles

Invoke-ReviewerStrictSchemaSmoke
  required for reviewer governed repair path
  sends response_format.type=json_schema
  uses small strict schema
  refuses backend start if unsupported
```

Print runtime config safely:

```text
MAIN response format
MAIN supports json_object
MAIN supports json_schema
REVIEWER response format
REVIEWER supports json_object
REVIEWER supports json_schema
FALLBACK response format
FALLBACK supports json_object
FALLBACK supports json_schema
```

Never print API keys or raw secrets.

---

## Required Tests

Add/update tests for these exact outcomes:

```text
1. reviewer supports_json_object=true but supports_json_schema=false
   → fail closed
   → no reviewer model call
   → REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE

2. reviewer response_format=json_object even with supports_json_object=true
   → fail closed for RepairReviewerOutput
   → REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE

3. reviewer response_format=json_schema and supports_json_schema=true
   → client sends response_format.type=json_schema
   → json_schema.name=RepairReviewerOutput
   → strict=true
   → schema comes from structured_response_schema

4. provider rejects json_schema
   → fail closed
   → reviewer_repair_schema_failure.json written
   → no final diff
   → no proposal

5. provider-safe schema
   → every top-level property is required
   → reason_for_rejection and revision_request are nullable required fields
   → every object has additionalProperties=false
   → root anyOf absent

6. reviewer returns valid RepairReviewerOutput
   → reviewer_repair_llm_output.json written
   → review_chain.json written
   → materialization continues

7. reviewer output valid but diff malformed
   → backend import replacement fallback allowed
   → backend_import_replacement.diff generated
   → final_reviewed_repair.diff promoted only if valid

8. main-only output exists
   → backend fallback not allowed
   → no proposal

9. /repair/proposals/current projection
   → schema diagnostics visible
   → title is Reviewer Schema Capability Unavailable
   → approve action absent

10. /llm/activity projection
   → deterministic reviewer capability failure visible
   → status=fallback or failed, not schema_invalid unless migration exists

11. duplicate-main unavailable event
   → not emitted after terminal reviewer schema capability failure

12. AMF-250B regression
   → no blank line between --- and +++ diff headers

13. ledger status safety
   → no invalid DB status such as schema_invalid is persisted unless migration allows it
```

Likely test files:

```text
tests/control_tower/test_v2_assistant_gpt5_client.py
tests/control_tower/test_v2_model_role_config.py
tests/control_tower/test_v2_model_role_router.py
tests/control_tower/test_v2_model_schemas.py
tests/control_tower/test_v2_repair_review_chain_producer.py
tests/control_tower/test_v2_repair_proposal_api.py
tests/control_tower/test_v2_llm_invocation_ledger.py
tests/control_tower/test_v2_repair_gate_service.py
tests/control_tower/test_v2_repair_diff_normalization.py
```

---

## Current Targeted Test Signal From ZIP Reanalysis

I ran this targeted command from the extracted ZIP with `PYTHONPATH=.`:

```bash
PYTHONPATH=. pytest -q \
  tests/control_tower/test_v2_model_role_router.py \
  tests/control_tower/test_v2_assistant_gpt5_client.py -q
```

Current result:

```text
59 tests collected in those slices
54 passed
5 failed
```

Failures observed:

```text
1. test_router_reports_reviewer_schema_invalid
   Reason: stale expectation says missing_fields should include notes.
   But notes is not required in current RepairReviewerOutput and should not be required in AMF-252 provider schema.

2. test_build_diagnostic_summary_from_diag_azure_rejected
   Reason: diagnostic summary helper returns empty for a response_format_used=false-only diagnostic.
   AMF-252 should replace/extend this with reviewer schema capability unavailable diagnostics.

3. test_reasoning_effort_from_main_env_var
4. test_reasoning_effort_falls_back_to_old_env_var
5. test_temperature_not_sent_when_reasoning_effort_set
   Reason: role config / reasoning-effort behavior is currently inconsistent with test expectations.
   This is not the AMF-252 core blocker, but if AMF-252 touches role config and these tests remain in the target suite, stabilize them intentionally.
```

Also verified targeted Python compilation for AMF-252 files:

```text
py_compile passed for:
v2_model_role_config.py
v2_model_role_router.py
v2_model_schemas.py
v2_assistant_model_client.py
repair_review_chain.py
v2_repair_gate_service.py
app.py
v2_llm_invocation_ledger.py
import_replacement_materializer.py
```

---

## Runtime Validation After Coding

Run the same Jackson failure scenario.

Inspect:

```powershell
$Job = "<NEW_JOB_ID>"
$Base = "http://127.0.0.1:8000"

Invoke-RestMethod "$Base/v1/v2/jobs/$Job/repair/proposals/current" |
  ConvertTo-Json -Depth 100

Invoke-RestMethod "$Base/v1/v2/jobs/$Job/llm/activity" |
  ConvertTo-Json -Depth 100

Invoke-RestMethod "$Base/v1/v2/migration-jobs/$Job/events/snapshot?after=0" |
  ConvertTo-Json -Depth 100
```

Expected success:

```text
main_status=completed
reviewer_status=completed
schema_name=RepairReviewerOutput
response_format_requested=true
response_format_used=true
reviewer_output_checksum=<non-empty>
final_diff_exists=true
policy_ran=true
gate_created=true
proposal_created=true
approve action appears
```

Expected safe fail:

```text
reason_code=REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE
schema_name=RepairReviewerOutput
parse_failure_category=unsupported_response_format
response_format_requested=true
response_format_used=false
schema_repair_attempted=false
schema_repair_succeeded=false
schema_repair_failure_reason=schema_capability_unavailable
reviewer_repair_schema_failure.json exists
final_diff_exists=false
policy_ran=false
gate_created=false
proposal_created=false
approve absent
```

---

## Acceptance Contract

AMF-252 is done only when the system has two truthful outcomes.

### Success Outcome

```text
Reviewer deployment supports json_schema.
Backend sends response_format.type=json_schema.
Backend sends json_schema.name=RepairReviewerOutput.
Backend sends json_schema.strict=true.
Reviewer returns schema-valid RepairReviewerOutput.
Backend validates returned JSON again.
Backend validates/materializes final diff.
git apply --check passes.
Patch policy passes.
Proposal appears.
Approve action appears.
```

### Safe-Fail Outcome

```text
Reviewer deployment does not support json_schema, or config does not explicitly enable it.
Backend fails closed before trusting output.
Reason is REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE.
reviewer_repair_schema_failure.json exists.
/repair/proposals/current shows truthful diagnostics.
/llm/activity shows truthful diagnostics.
No final diff.
No policy run.
No gate created.
No proposal.
No approve action.
```

---

## Do Not Commit

Do not commit runtime/debug artifacts:

```text
.cleanup/db_cleanup_log.txt
amf251-schema-capability-* folders
amf252-* runtime inspection folders
runtime inspection folders
API dump folders
__pycache__ folders
.pytest_cache folders
```

Clean before final commit:

```powershell
git restore -- .cleanup/db_cleanup_log.txt
Remove-Item -Recurse -Force .\amf251-schema-capability-* -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\amf252-* -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\.pytest_cache -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
git status --short
```

---

## Final Coding-Agent Mental Model

Use this as the implementation compass:

```text
AMF-252 creates a hard contract boundary before reviewer repair.

Main/proposer can still use existing JSON behavior if current product flow needs it.
Reviewer RepairReviewerOutput cannot.

Reviewer RepairReviewerOutput requires true json_schema support.

If reviewer route is not schema-capable:
  stop before reviewer freeform call
  write safe schema failure artifact
  record ledger fallback/failed with reason diagnostics
  emit truthful unavailable/materialization events
  show truthful /repair/proposals/current diagnostic
  create no final diff
  create no proposal
  show no approve action

If reviewer route is schema-capable:
  send response_format.type=json_schema
  send strict schema name RepairReviewerOutput
  backend validates returned JSON again
  only then materialize/review final diff
  prove git apply --check
  prove patch policy
  create proposal
  expose approve action
```

---

## Final Priority Order

Implement in this order:

```text
1. v2_model_role_config.py
   Reviewer supports_json_schema default false.

2. v2_model_role_router.py
   Reviewer RepairReviewerOutput capability gate requires supports_json_schema=true and response_format=json_schema.

3. v2_model_schemas.py
   Add structured_response_schema(); make RepairReviewerOutput provider-safe; align internal nullable fields.

4. v2_assistant_model_client.py
   Centralize response_format; send json_schema for reviewer RepairReviewerOutput; no downgrade.

5. v2_assistant_model_client.py provider rejection handling
   Convert reviewer json_schema rejection into REVIEWER_SCHEMA_CAPABILITY_UNAVAILABLE.

6. repair_review_chain.py
   Update reviewer prompt and preserve capability diagnostics.

7. v2_repair_gate_service.py
   Make event truth deterministic and suppress confusing duplicate-main terminal reason.

8. app.py
   Merge safe diagnostics into /repair/proposals/current.

9. v2_llm_invocation_ledger.py
   Do not persist invalid schema_invalid status; expose reason diagnostics separately.

10. import_replacement_materializer.py tests only
    Preserve lineterm="" behavior and add AMF-250B regression.

11. run-control-tower-backend.ps1
    Add strict reviewer json_schema smoke and safe runtime printout.

12. Tests
    Update/add all required unit and API tests.

13. Runtime validation
    Run Jackson failure and verify both success or safe-fail contract.
```

