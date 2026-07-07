# Normal Build/Test Flow Audit

Date: 2026-07-07
Auditor: Generated via code inspection
Scope: `migration_factory/agents/build_agent/`, `migration_factory/agents/test_agent/`, `migration_factory/orchestrator/`, `migration_factory/control_tower/`, `migration_factory/transform_v1_after_approval.py`, tests

---

## Executive Summary

**Verdict:** The normal build/test path is understandable and testable at the unit and component level, but it is **entangled with the legacy LangGraph orchestrator** and **coupled to the repair path through the same exit-handler function** (`_handle_exit`). The build agent is well-structured and independently testable. The test agent is a **passive parser** (does not run tests, only parses Surefire XML). The V2 Control Tower has good coverage of success proof and auto-queue tests, but there are **no end-to-end happy-path tests that exercise the full sandbox transform -> build -> test flow without mocking everything** and **no tests that verify the boundary between deterministic executor logic and LLM/repair/review logic**.

### Key Findings

| Area | Status |
|---|---|
| Build agent entry point | Clear, well-structured |
| Test agent entry point | Clear, parse-only |
| Orchestration model | Dual: legacy LangGraph + V2 subprocess runner |
| Build/test in transform | Interleaved: build per unit, test at end |
| API exposure | Events-based, no direct build/test status endpoint |
| Success proof | Strict contract check, well-tested |
| Auto-queue on success | Well-tested with fake processes |
| Normal vs repair separation | Entangled in `_handle_exit` |
| End-to-end tests | Missing: no full sandbox transform test without mocking |

---

## Entry Points

### 1. Normal Build Stage Entry Points

| # | File | Function / Class | Description |
|---|---|---|---|
| 1 | `migration_factory/agents/build_agent/agent.py:48` | `run_build_agent()` | **Primary entry.** Runs build validation for a project path. |
| 2 | `migration_factory/transform_v1_after_approval.py:321` | `_run_with_logged_output(lambda: run_build_agent(...))` | **Orchestrator call.** Build invoked per unit during sandbox transform loop. |
| 3 | `migration_factory/orchestrator/phase_services.py:123` | `run_sandbox_transform_phase()` | **LangGraph node.** Calls `apply_approved_sandbox_transform()` which internally runs build. |
| 4 | `migration_factory/orchestrator/runner.py` | CLI module | **Legacy CLI.** `python -m migration_factory.orchestrator.runner --mode full_sandbox_migration` |
| 5 | `migration_factory/control_tower/application/v2_worker_stage.py:81` | `V2WorkerStageService.build_stage1_manifest()` | **V2 backend.** Builds the command manifest (argv/env) for Stage 1. Does NOT run build itself. |
| 6 | `migration_factory/control_tower/application/v2_orchestrator_runner.py:128` | `V2OrchestratorRunner.start()` | **V2 runner.** Launches the orchestrator as a subprocess. Build/test happen inside that subprocess. |

**Input data `run_build_agent()` receives:**

```python
def run_build_agent(
    project_path: str | Path,          # Path to sandbox project
    timeout_seconds: int | None,       # Optional timeout override
    module: str | None,                # Maven module name
    main_class: str | None,            # Spring Boot main class
    auto_discover_maven_target: bool,  # Auto-detect module/main_class
    output_dir: str | Path | None,     # Output directory for error contracts
    ledger_file: str | Path | None,    # Migration ledger JSON for status updates
    stream_output: bool,               # Whether to stream to stdout
    stop_after_start: bool,            # Kill process after startup detection
    validation_unit_id: str | None,    # Which unit is being validated
    source_changing_unit: bool,        # Whether unit modifies source (affects reactor mode)
    validation_command: str | list[str] | None,   # Explicit validation command from plan
    source_jdk_home_env: str | None,   # Env var name for source JDK (for baseline)
    target_jdk_home_env: str | None,   # Env var name for target JDK (for post-transform)
) -> BuildRunResult
```

### 2. Normal Test Stage Entry Points

| # | File | Function / Class | Description |
|---|---|---|---|
| 1 | `migration_factory/agents/test_agent/agent.py:35` | `run_test_agent()` | **Primary entry.** Parse-only. Parses Surefire XML in sandbox. |
| 2 | `migration_factory/transform_v1_after_approval.py:506` | `_finalize_with_test_validation()` | **Orchestrator call.** Invoked after all units built successfully. |
| 3 | `migration_factory/orchestrator/phase_services.py:123` | `run_sandbox_transform_phase()` | Same as above -- LangGraph node calls transform, which calls test. |

**Input data `run_test_agent()` receives:**

```python
def run_test_agent(
    sandbox_path: str | Path,          # Sandbox containing target/surefire-reports/
    run_dir: str | Path,               # Run output directory
    run_id: str,                       # Run identifier
    source_log_path: str | Path,       # Source build log
    command: list[str] | None,         # Build command (for provenance, not execution)
    cwd: str | None,                   # Build working directory
    build_status: str | None,          # "BUILD_PASSED_IN_SANDBOX" or similar
    build_exit_code: int | None,       # Build exit code
    require_test_reports: bool,        # Whether missing reports = error
) -> TestAgentResult
```

