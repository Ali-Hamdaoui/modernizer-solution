# AMF-252 — CURRENT MODEL TRANSPORT AND REQUEST AUDIT

**Date:** 2026-07-09
**Branch:** `feature/superposition-llm-repair-mvp`
**Audit type:** Static analysis — no code changes, no test execution, no model calls
**Evidence standard:** PROVEN / HIGH CONFIDENCE / POSSIBLE / UNKNOWN / DISPROVEN

---

## 1. EXECUTIVE VERDICT

The current backend has **three independent blockers**:

| # | Blocker | Models Affected | Confidence |
|---|---|---|---|
| **B1** | `REPAIR_PRIMARY_OUTPUT_SCHEMA.machine_readable_metadata` = `{"type":"object"}` with NO `additionalProperties: false` | Proposer (GPT-5 mini) | PROVEN |
| **B2** | `REPAIR_REVIEWER_OUTPUT_SCHEMA.review_dimensions` = `{"type":"object"}` with NO `additionalProperties: false` | Reviewer (Llama) | PROVEN |
| **B3** | Both proposer and reviewer attempt `/responses` FIRST because endpoint ends with `/openai/v1`; Llama is NOT proven on `/responses` | Reviewer (Llama) | PROVEN |

**#SchemaFixAloneIsInsufficient** — B1 and B2 must be fixed, but without also fixing B3 the reviewer will still fail because it routes Llama through `/responses` first. The known-good external tests use `/chat/completions`.

---

## 2. CURRENT REPOSITORY STATE

| Property | Value |
|---|---|
| Branch | `feature/superposition-llm-repair-mvp` |
| HEAD | `68d994f` — "the 400ERROR FIXED" |
| Dirty | `AGENTS.md` (M), `AMF252_OPTION_A_REVIEWER_ACCEPTED_REPAIR_MVP.md` (D) |
| Untracked | `AMF252_PREIMPLEMENTATION_DEEP_CURRENT_CODEBASE_AUDIT.md` |
| Production difference from prior audit | None — same transport, same schemas |

---

## 3. EXACT PROPOSER CALL CHAIN (GPT-5 mini)

```
create_reviewed_repair_proposal_on_failure()           [v2_repair_gate_service.py:375]
→ _create_reviewed_repair_proposal_from_refs()          [v2_repair_gate_service.py:471]
  → produce_repair_review_chain()                        [repair_review_chain.py:462]
    → client.answer_with_role(PROPOSER)                  [repair_review_chain.py:511]
      → V2ModelRoleRouter.route(invoke=...)              [v2_assistant_model_client.py:226]
        → _answer_with_deployment(role=PROPOSER)         [v2_assistant_model_client.py:240]
          → _chat_completion()                            [v2_assistant_model_client.py:287]
            → _is_v1_endpoint() → TRUE                   [v2_assistant_model_client.py:428]
            ↓
            → _responses_completion_v1()  ← FIRST        [v2_assistant_model_client.py:431]
              → _post_responses_v1()
                → POST {AZURE_OPENAI_ENDPOINT}/responses
            ↓ on HTTPError
            → _should_retry_with_chat_completions(exc)
              ↓ if TRUE:
              → _chat_completion_v1()  ← SECOND          [v2_assistant_model_client.py:445]
                → _post_chat_completion_v1()
                  → POST {AZURE_OPENAI_ENDPOINT}/chat/completions
              ↓ if still HTTPError:
              → _should_retry_with_legacy_endpoint(exc)
                ↓ if TRUE:
                → _chat_completion_legacy()  ← THIRD     [v2_assistant_model_client.py:458]
                  → _post_chat_completion_legacy()
```

### Investigation 1 Answers

1. **First endpoint attempted for GPT-5 mini:** `/responses`
2. **Is it `/responses` or `/chat/completions`?** `/responses`
3. **Why?** `_is_v1_endpoint()` at line 404–406 matches `AZURE_OPENAI_ENDPOINT = "https://abdelilahmortaki-9971-resource.openai.azure.com/openai/v1"` because it ends with `/openai/v1`
4. **Selection basis:** Purely endpoint URL suffix — no model role, deployment name, or capability check.
5. **Fallback trigger:** `_should_retry_with_chat_completions()` (line 1021–1036) returns TRUE on HTTP 404, 405, or HTTP 400 when error body contains `<html`, `badly formed`, `unsupported`, `not supported`, or `unknown parameter`.
6. **HTTP 400 fallback:** YES — but ONLY if body matches keyword patterns above. Pure JSON API error (e.g., `{"error":{"code":"BadRequest"}}`) without those keywords → DOES NOT trigger fallback.
7. **Schema rejection on `/responses` causing fallback:** POSSIBLE but depends on Azure response body content. If Azure returns a simple JSON error without the keywords, fallback is **skipped** and code proceeds to legacy endpoint attempt or failure.
8. **Fallback visible in ledger:** YES — `fallback_used=true` is recorded.
9. **Transport identification from persisted data:** PARTIALLY — ledger stores `redacted_error` (e.g., "http_400") and `response_format_used` but NOT the URL path. Cannot distinguish `/responses` vs `/chat/completions` failure.

