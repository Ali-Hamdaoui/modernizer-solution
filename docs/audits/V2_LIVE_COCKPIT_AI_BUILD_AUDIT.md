# V2 Live Cockpit AI + Build + State Audit

| Field | Value |
|---|---|
| **Audit date** | 2025-07-17 |
| **Base branch** | `V2IMPROVMENT` |
| **Expected HEAD** | `e4336db85f449b5e3197269db7e5fbd07eb28a9f` |
| **Audit branch** | `v2/audit-live-cockpit-ai-build-state` |
| **Audit HEAD** | `e4336db85f449b5e3197269db7e5fbd07eb28a9f` |
| **Repository** | `modernizer-solution` |
| **Git status** | Clean — zero staged, zero dirty files |
| **`next-env.d.ts` staged** | No |

---

## Files inspected

### Documents
- `AGENTS.md`
- `V2_IMPLEMENTATION_SUBAGENT_PLAN.md`
- `improvmentV2.md`
- `docs/system/03-orchestrator-flow.md`
- `docs/system/09-how-to-run.md`
- `OPERATOR_RUNBOOK.md`

### Backend — FastAPI routing & projection
- `migration_factory/control_tower/adapters/fastapi/app.py`
  - Lines 3256–3305: `_PIPELINE_PHASES`, `_RAW_EVENT_TYPES`, `_IMPORTANT_EVENT_TYPES`
  - Lines 3307–3346: `_v2_pipeline_projection()` — builds pipeline rows, evidence, raw logs
  - Lines 3349–3375: `_pipeline_row_status()` — per-row status for human_approval and other phases
  - Lines 3378–3424: `_v2_failure_summary()` — failure/repair/artifacts from events
  - Lines 3468–3520: `_v2_stages_from_job()` — stage timeline with chain_status
  - Lines 3523–3534: `_stage_status_from_event()` — maps event to "pending\|queued\|running\|blocked\|completed\|failed"
  - Lines 1059–1107: `approve_decision_card()` — approval handler, emits `approval_resume_queued`
  - Lines 1201–1276: `ask_v2_assistant()` — assistant ask endpoint with model client
  - Lines 3151–3220: `_build_v2_assistant_prompt()` — prompt builder

### Backend — Application services
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
  - Full file: `_chat_completion_v1()`, `_chat_completion_legacy()`, `answer()`, `_fallback_result()`
- `migration_factory/control_tower/application/v2_azure_health_service.py`
  - Full file: `run_health_check()` — env-only check, no live call
- `migration_factory/control_tower/application/v2_settings.py`
- `migration_factory/control_tower/application/v2_setup_service.py`
  - Lines 173–216: `run_preflight()` — excludes `azure_model_ready` from `all_ready`
  - Lines 343–350+: `_compute_readiness()` — deterministic checks
- `migration_factory/control_tower/application/v2_worker_stage.py`
  - Full file: `build_stage1_manifest()` — builds Stage 1 argv/env
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
  - Lines 344–438: `_handle_exit()` — stage lifecycle, approval detection, failure emission
  - Lines 481–525: `_emit_diagnostic_failure_events()` — build_failed/transform_failed
- `migration_factory/control_tower/application/v2_stage_progression.py`
- `migration_factory/control_tower/application/v2_approval_mapping.py`

### Backend — Infrastructure
- `migration_factory/control_tower/infrastructure/sqlite/v2_event_repository.py`
- `migration_factory/control_tower/infrastructure/sqlite/v2_approval_repository.py`
- `migration_factory/control_tower/infrastructure/sqlite/v2_command_repository.py`
- `migration_factory/control_tower/infrastructure/sqlite/v2_job_repository.py`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0034_v2_job_events.sql`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0035_v2_approval_job_id.sql`

### Backend — Orchestrator (legacy terminal path)
- `migration_factory/orchestrator/runner.py`
- `migration_factory/orchestrator/resume.py`
- `migration_factory/orchestrator/graph.py`
- `migration_factory/orchestrator/approval.py`
- `migration_factory/orchestrator/events.py`
- `migration_factory/orchestrator/phase_services.py`
- `migration_factory/transform_v1_after_approval.py`

### Backend — Build agent & contracts
- `migration_factory/agents/build_agent/agent.py`
- `migration_factory/agents/build_agent/classifier.py`
- `migration_factory/contracts/build/schemas.py`

### AI Hub profiles & catalogs
- `modernizer-solution-ai-hub/profiles/springboot-2.1.6-to-2.7-java11.yaml`
- `modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml`
- `modernizer-solution-ai-hub/profiles/springboot-3.5-java17-to-java21.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-2.1.6-to-2.7-java11.yaml`

### Frontend
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
  - Full file: initial load, SSE connection, `appendEventFromSse()`, `refreshLiveState()`, `applyEventToStages()`, `IMPORTANT_SSE_TYPES`
- `web/control-tower/app/migrations/new/NewMigrationForm.tsx`
  - Lines 30–70: API base, `PreflightResponse`, `V2ReadinessResponse`
  - Lines 460–561: Preflight display, Start Migration button gating