**Important:** The test agent never runs tests. It parses existing Surefire XML reports. The `execution_owner` in its output is always `"build-agent"` and `execution_mode` is always `"parse_existing_surefire"`. Build validation (e.g., `mvn clean test`) has already run tests via the build agent.

---

## Happy Path Sequence

### Successful Build Flow (per unit in sandbox transform loop)

```
1. STATE: Orchestration status = "PASS" (previous phase succeeded)
         Approval = COMPLETED/approved
         Sandbox workspace prepared

2. ENTRY: apply_approved_sandbox_transform()
         -> _run_transformer_with_build_validation()
         (transform_v1_after_approval.py:252)

3. TRANSFORMER LOOP:
   a. Run transformation agent for current unit
   b. If status == AWAITING_BUILD_AGENT:
      i.   Emit "BUILD_VALIDATION_REQUIRED" status
      ii.  Emit "BUILD_RUNNING_IN_SANDBOX" status
      iii. Call run_build_agent() with:
           - project_path = sandbox_path
           - validation_unit_id = current unit
           - ledger_file = transformation ledger
           - validation_command from plan (if defined)
           - jdk_env (JAVA_HOME from profile)
      iv.  Build agent:
           a. detect_java_project(sandbox_path) -> JavaProjectInfo
           b. Determine validation mode (STARTUP, PLAN_COMMAND, or REACTOR_TEST)
           c. Resolve JAVA_HOME for unit (source_jdk for baseline, target_jdk for transform)
           d. Environment gate check (Java version, Maven version for Boot 4)
           e. Build command:
              - STARTUP: mvn -f <module>/pom.xml -Dspring-boot.run.main-class=... spring-boot:run
              - PLAN_COMMAND: explicit command from migration plan
              - REACTOR_TEST: mvn clean test for multi-module reactor
           f. Run: subprocess.Popen(command, cwd=sandbox_path, env={JAVA_HOME, PATH})
           g. Stream output, classify each line (compile errors, startup, port-in-use, etc.)
           h. If startup detected: kill process, return success
           i. If timeout/failure: return BuildRunResult(succeeded=False, ...)
      v.   On success:
           a. Emit "BUILD_PASSED_IN_SANDBOX" status
           b. Mark build_passed in ledger
           c. If more units remain: continue to next unit
           d. If all units done: proceed to _finalize_with_test_validation()
      vi.  On failure:
           a. Emit "BUILD_FAILED_IN_SANDBOX" status
           b. Write build_error_contract JSON
           c. Return TransformSandboxResult(exit_code=1, status=STATUS_BUILD_FAILED)
```

**JAVA_HOME/Maven resolution:**
- `_java_runtime_for_unit()` at `build_agent/agent.py:354`:
  - If `validation_unit_id == "baseline"` -> uses `source_jdk_home_env` (e.g., JAVA11_HOME)
  - If `validation_unit_id` is set -> uses `target_jdk_home_env` (e.g., JAVA21_HOME)
- `_build_command_env()` at `build_agent/agent.py:371`: sets JAVA_HOME and prepends `$JAVA_HOME/bin` to PATH
- `_target_environment_gate()` at `build_agent/agent.py:380`: checks Java major version and Maven version (for Boot 4)
- Maven executable resolved via `resolve_maven_command()` at `migration_factory/maven.py` (handles mvn.cmd on Windows)

**Artifact capture:**
- Build error contracts written to `run_dir/build/`
- Ledger updated with `mark_build_passed()` or `mark_build_failed()`
- Timing recorded per unit via `_record_transform_command_timing()`

**DB updates (V2 Control Tower):**
- Events persisted via `uow.v2_events.save()`:
  - `process_started`, `stdout`/`stderr` stream lines, `build_completed`, `test_completed`
- Final result JSON parsed and persisted to `v2_commands.result_json`
- If success: `proof_updated` + `stage_completed` events
- If failure: `stage_failed` event

### Successful Test Flow