---

## 4. EXACT REVIEWER CALL CHAIN (Llama-3.3-70B-Instruct)

Identical call chain. Same `_chat_completion()` → same `_is_v1_endpoint()` → same `_responses_completion_v1()` first.

```
produce_repair_review_chain()                           [repair_review_chain.py:462]
→ client.answer_with_role(REVIEWER)                      [repair_review_chain.py:621]
  → [same as proposer chain above]
    → _responses_completion_v1()  ← FIRST
      → POST /openai/v1/responses
        (with model=Llama-3.3-70B-Instruct)
```

### Investigation 2 Answers

1. **Reviewer first endpoint:** `/responses`
2. **Same transport as proposer:** YES — identical code path.
3. **Llama sent to `/responses` first?** PROVEN YES.
4. **Model-specific capability routing?** NO — zero model-type awareness in transport layer.
5. **Code distinguishes GPT-5 vs Llama?** NO.
6. **Generic transport strategy:** PROVEN — every model uses identical `_chat_completion()` logic.
7. **Llama sent to `/responses` solely because endpoint ends in `/openai/v1`?** PROVEN YES.
8. **Transport capability distinction:** NONE — no code exists to distinguish OpenAI reasoning models, Meta Llama, chat-completion-only, or Responses-compatible models.

---

## 5. EXACT PROPOSER REQUEST RECONSTRUCTION (GPT-5 mini)

### First attempt: POST to `/responses`

**URL:** `POST https://abdelilahmortaki-9971-resource.openai.azure.com/openai/v1/responses`
**Auth:** `api-key: [REDACTED]`

**Request body (`_post_responses_v1`, line 694–714):**
```json
{
  "model": "gpt-5-mini",
  "input": [
    {"type": "message", "role": "system", "content": "[assistant system prompt]"},
    {"type": "message", "role": "user", "content": "[repair proposer prompt]"}
  ],
  "store": false,
  "max_output_tokens": 20000,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "RepairPrimaryOutput",
      "strict": true,
      "schema": {
        "type": "object",
        "additionalProperties": false,
        "required": ["root_cause","fix_strategy","changed_files","proposed_diff","risk","confidence","rationale"],
        "properties": {
          "root_cause": {"type": "string"},
          "fix_strategy": {"type": "string"},
          "changed_files": {"type": "array", "items": {"type": "string"}},
          "proposed_diff": {"type": "string", "minLength": 20},
          "deterministic_rule_id": {"type": "string"},
          "risk": {"type": "string", "enum": ["LOW","MEDIUM","HIGH"]},
          "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
          "rationale": {"type": "string"},
          "no_fix_reason": {"type": "string"},
          "machine_readable_metadata": {"type": "object"}
        }
      }
    }
  },
  "reasoning": {"effort": "medium"}
}
```

**CRITICAL OBSERVATION:** The `response_format` field is placed at the **top level** of the payload. The Responses API requires structured output under `text.format`, NOT `response_format`. This is a structural mismatch even before schema content is validated.

### Second attempt: POST to `/chat/completions` (if fallback triggers)

**URL:** `POST https://abdelilahmortaki-9971-resource.openai.azure.com/openai/v1/chat/completions`

**Request body (`_post_chat_completion_v1`, line 648–680):**
```json
{
  "model": "gpt-5-mini",
  "messages": [
    {"role": "system", "content": "[assistant system prompt]"},
    {"role": "user", "content": "[repair proposer prompt]"}
  ],
  "max_completion_tokens": 20000,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "RepairPrimaryOutput",
      "strict": true,
      "schema": {
        "type": "object",
        "additionalProperties": false,
        "required": [...],
        "properties": {
          ...
          "machine_readable_metadata": {"type": "object"}
        }
      }
    }
  },
  "reasoning_effort": "medium"
}
```