- `web/control-tower/lib/controlTowerApi.ts`
  - Full file: all API methods including V2 endpoints
- `web/control-tower/lib/contracts.ts`
  - All V2 types including `V2FailureSummaryResponse`, `V2AssistantAskResponse`, `V2PipelineResponse`

---

## Runtime Flow Map

```
Browser UI                    FastAPI (app.py)              SQLite              Orchestrator Runner
  │                              │                           │                     │
  │── GET /v1/settings ─────────→│── build_settings_projection() ──→ reads env      │
  │←── {azure.endpoint.configured: true}                    │                     │
  │                              │                           │                     │
  │── POST /v1/migration-setups ─→│── V2SetupService ────────→ saves setup record  │
  │                              │                           │                     │
  │── POST /v1/migration-setups/preflight ──→ V2SetupService._compute_readiness()  │
  │←── {all_ready: true} (azure_model_ready excluded)        │                     │
  │                              │                           │                     │
  │── POST /v1/v2/migration-jobs/start-stage1 ──→ V2WorkerStageService ──→ save manifest
  │                              │── V2OrchestratorRunner.start() ─────────→ launch subprocess
  │                              │                           │                     │
  │── SSE /v1/v2/migration-jobs/{id}/events ◄─── poll DB ────────── stdin/events  │
  │                              │                           │                     │
  │── ...important event triggers refreshLiveState()          │                    │
  │    → GET /v1/v2/*/approvals                               │                    │
  │    → GET /v1/v2/*/stages                                  │                    │
  │    → GET /v1/v2/*/events/snapshot                         │                    │
  │    → GET /v1/v2/*/pipeline                                │                    │
  │    → GET /v1/v2/*/failure-summary                         │                    │
  │                              │                           │                     │
  │── POST /v1/v2/jobs/{id}/assistant/ask ──→ V2AssistantModelClient.answer()
  │←── fallback when HTTP 400 (no response body captured)    │                    │
```

---

## Findings

### P0-1 — Real LLM smoke readiness must block migration start

**Severity**: P0 — Users see "Azure configured" but model invocation fails silently.

#### Root cause A — `V2AzureHealthService.run_health_check()` is env-only

**File**: `v2_azure_health_service.py`, lines 77–174  
**File**: `v2_setup_service.py`, lines 182–184

```python
# v2_setup_service.py, line 182-184 (full excerpt):
all_ready = all(
    v for k, v in readiness.items()
    if k not in ("azure_model_ready",)  # <── explicitly excluded!
)
```

The `azure_model_ready` key is read from env var configuration but is **intentionally excluded** from `all_ready`. Per `improvmentV2.md` section 6: "Azure health does not block deterministic migration start." This was a design choice that contradicts the new P0-1 requirement.

In `v2_azure_health_service.py` line 100:
```python
# Simulated check — real check would call Azure
status = "ready"
```

No live API call is ever made. The health endpoint returns `{"overall_status": "ready"}` without ever touching the Azure endpoint.

#### Root cause B — HTTP 400 response body not captured

**File**: `v2_assistant_model_client.py`, lines 40–63

```python
except urllib.error.HTTPError as exc:
    code = getattr(exc, "code", 0)
    if code == 401:
        return _fallback_result(fallback, "Azure OpenAI authentication failed (HTTP 401).", "http_401")
    if code == 404:
        return _fallback_result(fallback, "Azure OpenAI deployment or endpoint not found (HTTP 404).", "http_404")
    return _fallback_result(
        fallback,
        f"Azure OpenAI request failed (HTTP {code}).",   # <── no response body!
        f"http_{code}",
    )
```

`exc.read()` is never called. The HTTP 400 response body from Azure OpenAI contains critical diagnostic info: `{"error": {"code": "DeploymentNotFound", "message": "..."}}` or content filter trigger details. Without this body, the root cause of HTTP 400 is opaque.

#### Root cause C — v1 endpoint URL construction

**File**: `v2_assistant_model_client.py`, lines 88–89

When `endpoint` ends with `/openai/v1`, the v1 path is:
```python
url = f"{endpoint}/chat/completions"
# Result: https://{resource}.openai.azure.com/openai/v1/chat/completions
```

This is correct for Azure OpenAI v1 API format. The request body (lines 90–103) sends `model`, `messages`, `temperature`, `max_tokens` — all valid v1 parameters. However, the user's specific Azure deployment may not have the expected model mapping or content filter policy causing HTTP 400.

#### Required API contract (new)

```
POST /v1/v2/settings/ai/smoke
→ {ready, provider, endpoint_mode, deployment_configured,
   request_shape, failure_reason, safe_error, last_checked_at}
```

Start Migration must gate on `ai_model_smoke_ready: true`.

---

### P0-2 — Assistant must be model-backed, not static fallback

**Severity**: P0 — Users get deterministic fallback responses without knowing model failed.

#### Root cause — Fallback is always returned on failure, indistinguishable from success

**File**: `v2_assistant_model_client.py`, lines 29–77

