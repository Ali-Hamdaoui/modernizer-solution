# V2 Audit Fixing Plan

## 1. Second Audit Verdict

**Adjusted Verdict: PARTIALLY CONFIRMED — BLOCKED (adjusted)**

The first audit verdict ("BLOCKED, ~40% objective") is **mostly correct** but requires severity adjustments:

| Aspect | First audit | Second audit |
|--------|-------------|-------------|
| Working state | ~40% | ~40% |
| Verdict | BLOCKED | **PARTIALLY CONFIRMED — BLOCKED** |
| Key differentiator | Correctly identified unwired services | Confirms each finding from source; adds persistence gap in job+command creation |

**What actually works (durably):**
- V2 settings & redaction (A1) — env refs, redacted projections
- Env block parser (A2) — allowlist, blocked keys, no execution
- Setup CRUD + preflight persistence (A3) — SQLite tables 0028, fully wired
- Azure health check persistence (A4) — SQLite table 0029, fully wired
- New Migration form UI (A5) — `/migrations/new` with real API calls

**What is defined but NOT wired or not persisted:**
- V2 job creation (A6) — returns in-memory result only, no DB persistence
- V2 worker stage command manifest (A7) — returns in-memory result only, no DB persistence
- Stage auto-progression (A8) — defined, never called, no API endpoint
- Approval mapping (A9) — defined, in-memory only, no API endpoint, no persistence
- Assistant service (A10) — defined, in-memory only, no API endpoint, no persistence
- Model schemas (A11) — defined, never validated at runtime
- Repair flow (A12) — defined, in-memory only, no API endpoint, no persistence
- Cockpit (A13) — placeholder/simulated data, no real API integration

**Execution gap: A1-A5 are substantively implemented (wired + persisted + tested). A6-A13 are defined as classes but lack persistence, API wiring, or both. The product has strong form/setup foundations but zero end-to-end migration flow.**

---

## 2. Source Baseline

| Item | Value |
|------|-------|
| **Base branch** | `V2IMPROVMENT` |
| **HEAD** | `fe54324198e4b43ec1b2d9c07c3a2b414c42baf2` |
| **Worktree status** | `M web/control-tower/next-env.d.ts` (known untracked, expected) |
| **Tests run** | Backend: 1364 passed, 3 skipped. API security: 15 passed. Frontend: 122 passed. Typecheck: clean. Build: clean. |
| **Commands** | `pytest tests/control_tower -q --tb=short`, `npm test`, `npm run typecheck`, `npm run build`, `git diff --check` |

---

## 3. First Audit Finding Review