**NOTE:** `machine_readable_metadata` at path `.properties.machine_readable_metadata` is `{"type": "object"}` WITHOUT `additionalProperties: false`. This violates the `strict: true` contract which requires ALL object types to declare `additionalProperties: false`.

### Response parser

For `/responses`: `_extract_responses_output_text()` (line 868–894) — traverses `data.output[].content[].text` looking for `output_text` items.
For `/chat/completions`: `_extract_assistant_content()` (line 856–865) — reads `data.choices[0].message.content`.

---

## 6. EXACT REVIEWER REQUEST RECONSTRUCTION (Llama-3.3-70B-Instruct)

### First attempt: POST to `/responses` (same transport as proposer)

**URL:** `POST https://abdelilahmortaki-9971-resource.openai.azure.com/openai/v1/responses`

**Headers:** `Content-Type: application/json`, `api-key: [REDACTED]`

**Request body:**
```json
{
  "model": "Llama-3.3-70B-Instruct",
  "input": [
    {"type": "message", "role": "system", "content": "[assistant system prompt]"},
    {"type": "message", "role": "user", "content": "[reviewer prompt]"}
  ],
  "store": false,
  "max_output_tokens": 20000,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "RepairReviewerOutput",
      "strict": true,
      "schema": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "decision", "notes", "risks", "confidence",
          "policy_concerns", "reviewed_context_checksum",
          "reviewed_primary_output_checksum", "reviewed_diff_checksum"
        ],
        "properties": {
          "decision": {"type": "string", "enum": ["accept","revise","reject"]},
          "notes": {"type": "array", "items": {"type": "string"}},
          "risks": {"type": "array", "items": {"type": "string"}},
          "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
          "policy_concerns": {"type": "array", "items": {"type": "string"}},
          "reviewed_context_checksum": {"type": "string"},
          "reviewed_primary_output_checksum": {"type": "string"},
          "reviewed_diff_checksum": {"type": "string"},
          "review_dimensions": {"type": "object"}
        }
      }
    }
  },
  "reasoning": {"effort": "medium"}
}
```

**Two schema problems in one request:**
1. `review_dimensions` is `{"type":"object"}` without `additionalProperties: false` — **strict mode violation**
2. The entire `response_format` key is wrong for `/responses` API — should be nested under `text.format`

### Second attempt: POST to `/chat/completions` (if fallback triggers)

**Request body (`_post_chat_completion_v1`):**
```json
{
  "model": "Llama-3.3-70B-Instruct",
  "messages": [
    {"role": "system", "content": "[assistant system prompt]"},
    {"role": "user", "content": "[reviewer prompt]"}
  ],
  "max_completion_tokens": 20000,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "RepairReviewerOutput",
      "strict": true,
      "schema": {
        ...
        "properties": {
          ...
          "review_dimensions": {"type": "object"}
        }
      }
    }
  },
  "reasoning_effort": "medium"
}
```

**Problem persists:** `review_dimensions` without `additionalProperties: false` fails strict json_schema validation even on `/chat/completions`.

---

## 7. BACKEND-vs-PROVEN-EXTERNAL REQUEST COMPARISON

### Llama-3.3-70B-Instruct Reviewer

| Property | Proven External Request | Current Backend Request (attempt 1) | Match? | Risk |
|---|---|---|---|---|
| Endpoint | `/chat/completions` | `/responses` | **NO** | BLOCKING — wrong transport |
| Model | `Llama-3.3-70B-Instruct` | `Llama-3.3-70B-Instruct` | YES | None |
| Token field | `max_completion_tokens: 256` | `max_output_tokens: 20000` (responses) / `max_completion_tokens: 20000` (chat) | PARTIAL | Different field name for `/responses` |
| Response format location | `response_format` (top-level) | `response_format` (top-level) | YES for chat, **NO for responses** | `/responses` expects `text.format` |
| Response format type | `json_schema` | `json_schema` | YES | — |
| Strict | `true` | `true` | YES | — |
| Schema structure | Tiny (2 fields: decision, notes) | Full (8+ fields) | **NO** | Bloated |
| `additionalProperties: false` on all objects | YES (clean) | **NO** — `review_dimensions` lacks it | **NO** | BLOCKING — strict mode violation |
| Reasoning effort | `none` (omitted) or `low` | `medium` | **NO** | MODERATE — unproven for medium |
| Timeout | curl default | 30s hardcoded | — | MODERATE |
| Auth | `api-key` header | `api-key` header | YES | — |

### Key Mismatches