The `answer()` method calls `_chat_completion()` and on any HTTPError returns a `_fallback_result()`. The fallback (line 165–175) includes `content` = the deterministic answer prepended with "Model: fallback\nSource: deterministic\nReason: ...".

The `ask_v2_assistant` route (app.py lines 1226–1234) passes the fallback string to both the model client:
```python
model_result = app.state.v2_assistant_model_client.answer(
    prompt=..., fallback=fallback_answer
)
```

When the model fails, the fallback answer content is returned with `model_status="fallback"`, `source="deterministic"`, `success=False`. The frontend (MigrationCockpit.tsx line 392) shows the model status: `Model: {data.assistantModel?.status ?? "unavailable"}`. When the model is created from the API response, it will show `fallback`, but only after the user explicitly asks.

**Current guardrails are correct** (app.py lines 1268–1275):
- `read_only`, `cannot_execute`, `cannot_approve`, `cannot_write_files`, `cannot_change_route_or_stage`, `cannot_override_proof` — all true.

But there is no system-level enforcement besides convention. The system prompt (client.py lines 95–98) says "Never approve, execute, write files..." but there is no output schema validation or guardrail enforcement layer.

#### Required fix

- When model is unreachable/errors and AI is required (not `skip_endpoint_smoke`), return explicit error instead of fallback
- Add output schema validation for `AssistantAnswer` schema
- All guardrails must be enforced at the API response boundary, not just in the model prompt

---

### P0-3 — Contradictory Stage/Pipeline status model

**Severity**: P0 — Stage 1 stays BLOCKED after approval + transform start/failure.

#### Root cause A — `_stage_status_from_event()` doesn't recognize post-approval events

**File**: `app.py`, lines 3523–3534

```python
def _stage_status_from_event(event_type: str, event_status: str) -> str:
    if event_type == "stage_failed" or event_status == "failed":
        return "failed"
    if event_type in {"approval_required", "stage_blocked_for_approval"} or event_status == "blocked":
        return "blocked"
    if event_type == "stage_completed":
        return "completed"
    if event_type in {"stage_started", "command_started", "stdout", "stderr"} or event_status == "running":
        return "running"
    if event_type in {"stage_queued", "next_stage_queued"} or event_status == "queued":
        return "queued"
    return "pending"     # <── everything else maps to pending!
```

Events that occur **after** approval:
| Event | Type | Status | Mapped by `_stage_status_from_event` | Precedence |
|---|---|---|---|---|
| `approval_resume_queued` | "approval_resume_queued" | "queued" | `"queued"` (status=="queued") | 1 |
| `resume_started` | "resume_started" | "started" | `"pending"` (fallthrough) | 0 |
| `approval_completed` | "approval_completed" | "completed" | `"pending"` (fallthrough) | 0 |
| `sandbox_transform_started` | "sandbox_transform_started" | "started" | `"pending"` (fallthrough) | 0 |
| `transform_failed` | "transform_failed" | "failed" | `"failed"` (status=="failed") | 5 |

None of these are recognized as meaningful stage transitions except `transform_failed`.

#### Root cause B — Precedence comparator is temporal-wrong

**File**: `app.py`, line 3505

```python
precedence = {"pending": 0, "queued": 1, "running": 2, "blocked": 3, "completed": 4, "failed": 5}
...
if precedence.get(mapped, 0) >= precedence.get(status_by_stage.get(event.stage, "pending"), 0):
    status_by_stage[event.stage] = mapped
```

`>=` means "only overwrite if same or **higher** precedence". Since `blocked` (3) has higher precedence than `queued` (1) or `running` (2), neither can overwrite it. Even `approval_resume_queued` (queued, prec 1) cannot lift the blocked state. The only events that can overwrite blocked are `stage_failed` (5) or `stage_completed` (4).

**Worse**: Because `sandbox_transform_started` maps to `pending` (prec 0) and the orchestrator emits it AFTER approval, the stage sees a `pending` event after `blocked`. The `>=` comparison: `0 >= 3` → `False`. So blocked stays.

#### Root cause C — BUILD_FAILED_IN_SANDBOX doesn't emit `stage_failed`

**File**: `v2_orchestrator_runner.py`, lines 403–407

```python
if final_status in ("FALLBACK_REPAIR_PLAN", "BUILD_FAILED_IN_SANDBOX", "TEST_FAILED"):
    self._emit_diagnostic_failure_events(job_id=job_id, stage_index=stage_index, command_id=command_id, result=result or {})
    # Don't proceed to completion if stage is clearly in failure state
    if final_status == "BUILD_FAILED_IN_SANDBOX" or ...:
        return   # <── returns WITHOUT emitting stage_failed!
```

`_emit_diagnostic_failure_events` emits `build_failed` and `transform_failed` (both with status "failed"), but not `stage_failed`. The stage timeline uses `stage_failed` to mark a stage as FAILED. Even though `transform_failed` → `_stage_status_from_event` → "failed" (prec 5), the `stage_completed` is never emitted so the stage remains in its prior state.

#### `_pipeline_row_status` correctness (separate computation)

**File**: `app.py`, lines 3349–3375