```
1. STATE: build_status = "BUILD_PASSED_IN_SANDBOX"
         All units built successfully

2. ENTRY: _finalize_with_test_validation()
         (transform_v1_after_approval.py:506)

3. FLOW:
   a. Run dependency policy layer (_run_dependency_policy_layer):
      - Scan POM for policy violations
      - Apply auto-policy patches if enabled
      - Invoke copilot dependency advisory if needed
   b. Extract build command and cwd from ledger:
      _build_command_and_cwd(ledger_file) -> command, cwd
      _build_exit_code(ledger_file) -> build_exit_code
   c. Call run_test_agent():
      - sandbox_path = sandbox
      - build_status = "BUILD_PASSED_IN_SANDBOX"
      - build_exit_code = 0 (from ledger)
      - require_test_reports = False
   d. Test agent:
      i.   Check sandbox directory exists
      ii.  Check build_status == BUILD_PASSED_IN_SANDBOX
           (if not, return TEST_ERROR with reason="BUILD_COMMAND_FAILED")
      iii. Detect test sources in src/test/**/*.java
      iv.  Find Surefire XML reports in **/target/surefire-reports/TEST-*.xml
      v.   Parse each report, aggregate totals (tests, passed, failures, errors, skipped)
      vi.  Determine test_status:
           - no reports + no runnable tests -> PASS_WITH_WARNINGS
           - no reports + has runnable tests -> PASS_WITH_WARNINGS
           - failures/errors > 0 -> TEST_FAILED
           - else -> TEST_PASSED
      vii. Write test_report.json, test_summary.md, test_agent.log
   d. Record test validation in ledger:
      _record_ledger_test_validation() -> ledger["test_validation"] = {...}
   e. On success (TEST_PASSED, PASS_WITH_WARNINGS, TESTS_NOT_FOUND):
      i.   Emit "TRANSFORM_APPLIED_IN_SANDBOX" status
      ii.  Status: STATUS_APPLIED
      iii. Write timing artifacts
      iv.  Return TransformSandboxResult(exit_code=0, status=STATUS_APPLIED)
   f. On failure (TEST_FAILED, TEST_ERROR):
      i.   Return TransformSandboxResult(exit_code=1, status=test_result.test_status)

4. UPSTREAM (phase_services.py:123):
   - If exit_code == 0 and status == STATUS_APPLIED:
     - Emit "sandbox_transform completed" event
     - Set orchestration_status = "PASS", build_status, test_status, etc.
     - If h2_startup_required: run h2 startup check
     - Return state with:
       ```
       orchestration_status = "PASS"
       transform_status = "TRANSFORM_APPLIED_IN_SANDBOX"
       build_status = "BUILD_PASSED_IN_SANDBOX"
       test_status = test_result.test_status
       test_totals = {...}
       artifact_refs = {...}
       ```
   - Route: sandbox_transform -> final_report -> END

5. V2 CONTROL TOWER (v2_orchestrator_runner.py:486):
   - _handle_exit() receives result JSON from subprocess stdout
   - Calls _emit_phase_outcome_events():
     - build_completed if BUILD_PASSED_IN_SANDBOX
     - test_completed if test_status in {"PASS","TEST_PASSED","TESTS_NOT_FOUND","PASS_WITH_WARNINGS"}
   - Calls _has_success_proof() to verify contract
   - On success:
     - proof_updated event
     - stage_completed event
     - _auto_queue_next_stage() for next stage
   - Stage progression:
     - Stage 1 (Spring Boot 2.1.6 -> 2.7, Java 11): analysis checkpoint, not build/test
     - Stage 2 (Spring Boot 2.7 -> 3.5, Java 17): planning checkpoint, not build/test
     - Stage 3 (Spring Boot 3.5 + Java 17 -> Java 21): **build/test runs here**
     - Stage 4 (Spring Boot 3.5 + Java 21 -> 4.0 + Java 21): **build/test runs here**
```

---

## State and Events

### DB / State Fields Used During Normal Build/Test

| Field | Source | Description |
|---|---|---|
| `build_status` | `MigrationState` / `TransformSandboxResult` | `"BUILD_PASSED_IN_SANDBOX"` or `"BUILD_FAILED_IN_SANDBOX"` |
| `test_status` | `MigrationState` / `TransformSandboxResult` | `"TEST_PASSED"`, `"TEST_FAILED"`, `"TEST_ERROR"`, `"PASS_WITH_WARNINGS"`, `"TESTS_NOT_FOUND"` |
| `test_totals` | `MigrationState` / `TransformSandboxResult` | `{"tests": N, "passed": N, "failures": N, "errors": N, "skipped": N}` |
| `transform_status` | `MigrationState` | `"TRANSFORM_APPLIED_IN_SANDBOX"` |
| `orchestration_status` | `MigrationState` | `"PASS"` (success) / `"FAIL"` |
| `final_status` | `MigrationState` | `"TRANSFORM_APPLIED_IN_SANDBOX"` (success) |
| `sandbox_path` | `MigrationState` | Absolute path to sandbox workspace |
| `artifact_refs` | `MigrationState` | Map of artifact kind -> file path |
| `timing` | `MigrationState` | Phase durations, command timings |
| `repair_loop_status` | `MigrationState` | Set to `"REPAIR_REVIEW_REQUIRED"` on failure |

### Emitted Events (Normal Build/Test Success)

From `migration_factory/orchestrator/events.py` (legacy) and `v2_orchestrator_runner.py` (V2):

| Event Type | Status | Phase | Source |
|---|---|---|---|
| `sandbox_transform_started` / `sandbox_transform` (started) | `running` | `sandbox_transform` | `phase_services.py:132` |
| `build_started` | `running` | `build_validation` | V2 runner (via orchestrator events) |
| `build_completed` | `completed` | `build_validation` | `v2_orchestrator_runner.py:954` |
| `test_completed` | `completed` | `test_validation` | `v2_orchestrator_runner.py:978` |
| `sandbox_transform_completed` | `completed` | `sandbox_transform` | `v2_orchestrator_runner.py:936` |
| `proof_updated` | `completed` | - | `v2_orchestrator_runner.py:853` |
| `stage_completed` | `completed` | - | `v2_orchestrator_runner.py:862` |
| `process_started` | `running` | - | `v2_orchestrator_runner.py:337` |
| `stdout` / `stderr` | `running` | - | Stream capture |

On failure, additional events:
- `build_failed`, `test_failed`, `stage_failed`
- `repair_failure_evidence_written` (if repair context written)
- `repair_context_pack_written`

---

## API / FastAPI Projection

### Endpoints Exposing Build/Test State