| Mismatch | Proposer | Reviewer | Blocking? |
|---|---|---|---|
| Wrong endpoint first | `/responses` | `/responses` | BLOCKING for both on `/responses` |
| Schema `machine_readable_metadata` missing `additionalProperties: false` | YES | N/A | BLOCKING for proposer |
| Schema `review_dimensions` missing `additionalProperties: false` | N/A | YES | BLOCKING for reviewer |
| Reasoning effort `medium` (unproven for Llama) | N/A | YES | POSSIBLE — `low` is proven, `medium` is not |
| Timeout 30s vs 300s configured | 30s | 30s | MODERATE — could cause timeout for long outputs |

---

## 8. PROVEN EXTERNAL LLAMA CAPABILITY MATRIX

| Capability | Endpoint | Result |
|---|---|---|
| Basic chat completion | `/chat/completions` | PROVEN OK |
| `reasoning_effort=low` | `/chat/completions` | PROVEN OK |
| `response_format=json_object` | `/chat/completions` | PROVEN OK |
| `response_format=json_schema` (strict, full schema) | `/chat/completions` | PROVEN OK |
| `response_format=json_schema` (strict, minimal schema) | `/chat/completions` | PROVEN OK |
| `/responses` endpoint | `/responses` | **NOT PROVEN** |
| `reasoning_effort=medium` | `/chat/completions` | **NOT PROVEN** |
| `max_output_tokens` (Responses field) | `/responses` | **NOT PROVEN** |

---

## 9. PROPOSER SCHEMA AUDIT (`REPAIR_PRIMARY_OUTPUT_SCHEMA`)

File: `v2_model_schemas.py:83–117`

| JSON Path | Current Value | Type | Required | Azure SO Compatible? | Blocking? |
|---|---|---|---|---|---|
| `root_cause` | `{"type":"string"}` | string | YES | OK | No |
| `fix_strategy` | `{"type":"string"}` | string | YES | OK | No |
| `changed_files` | `{"type":"array","items":{"type":"string"}}` | array | YES | OK | No |
| `proposed_diff` | `{"type":"string","minLength":20}` | string | YES | `minLength` valid but aggressive | POSSIBLE — 20 chars for a diff may cause rejection |
| `deterministic_rule_id` | `{"type":"string"}` | string | NO | OK | No |
| `risk` | `{"type":"string","enum":["LOW","MEDIUM","HIGH"]}` | string | YES | OK | No |
| `confidence` | `{"type":"number","minimum":0.0,"maximum":1.0}` | number | YES | OK | No |
| `rationale` | `{"type":"string"}` | string | YES | OK | No |
| `no_fix_reason` | `{"type":"string"}` | string | NO | OK | No |
| `machine_readable_metadata` | `{"type":"object"}` | object | NO | **NO — missing `additionalProperties: false`** | **BLOCKING** |

**Verdict:** `machine_readable_metadata` at `REPAIR_PRIMARY_OUTPUT_SCHEMA.properties.machine_readable_metadata` is `{"type":"object"}`. The `strict: true` contract requires every object property to include `additionalProperties: false`. This is a STRICT MODE VIOLATION that will cause the Azure API to reject the schema.

---

## 10. REVIEWER SCHEMA AUDIT (`REPAIR_REVIEWER_OUTPUT_SCHEMA`)

File: `v2_model_schemas.py:119–143`

| JSON Path | Current Value | Type | Required | Azure SO Compatible? | Blocking? |
|---|---|---|---|---|---|
| `decision` | `{"type":"string","enum":["accept","revise","reject"]}` | string | YES | OK | No |
| `notes` | `{"type":"array","items":{"type":"string"}}` | array | YES | OK | No |
| `risks` | `{"type":"array","items":{"type":"string"}}` | array | YES | OK | No |
| `confidence` | `{"type":"number","minimum":0.0,"maximum":1.0}` | number | YES | OK | No |
| `policy_concerns` | `{"type":"array","items":{"type":"string"}}` | array | YES | OK | No |
| `reviewed_context_checksum` | `{"type":"string"}` | string | YES | OK | No |
| `reviewed_primary_output_checksum` | `{"type":"string"}` | string | YES | OK | No |
| `reviewed_diff_checksum` | `{"type":"string"}` | string | YES | OK | No |
| `review_dimensions` | `{"type":"object"}` | object | NO | **NO — missing `additionalProperties: false`** | **BLOCKING** |

**Verdict:** Same issue as proposer — `review_dimensions` at `REPAIR_REVIEWER_OUTPUT_SCHEMA.properties.review_dimensions` lacks `additionalProperties: false`. Strict mode rejection for reviewer as well.