The `human_approval` pipeline row (lines 3356–3367) uses a **different** computation that correctly maps `approval_completed`, `approval_resume_queued`, `resume_started`, `sandbox_transform_started` → `pass`. This is why the Pipeline Status shows PASS while the Stage Timeline shows BLOCKED — they use different status algorithms!

#### Required fix

1. Add `approval_completed`, `sandbox_transform_started`, `resume_started` to `_stage_status_from_event` → `"running"`
2. Change the scanner (line 3505) from `>=` to `>` for the precedence check, OR use temporal ordering (latest event wins) with a special case that `failed` always wins
3. In `_handle_exit`, emit `stage_failed` for `BUILD_FAILED_IN_SANDBOX` cases
4. Align `_stage_status_from_event` with the event types used in `_pipeline_row_status`

---

### P0-4 — Diagnose why build failed although terminal migration used to work

**Severity**: P0 — Users see "Build failed" without actionable dependency information.

#### Root cause — V2 cockpit command manifest vs terminal command

**File**: `v2_worker_stage.py`, lines 80–90

V2 Stage 1 argv:
```python
argv = (
    sys.executable,
    "-m", "migration_factory.orchestrator.runner",
    "--run-id", effective_run_id,
    "--legacy", setup.legacy_app_path,
    "--modernized", setup.output_parent_path,
    "--ai-hub", setup.ai_hub_path,
    "--profile", "springboot-2.1.6-to-2.7-java11",
    "--mode", "full_sandbox_migration",
)
```

**Environment** (line 100–107):
```python
"JAVA_HOME": jdk_home,
"JAVA11_HOME": setup.java11_home,
"JAVA17_HOME": setup.java17_home,
"JAVA21_HOME": setup.java21_home,
"MAVEN_CMD": setup.maven_cmd,
"PATH_PREPEND": f"{jdk_home}/bin",
```

This matches the expected terminal command shape from `docs/system/09-how-to-run.md`. The `JAVA11_HOME` env var is set to the user-provided value from setup.

The issue is that `BuildErrorContract` (schemas.py lines 14–46) contains all fields needed for diagnosis: `matched_line`, `stdout_tail`, `stderr_tail`, `java_home`, `java_home_env`, `MAVEN_CMD`, `PATH_excerpt`, `platform`. But the V2 failure summary endpoint (`_v2_failure_summary` at app.py lines 3378–3424) only exposes event messages and a limited set of payload fields (build_status, test_status, final_status, etc.) — it does NOT include `matched_line`, `stderr_tail`, or dependency coordinates.

**Build error contract file path**: The `write_build_error` function (schemas.py lines 62–71) writes to a JSON file, but the V2 cockpit has no endpoint to read and present it. The failed build must be located in the run directory within `.migration/runs/{run_id}/`.

**Locked manifest env** (`V2OrchestratorRunner._build_env()`, lines 633–655): copies safe system env + manifest env + copilot env. This is correct and matches terminal behavior.

#### Required fix

Add a new endpoint:
```
GET /v1/v2/migration-jobs/{job_id}/build-failure
```

Or enrich `/failure-summary` to include:
- `matched_line` from the build error contract
- `dependency_coordinates` (extracted from matched_line)
- `command`, `cwd`, `java_home`, `MAVEN_CMD`
- `log_tail` (sanitized, without full local paths)
- `stderr_tail` (sanitized)

Do NOT expose raw secrets or full credential paths. Use `basename` or `.migration`-relative paths.

---

### P0-5 — Reduce frontend over-polling and use SSE correctly

**Severity**: P0 — Backend logs show repeated GETs during active SSE connection.

#### Findings — No timer-based polling

**File**: `MigrationCockpit.tsx`

The component does NOT use `setInterval` or `setTimeout` for periodic polling. The pattern is:

1. **Initial load** (line 54–96): One-shot `useEffect` that fires all fetches on mount. Cleanup via `cancelled` flag.
2. **SSE connection** (line 98–153): Single `EventSource` opened once per `normalizedJobId`. Cleanup calls `source?.close()`.
3. **Event-driven refresh** (line 155–179): `appendEventFromSse` calls `refreshLiveState()` for every event in `IMPORTANT_SSE_TYPES`.

**The over-polling**: `refreshLiveState()` (lines 207–225) fires **5 parallel GET requests** on every important SSE event:
```typescript
const [approvalsResponse, stagesResponse, eventsResponse, pipelineResponse, failureSummary] = await Promise.all([
    getV2JobApprovals(safeJobId),
    getV2MigrationJobStages(safeJobId),
    getV2JobEventSnapshot(safeJobId),
    getV2JobPipeline(safeJobId),
    getV2FailureSummary(safeJobId).catch(() => null),
]);
```

If multiple important events arrive in quick succession (e.g., `approval_completed` + `sandbox_transform_started` + `stage_started`), each triggers 5 parallel requests. There is no debouncing.

Additionally, **`getV2AssistantMessages` is NOT called in `refreshLiveState`**, so there's no polling loop for assistant messages — they only load on initial mount and after explicit `askV2Assistant` calls.