| Endpoint | Method | Description |
|---|---|---|
| `/v1/v2/migration-jobs/start-stage1` | `POST` | Starts Stage 1 orchestrator subprocess |
| `/v1/v2/migration-jobs/{job_id}/stages` | `GET` | Returns stage state derived from commands + events |
| `/v1/v2/migration-jobs/{job_id}/events/snapshot` | `GET` | Ordered event list with sequence number |
| `/v1/v2/migration-jobs/{job_id}/events` | `GET` | V2 event listing (legacy alias) |
| `/v1/v2/migration-jobs/{job_id}/pipeline` | `GET` | Full pipeline projection from events |
| `/v1/v2/migration-jobs/{job_id}/failure-summary` | `GET` | Redacted failure/repair summary |
| `/v1/v2/jobs/{job_id}/stages/progress` | `POST` | Stage progression (backend-owned) |
| `/v1/jobs/{job_id}/stages` | `GET` | V1 stage states |
| `/v1/jobs/{job_id}/events` | `GET` | V1 event listing |
| `/v1/jobs/{job_id}/events/stream` | `GET` | V1 SSE event stream |

### Key Response Contracts

**Stages response** (from `_v2_stages_from_job()` at `app.py`):
- `stages` array with stage index, chain status, status, artifacts, evidence_refs, sandbox_path, approval info

**Events response** (from `get_v2_job_event_snapshot()` at `app.py:2318`):
```python
{
    "job_id": str,
    "after": int,
    "events": [{"sequence": int, "stage": int, "type": str, "status": str, "message": str, "payload_json": str}],
    "latest_sequence": int,
}
```

**Frontend data sufficiency:** The frontend receives events as an ordered list with event types like `build_completed`, `test_completed`, `stage_completed`. It does NOT receive a direct "build/test status" field -- it must derive status from event streams. The `pipeline` and `failure-summary` endpoints provide derived projections. The `stages` endpoint provides a per-stage summary. The frontend has enough data to display build/test success, but it requires event replay/interpretation logic.

### Success Proof Contract

Enforced by `_has_success_proof()` at `v2_orchestrator_runner.py:2969`:

```python
expected = {
    "orchestration_status": "PASS",
    "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
    "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
    "build_status": "BUILD_PASSED_IN_SANDBOX",
    "test_status": {"PASS", "TEST_PASSED", "TESTS_NOT_FOUND", "PASS_WITH_WARNINGS"},
}
```

Must also have: non-empty `sandbox_path`, no `errors`, no `blockers`.

---

## Orchestration Model

### Is it LangGraph?

**Partially.** The system has **two orchestration layers:**

1. **Legacy LangGraph orchestrator** (`migration_factory/orchestrator/graph.py`):
   - Uses `StateGraph(MigrationState)` with nodes: analysis, planning, assessment, copilot_phase_assist, approval, approval_record, sandbox_transform, final_report, copilot_final_report
   - Has `build_graph()` function returning compiled graph
   - Uses LangGraph checkpointing via `SQLiteBackedInMemorySaver`
   - Uses `langgraph.types.interrupt` for human-in-the-loop approval
   - Uses `langgraph.types.Command` for resume
   - **This is the actual graph-based orchestration**

2. **V2 Control Tower subprocess runner** (`migration_factory/control_tower/application/v2_orchestrator_runner.py`):
   - Does NOT use LangGraph directly
   - Runs the legacy orchestrator (which IS LangGraph) as a **subprocess**
   - Captures stdout, parses events (JSONL lines prefixed with `CONTROL_TOWER_EVENT`), parses final JSON result
   - Manages stage progression manually (queue_next_stage, auto_queue_next_stage)
   - Completely different orchestration pattern

**Orchestration pattern is mixed:**
- **Stage-level:** Command-based (V2WorkerStageService builds manifest, V2OrchestratorRunner launches subprocess, V2StageProgressionService auto-queues next)
- **Within a stage:** LangGraph graph (analysis -> planning -> assessment -> approval -> transform -> report)
- **Event model:** JSONL stream parsing with sentinel-prefixed lines
- **Service-based:** V2ProfileRuntime resolves profiles, JDK env vars, catalogs
- **Command-based:** Each stage is a `python -m migration_factory.orchestrator.runner` invocation with specific --profile, --legacy, --mode args

### Boundary Between Layers

```
┌──────────────────────────────────────────────────────────────────┐
│                   V2 Control Tower (FastAPI)                      │
│  - V2WorkerStageService.build_stage1_manifest()                  │
│  - V2OrchestratorRunner.start() -> subprocess                    │
│  - V2StageProgressionService.queue_next_stage()                  │
│  - Event persistence, FastAPI routes, SSE notification            │
├──────────────────────────────────────────────────────────────────┤
│            Legacy LangGraph Orchestrator (subprocess)             │
│  - build_graph() -> StateGraph                                   │
│  - run_analysis_phase, run_planning_phase, run_assessment_phase │
│  - approval_node (langgraph.types.interrupt)                     │
│  - run_sandbox_transform_phase                                   │
│  - emit_control_tower_event() -> JSONL on stdout                 │
├──────────────────────────────────────────────────────────────────┤
│                Sandbox Transform (deterministic)                  │
│  - apply_approved_sandbox_transform()                            │
│  - prepare_sandbox_workspace()                                   │
│  - run_transformation_agent() -> OpenRewrite                     │
│  - run_build_agent() -> subprocess.Popen                         │
│  - run_test_agent() -> parse Surefire XML                        │
├──────────────────────────────────────────────────────────────────┤
│         Repair / LLM / Reviewer (only on failure)                │
│  - _merge_repair_updates() sets repair_loop_status               │
│  - _maybe_write_repair_failure_context()                         │
│  - repair_review_chain.py (F5 reviewer)                          │
│  - v2_repair_flow.py, copilot_repair/                            │
└──────────────────────────────────────────────────────────────────┘
```