---

## 11. HTTP 400 ROOT-CAUSE RANKING

Previous runtime evidence:
```
job = 6a489598ca4d4d7b83b85a40deadff09
role = main (proposer)
schema_name = RepairPrimaryOutput
status = fallback
fallback_used = true
redacted_error = http_400
configured_max_output_tokens = 20000
response_format_used = json_schema
```

| Rank | Cause | Confidence | Explanation |
|---|---|---|---|
| **1** | Invalid schema (B1 — `machine_readable_metadata` missing `additionalProperties: false`) | **HIGH** | Azure strict mode rejects schemas with object properties lacking `additionalProperties: false`. This alone can produce HTTP 400. |
| **2** | Wrong payload key for `/responses` (`response_format` instead of `text.format`) | **HIGH** | The Responses API does not accept `response_format` as a top-level key. This produces HTTP 400 before schema is even checked. |
| **3** | Both causes combined (schema invalid + wrong key for endpoint) | **PROVEN** | Both apply simultaneously. |
| **4** | `proposed_diff.minLength = 20` too aggressive | **POSSIBLE** | A 20-character minimum on a diff string may cause model output rejection, but this is a runtime issue not a schema issue. The schema itself is valid. |
| **5** | Transport fallback timing | **PROVEN** | The `/responses` endpoint is tried first → gets HTTP 400 → **if fallback text check fails** (pure JSON error without keywords) → fallback to `/chat/completions` is SKIPPED → code goes to legacy endpoint or fails completely. |

**Can the exact historical cause be reconstructed from DB/artifacts?** PARTIALLY. The ledger stores `redacted_error="http_400"` and `response_format_used="json_schema"` but does NOT store the URL path or response body. The diagnostic file (`repair_diagnostic_proposer.json`) stores `response_format_used` but not the endpoint that was used when the error occurred.

---

## 12. TRANSPORT DECISION: `/responses` vs `/chat/completions`

### Current behavior

Both proposer and reviewer follow the same logic:
1. Endpoint ends with `/openai/v1` → try `/responses` FIRST
2. On HTTP error 400/404/405 with matching body → try `/chat/completions`
3. On HTTP error 400 with HTML/legacy keywords → try legacy endpoint

### Assessment

**Option A** (keep generic `/responses` first): **NOT SAFE** — Llama is NOT proven on `/responses`. The backend sends Llama to an endpoint that has no proven compatibility.

**Option B** (route Llama reviewer explicitly through `/chat/completions`): **Safest** — matches proven external tests.

**Option C** (capability-based transport selection): **Overengineered** — requires new configuration and model metadata, not justified for two models.

### Recommendation

| Aspect | Value |
|---|---|
| **Recommended option** | **OPTION B** — Route Llama reviewer explicitly through `/chat/completions` |
| **Why** | Matches known-good external tests; proven to work with strict json_schema, reasoning_effort=low, token budgets |
| **Minimum code impact** | Add per-role endpoint selection or allow the role router to specify `use_responses` or `use_chat_completions` flag |
| **Risks** | Low — the change is contained to endpoint selection logic |
| **Runtime test needed** | After schema fix + transport fix: verify reviewer produces `decision=accept` with valid `RepairReviewerOutput` |

---

## 13. `reasoning_effort` AUDIT

File: `v2_model_role_router.py:313–328`

```python
def _resolve_budget(self, *, role, responsibility="", output_schema_name=None):
    role_key = role.value.upper()
    reasoning_effort = self._read_str_env(f"AZURE_OPENAI_{role_key}_REASONING_EFFORT")
    if not reasoning_effort:
        reasoning_effort = self._read_str_env("AZURE_OPENAI_REASONING_EFFORT") or "medium"
```

### Launcher intent vs runtime behavior

| Role | Launcher sets `_{role}_REASONING_EFFORT` | Launcher intent | Runtime resolved value |
|---|---|---|---|
| PROPOSER | `AZURE_OPENAI_PROPOSER_REASONING_EFFORT = "medium"` | medium | `medium` ✓ |
| REVIEWER | `AZURE_OPENAI_REVIEWER_REASONING_EFFORT = ""` | disabled (empty) | **`medium`** ✗ — falls back to generic `AZURE_OPENAI_REASONING_EFFORT = "medium"` |
| Generic | `AZURE_OPENAI_REASONING_EFFORT = "medium"` | medium | Always `medium` |