#### Required fix

1. Debounce `refreshLiveState` with a ~300ms debounce window
2. Skip `getV2JobEventSnapshot` in refresh since SSE already delivers events
3. Skip `getV2FailureSummary` unless a failure event arrives
4. Add guard to avoid `refreshLiveState` if component is unmounted

---

### P1-1 — Make Evidence useful, not noisy

**Severity**: P1 — Evidence panel shows all events in flat list.

#### Findings

**Current**: `_v2_pipeline_projection` builds `evidence` as the last 100 important events and `raw_logs` as the last 200 stdout/stderr events. Both are displayed as flat lists.

**Frontend**: MigrationCockpit.tsx lines 295–321: Evidence is shown as a flat list of all important events. Raw logs are inside a `<details>` element (collapsible), which is good.

**Missing**:
- No grouping by phase (analysis, planning, etc.)
- No collapse-by-default for raw stdout/stderr (already done but raw_logs section needs clearer labeling)
- No artifact count deduplication by relative path/artifact kind
- No "show only failures" filter

#### Required fix

1. Group evidence events by phase using `_event_phase_key`
2. Default view shows only phase transitions and failures
3. Raw logs stay collapsed
4. Artifact counts deduplicate by relative path
5. Filter for "show only failures"

---

### P1-2 — Approval UX must be impossible to misunderstand

**Severity**: P1 — Approval card and pipeline row can show contradictory states.

#### Findings

**Current state**: The approval card (MigrationCockpit.tsx lines 328–346) shows:
- Stage index, status badge (PASS/BLOCKED)
- Summary, checksum, approve/reject buttons
- Disabled when status !== "pending" or operation in progress

But because `_stage_status_from_event` doesn't recognize `approval_completed`, the **Stage Timeline** can show BLOCKED while the **Pipeline Status** shows PASS for Human Approval. This is the P0-3 status contradiction.

The note "LLM cannot approve; exact checksum required." (line 348) is present. But there's no warning about stale duplicate approve.

#### Required fix

1. Fix P0-3 to ensure Stage Timeline status aligns with Pipeline Status
2. After approval, the card should show "Approved by operator" with disabled buttons
3. On reload (stale card), re-fetch approvals state: show current status, not cached
4. Duplicate approve should be idempotent or return "already approved"
5. Add explicit "LLM cannot approve; human checksum approval required." warning on the card, not just in metadata

---

### P1-3 — Model output must stay advisory (not become proof)

**Severity**: P1 — Architecture is correct but has no enforcement layer.

#### Findings

The architecture correctly segregates:
- **Model output**: advisory only — used in `AssistantAnswer` response
- **Deterministic truth**: Command exit codes, Maven reports, build error contracts, checksums, ledger

Current code paths:
- `ask_v2_assistant` → model client → assistant message (read-only, no side effects)
- `draft_assistant_action` → validates against `ActionRequest` schema (draft only, no execution)
- Stage status, proof level, failure summary are all computed from events (deterministic)
- Approval requires exact checksum, enforced by `V2ApprovalMappingService.approve()`

**Gaps**:
1. The model output `AssistantAnswer` has no schema validation on the response
2. No system-level enforcement of "model cannot set stage status" — it's convention only
3. The `_build_v2_assistant_prompt` instructs the model to not override proof, but there's no output validator

#### Required fix

1. Add output schema validation for `AssistantAnswer` at the API response boundary
2. Add explicit test: "assistant answer cannot alter stage status, proof level, approval, failure, or command state"

---

### P2 — Lower-priority findings

#### P2-1 — `asyncio.run()` in sync FastAPI handlers

**File**: `app.py`, lines 1105 and 988

```python
asyncio.run(app.state.public_event_notifier.notify())
```

Inside sync `def` routes. This can crash on an already-running event loop. Should use `asyncio.get_event_loop().run_until_complete()` in sync context or convert routes to `async def`.

#### P2-2 — Duplicate OpenAPI operation IDs

```python
Duplicate Operation ID health_live_v1_health_live_get for function health_live
Duplicate Operation ID health_ready_v1_health_ready_get for function health_ready
```

FastAPI routes define duplicate operation IDs. Fix by adding unique operation IDs or renaming functions.

#### P2-3 — Stage chain checker timeout

The `V2StageProgressionService.get_stage_progression()` contains `_check_chain()` with `asyncio.wait_for(stop_future.wait(), timeout=timeout)` — appears to assume an async context but is used in sync context.

---

## Root cause hypotheses

### HTTP 400 on model invocation

1. **Deployment mapping mismatch**: The `AZURE_OPENAI_ASSISTANT_DEPLOYMENT` environment variable points to a deployment name that doesn't exist in the Azure OpenAI resource for the given endpoint. The v1 endpoint `{endpoint}/chat/completions` with `model: deployment` works only if the deployment model name exactly matches the deployment name.

2. **Content filter rejection**: The request payload's `system` message about "read-only migration cockpit assistant" may trigger Azure content filter rules. The prompt content may be rejected if it contains "migration", "Never approve", etc. patterns that the content filter interprets as restricted.