### Deterministic vs LLM/Agent vs Repair vs API Boundaries

| Component | Deterministic? | Code Locations |
|---|---|---|
| Build agent (`run_build_agent()`) | **Fully deterministic.** No LLM calls. Pattern-based output classification. | `migration_factory/agents/build_agent/agent.py`, `runner.py`, `classifier.py`, `detection.py` |
| Test agent (`run_test_agent()`) | **Fully deterministic.** XML parsing only. Never runs processes. | `migration_factory/agents/test_agent/agent.py` |
| Transform agent | **Deterministic + OpenRewrite.** Java rewrite recipes. No LLM. | `migration_factory/agents/transformation_agent/` |
| LLM/Agent logic | `copilot_assist/`, `copilot_repair/`, `repair_review_chain.py`, `v2_repair_flow.py`, `v2_reviewer_service.py`, `v2_assistant_service.py` | Only invoked on failure or when copilot assist mode is enabled (currently `off` by default) |
| Reviewer/Repair logic | `orchestrator/repair_review_chain.py`, `control_tower/application/v2_repair_flow.py`, `v2_repair_gate_service.py`, `v2_reviewer_service.py` | Only invoked when `repair_loop_status != NONE` or via repair proposal API |
| Control Tower API | `app.py` routes, `v2_orchestrator_runner.py`, `v2_stage_progression.py` | Event-based, backend-owned |

**Key insight:** The normal build/test path (`run_build_agent` + `run_test_agent`) is **entirely deterministic** and does **not require any LLM calls**. The LLM/agent code is only reached on the failure path or when explicitly enabled via environment variables.

---

## Existing Test Coverage

### Tests Covering Normal Build/Test Path

| File | Test Name | What It Asserts | Type |
|---|---|---|---|
| `tests/test_build_agent.py` | `test_detects_maven_wrapper` | Project detection with mvnw | Unit |
| `tests/test_build_agent.py` | `test_build_command_*` (multiple) | Command construction for Maven modules | Unit |
| `tests/test_build_agent.py` | `test_classifies_*` (multiple) | Output line classification | Unit |
| `tests/test_build_agent.py` | `test_runner_returns_success_and_stops_process_after_startup_detection` | `run_until_build_result` success path | Unit (mocked process) |
| `tests/test_build_agent.py` | `test_runner_timeout_kills_process_tree_and_returns_failure` | Timeout handling | Unit |
| `tests/test_build_agent.py` | `test_resolve_maven_command_prefers_maven_cmd_env` | Maven resolution via MAVEN_CMD | Unit |
| `tests/test_build_agent.py` | `test_baseline_*` (multiple) | Multi-module reactor, JDK env, validation modes | Unit |
| `tests/test_build_agent.py` | `test_full_validation_command_*` (multiple) | Command construction for reactor/test | Unit |
| `tests/test_test_agent.py` | `test_test_agent_parses_surefire_pass` | Happy path: pass | Unit (tmp_path) |
| `tests/test_test_agent.py` | `test_test_agent_parses_surefire_failed` | Failure detection | Unit (tmp_path) |
| `tests/test_test_agent.py` | `test_test_agent_missing_reports_*` (4 tests) | Edge cases for missing reports | Unit (tmp_path) |
| `tests/test_test_agent.py` | `test_test_agent_build_failed_is_error` | Build failure -> test error | Unit (tmp_path) |
| `tests/test_test_agent.py` | `test_test_agent_malformed_report_is_error` | XML parse error | Unit (tmp_path) |
| `tests/test_test_agent.py` | `test_test_agent_skipped_only_is_pass` | All tests skipped = pass | Unit (tmp_path) |
| `tests/control_tower/test_v2_orchestrator_runner.py` | `test_success_proof_accepts_*` | Success proof contract validation | Unit |
| `tests/control_tower/test_v2_orchestrator_runner.py` | `test_success_proof_rejects_*` | Contract mismatch detection | Unit |
| `tests/control_tower/test_v2_orchestrator_runner.py` | `test_stage1_pass_contract_auto_queues_stage2` | Full chain S1->S2 auto-queue | Integration (fake process) |
| `tests/control_tower/test_v2_orchestrator_runner.py` | `test_stage2_pass_contract_auto_queues_stage3` | Full chain S2->S3 auto-queue | Integration (fake process) |
| `tests/control_tower/test_v2_orchestrator_runner.py` | `test_stage3_pass_contract_queues_stage4` | Full chain S3->S4 auto-queue | Integration (fake process) |
| `tests/control_tower/test_v2_orchestrator_runner.py` | `test_stage_failed_not_emitted_for_valid_pass_contract` | No spurious failures | Integration (fake process) |
| `tests/control_tower/test_v2_orchestrator_runner.py` | `test_v2_runner_emits_stage_completed_for_stage3` | Stage 3 completion events | Integration (fake process) |
| `tests/control_tower/test_v2_auto_policy_regression.py` | `test_stage1_auto_queues_stage2` | Auto-queue regression | Integration |
| `tests/control_tower/test_v2_auto_policy_regression.py` | `test_stage2_auto_queues_stage3` | Auto-queue regression | Integration |
| `tests/control_tower/test_v2_stage_progression.py` | `test_queue_next_stage_*` (multiple) | Stage progression service | Integration |
| `tests/orchestrator/test_full_sandbox_migration.py` | `test_resume_approved_records_approval_and_runs_sandbox_transform` | Full LangGraph flow with fake transform | Integration (fake services) |