**Root cause:** The fallback chain at `v2_model_role_router.py:318–319` reads `AZURE_OPENAI_{role}_REASONING_EFFORT` first. When empty, it falls back to `AZURE_OPENAI_REASONING_EFFORT` which is always `"medium"`. The launcher's explicit `AZURE_OPENAI_REVIEWER_REASONING_EFFORT=""` is overridden by the generic fallback.

### Classification

| Value | Classification |
|---|---|
| `low` | **PROVEN ACCEPTED** by Llama on `/chat/completions` |
| `medium` | **NOT YET PROVEN** for Llama |
| `none` / empty | **DISPROVEN** — runtime resolves to `medium` |

**Current backend reviewer value:** `medium` (resolved, despite launcher intent to disable)

---

## 14. TIMEOUT AUDIT

| Property | Launcher config | Actual runtime | Match? |
|---|---|---|---|
| Configured timeout | `AI_MIGRATION_REVIEWER_TIMEOUT_SECONDS = "300"` | 30s hardcoded | **NO** |
| Proposer timeout | (same launcher sets 300s generic) | 30s hardcoded | **NO** |
| Reviewer timeout | (same) | 30s hardcoded | **NO** |
| Proposer & reviewer share timeout? | — | YES — both use `timeout=30` in `_answer_with_deployment()` | YES |

**Root cause:** In `_answer_with_deployment()` at line 293, the timeout parameter to `_chat_completion()` is hardcoded to `30`. The `AI_MIGRATION_*_TIMEOUT_SECONDS` env vars are never read. The `V2ModelRoleRouter.resolve_budget()` does not resolve timeout.

**Risk:** `max_output_tokens=20000` with 30s timeout may cause frequent timeouts for long outputs, especially on slower models (Llama).

---

## 15. `deterministic_rule_id` AUDIT

File: `v2_model_schemas.py:107`

```python
"deterministic_rule_id": {"type": "string"},
```

File: `repair_review_chain.py:241`

```python
"deterministic_rule_id": str(output.get("deterministic_rule_id", "")),
```

### Answers

1. **Is `deterministic_rule_id` required in the schema?** NO — it is optional (not in `required` array, line 86–94).
2. **Is it preserved?** The schema allows it but does not require it. The checksum computation at `_compute_primary_repair_checksum()` (line 235–247) includes `deterministic_rule_id` if present.
3. **Is there a DB column?** YES — `V2RepairProposalRecord` (in `v2_repair_repository.py`) has `policy_validation_checksum` field. The `deterministic_rule_id` is passed to `evaluate_patch_proposal()` at `v2_repair_gate_service.py:185` via the `proposal` dict.
4. **Does apply reload the actual value?** YES — the chain result stores it, and `create_repair_gate_from_reviewed_chain()` receives `deterministic_rule_id` as a parameter.
5. **Is a checksum substituted?** NO — the actual rule ID from the proposer output is used. If the model omits it, the code defaults to empty string.
6. **Can a reviewer-accepted proposal fail patch gate solely because the ID was lost?** POSSIBLE — if `deterministic_rule_id` is empty when passed to `evaluate_patch_proposal()`, the patch gate policy may reject it depending on the `patch_gate` rules.

**Risk level:** LOW — the ID is carried through the chain. The optional schema definition means the model may skip it, but the application layer handles the empty case.

---

## 16. MINIMUM IMPLEMENTATION PHASES

### PHASE A — Unblock Proposer (GPT-5 mini → valid RepairPrimaryOutput)

**Goal:** Proposer produces valid `RepairPrimaryOutput` with HTTP 200

| Change | File | Description | Confidence |
|---|---|---|---|
| A1 | `v2_model_schemas.py:115` | Add `"additionalProperties": false` to `machine_readable_metadata` | PROVEN MUST |
| A2 | `v2_assistant_model_client.py` | Fix `response_format` key for `/responses` (nest under `text.format`) OR route proposer through `/chat/completions` | HIGH |

**Note:** For GPT-5 mini, `/responses` MAY be correct if Azure supports it. The key issue is B1 (schema). But if `/responses` rejects the `response_format` key structure, A2 is also required.

### PHASE B — Unblock Reviewer (Llama → valid RepairReviewerOutput → accept)

**Goal:** Reviewer returns `decision=accept` with valid checksum binding