3. **API version mismatch**: The v1 endpoint format `{endpoint}/chat/completions` doesn't specify an `api-version` parameter. Azure OpenAI v1 API has a default version that may be older than the resource. The legacy path `{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21` explicitly sends a version. If the env ends with `openai/v1`, no version is sent.

**Without capturing the response body (P0-1 root cause B), we cannot determine which of these is the actual cause.**

### Build dependency failure

1. **OpenRewrite plugin version mismatch**: The catalog at `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-2.1.6-to-2.7-java11.yaml` references specific OpenRewrite plugin versions. If the sandbox workspace's `pom.xml` has a different OpenRewrite plugin version or the active recipe is not available in the catalog, OpenRewrite apply fails with `dependency_error`.

2. **Missing repository / parent POM**: The legacy application may require internal Maven repositories or parent POMs to resolve dependencies. The sandbox does not have network access or the required repository configuration.

3. **Java/Maven version mismatch**: The runner sets `JAVA11_HOME` from setup, but `JAVA_HOME` is also set to the same JDK. If the system `java` is different or the `MAVEN_CMD` path points to a different Maven installation, dependency resolution can fail.

---

## Tests to add

### Backend — P0-1: AI smoke readiness

| Test | File | What it covers |
|------|------|----------------|
| `test_ai_smoke_missing_endpoint_blocks_start` | `test_v2_setup_service.py` | Preflight reports `ai_model_smoke_ready=false` when endpoint empty |
| `test_ai_smoke_http_400_blocks_start` | `test_v2_assistant_model_backing.py` | Model smoke returns `ready: false, failure_reason: "http_400"` and response body is captured |
| `test_ai_smoke_success_enables_start` | `test_v2_assistant_model_backing.py` | Working model call returns `ready: true` |
| `test_ai_smoke_endpoint_contract` | `test_v2_assistant_model_backing.py` | `POST /v1/v2/settings/ai/smoke` returns all required fields |

### Frontend — P0-1: AI smoke gating

| Test | File | What it covers |
|------|------|----------------|
| `ai_model_smoke_ready_false_disables_start` | `newMigrationForm.test.tsx` | Start button disabled when `ai_model_smoke_ready=false` |
| `ai_model_smoke_http_400_shows_reason` | `newMigrationForm.test.tsx` | HTTP 400 blocks migration and shows failure reason |
| `ai_model_smoke_ready_enables_start` | `newMigrationForm.test.tsx` | Start enabled only when `ai_model_smoke_ready=true` |

### Backend — P0-2: Model-backed assistant

| Test | File | What it covers |
|------|------|----------------|
| `test_assistant_model_call_persists_source_metadata` | `test_v2_assistant_model_backing.py` | Successful model call returns `source: "azure_openai"`, `model_status: "live_ok"` |
| `test_assistant_model_failure_returns_safe_error` | `test_v2_assistant_model_backing.py` | Failed model call does NOT include `success: true` or fake content |
| `test_assistant_refuses_approve_execute_write` | `test_v2_assistant_model_backing.py` | Adversarial prompt asking to approve/execute/write is refused |

### Backend — P0-3: Stage status consistency

| Test | File | What it covers |
|------|------|----------------|
| `test_stage_status_pending_approval_blocked` | `test_v2_cockpit_events.py` | Stage 1 BLOCKED when approval card pending |
| `test_stage_status_approved_transform_started_running` | `test_v2_cockpit_events.py` | After approve + transform, Stage 1 RUNNING, Human Approval PASS |
| `test_stage_status_transform_failed` | `test_v2_cockpit_events.py` | Transform failure → Stage 1 FAILED, Transform Agent FAILED |
| `test_stage_status_stage_completed` | `test_v2_cockpit_events.py` | Stage completed → Stage 1 COMPLETED |
| `test_stage_status_old_blocked_does_not_override_later_terminal` | `test_v2_cockpit_events.py` | Old BLOCKED event never overrides later terminal/running |

### Backend — P0-4: Build failure diagnosis

| Test | File | What it covers |
|------|------|----------------|
| `test_failure_summary_includes_matched_line` | `test_v2_cockpit_events.py` | `dependency_error` failure summary includes `matched_line` |
| `test_failure_summary_no_raw_secrets` | `test_v2_cockpit_events.py` | No raw keys or full credential paths in failure payload |
| `test_build_failure_actionable_ui` | `test_v2_cockpit_events.py` | UI exposes dependency coordinates, not just "Build failed" |

### Backend — P0-5: SSE clean polling

| Test | File | What it covers |
|------|------|----------------|
| `test_event_source_opened_once_per_job` | Frontend cockpit test | EventSource opened once per `normalizedJobId` |
| `test_important_sse_event_triggers_one_debounced_refresh` | Frontend cockpit test | Important SSE triggers debounced, not multiple parallel |
| `test_no_polling_loop_without_new_events` | Frontend cockpit test | No `setInterval` or timer calling all endpoints |
| `test_sse_cleanup_on_unmount` | Frontend cockpit test | EventSource closed on component unmount/job change |