### Coverage Gaps in Happy Path

| Gap | Severity |
|---|---|
| No test that `run_build_agent()` succeeds with a real `subprocess.Popen` on a synthetic project | Medium |
| No test that `_finalize_with_test_validation()` runs to completion with build+test success | High |
| No test that `apply_approved_sandbox_transform()` returns `STATUS_APPLIED` status with full build+test success | High |
| No test that `run_sandbox_transform_phase()` returns `orchestration_status="PASS"` with proper build/test state | High |
| No test that `_handle_exit()` correctly routes through `_has_success_proof` -> `_auto_queue_next_stage` without entering repair | Medium |
| No test asserting the boundary: "normal success does NOT invoke LLM, repair, or reviewer" | High |
| No test for `_emit_phase_outcome_events()` with normal build/test success | Medium |
| No test asserting the exact event sequence on normal success | Medium |
| No contract-level test for migration_ledger format after build+test success | Low |
| No test for FastAPI routes returning correct stage/event data after normal build/test | Medium |

---

## Missing Happy-Path Tests

### Proposed Test Plan

```python
# --- Unit Tests for Build/Test Agents (no external deps) ---

# test_normal_build_success_on_fake_java_project
#   - Creates fake multi-module Maven project with pom.xml and Spring Boot main class
#   - Mocks subprocess.Popen to return "Started Application in 1.0 seconds"
#   - Asserts: BuildRunResult.succeeded == True, kind == SUCCESS
#   - Asserts: ledger updated with mark_build_passed
#   - Asserts: no console errors

# test_normal_build_with_explicit_validation_command
#   - Provides explicit_command="mvn clean test"
#   - Mocks Popen to return success
#   - Asserts: command is used as-is, BuildRunResult.succeeded == True

# test_build_agent_java_home_set_correctly_for_target_unit
#   - Sets target_jdk_home_env, creates fake unit_id
#   - Mocks Popen, captures env passed to Popen
#   - Asserts: JAVA_HOME in env matches the target JDK
#   - Asserts: PATH starts with target JDK bin

# --- Integration Tests for Sandbox Transform (fake process, fake ledger) ---

# test_normal_build_success_per_unit_in_loop
#   - Creates fake migration plan with 2 units
#   - Uses fake transformation agent (returns AWAITING_BUILD_AGENT then COMPLETED)
#   - Mocks run_build_agent to always return success
#   - Asserts: build called for each unit
#   - Asserts: _finalize_with_test_validation called after all units

# test_normal_test_success_routes_status_applied
#   - Calls _finalize_with_test_validation() with sandbox containing Surefire XML
#   - Asserts: TransformSandboxResult.exit_code == 0
#   - Asserts: TransformSandboxResult.status == STATUS_APPLIED
#   - Asserts: TransformSandboxResult.build_status == STATUS_BUILD_PASSED
#   - Asserts: TransformSandboxResult.test_status == "TEST_PASSED"

# --- V2 Orchestrator Runner Tests ---

# test_normal_success_does_not_enter_repair_loop
#   - Runs _handle_exit with success result
#   - Asserts: repair_loop_status not set to REPAIR_REVIEW_REQUIRED
#   - Asserts: no repair_failure_evidence_written event
#   - Asserts: repair context pack NOT written

# test_normal_build_test_success_emits_correct_event_sequence
#   - Runs _handle_exit with success result
#   - Asserts events in order: build_completed, test_completed, proof_updated, stage_completed
#   - Asserts: no build_failed, no test_failed, no stage_failed

# test_normal_success_triggers_auto_queue_next_stage
#   - Full fake process chain through 4 stages
#   - Asserts: next_stage_queued for each stage (2, 3, 4)
#   - Asserts: migration_completed after Stage 4

# --- API / Projection Tests (FastAPI TestClient) ---

# test_get_stages_returns_build_test_status_on_success
#   - Seeds DB with success events for Stage 3
#   - GET /v1/v2/migration-jobs/{job_id}/stages
#   - Asserts: response contains build_status, test_status for Stage 3

# test_get_pipeline_projection_after_build_test_success
#   - Seeds DB with full success event chain
#   - GET /v1/v2/migration-jobs/{job_id}/pipeline
#   - Asserts: pipeline shows build/test evidence, target proof level

# test_build_test_success_does_not_trigger_diagnosis_callback
#   - Injects diagnosis_callback that records calls
#   - Runs success result through _handle_exit
#   - Asserts: diagnosis callback was NOT called

# --- Boundary Tests ---

# test_normal_build_test_does_not_require_llm
#   - Creates success result
#   - Verifies copilot_enabled is False (default)
#   - Verifies no LLM invocation events emitted

# test_phase_services_does_not_set_repair_on_build_test_success
#   - Mocks apply_approved_sandbox_transform to return success
#   - Calls run_sandbox_transform_phase()
#   - Asserts: repair_loop_status is NOT set
#   - Asserts: repair_blocker is NOT set
```