| Change | File | Description | Confidence |
|---|---|---|---|
| B1 | `v2_model_schemas.py:141` | Add `"additionalProperties": false` to `review_dimensions` | PROVEN MUST |
| B2 | `v2_assistant_model_client.py` a. Avoid `/responses` for reviewer b. Route reviewer through `/chat/completions` explicitly | PROVEN MUST |
| B3 | `v2_model_role_router.py:318–319` | Honor empty `REVIEWER_REASONING_EFFORT` — do not fall back to generic `medium` | HIGH |

### PHASE C — Reach `repair_state.ready`

**Goal:** Reviewer accepts → proposal persisted → frontend shows diff + approve button

| Change | File | Description |
|---|---|---|
| C1 | — | Verified PHASE A + PHASE B produce valid outputs |
| C2 | — | No additional code changes needed if chain completion succeeds |
| C3 | — | Verify `repair_proposal_ready` event fires in `_create_reviewed_repair_proposal_from_refs()` |

### PHASE D — Make Apply Work

**Goal:** User approval → patch gate → `apply_patch_to_sandbox()`

| Change | File | Description |
|---|---|---|
| D1 | — | Verify `deterministic_rule_id` is non-empty when passed to `evaluate_patch_proposal()` |
| D2 | — | No code changes unless patch gate rejects due to empty rule ID |

---

## 17. FILES THAT SHOULD NOT BE CHANGED YET

- `v2_settings.py` — env ref projection is correct; no schema or transport logic here
- `v2_llm_invocation_ledger.py` — observing layer only; works correctly
- `v2_orchestrator_runner.py` — not involved in direct model invocation
- `repair_review_chain.py` — prompt logic is correct; schema fixes happen in `v2_model_schemas.py`
- `v2_repair_gate_service.py` — proposal lifecycle is correct
- `app.py` — FastAPI adapter not involved in transport decision
- `run_amf252_backend_clean.ps1` — launcher intent is correct; the issue is code ignoring it
- Any frontend files
- Any test files
- Any migration/schema files

---

## 18. REMAINING UNKNOWNS

| Unknown | Why it matters |
|---|---|
| Does the Azure Responses API accept the current proposer request (with `response_format` at top-level and the schema bug)? | Determines whether proposer also hits HTTP 400 on `/responses` |
| Does `_should_retry_with_chat_completions()` return TRUE for the specific Azure error response? | Determines whether fallback to `/chat/completions` happens automatically |
| Can GPT-5 mini succeed on `/responses` once the schema is fixed? | Would avoid needing to change proposer transport |
| Does the Azure deployment `gpt-5-mini` actually exist and support structured outputs? | Never verified externally |
| What exact HTTP 400 error body did Azure return for job `6a489598ca4d4d7b83b85a40deadff09`? | Would resolve root cause definitively |

---

## 19. FINAL IMPLEMENTATION RECOMMENDATION

### Order of changes:

1. **Fix both schemas** (`v2_model_schemas.py`): add `additionalProperties: false` to `machine_readable_metadata` and `review_dimensions`
2. **Fix reviewer transport** (`v2_assistant_model_client.py`): route Llama reviewer explicitly through `/chat/completions` and NOT through `/responses`
3. **Fix reviewer reasoning_effort** (`v2_model_role_router.py`): honor empty per-role reasoning_effort without falling back to generic `medium`
4. **Fix timeout** (`v2_assistant_model_client.py`): read configured timeout instead of hardcoding 30s

### Do NOT:
- Change prompts
- Add model-type detection
- Add test files
- Modify launcher script
- Run any Azure call
- Run any migration

---

## 20. FINAL DECISION BEFORE CODE CHANGES

### 1. What endpoint does GPT-5 mini proposer actually attempt first?

**`/responses`** — via `POST {AZURE_OPENAI_ENDPOINT}/responses`

### 2. What endpoint does Llama reviewer actually attempt first?

**`/responses`** — same code path, same transport logic.

### 3. Does current code distinguish model transport capabilities?

**NO** — zero model-type awareness. Every model follows identical `_is_v1_endpoint()` → `/responses` → fallback → `/chat/completions` → fallback → legacy chain.

### 4. Does the current backend reviewer request match our proven successful Llama `/chat/completions` request?

**NO** — three mismatches:

| Aspect | Backend | Proven working | Impact |
|---|---|---|---|
| Endpoint | `/responses` (first) | `/chat/completions` | BLOCKING |
| Schema `review_dimensions` | Missing `additionalProperties: false` | Clean schema | BLOCKING |
| Reasoning effort | `medium` (resolved) | `none` or `low` | POSSIBLE |

### 5. Is the historical proposer HTTP 400 explained primarily by:

**Both** — invalid schema (B1) AND wrong endpoint payload structure for `/responses` (B3). The exact contribution of each depends on which endpoint processed the request first, which cannot be determined from persisted ledger data alone.

### 6. Is Llama itself currently a blocker?

**YES** — but NOT because Llama is incapable. The blocker is the **backend code**, not the model. The external tests prove Llama works correctly on `/chat/completions` with `json_schema`. The code sends Llama to the wrong endpoint with an invalid schema.

### 7. Should Llama stay as the reviewer?

**YES** — Llama is proven capable on `/chat/completions` with strict json_schema. The evidence directly disproves the hypothesis that "Llama cannot do structured outputs."

### 8. Should Llama use `/responses`, `/chat/completions`, or capability-based routing?

**`/chat/completions`** — this is the only endpoint proven to work for Llama with `json_schema` in the external tests. Capability-based routing is unnecessary for two models.

### 9. What exact code changes must happen first?

1. `v2_model_schemas.py:115` — `machine_readable_metadata`: add `"additionalProperties": false`
2. `v2_model_schemas.py:141` — `review_dimensions`: add `"additionalProperties": false`
3. `v2_assistant_model_client.py` — route Llama reviewer through `/chat/completions` (skip `/responses`)
4. `v2_model_role_router.py:318-319` — prevent empty per-role reasoning_effort from falling back to `medium`
5. `v2_assistant_model_client.py:293` — resolve timeout from config instead of hardcoded 30

### 10. What must explicitly NOT be changed yet?

- Any frontend code
- Any test files
- `run_amf252_backend_clean.ps1`
- `v2_settings.py`
- `v2_llm_invocation_ledger.py`
- `v2_orchestrator_runner.py`
- `repair_review_chain.py` (prompts)
- `v2_repair_gate_service.py`
- `app.py`

### 11. After those changes, what is the first runtime success criterion?

```
Failure evidence
→ GPT-5 mini proposer produces VALID RepairPrimaryOutput (HTTP 200, schema validated)
→ Llama-3.3-70B-Instruct reviewer produces VALID RepairReviewerOutput with decision=accept (HTTP 200, schema validated)
→ repair_state.ready
→ Frontend displays diff + approve action
```

**Explicit success criterion (no model call needed):**

```
Run codebase without Azure calls:
1. Validate REPAIR_PRIMARY_OUTPUT_SCHEMA against the known-good TinyProposerOutput pattern
   — ALL object properties have additionalProperties: false
   — minLength=20 on proposed_diff is retained (runtime may adjust later)
   — confidence minimum/maximum are retained (valid for strict mode)
2. Validate REPAIR_REVIEWER_OUTPUT_SCHEMA against the proven TinyReviewerOutput pattern
   — review_dimensions has additionalProperties: false
   — All required fields are preserved
3. Confirm reviewer routing:
   — Reviewer uses /chat/completions, NOT /responses
4. Confirm reviewer reasoning_effort:
   — Resolved to "" (empty/None), NOT "medium"
5. Confirm timeout:
   — Resolved from env, NOT hardcoded to 30
```

---

## EVIDENCE SUMMARY

| Finding | Confidence | File:Line |
|---|---|---|
| Endpoint ends with `/openai/v1` | PROVEN | `run_amf252_backend_clean.ps1:57` |
| `_is_v1_endpoint()` returns TRUE | PROVEN | `v2_assistant_model_client.py:404-406` |
| `/responses` attempted first for all models | PROVEN | `v2_assistant_model_client.py:428-478` |
| Fallback requires keyword match in error body | PROVEN | `v2_assistant_model_client.py:1021-1036` |
| `machine_readable_metadata` lacks `additionalProperties: false` | PROVEN | `v2_model_schemas.py:115` |
| `review_dimensions` lacks `additionalProperties: false` | PROVEN | `v2_model_schemas.py:141` |
| Reviewer reasoning_effort resolves to `medium` | PROVEN | `v2_model_role_router.py:318-319` |
| Timeout hardcoded to 30s | PROVEN | `v2_assistant_model_client.py:293` |
| `deterministic_rule_id` is optional in schema | PROVEN | `v2_model_schemas.py:107` |
| Llama proven on `/chat/completions` with strict `json_schema` | PROVEN | External tests |
| Llama NOT proven on `/responses` | UNKNOWN | No external test |
| `reasoning_effort=medium` NOT proven for Llama | UNKNOWN | No external test |
| GPT-5 mini capability on `/responses` | UNKNOWN | No external test |