### Backend — P1-3: Model advisory only

| Test | File | What it covers |
|------|------|----------------|
| `test_assistant_cannot_alter_stage_status` | `test_v2_assistant_model_backing.py` | Assistant answer cannot change stage status, proof, approval, or command state |

### Existing test results

| Suite | Status | Count |
|-------|--------|-------|
| Backend V2 tests | ✅ ALL PASS | 95 tests |
| Frontend tests | ✅ ALL PASS | 142 tests (11 files) |
| Frontend typecheck | ✅ PASS | `tsc --noEmit` |
| Frontend build | ✅ PASS | Next.js production build |

---

## Manual UAT checklist

### Before migration start
- [ ] `GET /v1/v2/settings/ai/smoke` returns `ready: false` when `AZURE_OPENAI_ENDPOINT` is empty
- [ ] `GET /v1/v2/settings/ai/smoke` returns `ready: false` when `AZURE_OPENAI_API_KEY` is empty
- [ ] `GET /v1/v2/settings/ai/smoke` returns `ready: false` when `AZURE_OPENAI_ASSISTANT_DEPLOYMENT` is empty
- [ ] Start Migration button is disabled when `ai_model_smoke_ready=false`
- [ ] Start Migration button is enabled when `ai_model_smoke_ready=true`
- [ ] HTTP 400 smoke shows actionable failure reason (deployment mapping, content filter, etc.)
- [ ] Response body from HTTP 400 is captured and redacted into `safe_error`

### Assistant UX
- [ ] Successful model call returns `source: "azure_openai"`, `model_status: "live_ok"`
- [ ] Failed model call returns `success: false` with `failure_reason`
- [ ] Fallback content is NOT returned as if it were successful model output
- [ ] Adversarial "execute this command" is refused
- [ ] Adversarial "approve the card" is refused
- [ ] Assistant cannot write files, change stage, or override proof

### Stage/pipeline timeline
- [ ] Pending approval → Stage 1 BLOCKED, Human Approval BLOCKED
- [ ] After approve + transform started → Stage 1 RUNNING, Human Approval PASS
- [ ] Transform failed → Stage 1 FAILED, Transform Agent FAILED
- [ ] Stage completed → Stage 1 COMPLETED
- [ ] Old BLOCKED event never overrides later terminal/running events
- [ ] Pipeline row `human_approval` PASS when approval completed
- [ ] Stage timeline ALWAYS matches pipeline status (no contradictions)

### Build failure
- [ ] Failure summary includes `matched_line` for `dependency_error`
- [ ] Error UI shows actionable dependency coordinates
- [ ] No raw full local paths in the UI (basename or .migration-relative only)
- [ ] Build error contract JSON exists in run directory

### SSE / refresh
- [ ] EventSource opened once per job
- [ ] Multiple rapid important events do NOT trigger parallel refresh floods
- [ ] No `setInterval` polling visible in DevTools Network tab
- [ ] Cleanup closes EventSource on unmount

### Azure secret exposure
- [ ] No `AZURE_OPENAI_API_KEY` in any frontend response
- [ ] No `AZURE_OPENAI_ENDPOINT` in frontend (env ref only)
- [ ] No `AZURE_OPENAI_ASSISTANT_DEPLOYMENT` in frontend

### Evidence panel
- [ ] Raw logs collapsed by default
- [ ] Artifact counts deduplicated by relative path
- [ ] Failure events visible without opening raw logs

### Approval card
- [ ] Pending card shows enabled Approve/Reject buttons
- [ ] Approved card shows disabled buttons with "Approved" badge
- [ ] Duplicate approve returns "already approved" or idempotent
- [ ] LLM cannot approve warning displayed on card

---

## Security boundary check

| Item | Status |
|------|--------|
| `NEXT_PUBLIC_` in frontend | ✅ Only `CONTROL_TOWER_API_BASE_URL` and `API_BASE_URL` (no secrets) |
| Azure keys exposed to frontend? | ✅ No — backend-only via env vars |
| Azure deployment names exposed? | ✅ No — backend-only via env vars |
| Full local paths in frontend? | ⚠️ Setup response contains paths (redacted by `redact_absolute_paths`) |
| `next-env.d.ts` staged? | ✅ No |
| .env committed? | ✅ No — clean status |
| Build error contract has secret paths? | ⚠️ `project_path`, `cwd`, `java_home` contain local paths — redact when exposing via API |

---

## FIX PLAN

### P0-1: Real LLM smoke button

**Files to change**:
1. `v2_assistant_model_client.py` — Add `smoke()` method that calls a minimal chat completion with a short prompt, captures HTTP response body
2. `v2_azure_health_service.py` — Add live API call option to `run_health_check` (or create separate `V2AiSmokeService`)
3. `app.py` — Add `POST /v1/v2/settings/ai/smoke` endpoint
4. `v2_setup_service.py` — Include `ai_model_smoke_ready` in preflight checks (no longer excluded)
5. `MigrationCockpit.tsx` — Gate Start Migration on `ai_model_smoke_ready`
6. `NewMigrationForm.tsx` — Display AI smoke status, disable start when not ready
7. `contracts.ts` — Add `V2AiSmokeResponse` type
8. `controlTowerApi.ts` — Add `getAiSmoke()` method