| # | Finding | Original Severity | Second-Audit Status | Evidence | Adjusted Severity | Notes |
|---|---------|-------------------|---------------------|----------|-------------------|-------|
| F1 | Form setup, env parser, settings/redaction, setup persistence, preflight, Azure env-ref health are mostly wired | Info | **Confirmed** | All six have API endpoints in app.py, SQLite persistence, and passing tests. NewMigrationForm.tsx uses real API calls. | Info | Well-implemented baseline. |
| F2 | V2 job creation has no durable persistence | Blocker | **Confirmed** | `V2MigrationJobService.create_job()` returns `V2MigrationJobResult` but never saves to DB. No SQL migration for V2 jobs. No `save_job()` method in any repository. | **Blocker** | P0. Must fix first — job is the central entity. |
| F3 | V2 command manifests are not persisted | Blocker | **Confirmed** | `V2WorkerStageService.build_stage1_manifest()` returns `V2StageCommandResult` without persistence. No SQL table for V2 command manifests. | **Blocker** | P0. Fix after F2. |
| F4 | Stage auto-progression is defined but unwired | Blocker | **Confirmed** | `V2StageProgressionService` exists but is never instantiated in app.py, never called from any endpoint, no persistence. | **Blocker** | P0. Fix after F8/F9. |
| F5 | Approval mapping is defined but unwired/in-memory | Blocker | **Confirmed** | `V2ApprovalMappingService` stores data in `self._decisions` dict. No SQL table, no repository, no API endpoints expose it. | **Blocker** | P0. Fix after F2/F3. |
| F6 | Assistant service is defined but unwired/in-memory | Blocker | **Confirmed** | `V2AssistantService` stores messages/drafts in-memory dicts. No SQL table, no API endpoints. | **Blocker** | P0. Fix after F5/F11. |
| F7 | Repair flow is defined but unwired/in-memory | Blocker | **Confirmed** | `V2RepairFlowService` stores proposals/actions in-memory dicts. No SQL table, no API endpoints. | **Blocker** | P0. Fix after F11/F5. |
| F8 | Model schemas are strict but unused at runtime | High | **Confirmed** | `SCHEMA_REGISTRY` defines 5 strict schemas with `additionalProperties: false`. No code validates model output against them at runtime. | **High** | P1. Add schema validation service. |
| F9 | Cockpit frontend uses simulated/placeholder data | High | **Confirmed** | `MigrationCockpit.tsx:24` — `// Simulated data load — real API integration follows`. Hardcoded mock stages, approvals, messages. Evidence is a dashed-border placeholder. Start button alerts "available in next update." | **High** | P0. Wire real API calls after A6-A12. |
| F10 | Runbook/test/security docs may overclaim implementation status | Medium | **Partially Confirmed** | OPERATOR_RUNBOOK.md V2 Addendum says "Implemented (A1-A13 merged)" which is true for code presence but misleading for runtime wiring. V2_SECURITY_REVIEW.md correctly finds no security issues but misses integrity risk of in-memory data loss. V2_TEST_REPORT.md accurately reports test counts without overclaiming. | Medium | Fix docs to reflect actual wiring state. |
| F11 | Missing E2E, adversarial assistant, API-level checksum, persistence durability tests | Blocker | **Confirmed** | No E2E integration tests. No adversarial assistant tests beyond FORBIDDEN_CAPABILITIES check. No API-level checksum mismatch tests (approval mapping has unit-level checksum check but no API integration test). No persistence durability/crash recovery tests. | **Blocker** | P2. Add after P0/P1. |

---

## 4. Product Gap Summary

### What works now (~40%)

The V2 foundation layers are solid:

```
User opens /migrations/new
  → Parses env block (A2 wired) ✅
  → Saves setup draft (A3 persisted) ✅
  → Runs preflight (A3 persisted, all deterministic gates checked) ✅
  → Sees Azure settings (A1/A4 wired, env refs only, non-blocking) ✅
  → Sees Start button (gated on deterministic readiness) ✅
  → Clicking Start shows alert("next update") ❌
```

### What blocks the real cockpit objective (~60% gap)

```
  → Create V2 job (A6: defined, NOT persisted) ❌
  → Persist Stage 1 manifest (A7: defined, NOT persisted) ❌
  → Queue Stage 1 runner (no worker integration yet) ❌
  → Approval interrupt → decision card (A9: in-memory only, NOT exposed) ❌
  → Resume after approval (no API endpoint) ❌
  → Auto-progress Stage 2/3 (A8: defined, NEVER CALLED) ❌
  → Assistant chat messages/streaming (A10: in-memory, NOT exposed) ❌
  → Repair proposal/approval/apply (A12: in-memory, NOT exposed) ❌
  → Model schema validation at runtime (A11: defined, UNUSED) ❌
  → Cockpit real API integration (A13: simulated/placeholder data) ❌
  → E2E integration tests (missing) ❌
```

### Root cause

The subagent approach created isolated service classes with clean interfaces but no integration pass to wire them together. Each agent wrote a service + unit tests + (sometimes) a wire in app.py. But A6-A12 did not create persistence tables or repositories for their services. The services operate entirely in-memory. No agent owned the integration wiring that connects A6 → A7 → A9 → A8 → A10 → A12 → A13 into one end-to-end flow.

---

## 5. Dependency-Aware Fix Sequence

### Phase P0: Persistence Foundations

