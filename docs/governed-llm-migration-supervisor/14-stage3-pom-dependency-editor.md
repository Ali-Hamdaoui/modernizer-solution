# F14 — Stage 3 POM Review + LLM-guided Generic Dependency Edit + Backend-controlled Stage 3 Sandbox Apply + Auto Build/Test Validation + Failure Diagnosis + Repair Plan + Rollback

## Table of Contents

1. [Plan Update Reality Gate](#1-plan-update-reality-gate)
2. [Architecture Plan](#2-architecture-plan)
3. [API Contract Plan](#3-api-contract-plan)
4. [Domain/DTO Plan](#4-domaindto-plan)
5. [Frontend Plan](#5-frontend-plan)
6. [Security/Redaction Plan](#6-securityredaction-plan)
7. [Test Plan](#7-test-plan)
8. [Implementation Sequence](#8-implementation-sequence)
9. [Risk Register](#9-risk-register)

---

## 1. Plan Update Reality Gate

This plan was revised on 2026-06-16 to correct the F14 blueprint against actual repo state. Symbols cited below were verified via `git grep` on the current branch.

### 1.1 Verified Existing Symbols

The following symbols exist in source on the current branch. They are **real and usable**:

| Symbol | Location | Verified |
|---|---|---|
| `_build_stage3_dependency_review_answer()` | `app.py` line ~5605 | ✅ `git grep` confirms |
| `_detect_stage3_baseline()` | `app.py` line ~5187 | ✅ `git grep` confirms |
| `pom_dependency_change_request` (intent) | `app.py` line ~3905 | ✅ `git grep` confirms |
| `stage3_dependency_review` (intent) | `app.py` line ~3933 | ✅ `git grep` confirms |
| `_classify_stage3_dependencies()` | `app.py` line ~5230 | ✅ `git grep` confirms |
| `_classify_v2_assistant_intent()` | `app.py` | ✅ `git grep` confirms |
| `_build_pom_dependency_change_request_answer()` | `app.py` line ~5388 | ✅ `git grep` confirms |
| `_resolve_stage_sandbox_root()` | `app.py` line ~4372 | ✅ `git grep` confirms |
| `_resolve_root_pom_file_alias_preview()` | `app.py` line ~4274 | ✅ `git grep` confirms |
| `_is_unsafe_sandbox_root()` | `app.py` line ~4438 | ✅ `git grep` confirms |
| `PomContextSummaryBuilder` | `v2_pom_context_summary.py` | ✅ `git grep` confirms |
| `PatchPolicyService` | `patch_policy.py` line ~120 | ✅ `git grep` confirms |
| `V2RepairFlowService` | `v2_repair_flow.py` line ~69 | ✅ `git grep` confirms |
| `V2FailureDiagnosisService` | `v2_failure_diagnosis.py` line ~70 | ✅ `git grep` confirms |
| `StageCommandLaunchService` | `services.py` line ~2168 | ✅ `git grep` confirms |
| `TimeoutService` | `services.py` line ~1287 | ✅ `git grep` confirms |
| `run_validation_after_patch()` | `repair_loop/validation_runner.py` | ✅ `git grep` confirms |
| `F05_ALLOWED_ACTION_TYPES` (has `propose_pom_patch`) | `v2_model_schemas.py` line ~92 | ✅ `git grep` confirms |
| Test file `test_v2_assistant_stage3_dependency_review.py` | `tests/control_tower/` | ✅ `ls` confirms |

### 1.2 Symbols Verified as Absent

These symbols/files are **missing** from the current branch. Implementation must build from current repo reality, not from earlier handoff claims:

| Symbol/File | Status |
|---|---|
| `_build_apply_dependency_change_answer()` | ❌ Does not exist — must be created |
| `pom_dependency_editor.py` | ❌ Missing — must be created |
| `pom_dependency_review.py` | ❌ Missing — must be created |
| `pom_dependency_policy.py` | ❌ Missing — must be created |
| `pom_change_proposer.py` | ❌ Missing — must be created |
| `pom_xml_patcher.py` | ❌ Missing — must be created |
| `pom_validation_diagnosis.py` | ❌ Missing — must be created |
| `pom_change_models.py` | ❌ Missing — must be created |
| `apply_pom_change` in `F05_ALLOWED_ACTION_TYPES` | ❌ Not present — must be added |
| `Stage3DependencyReview.tsx` | ❌ Missing — must be created |
| `v2_pom_change_proposals` / `v2_pom_changes` / `v2_pom_validations` / `v2_pom_repair_plans` tables | ❌ Not present — must be created |
| `POST /stage/3/pom/apply-change` endpoint | ❌ Missing — must be created |
| Any `PomChangePlan`-accepting endpoint | ❌ Missing — must be created |

### 1.3 Reality Gate Rule

If any symbol listed as “verified existing” is found missing at implementation time, **stop and report**. The implementation must start from current branch reality. Do not assume features exist because a handoff document or chat message claims they do.

### 1.4 What Already Exists (Directly Reusable)

| Capability | File | Maturity |
|---|---|---|
| POM scanning / Boot detection | `migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py` → `scan_root_pom()` | Stable |
| Spring Boot version detection | `migration_factory/agents/transformation_agent/pom_patches.py` → `detect_spring_boot_version()` | Stable |
| Build command detection | `migration_factory/agents/build_agent/detection.py` → `full_validation_command()`, `detect_java_project()` | Stable |
| POM context summary builder | `migration_factory/control_tower/application/v2_pom_context_summary.py` → `PomContextSummaryBuilder` | F04, stable |
| Dependency policy scanner | `migration_factory/dependency_policy/scanner.py` → `scan_dependency_policy()` | Stable |
| Policy models | `migration_factory/dependency_policy/models.py` → `PolicyReport`, `PolicyRisk` | Stable |
| Sandbox root resolution | `app.py:_resolve_stage_sandbox_root()` — resolves sandbox path from command result/event payload | Stable |
| root_pom file alias preview | `app.py:_resolve_root_pom_file_alias_preview()` → bounded, redacted POM preview | Stable |
| Artifact preview (generic) | `app.py:get_v2_job_artifact_preview()` → bounded, redacted artifact lookup by kind | Stable |
| Patch policy validation | `migration_factory/control_tower/application/patch_policy.py` → snapshot, checksum, apply, rollback for sandbox | Stable |
| Repair flow service | `migration_factory/control_tower/application/v2_repair_flow.py` → proposal → action → sandbox apply through patch_gate | Stable |
| Append-only event repository | `migration_factory/control_tower/infrastructure/sqlite/v2_event_repository.py` → `SqliteV2JobEventRepository` | Stable |
| V2 event streaming (SSE) | `app.py:v2_events_stream_sse()` → polls after_sequence and emits ServerSentEvent | Stable |
| Assistant intent classification | `app.py:_classify_v2_assistant_intent()` → recognizes `pom_dependency_change_request`, `stage3_dependency_review`, `pom_change_proposal` | Stable |
| Assistant LLM client | `migration_factory/control_tower/application/v2_assistant_model_client.py` → Azure OpenAI with deterministic fallback | Stable |
| System prompt (POM-aware) | `v2_assistant_model_client.py:_assistant_system_prompt()` — already includes Stage 3 dependency review rules | Partially covers F14 |
| Assistant service | `migration_factory/control_tower/application/v2_assistant_service.py` → messaging, drafting, context pack building | Stable |
| Redaction | `migration_factory/control_tower/application/redaction.py` → path/secrets/prompt redaction primitives | Stable |
| Frontend cockpit | `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` → SSE consumption, event rendering | Stable |
| Frontend API client | `web/control-tower/lib/controlTowerApi.ts` → typed fetch wrappers for all V2 endpoints | Stable |
| Frontend contracts | `web/control-tower/lib/contracts.ts` → TypeScript types for all API responses | Stable |
| Worker/command launcher | `StageCommandLaunchService` in `services.py` line ~2168 — launches validation commands asynchronously | Stable |
| Validation runner | `repair_loop/validation_runner.py` → `run_validation_after_patch()` with `ValidationResult` | Stable |

### 1.5 What Exists But Needs Extension

| Capability | What Needs to Change |
|---|---|
| Assistant `ask_v2_assistant()` endpoint | Assistant explains and proposes but never applies. Need `apply_dependency_change` intent routed to same backend `PomDependencyEditor` service path that UI endpoints use. |
| F05 allowed action types | `F05_ALLOWED_ACTION_TYPES` has `propose_pom_patch` but no `apply_pom_change`. Need new action types, possibly `apply_dependency_change` and `rollback_pom_change`. |
| POM context summary | `PomContextSummary` is built for F04 failure diagnosis context. F14 needs a **generic dependency review** that classifies dependencies into buckets (Boot-managed, Jakarta platform, app-specific, plugins, transitive risk) and evaluates any requested target not just pre-blessed ones. |
| patch_policy | `PatchPolicyService` handles deterministic patches via `rule_registry` IDs. F14 needs a new path for **user-requested dependency version changes** that are not allowlisted deterministic rules. |
| v2_repair_flow | `V2RepairFlowService` applies patches through `patch_gate` + `patch_apply`. F14 reuses `patch_gate`/`patch_apply` but needs a **pre-apply policy validation** step specific to arbitrary dependency edits. |
| Event types | Existing event types are generic (`stage_completed`, `build_failed`, etc.). Need new event types: `pom_change_proposed`, `pom_change_applied`, `pom_validation_started`, `pom_validation_passed`, `pom_validation_failed`, `pom_repair_plan_created`, `pom_change_rolled_back`. |
| Frontend cockpit | No "Stage 3 Dependency Review" section. Need new tab/panel component. |
| Frontend contracts | No types for POM dependency review, change proposals, validation runs, repair plans. |
| v2_assistant_model_client system prompt | Already references Stage 3 review rules but may need extension for generic dependency policy modes and apply intent. |

### 1.6 What Is Completely Missing

| Capability | Status |
|---|---|
| Generic dependency compatibility policy layer (classify any requested target, detect control mode, decide risk/execution) | Missing — must be created |
| POM change proposal validation service (validates user request before apply) | Missing — must be created |
| XML patch builder for dependency/property/plugin/BOM changes (formatting-preserving, well-formedness-guaranteed) | Missing — must be created |
| Auto-validation trigger after POM change (asynchronous, via worker infrastructure) | Partially exists via `StageCommandLaunchService`, but no guard for "only Stage 3 sandbox, never original repo" |
| POM validation diagnosis (classify build/test failures from POM changes using structured log evidence) | Missing — must be created |
| Repair plan generation from POM validation failure (evidence-based, never generic) | Missing — must be created |
| POM change rollback (backed by stored before-content/checksum, idempotent) | Partially exists in `patch_policy` but needs F14-specific rollback path |
| POM change record persistence (tables: proposals, changes, validations, repair plans) | Missing — must be created |
| Idempotency key support for apply/repair/rollback | Missing — must be created |
| Frontend "Stage 3 Dependency Review" panel with tabs | Missing — must be created |
| API endpoints for dependency review, propose, apply, validate, repair, rollback | Missing — must be created |

### 1.7 Mismatches Between Previous Spec and Repo

| Spec Expectation | Repo Reality | Resolution |
|---|---|---|
| `migration_factory/orchestrator/*` directory | Exists at `migration_factory/orchestrator/` with runner, events, state, etc. These are V1 orchestrator components. | Use V2 services in `control_tower/application/`, not V1 orchestrator directly. |
| "existing `repair_loop`" for validation rerun | `repair_loop/validation_runner.py` exists with `run_validation_after_patch()`. | Reuse `validation_runner` for F14 auto-validation. |
| "OpenRewrite or existing dependency-policy" for complex dependency migrations | `dependency_policy/` exists with scanner, models, patching. `repair_loop/rule_registry.py` has allowlisted deterministic rules. | F14 primarily uses targeted XML patching for simple changes. Complex coordinate/migration/BOM changes may delegate to OpenRewrite or repair-loop patching. |
| Dedicated `root_pom` alias for Stage 3 | `_resolve_root_pom_file_alias_preview()` already handles stages 1-3. | Reuse `_resolve_stage_sandbox_root()` for both read and write. |

---

## 2. Architecture Plan

### 2.1 Core Principles

These principles are non-negotiable and govern every implementation decision:

1. **LLM interprets and explains.** The assistant may read POM, diagnose, propose, and explain. It never writes files or executes commands.
2. **Backend validates and writes.** Only the backend Python service writes to the Stage 3 sandbox POM. No frontend, no LLM, no user-submitted path can write.
3. **Build/test proves.** Every POM change is validated by automated Maven build/test run against the Stage 3 sandbox.
4. **Assistant reports from evidence.** Assistant responses about validation status, success, or failure must be based on backend-emitted event evidence, never on assumption.
5. **No original repository mutation.** Stage 3 sandbox is the only writable target. Original repo files are read-only.
6. **Frontend is not trusted.** The browser/frontend may submit proposal_id or user_request + idempotency_key. The backend must reload all evidence, re-resolve the sandbox path, and revalidate the change plan server-side before writing.

### 2.2 Module Map

```
migration_factory/control_tower/application/
├── pom_dependency_editor.py           [NEW] Main service orchestrator
├── pom_dependency_review.py           [NEW] Dependency review service
├── pom_dependency_policy.py           [NEW] Generic dependency compatibility policy
├── pom_change_proposer.py             [NEW] Server-side change validation
├── pom_xml_patcher.py                 [NEW] Formatting-preserving XML patch engine
├── pom_validation_diagnosis.py        [NEW] Build/test failure diagnosis
├── pom_change_models.py               [NEW] Domain models / DTOs for F14
├── v2_pom_context_summary.py          [EXISTING] Reuse Boot/Java detection
├── v2_assistant_service.py            [EXISTING] Reuse messaging pattern
├── v2_assistant_model_client.py       [EXISTING] Reuse LLM client pattern
├── patch_policy.py                    [EXISTING] Reuse checksum/snapshot/rollback
├── v2_repair_flow.py                  [EXISTING] Reuse patch_apply via repair_loop

migration_factory/control_tower/infrastructure/sqlite/
├── migrations/                        Add new migration for F14 tables
├── repositories.py                    Add pom change repositories

web/control-tower/app/migrations/[jobId]/
├── MigrationCockpit.tsx               [EXISTING] Integrate Stage 3 Dependency Review
├── Stage3DependencyReview.tsx         [NEW] Stage 3 dependency review panel
│   (or web/control-tower/app/migrations/[jobId]/components/Stage3DependencyReview.tsx)
```

### 2.3 Service Layer Design

#### `PomDependencyEditor` — Main Orchestrator

```python
class PomDependencyEditor:
    """Stage 3 POM review, change proposal, apply, validate, repair, rollback.

    This is the thin service that orchestrates F14 operations. It does NOT
    contain parsing logic, XML manipulation, or build execution. It delegates
    to sub-services.
    """

    def __init__(
        self,
        review_service: PomDependencyReviewer,         # dependency review
        policy: PomDependencyPolicy,                   # generic policy layer
        proposer: PomChangeProposer,                   # server-side change validation
        patcher: PomXmlPatcher,                        # XML patch engine
        validator: PomValidationRunner,                # async validation trigger
        diagnoser: PomValidationDiagnoser,             # failure diagnosis
        event_sink: EventSinkProtocol,                 # event recorder
        pom_repo: PomChangeRepositoryProtocol,         # change persistence
        unit_of_work_factory: UnitOfWorkFactory,
    ): ...

    # ── Read operations (no write) ──

    def get_stage3_pom(job_id: str) -> PomView: ...
    def review_stage3_dependencies(job_id: str) -> PomDependencyReview: ...
    def propose_change(job_id: str, user_request: str, idempotency_key: str | None = None) -> PomChangeProposal: ...

    # ── Write operations (backend-owned, server-side validated) ──

    def apply_change_from_proposal(
        self, job_id: str, proposal_id: str, idempotency_key: str
    ) -> PomApplyResult: ...
        # Reloads proposal from repository, revalidates against current POM/checksum

    def apply_change_from_user_request(
        self, job_id: str, user_request: str, idempotency_key: str
    ) -> PomApplyResult: ...
        # Classifies, plans, validates server-side, then writes

    # ── Validation (async) ──

    def enqueue_validation(self, job_id: str, change_id: str) -> str:
        """Enqueue async validation, returns validation_id. Does NOT block."""
        ...

    def get_validation_result(self, job_id: str, validation_id: str) -> PomValidationRun: ...

    # ── Repair / Rollback ──

    def explain_validation_failure(self, job_id: str, validation_id: str) -> PomRepairPlan: ...
    def apply_repair_plan(self, job_id: str, repair_plan_id: str, idempotency_key: str) -> PomApplyResult: ...
    def rollback_change(self, job_id: str, change_id: str, idempotency_key: str) -> PomRollbackResult: ...
    def list_changes(self, job_id: str) -> list[PomChangeRecordSummary]: ...
```

### 2.4 Chat Apply and UI Apply Must Use Same Backend Service

There is a single business logic path for applying POM changes:

```
assistant/ask  →  intent classification  →  PomDependencyEditor.apply_change_from_user_request()
UI endpoint    →  FastAPI thin handler    →  PomDependencyEditor.apply_change_from_user_request()
                                                                     or
                                                                  PomDependencyEditor.apply_change_from_proposal()
```

No separate code path for chat vs. UI. The assistant `/ask` endpoint may route the `apply_dependency_change` intent to the same backend service that the UI `POST /apply-change` endpoint uses. Assistant response is generated from the backend `PomApplyResult`, not from LLM-generated text about what "would" happen.

**Chat flow when user says "change gson to 2.11.0":**

1. `_classify_v2_assistant_intent()` returns `apply_dependency_change`
2. Assistant answer builder calls `PomDependencyEditor.apply_change_from_user_request(job_id, "change gson to 2.11.0", idempotency_key)`
3. If applied: assistant reports "Change applied. Validation is now running." with change_id and validation_id
4. If blocked: assistant explains why with proposal/next action
5. If policy requires proposal first: assistant returns review/proposal, not write

**UI apply flow when user clicks "Apply" button:**

1. Frontend calls `POST /v1/v2/jobs/{job_id}/stage/3/pom/apply-change` with `proposal_id` or `user_request`
2. Same `PomDependencyEditor` service validates and writes
3. Same result object returned

### 2.5 Dependency Compatibility Policy Layer

**File:** `migration_factory/control_tower/application/pom_dependency_policy.py`

A generic policy layer that evaluates **any** requested dependency/property/plugin/BOM/parent/dependencyManagement change before the backend writes. It is not Tomcat-specific or limited to any single dependency.

#### Responsibilities

- Classify the requested target (dependency, property, plugin, BOM, parent, dependencyManagement)
- Detect how the requested dependency is controlled in the current POM
- Detect whether the change is direct, property-managed, dependencyManagement-managed, parent/BOM-managed, plugin-managed, transitive-only, not present, inherited from parent, or unknown
- Detect whether the request is exact enough to apply (specific target + specific version)
- Decide risk level: `low`, `medium`, `high`, `blocked`, or `evidence_insufficient`
- Decide execution mode: targeted POM span patch, OpenRewrite recipe, repair-loop patch, or refusal/proposal only
- Generate evidence-backed warnings
- Produce a backend-verifiable decision object

#### Generic Control Modes

```python
class DependencyControlMode(Enum):
    DIRECT_DEPENDENCY_VERSION = "direct_dependency_version"
    PROPERTY_MANAGED_VERSION = "property_managed_version"
    DEPENDENCY_MANAGEMENT_ENTRY = "dependency_management_entry"
    PARENT_BOM_MANAGED = "parent_bom_managed"
    SPRING_BOOT_BOM_MANAGED = "spring_boot_bom_managed"
    PLUGIN_VERSION = "plugin_version"
    TRANSITIVE_ONLY = "transitive_only"
    NOT_PRESENT = "not_present"
    MULTI_MODULE_INHERITED = "multi_module_inherited"
    UNKNOWN = "unknown"
```

#### Generic Operation Risk Levels

**LOW** — may apply directly with standard policy check:

- Exact app-specific direct dependency version update where user gives exact version (e.g., "update gson to 2.11.0")
- Exact property update for app-specific dependency (e.g., "change jjwt.version to 0.12.6")
- Remove explicit dependency version when dependency is clearly BOM-managed

**MEDIUM** — may apply with warning if user request is explicit:

- dependencyManagement edit
- Plugin version update
- Add dependency with clear target and evidence
- Remove dependency

**HIGH** — requires explicit high-risk wording or prior backend proposal/action card:

- Major framework/runtime dependency change
- Hibernate major migration (e.g., 5.x → 6.x, 6.x → 7.x)
- Servlet/container stack change (e.g., Tomcat, Jetty, Undertow)
- javax-to-jakarta coordinate migration
- Parent/BOM change
- Dependency used transitively only
- Multi-module inherited version
- Any operation that may require code changes beyond the POM

**BLOCKED** — do not write; explain why and propose alternatives:

- Requested version conflicts with detected baseline/policy
- Target not present and no safe add rule exists
- Dependency is transitive-only and user did not explicitly request an override strategy
- Evidence is insufficient and the operation could break the project
- Stage is not 3
- Stage 3 sandbox is unavailable/incomplete/unstable
- Target file is not backend-resolved Stage 3 `root_pom`
- Vague request without specific target and version

#### Dependency Examples (not exhaustive; policy is generic)

These are examples only. The policy layer must handle any dependency, not just these:

| Example | Control Mode | Typical Risk |
|---|---|---|
| Gson direct dependency version update | `direct_dependency_version` | LOW (if exact version) |
| Hibernate major migration | `direct_dependency_version` or `bom_managed` | HIGH |
| javax.servlet → jakarta.servlet coordinate migration | `direct_dependency_version` (with coordinate change) | HIGH |
| Problem Spring Web version/coordinate change | `direct_dependency_version` | MEDIUM |
| JJWT version or coordinate migration | `direct_dependency_version` or `property_managed_version` | MEDIUM |
| Juneau update | `direct_dependency_version` | MEDIUM |
| Azure starter update | `dependency_management_entry` | MEDIUM |
| Maven compiler/surefire plugin update | `plugin_version` | MEDIUM |
| Spring Boot BOM/parent dependency management | `dependency_management_entry` | HIGH |
| Tomcat/container override (transitive) | `transitive_only` → `spring_boot_bom_managed` | HIGH |
| Add new dependency not present | `not_present` | MEDIUM/HIGH |

#### User Wording Policy

| User Wording | Behavior |
|---|---|
| "propose", "suggest", "review", "what should I change" | Propose/review only. No write. |
| "apply this" where "this" maps to a server-side `proposal_id` | Write if backend validates proposal is still valid. |
| "change X to Y", "update X to Y" where X and Y are specific | Write if policy allows. |
| "fix all dependencies", "make it better", "upgrade everything" | Propose/review only. Refuse write. |
| "upgrade to latest" | Refuse write unless project policy/evidence explicitly supplies the version. |

### 2.6 Backend Must Not Trust Frontend-Submitted Change Plans

The browser/frontend is not trusted. It may submit:

- **`proposal_id`** — generated and stored by the backend
- **`user_request` + `idempotency_key`** — treated as a new request

The backend must **never** trust a full client-submitted `PomChangePlan` as the authority for writing. Specifically:

1. Reload Stage 3 evidence from repository
2. Reload current Stage 3 root POM content from sandbox
3. Resolve Stage 3 sandbox path internally (never from client)
4. Reconstruct or revalidate the change plan server-side
5. Verify checksum and current POM content match expected state
6. Verify operation is in allowlist and passes policy decision
7. Only then write

The `apply-change` endpoint may accept a `plan_preview` field only as advisory/debug content for the response, never as authority for the write operation.

### 2.7 Validation Must Be Asynchronous

Apply writes the POM change and **returns immediately**. It does not block on Maven build/test.

Flow:

1. Backend writes POM change to Stage 3 sandbox
2. Backend persists change record with `before_checksum`, `after_checksum`, `diff_unified`
3. Backend emits `pom_change_applied` event
4. Backend enqueues validation via existing `StageCommandLaunchService` or worker infrastructure
5. Backend emits `pom_validation_started` event
6. Backend returns HTTP response: `status = "applied_pending_validation"` with `change_id` and `validation_id`
7. Later, worker/event infrastructure updates validation status to `passed` or `failed`
8. If failed, worker triggers failure diagnosis and emits `pom_repair_plan_created`

**Do not block the apply HTTP request for Maven build/test.**

### 2.8 Structured Change Plan (LLM Output → Backend Revalidation)

The LLM may produce this JSON structure as a **preview**, but the backend must revalidate it server-side before writing:

```json
{
  "intent": "apply_dependency_change",
  "stage": 3,
  "operation": "update_dependency_version",
  "target": {
    "kind": "dependency",
    "group_id": "com.google.code.gson",
    "artifact_id": "gson"
  },
  "requested_version": "2.11.0",
  "risk": "medium",
  "requires_validation": true,
  "evidence": ["root_pom", "dependency_policy_report"],
  "rationale": "User-requested explicit version update for Gson."
}
```

**Allowed operations** (enum in `pom_change_models.py`):

- `update_property_version` — e.g., `<java.version>21</java.version>`
- `update_dependency_version` — e.g., version of an existing GAV dependency
- `remove_dependency_version` — remove explicit version to allow BOM management
- `change_dependency_coordinates` — e.g., javax.servlet → jakarta.servlet
- `add_dependency` — add a new managed dependency (requires evidence)
- `remove_dependency` — remove a dependency
- `add_or_update_dependency_management_entry` — modify `<dependencyManagement>`
- `update_plugin_version` — modify `<build><plugins>` version

### 2.9 Validation Flow

After every successful POM change:

1. Backend records `before_content`, `after_content`, `before_checksum`, `after_checksum`, `diff_unified`
2. Emits `pom_change_applied` event
3. Marks Stage 3 validation/proof stale
4. Enqueues Maven build/test via existing `StageCommandLaunchService`
5. Emits `pom_validation_started` event
6. When worker reports result:
   - Pass → emit `pom_validation_passed` event
   - Fail → emit `pom_validation_failed`, run diagnosis, emit `pom_repair_plan_created`

Validation uses the existing infrastructure:

- `migration_factory/agents/build_agent/detection.py` → determine correct Maven command
- `StageCommandLaunchService` to launch validation asynchronously
- `migration_factory/repair_loop/validation_runner.py` → `run_validation_after_patch()` for result capture

### 2.10 OpenRewrite Usage

OpenRewrite is a backend execution option, not an assistant claim. Rules:

- Assistant may name a candidate operation/recipe
- Backend chooses executor (XML span patch, OpenRewrite, or repair-loop patch)
- Backend records which executor was used in the change record
- Backend never claims OpenRewrite ran unless actual backend evidence proves it
- Simple direct version/property changes use targeted POM patcher
- Complex coordinate/managed/parent/BOM changes may use OpenRewrite or repair-loop patching

---

## 3. API Contract Plan

### 3.1 Endpoint List

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/v2/jobs/{job_id}/stage/3/pom` | Get redacted Stage 3 POM content |
| `GET` | `/v1/v2/jobs/{job_id}/stage/3/dependency-review` | Get classified dependency review |
| `POST` | `/v1/v2/jobs/{job_id}/stage/3/pom/propose-change` | Propose a change (read-only, no write) |
| `POST` | `/v1/v2/jobs/{job_id}/stage/3/pom/apply-change` | Apply a change (backend validates then writes) |
| `GET` | `/v1/v2/jobs/{job_id}/stage/3/pom/changes` | List all POM changes for the job |
| `GET` | `/v1/v2/jobs/{job_id}/stage/3/pom/changes/{change_id}` | Get a specific change record |
| `GET` | `/v1/v2/jobs/{job_id}/stage/3/pom/validation/{validation_id}` | Get validation run result |
| `POST` | `/v1/v2/jobs/{job_id}/stage/3/pom/repair` | Apply a repair plan |
| `POST` | `/v1/v2/jobs/{job_id}/stage/3/pom/rollback` | Rollback last or specific change |

### 3.2 FastAPI Thinness Rule

`app.py` must remain thin. The new endpoints delegate to `PomDependencyEditor`:

```python
# In app.py — ADD these endpoints (each ≤ 15 lines of handler logic)

@app.get("/v1/v2/jobs/{job_id}/stage/3/pom")
def get_stage3_pom(job_id: str):
    editor = _pom_dependency_editor(uow)
    view = editor.get_stage3_pom(job_id)
    return view.to_public_dict()

@app.get("/v1/v2/jobs/{job_id}/stage/3/dependency-review")
def get_stage3_dependency_review(job_id: str):
    editor = _pom_dependency_editor(uow)
    review = editor.review_stage3_dependencies(job_id)
    return review.to_public_dict()

@app.post("/v1/v2/jobs/{job_id}/stage/3/pom/propose-change")
def propose_pom_change(job_id: str, payload: PomProposeRequest):
    editor = _pom_dependency_editor(uow)
    proposal = editor.propose_change(job_id, payload.user_request, payload.idempotency_key)
    return proposal.to_public_dict()

@app.post("/v1/v2/jobs/{job_id}/stage/3/pom/apply-change")
def apply_pom_change(job_id: str, payload: PomApplyRequest):
    editor = _pom_dependency_editor(uow)
    if payload.proposal_id:
        result = editor.apply_change_from_proposal(job_id, payload.proposal_id, payload.idempotency_key)
    elif payload.user_request:
        result = editor.apply_change_from_user_request(job_id, payload.user_request, payload.idempotency_key)
    else:
        raise HTTPException(400, "proposal_id or user_request required")
    # Validation is enqueued inside apply_change_* — do NOT block here
    return result.to_public_dict()

@app.get("/v1/v2/jobs/{job_id}/stage/3/pom/changes")
def list_pom_changes(job_id: str):
    editor = _pom_dependency_editor(uow)
    changes = editor.list_changes(job_id)
    return {"job_id": job_id, "changes": [c.to_public_dict() for c in changes]}

@app.get("/v1/v2/jobs/{job_id}/stage/3/pom/validation/{validation_id}")
def get_validation_result(job_id: str, validation_id: str):
    editor = _pom_dependency_editor(uow)
    result = editor.get_validation_result(job_id, validation_id)
    return result.to_public_dict()

@app.post("/v1/v2/jobs/{job_id}/stage/3/pom/repair")
def apply_repair_plan(job_id: str, payload: PomRepairApplyRequest):
    editor = _pom_dependency_editor(uow)
    result = editor.apply_repair_plan(job_id, payload.repair_plan_id, payload.idempotency_key)
    return result.to_public_dict()

@app.post("/v1/v2/jobs/{job_id}/stage/3/pom/rollback")
def rollback_pom_change(job_id: str, payload: PomRollbackRequest):
    editor = _pom_dependency_editor(uow)
    result = editor.rollback_change(job_id, payload.change_id, payload.idempotency_key)
    return result.to_public_dict()
```

### 3.3 Request/Response DTOs

#### `POST /stage/3/pom/propose-change`

Request:
```json
{
  "user_request": "update gson to 2.11.0",
  "idempotency_key": "optional-client-key"
}
```

Response:
```json
{
  "proposal_id": "prop_a1b2c3",
  "server_validated_plan_preview": {
    "intent": "apply_dependency_change",
    "stage": 3,
    "operation": "update_dependency_version",
    "target": {
      "kind": "dependency",
      "group_id": "com.google.code.gson",
      "artifact_id": "gson"
    },
    "current_version": "2.8.9",
    "requested_version": "2.11.0"
  },
  "risk": "medium",
  "can_apply": true,
  "warnings": ["Gson 2.10+ requires Java 11 minimum"],
  "applied": false,
  "control_mode": "direct_dependency_version",
  "created_at": "2026-06-16T12:00:00Z"
}
```

#### `POST /stage/3/pom/apply-change`

**Request Option A (by proposal_id):**
```json
{
  "proposal_id": "prop_a1b2c3",
  "idempotency_key": "optional-client-key"
}
```

**Request Option B (by user_request):**
```json
{
  "user_request": "change gson to 2.11.0",
  "idempotency_key": "optional-client-key"
}
```

**The backend must reject** any request that provides a full `change_plan` object and attempts to use it as the write authority. A full `change_plan` may only be accepted as a `plan_preview` field for advisory/debug purposes.

Response:
```json
{
  "change_id": "ch_a1b2c3",
  "status": "applied_pending_validation",
  "operation": "update_dependency_version",
  "target_desc": "com.google.code.gson:gson",
  "before_version": "2.8.9",
  "after_version": "2.11.0",
  "before_checksum": "sha256:abc123...",
  "after_checksum": "sha256:def456...",
  "diff_summary": "Updated gson version from 2.8.9 to 2.11.0",
  "validation_id": "val_d4e5f6",
  "rollback_available": true,
  "idempotency_key": "optional-client-key",
  "created_at": "2026-06-16T12:00:01Z",
  "message": "The POM change was applied to the Stage 3 sandbox. Validation is now running."
}
```

#### `GET /stage/3/pom` → PomView

```json
{
  "job_id": "string",
  "stage": 3,
  "exists": true,
  "content": "redacted XML content",
  "truncated": false,
  "content_type": "application/xml",
  "redaction_applied": true,
  "detected_baseline": {
    "java_version": "17",
    "spring_boot_version": "3.5.14",
    "spring_boot_version_location": "parent"
  }
}
```

#### `GET /stage/3/dependency-review` → PomDependencyReview

```json
{
  "job_id": "string",
  "stage": 3,
  "baseline": {
    "java_version": "17",
    "spring_boot_version": "3.5.14",
    "spring_boot_version_location": "parent",
    "detected_from": ["root_pom", "target_dependency_plan"]
  },
  "buckets": {
    "boot_managed": [],
    "jakarta_platform": [],
    "app_specific_third_party": [],
    "build_plugins": [],
    "transitive_or_bom_managed_risk": []
  },
  "findings": [
    {
      "dependency_name": "com.google.code.gson:gson",
      "current_version": "2.8.9",
      "source_location": "pom.xml:dependencies",
      "bucket": "app_specific_third_party",
      "control_mode": "direct_dependency_version",
      "risk": "low",
      "recommended_action": "update_to_2.11.0",
      "can_apply_now": true,
      "reason": "Explicit dependency with known target version",
      "evidence_source": "target_dependency_plan"
    }
  ],
  "evidence_loaded": ["root_pom", "target_dependency_plan", "dependency_policy_report"],
  "evidence_missing": ["dependency_tree"],
  "warnings": [],
  "created_at": "2026-06-16T12:00:00Z"
}
```

#### `GET /stage/3/pom/validation/{validation_id}` → PomValidationRun

```json
{
  "validation_id": "val_d4e5f6",
  "change_id": "ch_a1b2c3",
  "status": "passed",
  "command": "mvn clean compile test",
  "build_status": "passed",
  "test_status": "passed",
  "exit_code": 0,
  "duration_ms": 45000,
  "log_ref": "artifact:build_log:val_d4e5f6",
  "test_log_ref": "artifact:test_log:val_d4e5f6",
  "diagnosis": null,
  "repair_plan": null,
  "created_at": "2026-06-16T12:00:01Z",
  "completed_at": "2026-06-16T12:00:46Z"
}
```

When validation fails, `diagnosis` and `repair_plan` are populated:

```json
{
  "validation_id": "val_d4e5f6",
  "status": "failed",
  "diagnosis": {
    "failure_classification": "compilation_failure",
    "failed_phase": "compile",
    "exit_code": 1,
    "log_excerpt": "error: cannot find symbol...",
    "root_cause": "Gson 2.11.0 removed deprecated methods used in source code",
    "evidence_sufficient": true,
    "missing_evidence": []
  },
  "repair_plan": {
    "repair_plan_id": "rp_g7h8i9",
    "change_id": "ch_a1b2c3",
    "summary": "Update source imports to use Gson 2.11.0 API",
    "detailed_steps": ["Add explicit Gson builder import", "Replace deprecated JsonParser.parse() calls"],
    "confidence": "medium",
    "evidence_sources": ["build_log_ref", "changed_diff"],
    "actions_available": ["apply_repair", "rollback", "show_logs"]
  }
}
```

#### `POST /stage/3/pom/rollback` → PomRollbackResult

Request:
```json
{
  "change_id": "ch_a1b2c3",
  "idempotency_key": "optional-client-key"
}
```

Response:
```json
{
  "change_id": "ch_a1b2c3",
  "rollback_id": "rb_j0k1l2",
  "status": "rolled_back",
  "checksum_restored": true,
  "validation_triggered": true,
  "validation_id": "val_m3n4o5",
  "created_at": "2026-06-16T12:02:00Z"
}
```

### 3.4 Event Types

| Event Type | Payload (public-safe, no raw paths/secrets) | Emitted When |
|---|---|---|
| `pom_change_proposed` | `{proposal_id, operation, target_desc, risk, can_apply, stage_index}` | Change proposal generated (no write) |
| `pom_change_applied` | `{change_id, operation, target_desc, before_checksum, after_checksum, diff_summary, stage_index}` | Backend writes POM change |
| `pom_validation_started` | `{validation_id, change_id, command_desc, stage_index}` | Validation enqueued |
| `pom_validation_passed` | `{validation_id, change_id, build_status, test_status, duration_ms, stage_index}` | Build/test succeeds |
| `pom_validation_failed` | `{validation_id, change_id, exit_code, failed_phase, log_ref, stage_index}` | Build/test fails |
| `pom_repair_plan_created` | `{repair_plan_id, validation_id, change_id, failure_classification, confidence, stage_index}` | Diagnosis generates repair plan |
| `pom_change_rolled_back` | `{change_id, rollback_id, checksum_restored, stage_index}` | Rollback executed |

**Event payload rules:**
- No absolute sandbox paths
- No raw secrets or tokens
- No full build logs in SSE event
- Use log/artifact refs or redacted excerpts
- Include `change_id`, `validation_id`, `status`, `target_desc`, `risk`, `stage_index`, `diff_summary`, `log_ref` where appropriate

### 3.5 Status Lifecycle

```
                ┌─────────────────┐
                │   PROPOSED      │  (no write yet)
                └────────┬────────┘
                         │ user approves + apply
                         ▼
                ┌─────────────────┐
                │   APPLIED       │  POM_CHANGE_APPLIED_PENDING_VALIDATION
                │   (pending      │
                │   validation)   │
                └────────┬────────┘
                         │ async enqueue validation
                         ▼
                ┌─────────────────┐
                │ VALIDATION      │  VALIDATION_RUNNING
                │    RUNNING      │
                └────┬───────┬────┘
                     │       │
              pass ──┘       └── fail
                │                  │
                ▼                  ▼
         ┌──────────┐      ┌──────────────┐
         │ VALIDATED │      │   FAILED     │  VALIDATION_FAILED
         │  (passed) │      │  (diagnosis  │
         └──────────┘      │   pending)   │
                           └──────┬───────┘
                                  │ auto-diagnosis
                                  ▼
                           ┌──────────────┐
                           │   REPAIR     │  REPAIR_PROPOSED
                           │  PROPOSED    │
                           └──────┬───────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
              apply repair    rollback      show logs
                    │             │
                    ▼             ▼
             (back to       ┌──────────┐
              APPLIED)      │ ROLLED   │  ROLLBACK_AVAILABLE
                            │  BACK    │
                            └──────────┘
```

---

## 4. Domain/DTO Plan

### 4.1 New File: `pom_change_models.py`

```python
# Dataclasses for F14 domain models

@dataclass(frozen=True)
class PomProposeRequest:
    """User request to propose a POM change."""
    user_request: str
    idempotency_key: str | None = None

@dataclass(frozen=True)
class PomApplyRequest:
    """Request to apply a POM change. Backend validates server-side."""
    proposal_id: str | None = None
    user_request: str | None = None
    idempotency_key: str | None = None
    # plan_preview is advisory/debug only; never trusted as write authority
    plan_preview: dict[str, Any] | None = None

@dataclass(frozen=True)
class PomChangeTarget:
    """Identifies what to change."""
    kind: str  # "dependency" | "property" | "plugin" | "dependency_management" | "parent" | "bom"
    group_id: str | None = None
    artifact_id: str | None = None
    property_name: str | None = None
    plugin_group_id: str | None = None
    plugin_artifact_id: str | None = None

@dataclass(frozen=True)
class PomPatchOperation:
    """Single patch operation on a POM."""
    operation: str  # From ALLOWED_POM_OPERATIONS
    target: PomChangeTarget
    current_version: str
    requested_version: str
    before_xml_excerpt: str
    after_xml_excerpt: str

@dataclass(frozen=True)
class PomChangePlan:
    """Server-validated change plan."""
    intent: str  # "apply_dependency_change"
    stage: int
    operation: str
    target: PomChangeTarget
    requested_version: str
    risk: str  # "low" | "medium" | "high"
    control_mode: str  # From DependencyControlMode enum
    requires_validation: bool
    evidence: tuple[str, ...]
    rationale: str

@dataclass(frozen=True)
class PomChangeProposal:
    """Read-only proposal (no file written yet)."""
    proposal_id: str
    server_validated_plan_preview: dict[str, Any]
    risk: str
    can_apply: bool
    warnings: tuple[str, ...]
    applied: bool  # Always False for proposals
    control_mode: str
    created_at: str

@dataclass(frozen=True)
class PomApplyResult:
    """Result after backend applies a POM change."""
    change_id: str
    status: str  # "applied_pending_validation"
    operation: str
    target_desc: str
    before_version: str
    after_version: str
    before_checksum: str
    after_checksum: str
    diff_summary: str
    validation_id: str | None
    rollback_available: bool
    idempotency_key: str | None
    created_at: str
    message: str

@dataclass(frozen=True)
class PomValidationFailureDiagnosis:
    """Classified build/test failure from log evidence only."""
    failure_classification: str
    failed_phase: str
    exit_code: int
    log_excerpt: str  # Redacted, bounded excerpt
    log_ref: str  # Reference to full log artifact
    root_cause: str
    evidence_sufficient: bool
    missing_evidence: tuple[str, ...]

@dataclass(frozen=True)
class PomRepairPlan:
    """Repair plan after failed validation."""
    repair_plan_id: str
    change_id: str
    summary: str
    detailed_steps: tuple[str, ...]
    confidence: str  # "low" | "medium" | "high"
    evidence_sources: tuple[str, ...]
    actions_available: tuple[str, ...]  # "apply_repair", "rollback", "show_logs"
    created_at: str

@dataclass(frozen=True)
class PomValidationRun:
    """Validation run result."""
    validation_id: str
    change_id: str
    status: str  # "running" | "passed" | "failed"
    command: str
    build_status: str
    test_status: str
    exit_code: int | None
    duration_ms: int | None
    log_ref: str | None  # Reference to log artifact, never raw content in API
    test_log_ref: str | None
    diagnosis: PomValidationFailureDiagnosis | None
    repair_plan: PomRepairPlan | None
    created_at: str
    completed_at: str | None

@dataclass(frozen=True)
class PomRollbackResult:
    """Rollback result."""
    change_id: str
    rollback_id: str
    status: str  # "rolled_back"
    checksum_restored: bool
    validation_triggered: bool
    validation_id: str | None
    created_at: str

@dataclass(frozen=True)
class PomBaseline:
    """Detected Stage 3 baseline from root POM evidence."""
    java_version: str
    spring_boot_version: str
    spring_boot_version_location: str
    detected_from: tuple[str, ...]

@dataclass(frozen=True)
class PomDependencyFinding:
    """Single dependency finding in review."""
    dependency_name: str
    current_version: str
    source_location: str
    bucket: str
    control_mode: str
    risk: str
    recommended_action: str
    can_apply_now: bool
    reason: str
    evidence_source: str

@dataclass(frozen=True)
class PomDependencyReview:
    """Full Stage 3 dependency review."""
    job_id: str
    stage: int
    baseline: PomBaseline
    buckets: dict[str, list[PomDependencyFinding]]
    findings: tuple[PomDependencyFinding, ...]
    evidence_loaded: tuple[str, ...]
    evidence_missing: tuple[str, ...]
    warnings: tuple[str, ...]
    created_at: str

@dataclass(frozen=True)
class PomView:
    """Redacted POM view for public display."""
    job_id: str
    stage: int
    exists: bool
    content: str
    truncated: bool
    content_type: str
    redaction_applied: bool
    detected_baseline: PomBaseline | None
    reason: str | None

@dataclass(frozen=True)
class PomChangeRecordSummary:
    """Public-safe change record summary."""
    change_id: str
    operation: str
    target_desc: str
    before_version: str
    after_version: str
    before_checksum: str
    after_checksum: str
    diff_summary: str
    status: str
    validation_id: str | None
    rollback_id: str | None
    created_at: str

@dataclass(frozen=True)
class PomChangeRecord:
    """Persisted POM change record (internal, not exposed directly)."""
    change_id: str
    proposal_id: str | None
    job_id: str
    stage_index: int
    operation: str
    target_json: str  # JSON serialized target
    requested_version: str
    before_content_ref: str  # Reference to stored before-content
    after_content_ref: str   # Reference to stored after-content
    before_checksum: str
    after_checksum: str
    diff_unified: str
    status: str
    validation_id: str | None
    rollback_id: str | None
    idempotency_key: str | None
    created_at: str
    updated_at: str
```

### 4.2 Allowed Operations Enum

```python
ALLOWED_POM_OPERATIONS = frozenset({
    "update_property_version",
    "update_dependency_version",
    "remove_dependency_version",
    "change_dependency_coordinates",
    "add_dependency",
    "remove_dependency",
    "add_or_update_dependency_management_entry",
    "update_plugin_version",
})
```

### 4.3 Failure Classifications

```python
POM_VALIDATION_FAILURE_CLASSIFICATIONS = frozenset({
    "dependency_resolution_failure",
    "bom_conflict",
    "jakarta_javax_mismatch",
    "hibernate_api_break",
    "plugin_failure",
    "compilation_failure",
    "test_failure",
    "unknown_build_failure",
    "evidence_insufficient",
})
```

### 4.4 Dependency Control Modes (Enum in `pom_dependency_policy.py`)

```python
class DependencyControlMode(Enum):
    DIRECT_DEPENDENCY_VERSION = "direct_dependency_version"
    PROPERTY_MANAGED_VERSION = "property_managed_version"
    DEPENDENCY_MANAGEMENT_ENTRY = "dependency_management_entry"
    PARENT_BOM_MANAGED = "parent_bom_managed"
    SPRING_BOOT_BOM_MANAGED = "spring_boot_bom_managed"
    PLUGIN_VERSION = "plugin_version"
    TRANSITIVE_ONLY = "transitive_only"
    NOT_PRESENT = "not_present"
    MULTI_MODULE_INHERITED = "multi_module_inherited"
    UNKNOWN = "unknown"
```

### 4.5 Policy Decision Object (in `pom_dependency_policy.py`)

```python
@dataclass(frozen=True)
class DependencyPolicyDecision:
    """Decision object after evaluating a dependency change request."""
    control_mode: DependencyControlMode
    risk: str  # "low" | "medium" | "high" | "blocked" | "evidence_insufficient"
    can_apply: bool
    execution_mode: str  # "pom_span_patch" | "openrewrite" | "repair_loop_patch" | "proposal_only" | "refuse"
    warnings: tuple[str, ...]
    reason: str
    requires_explicit_high_risk: bool
    suggested_next_action: str
```

---

## 5. Persistence Plan

### 5.1 New SQLite Tables

Add an append-only migration to create these tables. Follow existing repository style in `migration_factory/control_tower/infrastructure/sqlite/`.

#### `v2_pom_change_proposals`

| Column | Type | Notes |
|---|---|---|
| `proposal_id` | TEXT PK | UUID |
| `job_id` | TEXT NOT NULL | FK to v2_jobs |
| `stage_index` | INTEGER NOT NULL | Must be 3 |
| `user_request` | TEXT NOT NULL | Original user request |
| `server_plan_json` | TEXT NOT NULL | Server-validated plan |
| `risk` | TEXT NOT NULL | low/medium/high/blocked/evidence_insufficient |
| `can_apply` | INTEGER NOT NULL | 0 or 1 |
| `control_mode` | TEXT NOT NULL | From DependencyControlMode |
| `expected_checksum` | TEXT | Checksum of POM at proposal time |
| `expires_at` | TEXT | Optional TTL |
| `status` | TEXT NOT NULL DEFAULT 'active' | active/expired/consumed |
| `created_at` | TEXT NOT NULL | ISO8601 |

#### `v2_pom_changes`

| Column | Type | Notes |
|---|---|---|
| `change_id` | TEXT PK | UUID |
| `proposal_id` | TEXT | FK nullable |
| `job_id` | TEXT NOT NULL | FK |
| `stage_index` | INTEGER NOT NULL | Must be 3 |
| `operation` | TEXT NOT NULL | From ALLOWED_POM_OPERATIONS |
| `target_json` | TEXT NOT NULL | JSON serialized target |
| `requested_version` | TEXT NOT NULL | |
| `before_checksum` | TEXT NOT NULL | |
| `after_checksum` | TEXT NOT NULL | |
| `before_content_ref` | TEXT NOT NULL | Reference/artifact key |
| `after_content_ref` | TEXT NOT NULL | Reference/artifact key |
| `diff_unified` | TEXT NOT NULL | |
| `status` | TEXT NOT NULL | applied_pending_validation / validated_passed / validated_failed / repair_applied / rolled_back |
| `validation_id` | TEXT | FK nullable |
| `rollback_id` | TEXT | FK nullable |
| `idempotency_key` | TEXT | Unique per job_id for dedup |
| `executor` | TEXT NOT NULL DEFAULT 'pom_span_patch' | Which executor was used |
| `created_at` | TEXT NOT NULL | ISO8601 |
| `updated_at` | TEXT NOT NULL | ISO8601 |

#### `v2_pom_validations`

| Column | Type | Notes |
|---|---|---|
| `validation_id` | TEXT PK | UUID |
| `change_id` | TEXT NOT NULL | FK |
| `job_id` | TEXT NOT NULL | FK |
| `stage_index` | INTEGER NOT NULL | 3 |
| `command` | TEXT NOT NULL | Maven command used |
| `status` | TEXT NOT NULL | running / passed / failed / timed_out |
| `exit_code` | INTEGER | |
| `duration_ms` | INTEGER | |
| `log_ref` | TEXT | Reference to log artifact |
| `test_log_ref` | TEXT | Reference to test log artifact |
| `failure_classification` | TEXT | From failure classifications |
| `diagnosis_json` | TEXT | JSON diagnosis object |
| `created_at` | TEXT NOT NULL | ISO8601 |
| `completed_at` | TEXT | ISO8601 |

#### `v2_pom_repair_plans`

| Column | Type | Notes |
|---|---|---|
| `repair_plan_id` | TEXT PK | UUID |
| `validation_id` | TEXT NOT NULL | FK |
| `change_id` | TEXT NOT NULL | FK |
| `summary` | TEXT NOT NULL | |
| `steps_json` | TEXT NOT NULL | JSON array of steps |
| `confidence` | TEXT NOT NULL | low/medium/high |
| `evidence_refs_json` | TEXT NOT NULL | JSON array of evidence refs |
| `status` | TEXT NOT NULL | proposed/applied/expired |
| `created_at` | TEXT NOT NULL | ISO8601 |

### 5.2 Idempotency

- `idempotency_key` is required for `POST apply-change`, `POST repair`, `POST rollback`
- Duplicate apply request with the same `idempotency_key` returns the existing result, not a second write
- Lookup: `SELECT * FROM v2_pom_changes WHERE job_id = ? AND idempotency_key = ?`
- Retry-safe event emission must not duplicate writes

### 5.3 Repository Pattern

Add repository classes in `migration_factory/control_tower/infrastructure/sqlite/repositories.py`:

```python
class SqlitePomChangeProposalRepository: ...
class SqlitePomChangeRepository: ...
class SqlitePomValidationRepository: ...
class SqlitePomRepairPlanRepository: ...
```

Follow existing repository patterns (unit of work, typed Row factories, context managers).

---

## 6. POM Patcher Design

### 6.1 Formatting-Preserving Patch Strategy

Do not use `xml.etree.ElementTree` to serialize the full POM. It destroys formatting, comments, order, namespace prefixes, and schema URLs.

Instead:

1. Parse XML with a parser that retains position/span info (e.g., `lxml.etree` or `xml.etree` for node location only)
2. Identify target nodes and verify XML well-formedness
3. Apply **minimal text/span edits** to the raw POM text:
   - Locate the exact `<version>` child element of the target dependency/property/plugin
   - Replace only the version text node
   - Preserve all surrounding whitespace, comments, and formatting
4. After patch, parse the modified XML again to verify well-formedness
5. Compute checksum (SHA-256) of the full file
6. Compute unified diff

### 6.2 Supported Operations

The patcher must support these exact operations:

| Operation | Patch Strategy |
|---|---|
| `update_property_version` | Replace text content of `<version>` or value element within the named property |
| `update_dependency_version` | Replace text content of `<version>` within the identified dependency block |
| `remove_dependency_version` | Remove `<version>` element from dependency when BOM-managed |
| `change_dependency_coordinates` | Replace `<groupId>` and/or `<artifactId>` text content |
| `add_dependency` | Insert a well-formed `<dependency>` block, preserving surrounding whitespace |
| `remove_dependency` | Remove the identified `<dependency>` block |
| `add_or_update_dependency_management_entry` | Insert or update within `<dependencyManagement>` |
| `update_plugin_version` | Replace `<version>` within a `<plugin>` block |

### 6.3 Complex Operations

For complex changes (coordinate migrations, BOM restructuring, multi-module patching), the backend may use:

- **OpenRewrite** — via existing recipe infrastructure if available
- **repair_loop patching** — via existing `patch_apply` machinery

The `executor` field in `v2_pom_changes` records which executor was actually used.

---

## 7. Stage and Baseline Rules

### 7.1 Stage Enforcement

- Stage 1/2: can **explain/show** POM and identify **risks**, but **cannot apply** final dependency modernization
- Stage 3 is **required** for apply
- `PomDependencyEditor.apply_change_*()` refuses if stage != 3
- `PomDependencyEditor.apply_change_*()` refuses if Stage 3 sandbox is unavailable, incomplete, or unstable

### 7.2 Baseline Detection

Java/Spring Boot baseline must be **detected from Stage 3 root POM evidence**, not hardcoded:

Detection sources (in priority order):
1. root_pom parent `spring-boot-starter-parent` version
2. root_pom `dependencyManagement` `spring-boot-dependencies` BOM version
3. root_pom property `spring-boot.version`
4. `target_dependency_plan` / `migration_plan.yaml` / `dependency_policy_report` artifacts
5. `java.version` property in root_pom

**Never hardcode** Java 21, Spring Boot 3, or any specific version in the logic. The product may target those versions for the demo, but the implementation must detect from evidence. The existing `_detect_stage3_baseline()` function in `app.py` already implements this pattern.

### 7.3 Assistant Claim Rules

- Assistant **must never** claim "validation passed" before backend emits `pom_validation_passed` event
- Assistant **must never** claim "change applied and everything is good" — must say "change applied, validation is running"
- Assistant must report validation status from backend evidence/events only
- If evidence is insufficient, assistant must say "evidence is insufficient"

---

## 8. Repair Plan Design

### 8.1 Evidence-Based Failure Diagnosis

`PomValidationDiagnoser` must use only real log evidence to diagnose failures:

1. **Maven exit code** — determines severity and phase
2. **Failed phase** — compile, test, package, dependency resolution
3. **Dependency resolution errors** — missing artifact, version conflict, BOM mismatch
4. **Compiler errors** — symbol not found, incompatible types, deprecated API removed
5. **Test report excerpts** — failed test names and assertions
6. **Log refs** — references to full log artifacts, never inline full logs
7. **Change diff** — identifies what changed to correlate with failures

### 8.2 Diagnosis Rules

- If log evidence is sufficient to identify root cause → emit specific diagnosis
- If log evidence is insufficient → emit `evidence_insufficient` diagnosis with missing evidence list
- Never emit generic/fake root cause (e.g., never say "unknown error" when logs are available)
- Never emit the word "probably" without citing specific log evidence

### 8.3 Repair Plan Rules

- Failed state is **preserved** — no auto-rollback
- User can **apply repair** or **rollback**
- Repair plan steps must cite specific evidence sources
- Repair plan confidence must be backed by evidence mapping
- No default/automatic repair — human must decide

### 8.4 Rollback

- Backend restores POM from stored `before_content_ref`
- Verifies restored checksum matches stored `before_checksum`
- If checksum mismatch → refuse rollback, emit error event
- Rollback is idempotent (same `idempotency_key` returns existing result)
- After rollback, optionally triggers re-validation

---

## 9. Frontend Plan

### 9.1 Component Location

Verify actual route structure. The existing cockpit is at:

```
web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx
```

Place the new component near the cockpit:

```
web/control-tower/app/migrations/[jobId]/Stage3DependencyReview.tsx
```

Or as a sub-component:

```
web/control-tower/app/migrations/[jobId]/components/Stage3DependencyReview.tsx
```

### 9.2 New Types in `contracts.ts`

```typescript
// Stage 3 POM dependency review types
export type PomBaseline = {
  java_version: string;
  spring_boot_version: string;
  spring_boot_version_location: string;
  detected_from: string[];
};

export type PomDependencyFinding = {
  dependency_name: string;
  current_version: string;
  source_location: string;
  bucket: string;
  control_mode: string;
  risk: string;
  recommended_action: string;
  can_apply_now: boolean;
  reason: string;
  evidence_source: string;
};

export type PomDependencyReview = {
  job_id: string;
  stage: number;
  baseline: PomBaseline;
  buckets: Record<string, PomDependencyFinding[]>;
  findings: PomDependencyFinding[];
  evidence_loaded: string[];
  evidence_missing: string[];
  warnings: string[];
  created_at: string;
};

export type PomChangePlan = {
  intent: string;
  stage: number;
  operation: string;
  target: {
    kind: string;
    group_id?: string;
    artifact_id?: string;
    property_name?: string;
  };
  requested_version: string;
  risk: string;
  control_mode: string;
  requires_validation: boolean;
  evidence?: string[];
  rationale?: string;
};

export type PomChangeProposal = {
  proposal_id: string;
  server_validated_plan_preview: Record<string, unknown>;
  risk: string;
  can_apply: boolean;
  warnings: string[];
  applied: boolean;
  control_mode: string;
  created_at: string;
};

export type PomApplyResult = {
  change_id: string;
  status: string;
  operation: string;
  target_desc: string;
  before_version: string;
  after_version: string;
  before_checksum: string;
  after_checksum: string;
  diff_summary: string;
  validation_id: string | null;
  rollback_available: boolean;
  idempotency_key: string | null;
  created_at: string;
  message: string;
};

export type PomValidationFailureDiagnosis = {
  failure_classification: string;
  failed_phase: string;
  exit_code: number;
  log_excerpt: string;
  log_ref: string;
  root_cause: string;
  evidence_sufficient: boolean;
  missing_evidence: string[];
};

export type PomRepairPlan = {
  repair_plan_id: string;
  change_id: string;
  summary: string;
  detailed_steps: string[];
  confidence: string;
  evidence_sources: string[];
  actions_available: string[];
  created_at: string;
};

export type PomValidationRun = {
  validation_id: string;
  change_id: string;
  status: string;
  command: string;
  build_status: string;
  test_status: string;
  exit_code: number | null;
  duration_ms: number | null;
  log_ref: string | null;
  test_log_ref: string | null;
  diagnosis: PomValidationFailureDiagnosis | null;
  repair_plan: PomRepairPlan | null;
  created_at: string;
  completed_at: string | null;
};

export type PomRollbackResult = {
  change_id: string;
  rollback_id: string;
  status: string;
  checksum_restored: boolean;
  validation_triggered: boolean;
  validation_id: string | null;
  created_at: string;
};

export type PomView = {
  job_id: string;
  stage: number;
  exists: boolean;
  content: string;
  truncated: boolean;
  content_type: string;
  redaction_applied: boolean;
  detected_baseline: PomBaseline | null;
  reason: string | null;
};

export type PomChangeRecordSummary = {
  change_id: string;
  operation: string;
  target_desc: string;
  before_version: string;
  after_version: string;
  before_checksum: string;
  after_checksum: string;
  diff_summary: string;
  status: string;
  validation_id: string | null;
  rollback_id: string | null;
  created_at: string;
};

export type PomProposeRequest = {
  user_request: string;
  idempotency_key?: string;
};

export type PomApplyRequest = {
  proposal_id?: string;
  user_request?: string;
  idempotency_key?: string;
};
```

### 9.3 New API Client Functions in `controlTowerApi.ts`

```typescript
export async function getStage3Pom(jobId: string): Promise<PomView>
export async function getStage3DependencyReview(jobId: string): Promise<PomDependencyReview>
export async function proposePomChange(jobId: string, request: PomProposeRequest): Promise<PomChangeProposal>
export async function applyPomChange(jobId: string, request: PomApplyRequest): Promise<PomApplyResult>
export async function listPomChanges(jobId: string): Promise<{ changes: PomChangeRecordSummary[] }>
export async function getPomChange(jobId: string, changeId: string): Promise<PomChangeRecordSummary>
export async function getPomValidationResult(jobId: string, validationId: string): Promise<PomValidationRun>
export async function applyPomRepairPlan(jobId: string, repairPlanId: string, idempotencyKey: string): Promise<PomApplyResult>
export async function rollbackPomChange(jobId: string, changeId: string, idempotencyKey: string): Promise<PomRollbackResult>
```

### 9.4 New Component: `Stage3DependencyReview.tsx`

**Structure:** Tabbed panel with sections:

1. **Current POM tab** — Renders the redacted POM content with syntax highlighting
2. **Dependency Review tab** — Table of findings by bucket, with risk badges, control mode, action buttons
3. **Proposed Changes tab** — Shows pending proposals with diff excerpts
4. **Diff tab** — Shows before/after diff for applied changes
5. **Validation tab** — Shows validation status, build/test results, log refs (not raw logs)
6. **Repair Plan tab** — Shows diagnosis and repair plan when validation fails
7. **Evidence tab** — Shows loaded evidence sources

**Integration:** The component is conditionally rendered in `MigrationCockpit.tsx` when the job has a completed Stage 3. It receives `jobId` as a prop and manages its own fetch/state.

### 9.5 UI States

| State | What User Sees |
|---|---|
| Stage 3 not completed | "Stage 3 is not yet completed. Dependency editing is not available." |
| Stage 3 completed, no changes | Current POM tab active. "Request a review" and "Propose a change" buttons available. |
| Dependency review loaded | Bucketed findings table. "Apply" buttons for `can_apply_now: true` items. |
| Proposal generated | Proposal card with before/after XML, warnings, risks. "Apply this change" button. |
| Change applied, validating | Status badge: "VALIDATING". Spinner. Message: "Change applied. Validation is running." |
| Validation passed | Status badge: "PASSED". Green checkmark. Evidence summary. |
| Validation failed | Status badge: "FAILED". Red X. Diagnosis card with root cause from log evidence. Repair plan card. "Apply Repair" and "Rollback" buttons. |
| Repair applied | Back to VALIDATING state, then re-evaluates. |
| Rolled back | Status: "ROLLED BACK". Previous POM state restored. |

### 9.6 SSE Integration

The `MigrationCockpit` already listens to V2 events via SSE. The new component catches `pom_change_*` and `pom_validation_*` event types from the existing event stream to auto-update. No new SSE connection needed. Frontend must verify events come from the SSE stream (backend-authoritative), not from optimistic local state.

---

## 10. Security/Redaction Plan

### 10.1 Path Safety

- The backend resolves Stage 3 sandbox POM via `_resolve_stage_sandbox_root(stage=3)`, same as existing `_resolve_root_pom_file_alias_preview()`
- Write operations use the **same resolved path** — no user-provided paths accepted
- Before write: verify resolved path is within sandbox via `candidate.relative_to(resolved_root)`
- After write: verify new checksum and that file still exists in sandbox
- `_is_unsafe_sandbox_root()` prevents path traversal attacks

### 10.2 Checksum Safety

- `patch_policy.py` already provides sandbox snapshot and checksum verification
- Before every POM write: compute `before_checksum` and compare with stored `expected_checksum` (from proposal or last known state)
- After every POM write: compute `after_checksum`, record in change record
- Rollback: restore from stored `before_content_ref` and verify `before_checksum`

### 10.3 Prompt Injection Safety

- The LLM produces a structured plan JSON, but the backend revalidates it server-side
- Backend validates before writing:
  - Operation is in `ALLOWED_POM_OPERATIONS`
  - Stage is exactly 3
  - Target dependency/property exists (or operation is `add_*`)
  - Requested version is non-empty and matches a reasonable pattern
  - Target file is the fixed `root_pom` alias (resolved internally)
  - Policy decision allows the operation
- If validation fails, the change is rejected with a specific error message

### 10.4 No Raw Sandbox Paths or Secrets

All public responses pass through `redact_model_summary()` and `redact_public_value()` from `redaction.py`. The existing `_resolve_root_pom_file_alias_preview()` already pops `_path` from public response — same pattern for F14 endpoints. Sandbox path is never included in API responses, SSE events, or frontend rendering.

### 10.5 No Original Repo Mutation

- Stage validation: `apply_change_*()` refuses unless stage == 3
- Path validation: resolved path must be within Stage 3 sandbox (verified via `_resolve_stage_sandbox_root`)
- Write validation: operation is only applied to the resolved sandbox POM path, never to original repo

### 10.6 Event Payload Safety

- No absolute sandbox paths in event payloads
- No raw secrets or tokens in events
- No full build logs in SSE events — use `log_ref` references
- Include `change_id`, `validation_id`, `status`, `target_desc`, `risk`, `stage_index`, `diff_summary`, `log_ref` where appropriate
- Frontend must never render raw sandbox paths received from any API or event

---

## 11. Test Plan

### 11.1 Backend Test Files (New)

| Test File | Cases | What It Proves |
|---|---|---|
| `tests/control_tower/test_v2_stage3_pom_dependency_review.py` | ~10 | Dependency review returns correct buckets; baseline detection from evidence; Stage 1/2 defers; evidence loading; control mode detection for direct/property/BOM/transitive/not_present |
| `tests/control_tower/test_v2_stage3_pom_apply.py` | ~18 | Specific apply patches only Stage 3 sandbox; refuses arbitrary path; refuses incomplete Stage 3; apply endpoint rejects full client-submitted `PomChangePlan` unless server revalidates from `proposal_id`/`user_request`; duplicate apply with same `idempotency_key` does not write twice; chat "change gson to 2.11.0" and UI apply both call same service path; "propose gson update" creates no file write; "fix all dependencies" creates no file write and returns review/proposal; Stage 1/2 apply requests are rejected/deferred; Stage 3 incomplete/unstable rejects apply; transitive-only dependency request does not blindly add direct dependency; dependencyManagement/BOM-managed dependency removes version or proposes policy-aware action; high-risk operation requires explicit high-risk confirmation or action-card policy; apply creates change record with checksum and diff; apply emits event; apply returns immediately with `applied_pending_validation` |
| `tests/control_tower/test_v2_stage3_pom_validation.py` | ~6 | Validation starts asynchronously after apply; assistant does not claim validated success before validation passed event; passed validation emits success event; failed validation emits diagnosis; validation uses Stage 3 sandbox Maven |
| `tests/control_tower/test_v2_stage3_pom_repair_plan.py` | ~8 | Failed validation generates repair plan from log evidence; repair plan is evidence-based not generic; insufficient log evidence returns evidence-insufficient diagnosis; rollback uses stored before content/checksum; rollback is idempotent; rollback restores checksum |
| `tests/control_tower/test_v2_stage3_pom_redaction.py` | ~6 | No raw sandbox path leaks in API responses; no raw sandbox path in event payloads; no secrets in SSE events; public POM view is redacted; change record summaries don't expose raw paths; frontend contract types match backend redaction patterns |

### 11.2 Existing Tests to Extend

| Test File | Extension |
|---|---|
| `test_v2_assistant_stage3_dependency_review.py` | Add tests for `apply_dependency_change` intent routing; verify assistant response when backend applies vs. blocks |
| `test_v2_assistant_pom_proposal.py` | Add tests for validate-then-reject invalid plans |
| `test_v1_00d_redaction_baseline.py` | Add redaction check for POM change event payloads |

### 11.3 Frontend Tests

| Test | What It Proves |
|---|---|
| `web/control-tower/tests/stage3DependencyReview.test.tsx` | Component renders tabs correctly; apply change shows validation running state; failed validation shows repair plan; passed validation shows validated state; rollback button appears only when available; no raw sandbox path rendered; SSE events update component state |

### 11.4 Verification Commands

```bash
# Backend — new tests
python -m pytest tests/control_tower/test_v2_stage3_pom_dependency_review.py -q -rs --tb=short
python -m pytest tests/control_tower/test_v2_stage3_pom_apply.py -q -rs --tb=short
python -m pytest tests/control_tower/test_v2_stage3_pom_validation.py -q -rs --tb=short
python -m pytest tests/control_tower/test_v2_stage3_pom_repair_plan.py -q -rs --tb=short
python -m pytest tests/control_tower/test_v2_stage3_pom_redaction.py -q -rs --tb=short

# Backend — existing tests (regression)
python -m pytest tests/control_tower/test_v2_assistant_stage3_dependency_review.py -q -rs --tb=short
python -m pytest tests/control_tower/test_v2_assistant_pom_proposal.py -q -rs --tb=short
python -m pytest tests/control_tower/test_v1_00d_redaction_baseline.py -q -rs --tb=short

# Frontend (if UI changes)
cd web/control-tower && npx tsc --noEmit && npm test && npm run build
```

---

## 12. Implementation Sequence

### Phase 1: Foundation — Models, Persistence, and Review (No Writes)

**Goal:** Users can view Stage 3 POM and get dependency review. No files are written. Persistence tables created.

| Order | File | Action | Notes |
|---|---|---|---|
| 1.1 | `pom_change_models.py` | Create | All dataclasses for F14 domain |
| 1.2 | SQLite migration | Create | Tables: `v2_pom_change_proposals`, `v2_pom_changes`, `v2_pom_validations`, `v2_pom_repair_plans` |
| 1.3 | `repositories.py` | Extend | Add PomChangeProposal, PomChange, PomValidation, PomRepairPlan repositories |
| 1.4 | `pom_dependency_policy.py` | Create | Generic dependency compatibility policy: control mode detection, risk evaluation, decision object |
| 1.5 | `pom_dependency_review.py` | Create | Dependency review service: loads evidence, detects baseline, classifies dependencies into buckets, integrates with policy layer |
| 1.6 | `pom_dependency_editor.py` | Create | Skeleton orchestrator with `get_stage3_pom()`, `review_stage3_dependencies()`, `propose_change()` |
| 1.7 | `app.py` | Add endpoints: `GET /stage/3/pom`, `GET /stage/3/dependency-review`, `POST /stage/3/pom/propose-change` | Thin handlers |
| 1.8 | `contracts.ts` | Add `PomView`, `PomDependencyReview`, `PomBaseline`, `PomDependencyFinding`, `PomChangeProposal`, `PomProposeRequest` | |
| 1.9 | `controlTowerApi.ts` | Add `getStage3Pom()`, `getStage3DependencyReview()`, `proposePomChange()` | |
| 1.10 | `Stage3DependencyReview.tsx` | Create | Component with Current POM and Dependency Review tabs |
| 1.11 | `MigrationCockpit.tsx` | Integrate | Conditionally render `Stage3DependencyReview` when Stage 3 completed |
| 1.12 | `test_v2_stage3_pom_dependency_review.py` | Create | ~10 test cases for review |

**Verification:** Load cockpit, see Stage 3 POM and dependency review. No writes occur. Proposals generate but no file is modified.

### Phase 2: Backend POM Write + Policy Gate + Async Validation

**Goal:** User applies a change. Backend validates through policy layer, writes to Stage 3 sandbox POM only. Auto-validation triggers asynchronously.

| Order | File | Action | Notes |
|---|---|---|---|
| 2.1 | `pom_xml_patcher.py` | Create | Formatting-preserving XML patch engine with well-formedness verification |
| 2.2 | `pom_change_proposer.py` | Create | Server-side change validation: classifies user_request, integrates with policy layer, produces validated plan |
| 2.3 | `PomDependencyEditor.apply_change_from_user_request()` | Implement | Validates through proposer + policy, resolves sandbox path, calls patcher, persists change, emits event, enqueues async validation |
| 2.4 | `PomDependencyEditor.apply_change_from_proposal()` | Implement | Reloads proposal, revalidates checksum, then same as above |
| 2.5 | `PomDependencyEditor.enqueue_validation()` | Implement | Launches Maven build/test via `StageCommandLaunchService`, does NOT block |
| 2.6 | `app.py` | Add endpoints: `POST /stage/3/pom/apply-change`, `GET /stage/3/pom/changes`, `GET /stage/3/pom/changes/{id}`, `GET /stage/3/pom/validation/{id}` | Thin handlers, all logic in service |
| 2.7 | `_classify_v2_assistant_intent()` | Extend | Route `apply_dependency_change` to same `PomDependencyEditor` service |
| 2.8 | `_build_v2_assistant_answer()` | Extend | Build assistant response from `PomApplyResult` (not from LLM guess) |
| 2.9 | `v2_model_schemas.py` | Extend | Add `apply_pom_change` to `F05_ALLOWED_ACTION_TYPES` if needed |
| 2.10 | `contracts.ts` | Add `PomApplyResult`, `PomApplyRequest`, `PomChangeRecordSummary`, `PomValidationRun` | |
| 2.11 | `controlTowerApi.ts` | Add `applyPomChange()`, `listPomChanges()`, `getPomChange()`, `getPomValidationResult()` | |
| 2.12 | `Stage3DependencyReview.tsx` | Add Apply button, Diff tab, Validation tab | |
| 2.13 | `test_v2_stage3_pom_apply.py` | Create | ~18 test cases for apply safety |
| 2.14 | `test_v2_stage3_pom_validation.py` | Create | ~6 test cases for async validation flow |

**Verification:** Apply change → POM file changes in sandbox → event emitted → validation enqueued → returns immediately with `applied_pending_validation`. Chat "change gson to 2.11.0" and UI button both call same `PomDependencyEditor` path. Duplicate idempotency_key does not write twice.

### Phase 3: Failure Diagnosis + Repair Plan + Rollback

**Goal:** When validation fails, system classifies failure from log evidence, generates repair plan. User can apply repair or rollback.

| Order | File | Action | Notes |
|---|---|---|---|
| 3.1 | `pom_validation_diagnosis.py` | Create | Parses Maven/build output, classifies failures, generates evidence-based repair plan, handles evidence-insufficient case |
| 3.2 | `PomDependencyEditor.explain_validation_failure()` | Implement | Delegates to diagnoser |
| 3.3 | `PomDependencyEditor.rollback_change()` | Implement | Restores POM from stored before-content, verifies checksum, idempotent |
| 3.4 | `PomDependencyEditor.apply_repair_plan()` | Implement | Applies repair steps, re-triggers async validation |
| 3.5 | `app.py` | Add endpoints: `POST /stage/3/pom/repair`, `POST /stage/3/pom/rollback` | |
| 3.6 | `contracts.ts` | Add `PomValidationFailureDiagnosis`, `PomRepairPlan`, `PomRollbackResult` | |
| 3.7 | `controlTowerApi.ts` | Add `applyPomRepairPlan()`, `rollbackPomChange()` | |
| 3.8 | `Stage3DependencyReview.tsx` | Add Repair Plan and Evidence tabs, rollback button | |
| 3.9 | `test_v2_stage3_pom_repair_plan.py` | Create | ~8 test cases for repair/rollback |
| 3.10 | `test_v2_stage3_pom_redaction.py` | Create | ~6 test cases for redaction |

**Verification:** Bad dependency change → validation fails → diagnosis shown from log evidence → repair plan offered → rollback works and is idempotent → insufficient evidence returns honest diagnosis.

### Phase 4: Integration and Polish

| Order | File | Action | Notes |
|---|---|---|---|
| 4.1 | `app.py` | SSE enrichment | Ensure `pom_change_*` and `pom_validation_*` events appear in SSE stream for frontend auto-update |
| 4.2 | `_classify_v2_assistant_intent()` | Finalize | Add all new intents with proper priorities; ensure vague requests route to propose only |
| 4.3 | `_build_v2_assistant_prompt()` | Extend | Include POM change history, validation results in prompt context |
| 4.4 | `pom_change_models.py` | Add `to_public_dict()` methods | Ensure all models have redacted public serialization |
| 4.5 | Frontend tests | Create | `stage3DependencyReview.test.tsx` |
| 4.6 | Regression tests | Run | All existing F02/F04/F05/F07 tests |

---

## 13. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| XML patcher corrupts POM structure | Medium | High | Use span-targeted text edits, not full XML serialization. Always snapshot full file before write. Verify XML well-formedness after write with a parse step. |
| Stage 3 sandbox resolution fails during write | Low | High | Validate sandbox exists before write. Use same resolver as existing root_pom preview (proven path). Guard with `_is_unsafe_sandbox_root()`. |
| Validation job hangs indefinitely | Medium | Medium | Set command timeout via existing `TimeoutService`. Emit `pom_validation_failed` with timeout reason. |
| LLM produces invalid change plan JSON | Medium | Low | Backend revalidates plan server-side against policy before applying. Fallback: return structured error asking user to be more specific. |
| Multi-module POM: change applied to root but child modules break | High | Medium | Initial implementation patches only root POM (by design). Dependency review warns if child modules detected. Future iteration can add multi-module support. |
| Checksum mismatch on rollback | Low | High | Store full `before_content_ref`. Verify `before_checksum` matches before rollback. If mismatch, refuse rollback and emit error event. |
| Assistant bypasses structured plan and tries to write directly | Low | High | Existing guardrails in system prompt forbid writing. All write endpoints reject requests without validated server-side plan. `_classify_v2_assistant_intent` routes vague requests to propose-only. |
| Event burst on rapid apply/rollback/apply | Low | Low | Each operation is synchronous for write, async for validation. Idempotency key prevents duplicate apply. |
| Transitive dependency request: user insists on injecting direct dependency | Medium | Medium | Policy layer blocks transitive-only without explicit override strategy. User must confirm high-risk action with high-risk wording. |
| Validation runner detects wrong Maven command for multi-module project | Medium | Medium | Reuse `build_agent/detection.py` which already handles multi-module. Fallback: `mvn clean compile test -f pom.xml`. |
| POM formatting loss after patch | Medium | Medium | Span-targeted text edits preserve formatting. Post-patch XML parse verifies well-formedness. OpenRewrite fallback for complex changes. |
| High-risk operation without explicit confirmation | Medium | High | Policy layer requires high-risk wording or action-card approval. Blocked operations explain why and propose alternatives. |

---

## 14. Hard Constraints Checklist

| Constraint | How Enforced |
|---|---|
| No large business logic in `app.py` | All logic in new `application/pom_dependency_editor.py` and sub-services |
| No duplicate workspace/sandbox resolution | Reuse `_resolve_stage_sandbox_root()` from `app.py` |
| Chat and UI both use same backend service | `assistant/ask` intent → `PomDependencyEditor`; UI endpoint → `PomDependencyEditor` |
| No patch of original repo files | Stage 3 sandbox POM only; path verified via relative_to check |
| No user-provided paths accepted | Endpoints take `job_id` only; backend resolves sandbox path internally |
| No raw sandbox paths/secrets exposed | All responses redacted via `redact_public_value()`; event payloads use log_ref not raw content |
| No claim of applied change without write evidence | `PomApplyResult.status == "applied_pending_validation"` only after backend write + checksum verification |
| No claim of validation passed without build/test evidence | `PomValidationRun.status == "passed"` only after worker reports build_completed + test_completed |
| No guess of dependency versions | Versions from user request or target_dependency_plan/dependency_policy_report evidence |
| Frontend not trusted for change plans | `proposal_id` or `user_request` only; server revalidates everything before write |
| No hardcoded Java/Spring Boot versions | Baseline detected from Stage 3 root_pom evidence via `_detect_stage3_baseline()` |
| Validation never blocks HTTP response | Apply returns immediately; validation launched asynchronously via worker |
| Idempotency enforced | Duplicate apply/repair/rollback with same `idempotency_key` returns existing result |
| Compatible with F02/F04/F05/F07 | New services are additive; existing repair flow, reviewer, assistant guardrails unchanged |

---

## 15. Files to Create

1. `migration_factory/control_tower/application/pom_change_models.py`
2. `migration_factory/control_tower/application/pom_dependency_policy.py`
3. `migration_factory/control_tower/application/pom_dependency_editor.py`
4. `migration_factory/control_tower/application/pom_dependency_review.py`
5. `migration_factory/control_tower/application/pom_change_proposer.py`
6. `migration_factory/control_tower/application/pom_xml_patcher.py`
7. `migration_factory/control_tower/application/pom_validation_diagnosis.py`
8. SQLite migration for `v2_pom_change_proposals`, `v2_pom_changes`, `v2_pom_validations`, `v2_pom_repair_plans`
9. Repository classes in `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
10. `web/control-tower/app/migrations/[jobId]/Stage3DependencyReview.tsx`
11. `tests/control_tower/test_v2_stage3_pom_dependency_review.py`
12. `tests/control_tower/test_v2_stage3_pom_apply.py`
13. `tests/control_tower/test_v2_stage3_pom_validation.py`
14. `tests/control_tower/test_v2_stage3_pom_repair_plan.py`
15. `tests/control_tower/test_v2_stage3_pom_redaction.py`
16. `web/control-tower/tests/stage3DependencyReview.test.tsx`

## 16. Files to Modify

1. `migration_factory/control_tower/adapters/fastapi/app.py` — Add 9 new endpoints (~10 lines each) + extend intent classifier + add fallback answer builders for `apply_dependency_change`
2. `migration_factory/control_tower/application/v2_model_schemas.py` — Add `apply_pom_change`, `rollback_pom_change` to `F05_ALLOWED_ACTION_TYPES` if action-card integration needed
3. `migration_factory/control_tower/application/v2_assistant_model_client.py` — Minor extension to system prompt for generic dependency policy modes (only if needed)
4. `web/control-tower/lib/contracts.ts` — Add F14 TypeScript types
5. `web/control-tower/lib/controlTowerApi.ts` — Add 9 new API client functions
6. `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` — Integrate `Stage3DependencyReview` component
7. `tests/control_tower/test_v2_assistant_stage3_dependency_review.py` — Extend with apply intent tests
8. `tests/control_tower/test_v2_assistant_pom_proposal.py` — Extend with plan validation rejection tests

## 17. Files to Avoid Modifying Unless Integration Requires It

Prefer not to modify these files, but allow small focused changes if required for integration. Any modification must be justified in the implementation plan and covered by focused tests:

- `migration_factory/control_tower/application/v2_assistant_model_client.py` — system prompt extension only
- `migration_factory/control_tower/application/v2_assistant_service.py` — action type mapping extension only
- `migration_factory/control_tower/application/v2_repair_flow.py` — reuse via import; modify only if repair_loop integration requires it
- `migration_factory/control_tower/application/v2_pom_context_summary.py` — reuse pattern; modify only if review service needs extended summary fields
- `migration_factory/control_tower/application/redaction.py` — reuse functions; add new redaction patterns only if needed
- `migration_factory/repair_loop/*` — reuse via import; no changes expected
- `migration_factory/agents/*` — reuse via import; no changes expected

---

## 18. Acceptance Criteria

F14 plan is accepted and implementation is complete only if:

1. **Generic, not Tomcat-centered.** The dependency editing system handles any dependency/property/plugin/BOM/parent/dependencyManagement request, not just Tomcat.
2. **Stage 3 POM review works read-only.** Users can view and get classified dependency reviews without any file writes.
3. **Propose mode never writes.** "propose", "suggest", "review" requests produce proposals only, no file modifications.
4. **Explicit apply/change/update can write only through backend validation.** Specific requests with exact targets and versions are written after policy and checksum validation.
5. **Backend writes only to Stage 3 sandbox root_pom.** No original repo files modified. Path resolved internally, never from client.
6. **Frontend does not submit trusted change plans.** `proposal_id` or `user_request` + `idempotency_key` only. Server revalidates everything.
7. **Every apply persists change record, diff, checksum, and event.** Full audit trail in `v2_pom_changes` table.
8. **Every apply starts validation asynchronously.** Validation does not block the HTTP response. Returns `applied_pending_validation`.
9. **Validation pass/fail is reported from backend evidence.** Assistant and UI report from events/validation records, never from assumptions.
10. **Failure diagnosis is evidence-based and produces repair plan.** Diagnosis uses Maven exit code, failed phase, log excerpts, and change diff. Insufficient evidence produces honest "evidence insufficient" result.
11. **Rollback is available and checksum-guarded.** Restores from stored before-content, verifies checksum, idempotent.
12. **Dependency compatibility policy handles all control modes.** direct, property, dependencyManagement, BOM, plugin, transitive, inherited, not present, unknown.
13. **OpenRewrite is supported as backend executor for complex changes.** Backend records which executor was used. Simple changes use targeted POM patcher.
14. **No raw paths/secrets leak.** All API responses, SSE events, and frontend rendering are redacted. Event payloads use log_ref, not inline raw content.
15. **No hardcoded Java/Spring Boot version decisions.** Baseline detected from evidence.
16. **Existing F02/F04/F05/F07 behavior is not reopened** except for focused integration points (e.g., adding action types).
17. **Chat apply and UI apply use the same backend service path.** No separate business logic for assistant vs. UI endpoints.
18. **POM patcher preserves formatting.** Targeted text/span edits; XML well-formedness verified after patch.
19. **User wording policy enforced.** "propose/suggest/review" = no write; "fix all/upgrade everything" = propose only; "latest" = refused unless policy supplies version.

---

*Plan version: 2.0 | Date: 2026-06-16 | Author: AI Coding Agent (codebase analysis + 15 major corrections)*
*Corrections: Tomcat→generic, frontend trust removal, async validation, persistence+idempotency, formatting-preserving patcher, event safety, baseline detection, OpenRewrite executor role, reality gate*
