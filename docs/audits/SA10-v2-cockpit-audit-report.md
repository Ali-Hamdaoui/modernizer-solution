# SA10 — Final Audit Report: V2 Cockpit AI Build Execution Fix

**Date:** 2026-06-14
**Branch:** `v2/fix-cockpit-ai-build-execution-audit`
**Base:** `V2IMPROVMENT` @ `e30565f` (fix(v2): reduce cockpit stage status chronologically (#117))
**PR Target:** `V2IMPROVMENT`

---

## Summary

20 files changed (+1817 / −65 lines) across 10 sub-agents (SA1–SA10). All work is on a single branch with one focused mission: fix and harden the V2 cockpit to correctly handle AI-assisted build failures, stage progression, redaction, and operator UX.

---

## Sub-Agent Results

| SA | Title | Key Fix | Tests Added | Status |
|----|-------|---------|-------------|--------|
| SA1 | AI readiness & model smoke gate | `V2ModelSmokeResult`, `smoke()`, `/v1/v2/azure/check-smoke` endpoint, AI readiness gate before start-stage1 | 228 pass | ✅ |
| SA2 | Cockpit lifecycle reducer consistency | Already implemented — confirmed 68 reducer tests pass | 68 pass | ✅ |
| SA3 | Approval & resume idempotency | Duplicate approve/reject returns existing result (not error); `start_resume` skips for duplicates | +6 tests | ✅ |
| SA4 | Terminal migration parity | Resume env inheritance from original stage command; BuildErrorContract diagnostic forwarding; profile verification (S1→java11, S2→java17, S3→java21); output path isolation via unique run IDs | +11 tests | ✅ |
| SA5 | Failure & Repair UX | Failure summary endpoint, structured diagnostic display in cockpit, `_next_operator_action` guidance | — | ✅ |
| SA6 | Assistant as real migration coach | `_build_v2_assistant_prompt` with bounded context; prompt excludes secrets/raw env/raw paths; prompt injection protections | — | ✅ |
| SA7 | SQLite migrations & dev DB reset | `_is_dev_mode()` (CONTROL_TOWER_DEV_MODE=1), `_dev_reset_database()` on checksum mismatch, cross-platform CRLF→LF hash normalization | +3 tests | ✅ |
| SA8 | Stage 2/3 auto-progression | **Critical fix:** 4 terminal failures (BUILD_FAILED, TEST_FAILED, FALLBACK_REPAIR_PLAN, TRANSFORM_FAILED) now block progression → `stage_failed`; missing-sandbox guard; unapproved-card guard; Stage 3 final report lifecycle events | +5 tests | ✅ |
| SA9 | Security, redaction & prompt hygiene | `_safe_failure_str` defense-in-depth redaction; pipeline + failure-summary endpoints wrapped in `redact_public_data`; **Fixed `_WINDOWS_ABSOLUTE_PATH_RE` regex** (only matched first directory component); frontend secret pattern test | +5 tests | ✅ |
| SA10 | Audit report & operator runbook | This document | — | ✅ |

---

## Critical Bug Fixed (SA8)

**Before:** The `_handle_exit` method in `v2_orchestrator_runner.py` only blocked `BUILD_FAILED_IN_SANDBOX`. `TEST_FAILED`, `FALLBACK_REPAIR_PLAN`, and `TRANSFORM_FAILED` fell through to `stage_completed` and auto-queued the next stage.

**After:** A unified `is_terminal_failure` check gates all 4 failure kinds. Missing sandbox, unapproved cards, and Stage 3 final report lifecycle are also guarded.

| Failure Kind | Before | After |
|---|---|---|
| BUILD_FAILED_IN_SANDBOX | Blocked ✅ | Blocked ✅ |
| TEST_FAILED | Auto-queued ❌ | Blocked ✅ |
| FALLBACK_REPAIR_PLAN | Auto-queued ❌ | Blocked ✅ |
| TRANSFORM_FAILED | Auto-queued ❌ | Blocked ✅ |
| Missing sandbox (stage 1/2) | Unchecked ❌ | Blocked ✅ |
| Unapproved card | Unchecked ❌ | Blocked ✅ |

---

## Critical Bug Fixed (SA9)

**Before:** `security.py`'s `_WINDOWS_ABSOLUTE_PATH_RE` used `[^\\s]*` which only matched the first directory component (e.g., `C:\Users`), leaving the rest of the path (`\operator\app\file.json`) unredacted.

**After:** Aligned with `redaction.py`'s correct multi-component regex `(?:[^\\/\s:]*[\\/])*[^\\/\s:]*` — full absolute paths are now redacted from all 30+ `redact_public_data` call sites.

---

## Env Allowlist

`_build_env` merges 3 tiers, all safe:

- **OS-level:** JAVA_HOME, JAVA11_HOME, JAVA17_HOME, JAVA21_HOME, MAVEN_CMD, PATH, SystemRoot, ComSpec, PATHEXT, TEMP, TMP, USERPROFILE, HOMEDRIVE, HOMEPATH
- **Manifest:** JAVA_HOME, JAVA11_HOME, JAVA17_HOME, JAVA21_HOME, MAVEN_CMD, PATH_PREPEND
- **Copilot flags:** AI_MIGRATION_* (with `_SECRET_ENV_MARKERS` filter excluding KEY/SECRET/TOKEN/PASSWORD/CREDENTIAL/AUTHORIZATION)

---

## Redaction Layers (Defense-in-Depth)

1. **Orchestrator** → `_event()` calls `redact_public_value` before persistence
2. **`_bounded()`** → 4096-char cap + `redact_model_summary`
3. **`_sanitize_body_snippet`** → HTTP error bodies redacted, 500-char cap
4. **`_safe_failure_str`** → 256-char cap + `redact_model_summary`
5. **`_safe_failure_list`** → 6-entry cap, each through `_safe_failure_str`
6. **SSE endpoint** → `_v2_event_payload` redacts via `redact_public_data`
7. **API endpoints** → Pipeline, failure-summary, stages, approvals all wrapped in `redact_public_data`

---

## Frontend Hardening

- Only `NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL` and `NEXT_PUBLIC_API_BASE_URL` — safe, no secrets
- Cockpit test verifies redacted payloads contain no real secret tokens or absolute paths
- Raw logs collapsed by default in SSE stream
- Stage inputs are pipeline-fixed (not user-selectable)

---

## Test Results

| Suite | Passed | Skipped | Failed |
|-------|--------|---------|--------|
| Backend (control_tower) | 1576 | 2 | 0 |
| Frontend (web) | 150 | 0 | 0 |
| TypeScript | Clean | — | 0 |
| Next.js build | Passed | — | — |

---

## Files Changed

```
20 files changed, 1817 insertions(+), 65 deletions(-)

migration_factory/control_tower/adapters/fastapi/app.py          (+237)
migration_factory/control_tower/adapters/fastapi/dev_app.py      (+11)
migration_factory/control_tower/adapters/fastapi/security.py     (+2)
migration_factory/control_tower/application/v2_approval_mapping.py (+32)
migration_factory/control_tower/application/v2_assistant_model_client.py (+163)
migration_factory/control_tower/application/v2_orchestrator_runner.py (+162)
migration_factory/control_tower/application/v2_setup_service.py  (+59)
migration_factory/control_tower/infrastructure/sqlite/migrations/__init__.py (+83)
tests/control_tower/test_api_security.py                         (+140)
tests/control_tower/test_repository_hygiene.py                   (+99)
tests/control_tower/test_v2_approval_mapping.py                  (+30)
tests/control_tower/test_v2_approval_stage_api.py                (+103)
tests/control_tower/test_v2_assistant_model_backing.py           (+252)
tests/control_tower/test_v2_checksum_api.py                      (+8)
tests/control_tower/test_v2_cockpit_events.py                    (+2)
tests/control_tower/test_v2_orchestrator_runner.py               (+271)
tests/control_tower/test_v2_worker_stage.py                      (+136)
web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx    (+30)
web/control-tower/lib/contracts.ts                               (+13)
web/control-tower/tests/migrationCockpit.test.tsx                (+49)
```

---

## Operator Runbook

### Starting the Control Tower

```powershell
# Backend (from repo root)
$env:CONTROL_TOWER_DEV_MODE = "1"
py -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd web\control-tower
npm run dev
```

### Running a Migration (UAT Flow)

1. Open `http://127.0.0.1:3000/migrations/new`
2. Fill in legacy app path, output path, AI hub path, JDK homes, Maven path
3. Run preflight — wait for all checks to pass (including Azure model smoke)
4. Start migration
5. Watch pipeline rows advance:
   - Analysis Agent → running/pass
   - Planning Agent → running/pass
   - Assessment Agent → running/pass
   - Human Approval → blocked
6. Approve with exact checksum when card appears
7. Confirm Human Approval → pass, Stage 1 moves to running
8. Watch Transform → Build → Test
9. If failure: Failure & Repair panel shows structured diagnostics (matched line, command, module, result kind)
10. Ask assistant: "What failed?", "What should I do next?"
11. Confirm no secrets in UI, logs, or SSE events

### Dev Mode

Set `CONTROL_TOWER_DEV_MODE=1` to enable automatic DB reset on migration checksum mismatch. Production (flag absent) treats mismatch as hard crash.

---

## Remaining Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Azure model smoke depends on network | Low | Fallback to deterministic assistant when smoke fails |
| `next-env.d.ts` auto-generated on build | Low | Excluded from staging per V2 rules |
| Windows CRLF vs git LF in migrations | Low | SA7 normalizes both sides before hash comparison |
| `_WINDOWS_ABSOLUTE_PATH_RE` duplication (security.py vs redaction.py) | Low | Both now use identical regex; future DRY-up recommended |

---

## Deviations

None. All 10 sub-agents completed within assigned scope. No adjacent work performed. No secrets exposed.

---

## Next Steps

- [ ] Human UAT per operator runbook above
- [ ] Rotate Azure key if any was exposed during development
- [ ] Commit and push to `v2/fix-cockpit-ai-build-execution-audit`
- [ ] Create PR targeting `V2IMPROVMENT`
- [ ] After merge, rebase future V2 work onto updated `V2IMPROVMENT`

---

## Acceptance

- [x] No secrets in prompt, event, SSE, logs, failure summary, assistant messages, or frontend DOM
- [x] Stage 2/3 failures block progression (not auto-queue)
- [x] Unapproved cards block progression
- [x] Missing sandbox blocks progression
- [x] Stage 3 emits final report events
- [x] Approval idempotent (duplicate approve/reject safe)
- [x] BuildErrorContract diagnostics reach cockpit
- [x] Migrations auto-reset in dev mode on checksum mismatch
- [x] 1576 backend tests pass, 150 frontend tests pass
- [x] TypeScript clean, build passes