| Step | Fix | Depends on |
|------|-----|-----------|
| P0a | Create migration 0030: `v2_migration_jobs` table + `v2_stage_commands` table | None |
| P0b | Add `save_job()` / `get_job()` to `SqliteV2SetupRepository` or new `SqliteV2JobRepository` | P0a |
| P0c | Add `save_command()` / `get_command()` to new `SqliteV2CommandRepository` | P0a |
| P0d | Create migration 0031: `v2_approval_decisions` table + `v2_resume_commands` table | P0a |
| P0e | Create migration 0032: `v2_assistant_messages` table + `v2_pending_action_drafts` table | P0a |
| P0f | Create migration 0033: `v2_repair_proposals` table + `v2_sandbox_actions` table | P0a |
| P0g | Update `SqliteControlTowerUnitOfWork` to expose all new repositories | P0b-P0f |

### Phase P0: Backend Runtime Wiring

| Step | Fix | Depends on |
|------|-----|-----------|
| P0h | Wire `V2MigrationJobService` to persist job to DB; update endpoint to return stored job ID | P0b |
| P0i | Wire `V2WorkerStageService` to persist command manifest to DB; update endpoint | P0c |
| P0j | Wire `V2ApprovalMappingService` to approval repo + expose API endpoints in app.py | P0d |
| P0k | Wire `V2StageProgressionService` — instantiate in app.py, add progression endpoint | P0h, P0j |
| P0l | Wire `V2AssistantService` to message repo + expose API endpoints in app.py | P0e |
| P0m | Wire `V2RepairFlowService` to repair repo + expose endpoints in app.py | P0f, P0j |

### Phase P0: Cockpit Real API Wiring

| Step | Fix | Depends on |
|------|-----|-----------|
| P0n | Replace `MigrationCockpit.tsx` simulated data with real API calls | P0h-P0m |
| P0o | Wire Start button to POST `/v1/v2/migration-jobs` then POST `/v1/v2/migration-jobs/start-stage1` | P0h, P0i |
| P0p | Add SSE streaming or polling for stage progression, approvals, and assistant messages | P0k, P0l |
| P0q | Add decision card UI bound to real approval API endpoints | P0j |

### Phase P1: Authority/Security Tests & Docs Correction

| Step | Fix | Depends on |
|------|-----|-----------|
| P1a | Add schema validation service that validates model output against `SCHEMA_REGISTRY` at runtime | None (parallel) |
| P1b | Add API-level checksum mismatch integration tests | P0j |
| P1c | Add adversarial assistant authority tests (execution attempts rejected) | P0l |
| P1d | Fix OPERATOR_RUNBOOK.md V2 Addendum to reflect actual wiring state | None (parallel) |
| P1e | Update V2_SECURITY_REVIEW.md to note in-memory data loss risk | None (parallel) |

### Phase P2: Preflight/Tool Validation & E2E Coverage

| Step | Fix | Depends on |
|------|-----|-----------|
| P2a | Add real JDK version subprocess checks in preflight (currently only path-exists) | None (parallel to P0) |
| P2b | Add real Maven version subprocess check | P2a |
| P2c | Add real AI Hub profile/catalog/policy checksum verification | None (parallel) |
| P2d | Write E2E integration test: form → setup → preflight → job → command → approval → resume | P0h-P0q |
| P2e | Write persistence durability test: verify data survives simulated crash/restart | P0a-P0g |
| P2f | Write stage progression integration test: Stage 1 complete → Stage 2 auto-queued | P0k |
| P2g | Write repair flow integration: failure → proposal → approval → patch → validate → rollback | P0m |

---

## 6. Proposed Fix Issues

### Issue P0-001: Add V2 job and command persistence tables

- **Title:** Add SQLite migrations for V2 job and command manifest persistence
- **Branch:** `v2/fix-p0-job-command-persistence`
- **Files likely touched:**
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0030_v2_jobs_and_commands.sql` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/v2_job_repository.py` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/v2_command_repository.py` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py` (update)
- **Scope:** Create SQL tables for V2 migration jobs and stage commands. Create repositories. Register in UoW.
- **Not in scope:** Wiring services (P0-002), progression (P0-004), approval (P0-003)
- **Acceptance criteria:**
  - Migration 0030 applies, rolls back
  - `v2_migration_jobs` table stores job_id, setup_id, setup_checksum, pipeline_id, stage_chain_json, status, created_at
  - `v2_stage_commands` table stores command_id, job_id, stage_index, manifest_checksum, argv_json, status, created_at
  - Append-only triggers exist on both tables
  - Unit tests verify save/read/list by job_id