---

## Normal Path vs Repair Path Comparison

### What Normal Build/Test Does When Green

1. `run_build_agent()` -> `subprocess.Popen` + `run_until_build_result()` -> classifies output -> returns success
2. `run_test_agent()` -> parses Surefire XML -> returns test_status
3. `_finalize_with_test_validation()` -> returns `TransformSandboxResult(exit_code=0, status=STATUS_APPLIED)`
4. `run_sandbox_transform_phase()` -> emits `sandbox_transform completed` -> returns `orchestration_status="PASS"`
5. V2 runner: `_handle_exit()` -> `_has_success_proof()` -> `proof_updated` + `stage_completed` + `_auto_queue_next_stage()`

**The normal path never touches:**
- `_merge_repair_updates()`
- `_maybe_write_repair_failure_context()`
- `build_failure_evidence()`
- `build_repair_context_pack()`
- Any LLM client (`v2_assistant_model_client`, `v2_mistral_provider_client`, `v2_model_role_router`)
- `copilot_repair/` module
- `repair_loop/` module
- `v2_repair_flow.py`, `v2_repair_gate_service.py`, `v2_reviewer_service.py`

### What Repair Validation Does After Patch

1. Build command re-run in sandbox
2. Test command re-run (or Surefire XML re-parsed)
3. `V2RepairValidationRunner.validate()` returns `RepairValidationResult`
4. If passed: auto-queue next stage (same as normal path)
5. If failed: create next repair cycle or rollback

### What Should Be Shared

- **Share:** The success contract check (`_has_success_proof()`). Both normal and repair success should pass the same proof.
- **Share:** Event emission patterns (`build_completed`, `test_completed`, `stage_completed`, `proof_updated`).
- **Share:** Stage progression (`V2StageProgressionService.queue_next_stage()`). Both normal and repair-validated success should advance stages the same way.
- **Share:** Artifact capture and DB persistence of results.

### What Should Stay Separate

- **Separate:** The execution path. Normal is a single pass; repair is a loop that can retry.
- **Separate:** The gate model. Repair has its own gate service (`V2RepairGateService`) distinct from the analysis/planning checkpoint gates.
- **Separate:** Evidence collection. Failure evidence and context packs are only needed on failure, not on normal success.
- **Separate:** The diagnosis callback (`_maybe_diagnose()`). Should only fire on failure.

### Current Code Mixing Issues

**Issue 1: `_handle_exit()` handles both success and failure in one 800+ line function** (`v2_orchestrator_runner.py:486-1361`). The function proceeds through:
- exit_code != 0 path (failure)
- result is None path (parse failure)
- command_phase == "analysis"/"planning" handling
- general phase outcome events
- failure repair events
- approval_required path
- terminal failure path
- success proof check
- auto-queue next stage

A simpler split would be `_handle_exit_success()` and `_handle_exit_failure()`.

**Issue 2: `_merge_repair_updates()` is called from `run_sandbox_transform_phase()` even for environment gate failures** (`phase_services.py:225`). The function sets `repair_loop_status = "REPAIR_REVIEW_REQUIRED"` and `final_status = "REPAIR_REVIEW_REQUIRED"` on any failure of the sandbox transform, not just build/test failures. For example, if h2_startup fails, it enters repair state.

**Issue 3: Build/test status strings are mixed across modules.** `STATUS_BUILD_PASSED = "BUILD_PASSED_IN_SANDBOX"` is defined in `transform_v1_after_approval.py:67` but the exact string `"BUILD_PASSED_IN_SANDBOX"` is also hardcoded in:
- `test_agent/agent.py:18` (`BUILD_STATUS_PASSED`)
- `v2_orchestrator_runner.py:95` (`_SUCCESS_BUILD_STATUS`)
- Multiple test files

**Issue 4: The test agent depends on build agent output but only passively.** If `run_test_agent()` is called without `build_status="BUILD_PASSED_IN_SANDBOX"`, it returns `TEST_ERROR` immediately. There is no way for the test agent to independently verify build success.

---

## Potential Issues

1. **Test agent is parse-only.** The `execution_mode` is always `"parse_existing_surefire"` and `execution_owner` is always `"build-agent"`. This means the test agent cannot detect test failures from the build output -- it can only parse XML reports. If tests ran as part of `mvn test` during build and no Surefire XML was produced, the test agent reports `PASS_WITH_WARNINGS`, not failure.

2. **Build and test are inseparable in the sandbox transform loop.** You cannot run only-build or only-test independently through the orchestrator -- they always run together in sequence within `_run_transformer_with_build_validation()`.

3. **Copilot assist is hard-disabled** in `graph.py:230`: `_should_route_to_copilot_assist()` always returns `False`. The entire `copilot_phase_assist` node is unreachable in the normal path.