### P0-2: Model-backed assistant (no fake success)

**Files to change**:
1. `v2_assistant_model_client.py` — When `skip_endpoint_smoke=false` and model fails, return `V2AssistantModelResult(success=False, content="")` with `failure_reason` instead of fallback content
2. `app.py` — In `ask_v2_assistant`, when `model_result.success==False` and AI is required, return error response instead of fallback
3. Add `AssistantAnswer` schema validation at API boundary

### P0-3: Fix stage/pipeline status model

**Files to change**:
1. `app.py` — `_stage_status_from_event`: Add `approval_completed`, `sandbox_transform_started`, `resume_started`, `transform_failed`, `build_failed` to mapped statuses
2. `app.py` — Line 3505 precedence scanner: Change to temporal ordering (latest event wins); failed always wins; approval-completed + transform-started overrides blocked
3. `v2_orchestrator_runner.py` — `_handle_exit`: Emit `stage_failed` for `BUILD_FAILED_IN_SANDBOX` before returning

### P0-4: Build failure diagnosis

**Files to change**:
1. `app.py` — Add `GET /v1/v2/migration-jobs/{job_id}/build-failure` or enrich `/failure-summary` with `matched_line`, `dependency_coordinates`, `command`, `java_home`, `MAVEN_CMD`, sanitized `log_tail`
2. `v2_orchestrator_runner.py` — Pass build error contract content into failure event payload
3. `MigrationCockpit.tsx` — Add "Build Failure Details" section showing actionable error

### P0-5: Reduce over-polling

**Files to change**:
1. `MigrationCockpit.tsx` — Debounce `refreshLiveState` with ~300ms; skip snapshot fetch when SSE delivers events; skip failure-summary unless failure event; add mounted guard

### P1-1: Evidence grouping

**Files to change**:
1. `app.py` — Return evidence grouped by phase
2. `MigrationCockpit.tsx` — Render grouped evidence with collapsible phase sections

### P1-2: Approval UX clarity

**Files to change**:
1. `MigrationCockpit.tsx` — Add "LLM cannot approve" warning to card, disable buttons after approval, handle stale duplicate approve

### P1-3: Model advisory enforcement

**Files to change**:
1. `v2_assistant_model_client.py` — Add output schema validation for `AssistantAnswer` schema
2. `app.py` — Validate model output against schema before returning
3. `contracts.py` — Define `AssistantAnswer` schema with allowed fields

### P2-1: asyncio.run() fix

**File**: `app.py` — Convert sync routes to `async def` or use `run_until_complete`

---

## Risks

1. **P0-1 gating breaks existing behavior**: Blocking migration on AI smoke is a new requirement. Existing operators with working terminal pipelines but no Azure deployment will be blocked. Must check `skip_endpoint_smoke` or have a kill switch.

2. **P0-3 stage status fix may surface new bugs**: Changing the precedence scanner from `>=` to temporal ordering may cause stages to show incorrect transient states during rapid event delivery. Must test with actual orchestrator event trace.

3. **P0-4 build error exposure**: Adding `matched_line`, `dependency_coordinates`, and log tails to the API and UI may leak local paths or PII. Must sanitize using `redact_absolute_paths` and `_bounded_event_text`-style truncation.

4. **P0-1 HTTP 400 response capture**: The HTTP response body from Azure OpenAI may contain deployment IDs, model names, and region information. Must be captured then redacted before storing/displaying.

---

## Next steps

### Recommended implementation branches (in order)

| Branch | Description | Dependencies |
|--------|-------------|--------------|
| `v2/fix-stage-status-model` | Fix P0-3: stage status computation and event mapping | None |
| `v2/add-ai-smoke-endpoint` | Fix P0-1: AI smoke endpoint with live API call | None |
| `v2/capture-http400-body` | Fix P0-1 root cause B: capture HTTP 400 response body | None |
| `v2/backend-backed-assistant` | Fix P0-2: no fake success, output schema validation | `v2/add-ai-smoke-endpoint` |
| `v2/build-failure-diagnosis` | Fix P0-4: expose build error contract via API | None |
| `v2/debounce-frontend-refresh` | Fix P0-5: debounce SSE-triggered refresh | None |
| `v2/evidence-grouping` | Fix P1-1: phase-grouped evidence display | None |
| `v2/approval-ux-polish` | Fix P1-2: clear approval states | `v2/fix-stage-status-model` |

### Recommended first implementation

```
v2/fix-stage-status-model
```

Rationale: P0-3 is the most visible bug (contradictory states), has the simplest fix (3 functions in app.py), and is a prerequisite for approval UX, evidence grouping, and pipeline correctness. It requires no new endpoints, no new DB migrations, and can be tested entirely with unit tests using synthetic event lists.

---

## Hygiene

```
git diff --check   → clean (no whitespace errors)
git status --short → clean (no staged/unstaged changes)
next-env.d.ts      → NOT staged
```