- **Tests to run:** New migration tests, new repository tests, existing migration tests
- **Dependency:** None

### Issue P0-002: Wire V2 job creation service to persistence

- **Title:** Wire V2MigrationJobService to persist jobs and return stored job IDs
- **Branch:** `v2/fix-p0-job-service-wiring`
- **Files likely touched:**
  - `migration_factory/control_tower/application/v2_job_service.py` (update)
  - `migration_factory/control_tower/adapters/fastapi/app.py` (minor update to response)
  - `tests/control_tower/test_v2_job_service.py` (update)
- **Scope:** `create_job()` saves to repository. `StartV2JobRequest` validated against stored job. Endpoint returns stored job_id.
- **Not in scope:** Command persistence (P0-003), worker launch
- **Acceptance criteria:** Created job survives restart. Duplicate creation fails. Stale checksum fails.
- **Tests to run:** `test_v2_job_service.py`, API integration test for job creation
- **Dependency:** P0-001

### Issue P0-003: Wire V2 worker stage command to persistence

- **Title:** Wire V2WorkerStageService to persist command manifests
- **Branch:** `v2/fix-p0-worker-stage-persistence`
- **Files likely touched:**
  - `migration_factory/control_tower/application/v2_worker_stage.py` (update)
  - `migration_factory/control_tower/adapters/fastapi/app.py` (minor update)
  - `tests/control_tower/test_v2_worker_stage.py` (update)
- **Scope:** `build_stage1_manifest()` saves to repository. Return stored command_id.
- **Not in scope:** Worker process launch, approval mapping
- **Acceptance criteria:** Manifest survives restart. Validates setup still exists.
- **Tests to run:** `test_v2_worker_stage.py`, API test
- **Dependency:** P0-001

### Issue P0-004: Add approval, assistant, and repair persistence layers

- **Title:** Add SQLite migrations and repositories for approvals, assistant, and repair
- **Branch:** `v2/fix-p0-approval-assistant-repair-persistence`
- **Files likely touched:**
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0031_v2_approvals.sql` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0032_v2_assistant.sql` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0033_v2_repairs.sql` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/v2_approval_repository.py` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/v2_assistant_repository.py` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py` (new)
  - `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py` (update)
- **Scope:** Create tables + repositories for decision cards, resume commands, messages, pending drafts, repair proposals, sandbox actions. Append-only triggers.
- **Not in scope:** Wiring to services (P0-005, P0-006), API endpoints
- **Acceptance criteria:** All tables created with append-only triggers. Repositories tested for save/read/list.
- **Tests to run:** New migration and repository tests
- **Dependency:** P0-001

### Issue P0-005: Wire approval mapping and stage progression services

- **Title:** Wire V2ApprovalMappingService and V2StageProgressionService with persistence and API endpoints
- **Branch:** `v2/fix-p0-approval-stage-wiring`
- **Files likely touched:**
  - `migration_factory/control_tower/application/v2_approval_mapping.py` (update)
  - `migration_factory/control_tower/application/v2_stage_progression.py` (update)
  - `migration_factory/control_tower/adapters/fastapi/app.py` (add endpoints)
  - `tests/control_tower/test_v2_approval_mapping.py` (update)
  - `tests/control_tower/test_v2_stage_progression.py` (update)
- **Scope:** Approval service uses repository. Expose `POST /v1/v2/jobs/{job_id}/approvals/{card_id}/approve`, `POST /v1/v2/jobs/{job_id}/approvals/{card_id}/reject`, `POST /v1/v2/jobs/{job_id}/stages/progress`. Stage progression reads previous sandbox from DB and queues next stage.
- **Not in scope:** Assistant (P0-006), Repair (P0-007), Cockpit (P0-008)
- **Acceptance criteria:** Approval persists, resume command queued. Progression creates next stage command. Checksum validation.
- **Tests to run:** Updated approval and progression tests, new API integration tests
- **Dependency:** P0-004

### Issue P0-006: Wire assistant service with persistence and API endpoints