4. **`_merge_repair_updates()` is called unconditionally on any sandbox transform failure** (`phase_services.py:225`), not just build/test failures. This means even a `STATUS_FAILED` from a blocked unit, or `STATUS_APPROVAL_FAILED`, triggers repair state in the orchestrator state. The `_handle_exit()` in the V2 runner has more nuanced detection, but the LangGraph state always gets `repair_loop_status = "REPAIR_REVIEW_REQUIRED"` on any transform failure.

5. **The `_diagnosis_callback` is injected at V2OrchestratorRunner construction but only fires on failure** (`_maybe_diagnose()` at `v2_orchestrator_runner.py:1281`). This is correct behavior, but the callback is part of the same `__init__` as the success path runner. A clearer architecture would separate the diagnosis concern.

---

## Recommended Next Steps

### Safe, Small Steps

1. **Add the missing tests** listed in "Missing Happy-Path Tests" above. Priority:
   - `test_normal_build_test_success_emits_correct_event_sequence`
   - `test_normal_success_does_not_enter_repair_loop`
   - `test_normal_build_test_does_not_require_llm`
   - `test_normal_build_success_on_fake_java_project`

2. **Extract status constants** into a shared contracts module (e.g., `migration_factory/contracts/statuses.py` or `migration_factory/contracts/build/statuses.py`) to eliminate duplicate string literals for `"BUILD_PASSED_IN_SANDBOX"`, `"TEST_PASSED"`, etc.

3. **Add a single `test build+test passes full sandbox transform` end-to-end test** using a fake Java project with a real `subprocess` command. A synthetic project with `pom.xml`, `src/main/java` with a class that just prints "Started Application", and a fake Surefire XML. This would catch integration bugs.

4. **Refactor `_handle_exit()` into `_handle_exit_success()` and `_handle_exit_failure()`** to reduce cognitive load and make the boundary clearer. This is a structural change but low-risk if done with existing test coverage.

5. **Add an API-level test with FastAPI TestClient** that seeds events and verifies the `GET /stages` and `GET /pipeline` responses show correct build/test status.

### Avoid Without Justification

- Do NOT rewrite the LangGraph orchestrator unless you want to replace the entire orchestration model
- Do NOT change the test agent to actually run tests (that would be a fundamentally different product decision)
- Do NOT merge the two orchestration layers (legacy LangGraph + V2 subprocess runner) -- they serve different purposes (CLI/offline vs. backend-owned server-side)

---

## Files Inspected

1. `migration_factory/agents/build_agent/__init__.py`
2. `migration_factory/agents/build_agent/agent.py` (503 lines)
3. `migration_factory/agents/build_agent/runner.py` (header)
4. `migration_factory/agents/build_agent/classifier.py`
5. `migration_factory/agents/build_agent/detection.py`
6. `migration_factory/agents/test_agent/agent.py` (246 lines)
7. `migration_factory/orchestrator/graph.py` (264 lines)
8. `migration_factory/orchestrator/state.py` (369 lines)
9. `migration_factory/orchestrator/events.py` (19 lines)
10. `migration_factory/orchestrator/phase_services.py` (531 lines)
11. `migration_factory/transform_v1_after_approval.py` (1184 lines)
12. `migration_factory/control_tower/application/v2_orchestrator_runner.py` (3162 lines)
13. `migration_factory/control_tower/application/v2_worker_stage.py` (230 lines)
14. `migration_factory/control_tower/application/v2_stage_progression.py` (1347+ lines)
15. `migration_factory/control_tower/adapters/fastapi/app.py` (14857 lines, key sections)
16. `migration_factory/control_tower/adapters/fastapi/dev_app.py`
17. `tests/test_build_agent.py` (771 lines, key sections)
18. `tests/test_test_agent.py` (179 lines)
19. `tests/control_tower/test_v2_orchestrator_runner.py` (2166 lines, key sections)
20. `tests/control_tower/test_v2_stage_progression.py` (969 lines, key sections)
21. `tests/control_tower/test_v2_auto_policy_regression.py` (256 lines, key sections)
22. `tests/orchestrator/test_full_sandbox_migration.py` (498 lines, key sections)

## Tests / Commands Run

### Python Compile Check

```
python -m py_compile migration_factory/agents/build_agent/agent.py
python -m py_compile migration_factory/agents/test_agent/agent.py
python -m py_compile migration_factory/orchestrator/phase_services.py
python -m py_compile migration_factory/orchestrator/graph.py
python -m py_compile migration_factory/orchestrator/state.py
python -m py_compile migration_factory/orchestrator/events.py
python -m py_compile migration_factory/control_tower/application/v2_orchestrator_runner.py
python -m py_compile migration_factory/control_tower/application/v2_worker_stage.py
python -m py_compile migration_factory/control_tower/application/v2_stage_progression.py
python -m py_compile migration_factory/control_tower/adapters/fastapi/app.py
```

### Focused Pytest Collection (targeted)

```
pytest tests/test_build_agent.py --collect-only -q
pytest tests/test_test_agent.py --collect-only -q
pytest tests/control_tower/test_v2_orchestrator_runner.py --collect-only -q
pytest tests/control_tower/test_v2_stage_progression.py --collect-only -q
```

### Results

- All `--collect-only` succeeded, confirming test files are syntactically valid and discoverable by pytest.
- `py_compile` checks for all key files passed without errors.

No commands failed.

---

## Path to Report

`NORMAL_BUILD_TEST_FLOW_AUDIT.md` in the repository root.