- **Title:** Wire V2AssistantService with persistence and API endpoints
- **Branch:** `v2/fix-p0-assistant-wiring`
- **Files likely touched:**
  - `migration_factory/control_tower/application/v2_assistant_service.py` (update)
  - `migration_factory/control_tower/adapters/fastapi/app.py` (add endpoints)
  - `tests/control_tower/test_v2_assistant_service.py` (update)
- **Scope:** Message and draft storage uses repository. Expose `GET/POST /v1/v2/jobs/{job_id}/assistant/messages`, `POST /v1/v2/jobs/{job_id}/assistant/actions/draft`.
- **Not in scope:** SSE streaming, repair flow, cockpit
- **Acceptance criteria:** Messages persist, drafts persist with status "draft", FORBIDDEN_CAPABILITIES still enforced.
- **Tests to run:** Updated assistant tests, new API tests
- **Dependency:** P0-004

### Issue P0-007: Wire repair flow service with persistence and API endpoints

- **Title:** Wire V2RepairFlowService with persistence and API endpoints
- **Branch:** `v2/fix-p0-repair-wiring`
- **Files likely touched:**
  - `migration_factory/control_tower/application/v2_repair_flow.py` (update)
  - `migration_factory/control_tower/adapters/fastapi/app.py` (add endpoints)
  - `tests/control_tower/test_v2_repair_flow.py` (update)
- **Scope:** Proposal and action storage uses repository. Expose proposal create, approve, apply endpoints.
- **Not in scope:** Cockpit integration
- **Acceptance criteria:** Proposals persist, approval required before apply, patch applies to sandbox only, rollback on failure.
- **Tests to run:** Updated repair tests, API tests
- **Dependency:** P0-004

### Issue P0-008: Wire cockpit with real API data

- **Title:** Wire MigrationCockpit with real V2 API data
- **Branch:** `v2/fix-p0-cockpit-real-api`
- **Files likely touched:**
  - `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` (major update)
  - `web/control-tower/lib/contracts.ts` (add V2 job/command/approval/assistant types)
  - `web/control-tower/lib/controlTowerApi.ts` (add V2 API methods)
  - `web/control-tower/tests/migrationCockpit.test.tsx` (update)
  - `web/control-tower/app/migrations/new/NewMigrationForm.tsx` (wire Start button)
- **Scope:** Replace simulated data with real `fetch()` calls to V2 APIs. Start button calls POST job + POST start-stage1. Stage timeline, decisions, evidence, assistant, proof panels display real data.
- **Not in scope:** SSE streaming (deferred to P0-009), visual polish
- **Acceptance criteria:** Cockpit shows real stage data. Start button triggers job creation and stage 1. No simulated data remains.
- **Tests to run:** Updated cockpit tests, new form tests for start flow
- **Dependency:** P0-002, P0-003, P0-005, P0-006, P0-007

### Issue P1-001: Add runtime schema validation for model outputs

- **Title:** Add runtime schema validation service using V2 model schemas
- **Branch:** `v2/fix-p1-schema-validation`
- **Files likely touched:**
  - `migration_factory/control_tower/application/v2_model_schemas.py` (add validation function)
  - `migration_factory/control_tower/application/v2_model_schemas.py` (add `validate_against_schema()`)
  - `tests/control_tower/test_v2_model_schemas.py` (add validation tests)
- **Scope:** Add a `validate_against_schema(schema_name, data)` function that validates a dict against the registered schema. Use `jsonschema` or manual checks.
- **Not in scope:** Model call pipeline integration
- **Acceptance criteria:** Valid data passes, invalid data fails with descriptive error. All 5 schemas tested.
- **Tests to run:** `test_v2_model_schemas.py`
- **Dependency:** None

### Issue P1-002: Correct docs to reflect wiring state

- **Title:** Update docs to accurately describe V2 implementation state
- **Branch:** `v2/fix-p1-docs-correction`
- **Files likely touched:**
  - `OPERATOR_RUNBOOK.md` — update V2 Addendum
  - `docs/security/V2_SECURITY_REVIEW.md` — add in-memory data loss risk
  - `V2_IMPLEMENTATION_SUBAGENT_PLAN.md` — update integration status
- **Scope:** Fix overclaiming statements in runbook, security review, and plan
- **Not in scope:** Product code
- **Acceptance criteria:** No statement claims a V2 feature is implemented unless it is wired, persisted, and API-exposed.
- **Tests to run:** `git diff --check`
- **Dependency:** None (parallel)

### Issue P2-001: Add E2E and persistence durability tests

- **Title:** Add E2E integration, adversarial assistant, and persistence durability tests
- **Branch:** `v2/fix-p2-e2e-durability-tests`
- **Files likely touched:**
  - `tests/control_tower/test_v2_e2e.py` (new — full form → setup → preflight → job → stage1 → approval → resume flow)
  - `tests/control_tower/test_v2_assistant_adversarial.py` (new)
  - `tests/control_tower/test_v2_checksum_api.py` (new)
  - `tests/control_tower/test_v2_persistence_durability.py` (new)
- **Scope:** Full E2E integration test. Adversarial tests for assistant FORBIDDEN_CAPABILITIES at API level. Checksum mismatch tests. Persistence durability (save then reload in new UoW).
- **Not in scope:** Live Azure calls, visual snapshot tests
- **Acceptance criteria:** All new tests pass. E2E covers the critical path. Adversarial tests confirm assistant cannot execute/approve/write.
- **Tests to run:** All new test files plus existing regressions
- **Dependency:** P0-008, P0-005, P0-006, P0-007

### Issue P2-002: Add real JDK/Maven/AI Hub version checks in preflight

- **Title:** Add real subprocess checks for JDK version, Maven version, and AI Hub checksums in preflight
- **Branch:** `v2/fix-p2-preflight-real-checks`
- **Files likely touched:**
  - `migration_factory/control_tower/application/v2_setup_service.py` (update `_compute_readiness`)
  - `tests/control_tower/test_v2_setup_service.py` (update)
- **Scope:** `_check_jdk_path` runs `java -version` and parses major version. `_check_maven_path` runs `mvn --version`. AI Hub checksums verified.
- **Not in scope:** Azure health live checks (deferred)
- **Acceptance criteria:** JDK check verifies actual major version matches expected. Maven check runs under timeout. AI Hub profile checksums validate.
- **Tests to run:** `test_v2_setup_service.py`, preflight API tests
- **Dependency:** None (parallel with P0)

---

## 7. Test Strategy

| Test Type | Coverage | Priority | Target Files |
|-----------|----------|----------|-------------|
| **Unit tests (existing)** | Service logic, edge cases, validation | P0 | `test_v2_*.py` (all V2 test files) |
| **Persistence durability tests** | Save → reconnect → read verifies data survives | P2 | `test_v2_persistence_durability.py` |
| **API integration tests** | Endpoint → service → repository round trip | P0 | `test_v2_job_service.py`, `test_v2_worker_stage.py`, `test_v2_approval_mapping.py`, `test_v2_assistant_service.py`, `test_v2_repair_flow.py` |
| **Checksum gating tests** | Mismatch rejection at API level | P1 | `test_v2_checksum_api.py` |
| **Adversarial assistant tests** | FORBIDDEN_CAPABILITIES enforced at API level | P1 | `test_v2_assistant_adversarial.py` |
| **Stage progression tests** | Stage 2/3 auto-queue after completion | P0 | `test_v2_stage_progression.py` |
| **E2E integration** | Full flow: form → setup → preflight → job → stage1 → approval → resume | P2 | `test_v2_e2e.py` |
| **Frontend unit tests (existing)** | Form contract, no forbidden fields, Azure non-blocking | P0 | `newMigrationForm.test.tsx`, `migrationCockpit.test.tsx` |
| **Frontend integration tests** | Start button triggers real API, cockpit shows live data | P0 | Updated `migrationCockpit.test.tsx` |
| **TypeScript/Build** | Typecheck, production build | P0 | `npm run typecheck`, `npm run build` |
| **Security regression** | Redaction, env refs only, no secrets in responses | P0 | `test_api_security.py` |
| **Migration hygiene** | Append-only, rollback, index coverage | P0 | `test_sqlite_migrations.py` |

---

## 8. Risk Controls

| Risk | Control | Status |
|------|---------|--------|
| **Secrets in responses** | `redact_public_data()` in response path; env ref projection pattern in `v2_settings.py` | ✅ Clean |
| **NEXT_PUBLIC secrets** | No `NEXT_PUBLIC_*` Azure/OpenAI secrets in frontend. Only `NEXT_PUBLIC_API_BASE_URL` = `http://127.0.0.1:8000` | ✅ Clean |
| **Subprocess safety** | No `Popen`, `shell=True`, `os.system` in V2 services. Preflight checks use `Path.exists()` only | ✅ Clean |
| **Browser-controlled execution** | Browser cannot supply argv/env/Maven goals/deployment IDs. All backend-owned | ✅ Clean |
| **Assistant authority** | `FORBIDDEN_CAPABILITIES` list in `v2_assistant_service.py`. Draft-only actions. No execute/approve/write | ✅ Defined, needs persistence + API wiring (P0-006) |
| **Checksum approval** | `V2ApprovalMappingService.approve()` validates checksum before queueing resume | ✅ Defined, needs persistence + API wiring (P0-005) |
| **Proof separation** | Deterministic gates from stage chain ledger, not from LLM | ✅ Already enforced in V1 (not V2 scope) |
| **Data loss on restart** | In-memory dicts in A9, A10, A12; no job/command persistence in A6/A7 | ❌ **BLOCKER** — fixed by P0-001, P0-004 |
| **In-memory data loss** | If approval, assistant, or repair services restart, all pending decisions are lost | ❌ **HIGH** — fixed by P0-004 |

---

## 9. Recommended First Fix Branch

**Branch:** `v2/fix-p0-job-command-persistence`

**Why first:** Every other fix (approval wiring, assistant wiring, repair wiring, cockpit integration, E2E tests) depends on durable storage for V2 jobs and commands. Without persistence, nothing survives a restart, making the entire V2 flow ephemeral.

**Contains:**
- Migration 0030: `v2_migration_jobs` + `v2_stage_commands` tables
- `SqliteV2JobRepository` + `SqliteV2CommandRepository`
- UoW registration
- Tests: migration apply/rollback, save/read/list, append-only trigger enforcement

**Acceptance:**
- `v2_migration_jobs` has columns: `job_id`, `setup_id`, `setup_checksum`, `pipeline_id`, `stage_chain_json`, `status`, `created_at`
- `v2_stage_commands` has columns: `command_id`, `job_id`, `stage_index`, `manifest_checksum`, `argv_json`, `status`, `created_at`
- Append-only triggers on both tables
- All existing tests still pass

---

## Final Report

| Item | Value |
|------|-------|
| **Base branch** | `V2IMPROVMENT` |
| **HEAD before** | `fe54324198e4b43ec1b2d9c07c3a2b414c42baf2` |
| **HEAD after** | `fe54324198e4b43ec1b2d9c07c3a2b414c42baf2` (no changes) |
| **Doc path** | `docs/V2_AUDIT_FIXING_PLAN.md` |
| **Confirmed blockers** | F2 (job persistence), F3 (command persistence), F4 (progression unwired), F5 (approval in-memory), F6 (assistant in-memory), F7 (repair in-memory), F9 (cockpit simulated), F11 (missing E2E/tests) — **8 blockers** |
| **Confirmed highs** | F8 (schemas unused at runtime) — **1 high** |
| **Confirmed mediums** | F10 (docs) — **1 medium** |
| **Commands run** | `pytest tests/control_tower -q --tb=short` → 1364 passed, 3 skipped. `pytest tests/control_tower/test_api_security.py -q --tb=short` → 15 passed. `cd web/control-tower && npm test` → 122/122 passed. `npm run typecheck` → clean. `npm run build` → clean. `git diff --check` → clean. `git status --short` → `M web/control-tower/next-env.d.ts` (expected). |
| **First recommended fix** | `v2/fix-p0-job-command-persistence` — add SQLite tables for V2 jobs and stage commands |
| **Uncertainty** | None. All findings verified directly from source at HEAD fe54324. |
