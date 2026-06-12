# AI Migration Control Tower V1 — Issue Breakdown

Provisional issue keys `V1-01`…`V1-19` are dependency anchors for publishing order. Replace them with tracker issue IDs after creation.

---

# [chore] Remove local runtime artifacts
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `repository packaging | .gitignore | Control Tower dev runtime`
- stack: `SQLite | FastAPI | local dev workspace`
- related: `V1-02`

## goal
<!-- One sentence. Start with a verb. -->
> Remove local Control Tower runtime artifacts from the shared codebase package and prevent them from being committed again.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `.gitignore` — ignore `.control-tower-dev/`, `*.sqlite3`, `*.sqlite3-shm`, and `*.sqlite3-wal`
- [ ] repository root — remove any checked-in `.control-tower-dev/control_tower.sqlite3` runtime artifact if present
- [ ] `tests/control_tower/test_repository_hygiene.py` — add a test that fails when local SQLite runtime DB files are tracked under project runtime folders
- ~~not in scope: database schema changes~~
- ~~not in scope: deleting user machines' local runtime folders~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] `.gitignore` contains entries for `.control-tower-dev/`, `*.sqlite3`, `*.sqlite3-shm`, and `*.sqlite3-wal` (file exists)
- [ ] `git status --short` shows no tracked `.control-tower-dev/control_tower.sqlite3` file after the change (log line)
- [ ] `py -m pytest -q tests/control_tower/test_repository_hygiene.py -rs` passes (unit test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none
- model: none
- token budget: none
- do NOT touch: `migration_factory/control_tower/infrastructure/sqlite/migrations/*.sql`

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| current_zip_root | `modernizer-solution-DEMO2` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```text
PR with .gitignore update, runtime artifact removal if tracked, and hygiene test.
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocks | `V1-02` |

## effort
`XS`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Lock V1 migration route
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `control_tower pipeline schema | ai-hub profiles/catalogs | tests`
- stack: `Pydantic | YAML | OpenRewrite | Spring Boot 3.5.6`
- related: `V1-03`

## goal
<!-- One sentence. Start with a verb. -->
> Implement the locked V1 three-stage migration route and make Spring Boot 4 unselectable from the supported Control Tower pipeline.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/schemas/pipeline_definition.py` — add V1 fields for `output_subfolder`, `previous_stage_sandbox`, stage target metadata, and known continuation policies
- [ ] `modernizer-solution-ai-hub/profiles/*.yaml` — normalize supported route to the three V1 profiles only
- [ ] `modernizer-solution-ai-hub/catalogs/openrewrite/*.yaml` — add or rename the Stage 2 catalog as `springboot-2.7-to-3.5-java17.yaml`
- [ ] `tests/control_tower/test_pipeline_definition_schema.py` — assert the V1 route has exactly Stage 1, Stage 2, Stage 3 with target `3.5.6` and Java 21 final target
- [ ] `tests/control_tower/test_pipeline_registration.py` — assert Boot 4 profiles/catalogs are not selectable through `/v1/pipelines`
- ~~not in scope: executing the migration runner~~
- ~~not in scope: Azure model registry~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] `springboot-216-to-356-java21-three-stage` validates with exactly three stages (unit test)
- [ ] Stage 1 target is Spring Boot `2.7.18` and Java `11` (unit test)
- [ ] Stage 2 target is Spring Boot `3.5.6` and Java `17` (unit test)
- [ ] Stage 3 target is Spring Boot `3.5.6` and Java `21` (unit test)
- [ ] Boot 4 profile/catalog files may exist historically, but are not returned in supported V1 route APIs (API response | unit test)
- [ ] No execution-relevant V1 profile points to `3.5.14` (unit test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none
- model: none
- token budget: none
- do NOT touch: `migration_factory/orchestrator/*`

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| pipeline_id | `springboot-216-to-356-java21-three-stage` |
| stage1_profile | `springboot-2.1.6-to-2.7-java11` |
| stage2_profile | `springboot-2.7-to-3.5-java17` |
| stage3_profile | `springboot-3.5-java17-to-java21` |
| final_spring_boot | `3.5.6` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```text
PR that adds the V1 pipeline contract and tests proving route lock, target lock, and Boot 4 exclusion.
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-01` |
| blocks | `V1-03` |

## effort
`M`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Persist normalized stage chain
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `Control Tower persistence | job creation | stage_runs`
- stack: `SQLite | UnitOfWork | Pydantic contracts`
- related: `V1-02`

## goal
<!-- One sentence. Start with a verb. -->
> Implement a normalized immutable stage-chain ledger populated at job creation.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0007_v1_stage_chain.sql` — create `stage_chain_ledger`, `stage_status_history`, `stage_command_links`, `stage_approval_links`, `stage_action_links`, `stage_artifact_links`, and `proof_gates`
- [ ] `migration_factory/control_tower/domain/entities.py` — add immutable `StageChainLedgerRecord`
- [ ] `migration_factory/control_tower/application/ports.py` — add repository protocol for stage-chain ledger operations
- [ ] `migration_factory/control_tower/infrastructure/sqlite/repositories.py` — implement insert/list/get for stage-chain ledger and immutable triggers
- [ ] `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py` — expose the ledger repository
- [ ] `migration_factory/control_tower/application/services.py` — populate ledger rows during `CreateMigrationJobService.execute`
- [ ] `tests/control_tower/test_v1_stage_chain_ledger.py` — prove creation, immutable rows, checksums, and stage binding
- ~~not in scope: worker execution~~
- ~~not in scope: approval state machine~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Creating a V1 job inserts exactly three `stage_chain_ledger` rows (unit test)
- [ ] Stage 2 ledger `source_kind` is `previous_stage_sandbox` and `input_ref` points to Stage 1 sandbox ref (unit test)
- [ ] Stage 3 ledger `source_kind` is `previous_stage_sandbox` and `input_ref` points to Stage 2 sandbox ref (unit test)
- [ ] Ledger rows store pipeline checksum, profile checksum, catalog checksum, selected JDK, run dir, sandbox dir, and output root (unit test)
- [ ] Updating or deleting a ledger row fails through SQLite immutability triggers (unit test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none
- model: none
- token budget: none
- do NOT touch: existing migration files `0001_foundation.sql` through `0006_m2_terminal_artifacts.sql` except migration runner ordering tests if required

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| migration_number | `0007_v1_stage_chain.sql` |
| source_binding_rule | `Stage 2 <- Stage 1 sandbox; Stage 3 <- Stage 2 sandbox` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```text
PR with migration 0007, domain/repository/UoW support, job-creation integration, and tests.
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-02` |
| blocks | `V1-04` |

## effort
`L`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Expose stage chain projections
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `FastAPI adapter | Control Tower queries | Next.js contracts`
- stack: `FastAPI | SQLite | Next.js App Router`
- related: `V1-03`

## goal
<!-- One sentence. Start with a verb. -->
> Expose the persisted V1 stage chain through read APIs and a minimal UI projection.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/application/dto.py` — add `StageChainLedgerDto`
- [ ] `migration_factory/control_tower/application/queries.py` — add query service for job stage chain
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add `GET /v1/jobs/{job_id}/stages` and `GET /v1/jobs/{job_id}/stages/{stage_id}` backed by the ledger
- [ ] `web/control-tower/lib/contracts.ts` — add stage-chain DTO types
- [ ] `web/control-tower/lib/controlTowerApi.ts` — add stage-chain client calls
- [ ] `web/control-tower/app/page.tsx` — render a minimal stage timeline from API data when a job is selected
- [ ] `tests/control_tower/test_v1_stage_chain_api.py` — assert API shape and redaction
- [ ] `web/control-tower/tests/controlTowerApi.test.ts` — assert client parses stage projections
- ~~not in scope: live stage execution~~
- ~~not in scope: assistant panel~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] `GET /v1/jobs/{job_id}/stages` returns exactly three ledger-backed stage rows for V1 jobs (API response)
- [ ] API response includes stage key, profile ID, target Java/Spring Boot, selected JDK, status, run dir ref, and sandbox dir ref (API response)
- [ ] API response does not expose absolute local filesystem paths unless already represented as registered-root-relative refs (unit test)
- [ ] UI test proves the stage timeline labels Stage 1, Stage 2, and Stage 3 (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none for dev API; preserve existing API security middleware
- model: none
- token budget: none
- do NOT touch: worker launcher implementation

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| endpoint_list | `GET /v1/jobs/{job_id}/stages` |
| endpoint_detail | `GET /v1/jobs/{job_id}/stages/{stage_id}` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "stages": [
    {
      "stage_id": "stage1_boot216_to_boot27_java11",
      "stage_index": 1,
      "profile_id": "springboot-2.1.6-to-2.7-java11",
      "target_spring_boot": "2.7.18",
      "target_java": "11",
      "selected_jdk_id": "java11",
      "status": "PENDING"
    }
  ]
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-03` |
| blocks | `V1-05` |

## effort
`M`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Validate runner JDK readiness
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `runner profile | health diagnostics | stage-chain ledger`
- stack: `Python subprocess | Maven | Java 11/17/21`
- related: `V1-04`

## goal
<!-- One sentence. Start with a verb. -->
> Implement backend-owned Maven and per-stage JDK readiness checks for the V1 route.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/schemas/runner_profile.py` — support env-backed `MAVEN_CMD`, `JAVA11_HOME`, `JAVA17_HOME`, and `JAVA21_HOME` references without exposing raw browser-edited paths
- [ ] `migration_factory/control_tower/application/services.py` — add runner readiness service that verifies each configured JDK major version and Maven availability
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add `GET /v1/runner-profiles/{id}` and `POST /v1/runner-profiles/{id}/health-check` if missing
- [ ] `web/control-tower/app/page.tsx` — show runner readiness badges for Java 11, Java 17, Java 21, and Maven
- [ ] `tests/control_tower/test_v1_runner_readiness.py` — fake command runner tests for pass/fail/degraded states
- ~~not in scope: Maven Toolchains XML generation~~
- ~~not in scope: running OpenRewrite~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Health check returns `READY` only when Java 11, Java 17, Java 21, and Maven checks pass (unit test)
- [ ] Stage 1 maps to `JAVA11_HOME`, Stage 2 maps to `JAVA17_HOME`, and Stage 3 maps to `JAVA21_HOME` (unit test)
- [ ] Failed or missing env refs return `BLOCKED` with redacted details (API response)
- [ ] Browser request cannot override JDK path, Maven path, or arbitrary environment keys (unit test)
- [ ] UI renders readiness status without showing secret values or raw API keys (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none for local dev; preserve existing security middleware
- model: none
- token budget: none
- do NOT touch: global system `JAVA_HOME`; do not write `~/.m2/toolchains.xml`

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| maven_ref | `MAVEN_CMD` |
| java11_ref | `JAVA11_HOME` |
| java17_ref | `JAVA17_HOME` |
| java21_ref | `JAVA21_HOME` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "runner_profile_id": "windows-local-v1-migration",
  "status": "READY | BLOCKED | DEGRADED",
  "checks": [
    {"id": "java11", "expected_major": 11, "status": "PASS | FAIL"},
    {"id": "java17", "expected_major": 17, "status": "PASS | FAIL"},
    {"id": "java21", "expected_major": 21, "status": "PASS | FAIL"},
    {"id": "maven", "status": "PASS | FAIL"}
  ],
  "secrets_redacted": true
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-04` |
| blocks | `V1-06` |

## effort
`L`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Execute worker-owned Stage One
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `worker launcher | command manifests | migration orchestrator`
- stack: `FastAPI | Windows Job Objects | LangGraph runner | Maven`
- related: `V1-05`

## goal
<!-- One sentence. Start with a verb. -->
> Execute Stage 1 through a durable worker command that invokes the existing migration orchestrator runner.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/application/commands.py` — add typed `RunOrchestratorStageCommand`
- [ ] `migration_factory/control_tower/application/services.py` — enqueue `RUN_ORCHESTRATOR_STAGE` only for current eligible stage
- [ ] `migration_factory/control_tower/infrastructure/worker_launcher.py` — build backend-owned argv for `python -m migration_factory.orchestrator.runner`
- [ ] `migration_factory/control_tower/domain/manifests.py` — include stage ledger ID, selected JDK ID, profile checksum, catalog checksum, and sandbox dirs in command manifest
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — replace any direct migration execution path with enqueue/launch command only
- [ ] `tests/control_tower/test_v1_worker_stage_execution.py` — assert command persistence before launch and no route-handler execution
- ~~not in scope: Stage 2/3 automatic continuation~~
- ~~not in scope: AI repair~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Starting a V1 job enqueues a `RUN_ORCHESTRATOR_STAGE` command for Stage 1 only (unit test)
- [ ] Command manifest is written before process launch and includes profile/catalog checksums (unit test)
- [ ] Worker argv is backend-owned and contains no browser-supplied executable or shell string (unit test)
- [ ] Stage 1 command environment uses `JAVA11_HOME` through `JAVA_HOME/PATH` mapping (unit test)
- [ ] On non-Windows, real process launch fails closed with clear unsupported-platform error where Job Object control is required (unit test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none
- model: none
- token budget: none
- do NOT touch: arbitrary shell support; `shell=True` forbidden

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| runner_module | `migration_factory.orchestrator.runner` |
| command_type | `RUN_ORCHESTRATOR_STAGE` |
| stage | `stage1_boot216_to_boot27_java11` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "command_type": "RUN_ORCHESTRATOR_STAGE",
  "stage_index": 1,
  "selected_jdk_id": "java11",
  "argv_owned_by_backend": true,
  "manifest_checksum": "sha256:<hex>"
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-05` |
| blocks | `V1-07` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Resume approvals through Control Tower
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `orchestrator interrupt/resume | Control Tower state | approval audit`
- stack: `LangGraph | SQLite | FastAPI | Next.js`
- related: `V1-06`

## goal
<!-- One sentence. Start with a verb. -->
> Implement Control Tower approval and resume state for orchestrator pauses without side effects before approval.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0008_v1_approvals.sql` — create `approvals` table and stage approval links
- [ ] `migration_factory/control_tower/domain/entities.py` — add `ApprovalRecord`
- [ ] `migration_factory/control_tower/application/services.py` — create, approve, reject, and consume exact-checksum approvals
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add approval list/detail/approve/reject endpoints under `/v1/jobs/{job_id}/approvals`
- [ ] `web/control-tower/app/page.tsx` — render a minimal approval card with approve/reject controls
- [ ] `tests/control_tower/test_v1_approval_resume.py` — test approve, reject, stale checksum, and side-effect-safe resume
- ~~not in scope: GPT-generated plan amendments~~
- ~~not in scope: patch application~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Worker/orchestrator pause creates an `APPROVAL_REQUIRED` record with immutable candidate checksum (unit test)
- [ ] Approving with the exact checksum transitions approval to `APPROVED` and enqueues `RESUME_ORCHESTRATOR_STAGE` (unit test)
- [ ] Approving with stale checksum fails with a deterministic conflict error (unit test)
- [ ] Rejection records actor, reason, and audit event without resuming the worker (unit test)
- [ ] No mutation or non-idempotent worker action happens before approval resume (unit test)
- [ ] UI approval card can approve/reject using API mocks (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing local actor attribution only
- model: none
- token budget: none
- do NOT touch: AI model/provider code

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| resume_module | `migration_factory.orchestrator.resume` |
| checksum_rule | `approval applies only to exact candidate checksum` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "approval_id": "approval-...",
  "job_id": "job-...",
  "stage_id": "stage1_boot216_to_boot27_java11",
  "state": "APPROVAL_REQUIRED | APPROVED | REJECTED",
  "candidate_checksum": "sha256:<hex>",
  "resume_command_id": "cmd-..."
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-06` |
| blocks | `V1-08` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Continue stages through sandboxes
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `stage-chain ledger | worker stage execution | continuation policy`
- stack: `SQLite | Windows worker | Maven/OpenRewrite`
- related: `V1-07`

## goal
<!-- One sentence. Start with a verb. -->
> Implement backend-owned Stage 2 and Stage 3 continuation through previous-stage sandbox outputs.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/application/services.py` — select next stage only when current stage gates pass
- [ ] `migration_factory/control_tower/domain/transitions.py` — add stage-level continuation rules for V1 pipeline
- [ ] `migration_factory/control_tower/infrastructure/worker_launcher.py` — map Stage 2 to Java 17 and Stage 3 to Java 21
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — expose current stage and continuation status in job projection
- [ ] `web/control-tower/app/page.tsx` — update stage timeline based on queued/running/passed/failed states
- [ ] `tests/control_tower/test_v1_stage_continuation.py` — prove Stage 2/3 block/unblock rules and sandbox binding
- ~~not in scope: AI repair on failed stages~~
- ~~not in scope: privileged ad hoc actions~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Stage 2 cannot queue before Stage 1 has `transform_applied_in_sandbox` and `build_passed_in_sandbox` proof gates (unit test)
- [ ] Stage 3 cannot queue before Stage 2 has required proof gates (unit test)
- [ ] Stage 2 worker command uses Stage 1 `sandbox_dir` as input and Java 17 as selected JDK (unit test)
- [ ] Stage 3 worker command uses Stage 2 `sandbox_dir` as input and Java 21 as selected JDK (unit test)
- [ ] Failed stage blocks automatic continuation and records `stage.failed` event (unit test)
- [ ] UI shows completed/current/blocked stages from API state (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none
- model: none
- token budget: none
- do NOT touch: Azure/model registry files

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| stage2_input | `stage1.sandbox_dir` |
| stage3_input | `stage2.sandbox_dir` |
| required_gates | `transform_applied_in_sandbox, build_passed_in_sandbox` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "job_id": "job-...",
  "current_stage_index": 2,
  "continuation_status": "READY | BLOCKED | FAILED",
  "input_ref": "stage1.sandbox_dir",
  "selected_jdk_id": "java17"
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-07` |
| blocks | `V1-09` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Register Azure model profiles
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `Control Tower model registry | capabilities API | readiness UI`
- stack: `Azure AI Foundry | Azure OpenAI | Pydantic | FastAPI`
- related: `V1-08`

## goal
<!-- One sentence. Start with a verb. -->
> Implement provider-neutral Azure model profiles and schema capability health checks.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0009_v1_model_profiles.sql` — create `model_profiles`, `model_capabilities`, and `model_health_checks`
- [ ] `migration_factory/control_tower/domain/entities.py` — add model profile, capability, and health check records
- [ ] `migration_factory/control_tower/application/services.py` — add fake-provider-first model health service
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add `GET /v1/model-profiles`, `GET /v1/model-profiles/{id}`, `POST /v1/model-profiles/{id}/health-check`, and include model status in `GET /v1/capabilities`
- [ ] `web/control-tower/app/page.tsx` — show model readiness summary on job creation/status view
- [ ] `tests/control_tower/test_v1_model_registry.py` — test fake provider schema pass/fail, fallback disabled, redaction
- ~~not in scope: real repair calls~~
- ~~not in scope: assistant chat streaming~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] `azure-foundry-v1` profile registers GPT-5-mini proposer, Mistral-Large-3 reviewer, and disabled Llama fallback (unit test)
- [ ] Health check stores capability strategy for proposer plan schema, proposer repair schema, and reviewer critique schema (unit test)
- [ ] Missing endpoint/API key/API version reports `BLOCKED` with secrets redacted (API response)
- [ ] Llama fallback cannot be invoked automatically and returns `DISABLED` (unit test)
- [ ] Normal CI uses fake provider only; live Azure tests require `RUN_LIVE_AZURE_TESTS=true` (unit test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: BYOK through env refs only
- model: `gpt-5-mini` proposer, `Mistral-Large-3` reviewer, `Llama-3.3-70B-Instruct` disabled
- token budget: health check ≤1,000 input / ≤500 output per schema probe
- do NOT touch: orchestrator runner execution path

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| endpoint_env | `AZURE_OPENAI_ENDPOINT` |
| api_key_env | `AZURE_OPENAI_API_KEY` |
| api_version_env | `AZURE_OPENAI_API_VERSION` |
| proposer_deployment_ref | `AZURE_DEPLOYMENT_GPT5_MINI` |
| reviewer_deployment_ref | `AZURE_DEPLOYMENT_MISTRAL_LARGE_3` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "profile_id": "azure-foundry-v1",
  "status": "READY | DEGRADED | BLOCKED | DISABLED",
  "checks": [
    {"role": "proposer", "schema": "PlanProposalV1", "status": "PASS | FAIL"},
    {"role": "reviewer", "schema": "ReviewerCritiqueV1", "status": "PASS | FAIL"}
  ],
  "secrets_redacted": true
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-08` |
| blocks | `V1-10` |

## effort
`L`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Audit model invocations
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `model calls | audit trail | events`
- stack: `Azure OpenAI | SQLite | FastAPI SSE`
- related: `V1-09`

## goal
<!-- One sentence. Start with a verb. -->
> Persist redacted model invocation records and stream public model-call events from Control Tower.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0010_v1_model_calls.sql` — create `model_calls` table with redacted request/response refs and usage fields
- [ ] `migration_factory/control_tower/domain/entities.py` — add `ModelCallRecord`
- [ ] `migration_factory/control_tower/application/services.py` — wrap fake and live provider calls with audited start/completion/failure records
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — expose model-call summaries under job details and run events
- [ ] `web/control-tower/app/page.tsx` — render a minimal model activity list without raw prompts/secrets
- [ ] `tests/control_tower/test_v1_model_call_audit.py` — test redaction, event creation, failure classification, and replay
- ~~not in scope: Context Builder retrievers~~
- ~~not in scope: plan amendment workflow~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Every model call records provider, deployment ref, role, purpose, context ref, status, latency, and token usage when available (unit test)
- [ ] Raw API keys and secret-like values are never persisted in `model_calls` or events (unit test)
- [ ] `model.call_started`, `model.call_completed`, and `model.call_failed` events replay through existing event APIs (unit test)
- [ ] UI renders model role/purpose/status but not raw prompt text (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: BYOK through env refs only
- model: registered model profiles only
- token budget: do not create model calls in normal tests except fake provider
- do NOT touch: patch application or filesystem mutation

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| table | `model_calls` |
| event_types | `model.call_started, model.call_completed, model.call_failed` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "model_call_id": "model-call-...",
  "job_id": "job-...",
  "role": "proposer | reviewer | assistant",
  "purpose": "plan_generation | repair_proposal | assistant_answer",
  "status": "STARTED | COMPLETED | FAILED",
  "secrets_redacted": true
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-09` |
| blocks | `V1-11` |

## effort
`M`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Build bounded context packs
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `context builder | artifacts | model-call audit`
- stack: `SQLite | file retrievers | Azure OpenAI`
- related: `V1-10`

## goal
<!-- One sentence. Start with a verb. -->
> Implement immutable bounded context packs for model calls using deterministic retrievers and secret redaction.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0011_v1_context_packs.sql` — create `context_packs` and evidence manifest storage
- [ ] `migration_factory/control_tower/domain/entities.py` — add `ContextPackRecord`
- [ ] `migration_factory/control_tower/application/context_builder.py` — implement context pack builder with budgets and manifest checksums
- [ ] `migration_factory/control_tower/application/retrievers.py` — implement first retrievers: Maven error window, changed files, stage ledger, proof gates, artifact refs, POM section
- [ ] `migration_factory/control_tower/application/redaction.py` — implement forbidden file filter and secret redactor
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — expose context-pack summaries for job/stage debugging
- [ ] `tests/control_tower/test_v1_context_builder.py` — test budgets, redaction, no full repo/full log, immutable checksums
- ~~not in scope: generating plan proposals~~
- ~~not in scope: applying patches~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Builder creates a context pack with purpose, job ID, stage ID, budget tokens, estimated tokens, evidence refs, and checksum (unit test)
- [ ] Full repository dumps are rejected by policy (unit test)
- [ ] Full logs are rejected; only bounded log windows are included (unit test)
- [ ] Forbidden files such as `.env`, keys, certs, keystores, and credential-like names are filtered (unit test)
- [ ] Secret-like values are redacted and redaction summary is persisted (unit test)
- [ ] Context pack rows are immutable after creation (unit test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: none
- model: none during normal tests
- token budget: plan 20,000/5,000; repair 20,000/5,000; reviewer 12,000/3,000; assistant 6,000/1,500
- do NOT touch: model provider networking code except references to context IDs

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| default_forbidden_files | `.env, keys, tokens, keystores, certs, credentials, local secret DBs` |
| first_purposes | `BUILD_FAILURE_CONTEXT, REPAIR_PROPOSAL_CONTEXT, ASSISTANT_ANSWER_CONTEXT` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "context_pack_id": "ctx-...",
  "purpose": "BUILD_FAILURE_CONTEXT",
  "job_id": "job-...",
  "stage_id": "stage2_boot27_to_boot356_java17",
  "budget_tokens": 20000,
  "estimated_tokens": 15400,
  "evidence_refs": [],
  "redaction_summary": {"secret_like_values_removed": 0},
  "checksum": "sha256:<hex>"
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-10` |
| blocks | `V1-12` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Propose plan amendments
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `plan amendments | context packs | model registry | approval UI`
- stack: `Azure OpenAI | Mistral reviewer later | FastAPI | Next.js`
- related: `V1-11`

## goal
<!-- One sentence. Start with a verb. -->
> Implement GPT-5-mini plan amendment proposals from immutable user instructions and bounded context packs.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0012_v1_plan_amendments.sql` — create `plan_amendments` and `plan_revisions`
- [ ] `migration_factory/control_tower/domain/entities.py` — add plan amendment and plan revision records
- [ ] `migration_factory/control_tower/application/services.py` — add workflow states from `DRAFT` to `USER_ACCEPTED_FOR_REVIEW`
- [ ] `migration_factory/control_tower/application/model_schemas.py` — define `PlanProposalV1` structured output schema
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add `POST /v1/jobs/{job_id}/plan-amendments` and list/detail endpoints
- [ ] `web/control-tower/app/page.tsx` — render plan amendment form and proposal preview
- [ ] `tests/control_tower/test_v1_plan_amendments.py` — test immutable instructions, proposal schema validation, revision chain, and user accept/reject
- ~~not in scope: Mistral critique gate~~
- ~~not in scope: executing approved plan~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] User instruction is persisted immutably before any model call (unit test)
- [ ] Context pack purpose is `PLAN_AMENDMENT_CONTEXT` and references stage evidence only through manifest refs (unit test)
- [ ] Fake GPT provider returns a schema-valid `PlanProposalV1` saved as `PROPOSED` (unit test)
- [ ] User can reject a proposal and the state becomes `USER_REJECTED` without worker execution (unit test)
- [ ] User can accept a proposal for review and the state becomes `USER_ACCEPTED_FOR_REVIEW` (unit test)
- [ ] UI shows proposal before any final approval control appears (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing actor attribution only
- model: `gpt-5-mini` proposer through registered model profile
- token budget: 16,000 input / 4,000 output for plan amendments
- do NOT touch: worker execution/resume for approved plans

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| schema | `PlanProposalV1` |
| first_state | `DRAFT` |
| terminal_non_execution_state | `USER_ACCEPTED_FOR_REVIEW` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "plan_revision_id": "plan-rev-...",
  "state": "PROPOSED",
  "proposal_checksum": "sha256:<hex>",
  "context_pack_id": "ctx-...",
  "model_call_id": "model-call-..."
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-11` |
| blocks | `V1-13` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Gate plans with reviewer
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `plan revisions | reviewer critiques | backend policy gate`
- stack: `Azure OpenAI | Mistral-Large-3 | SQLite | FastAPI`
- related: `V1-12`

## goal
<!-- One sentence. Start with a verb. -->
> Implement reviewer critique and backend policy validation before any plan can become approval-ready.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0013_v1_reviewer_policy.sql` — create `reviewer_critiques` and policy validation result storage
- [ ] `migration_factory/control_tower/application/model_schemas.py` — define `ReviewerCritiqueV1`
- [ ] `migration_factory/control_tower/application/policy_gate.py` — validate schema, model readiness, stage state, path containment, command allowlist, and checksum consistency
- [ ] `migration_factory/control_tower/application/services.py` — transition plan revisions through `CRITIQUED`, `POLICY_VALIDATED`, and `APPROVAL_REQUIRED`
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — expose critique/policy result with plan detail
- [ ] `web/control-tower/app/page.tsx` — show critique risk, missing evidence, validation gaps, and approval readiness
- [ ] `tests/control_tower/test_v1_reviewer_policy_gate.py` — test approve/revise/reject critique and backend policy failures
- ~~not in scope: patch apply/rollback~~
- ~~not in scope: assistant chat~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Accepted plan proposal is sent to reviewer using `REVIEWER_CRITIQUE_CONTEXT` (unit test)
- [ ] Reviewer output must match `ReviewerCritiqueV1` or the workflow becomes `FAILED`/`REVISE` without approval (unit test)
- [ ] Backend policy blocks unsafe command, path escape, stale stage version, missing evidence, or disabled reviewer (unit test)
- [ ] Reviewer cannot approve execution; only backend policy can mark `APPROVAL_REQUIRED` (unit test)
- [ ] UI displays critique and policy result before approval controls (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing actor attribution only
- model: `Mistral-Large-3` reviewer through registered model profile
- token budget: 12,000 input / 3,000 output for reviewer critique
- do NOT touch: worker process launch internals

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| reviewer_schema | `ReviewerCritiqueV1` |
| reviewer_role | `Mistral-Large-3` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "critique_id": "critique-...",
  "decision": "APPROVE | REVISE | REJECT",
  "risk_level": "LOW | MEDIUM | HIGH",
  "policy_result": "PASS | FAIL",
  "approval_ready": true
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-12` |
| blocks | `V1-14` |

## effort
`L`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Detect repair opportunities
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `command results | stage failures | context builder`
- stack: `Maven | OpenRewrite | SQLite | Azure OpenAI fake provider`
- related: `V1-13`

## goal
<!-- One sentence. Start with a verb. -->
> Implement deterministic failure classification and GPT repair proposal creation without applying changes.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0014_v1_repair_attempts.sql` — create `repair_attempts`, `repair_instructions`, `repair_proposals`, and `validation_plans`
- [ ] `migration_factory/control_tower/application/repair_classifier.py` — classify Maven/OpenRewrite/build/test failures deterministically first
- [ ] `migration_factory/control_tower/application/model_schemas.py` — define `RepairProposalV1` and `ValidationPlanV1`
- [ ] `migration_factory/control_tower/application/services.py` — create repair attempts and proposals from failed command evidence
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add repair list/detail/instruction endpoints
- [ ] `web/control-tower/app/page.tsx` — render repair proposal preview and user instruction form
- [ ] `tests/control_tower/test_v1_repair_proposals.py` — test classification, context pack, schema validation, attempt limits
- ~~not in scope: applying patches~~
- ~~not in scope: rollback~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Failed Maven/OpenRewrite command creates `FAILURE_DETECTED` repair attempt with deterministic classification (unit test)
- [ ] Repair context uses `BUILD_FAILURE_CONTEXT` or `OPENREWRITE_FAILURE_CONTEXT` and bounded evidence only (unit test)
- [ ] Fake GPT proposer creates schema-valid repair proposal with patch metadata and validation plan (unit test)
- [ ] Max repair attempts per stage is enforced at `3` (unit test)
- [ ] User repair instruction is immutable and included only in the next proposal context (unit test)
- [ ] UI renders repair proposal without apply/approve execution when reviewer gate is absent (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing actor attribution only
- model: `gpt-5-mini` proposer through registered model profile
- token budget: 20,000 input / 5,000 output for repair proposal
- do NOT touch: sandbox files or patch application code

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| max_repair_attempts_per_stage | `3` |
| max_model_calls_per_attempt | `5` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "repair_attempt_id": "repair-...",
  "state": "PROPOSED",
  "classification": "MAVEN_BUILD_FAILURE | OPENREWRITE_FAILURE | TEST_FAILURE",
  "proposal_checksum": "sha256:<hex>",
  "validation_plan_id": "validation-plan-..."
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-13` |
| blocks | `V1-15` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Apply approved repair patches
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `repair proposals | sandbox workspace | worker commands`
- stack: `SQLite | patch application | Maven validation | Windows worker`
- related: `V1-14`

## goal
<!-- One sentence. Start with a verb. -->
> Apply exact approved repair patches inside sandbox only, validate them, and rollback on failure.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0015_v1_patch_artifacts.sql` — create `patch_artifacts` and repair snapshot records
- [ ] `migration_factory/control_tower/application/patch_policy.py` — validate patch scope, file allowlist, forbidden files, path containment, legacy checksum unchanged, and patch size limits
- [ ] `migration_factory/control_tower/application/services.py` — approve, snapshot, apply, validate, rollback, and escalate repair attempts
- [ ] `migration_factory/control_tower/infrastructure/worker_launcher.py` — add typed worker commands `APPLY_APPROVED_PATCH`, `RUN_MAVEN_OPERATION`, and `ROLLBACK_REPAIR`
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add repair approve/reject/rollback endpoints
- [ ] `web/control-tower/app/page.tsx` — render repair approve/reject/rollback controls with checksum display
- [ ] `tests/control_tower/test_v1_patch_apply_rollback.py` — test path escape, checksum mismatch, validation fail, rollback success
- ~~not in scope: arbitrary shell diagnostics~~
- ~~not in scope: writing legacy source~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Patch cannot be applied unless reviewer critique and backend policy pass (unit test)
- [ ] Approval requires exact proposal checksum and current stage version (unit test)
- [ ] Patch paths outside sandbox are rejected (unit test)
- [ ] Forbidden files and secret-like paths are rejected (unit test)
- [ ] Sandbox snapshot is created before patch application (unit test)
- [ ] Validation plan runs only approved Maven operations and selected stage JDK (unit test)
- [ ] Failed validation triggers rollback and records `repair.rolled_back` event (unit test)
- [ ] UI shows exact diff/checksum before approve button is enabled (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing actor attribution only
- model: none during patch application
- token budget: none
- do NOT touch: legacy source root; arbitrary shell remains disabled

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| max_patch_files | `20` |
| max_patch_bytes | `512 KB` |
| max_validation_time_seconds | `3600` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "repair_attempt_id": "repair-...",
  "state": "VALIDATION_PASSED | VALIDATION_FAILED | ROLLED_BACK",
  "patch_artifact_id": "patch-...",
  "snapshot_id": "snapshot-...",
  "validation_command_id": "cmd-..."
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-14` |
| blocks | `V1-16` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Add read-only assistant tools
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `assistant threads | context packs | read tools | job UI`
- stack: `Azure OpenAI | FastAPI | Next.js | SQLite`
- related: `V1-15`

## goal
<!-- One sentence. Start with a verb. -->
> Implement an evidence-grounded assistant that can inspect bounded job evidence but cannot execute or approve actions.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0016_v1_assistant_tools.sql` — create `assistant_threads`, `assistant_messages`, and `tool_calls`
- [ ] `migration_factory/control_tower/application/read_tools.py` — implement read-only tools for stage artifacts, log windows, sandbox file windows, diffs, proof gates, and stage chain
- [ ] `migration_factory/control_tower/application/services.py` — add assistant message service with tool filtering and context-pack creation
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add assistant messages endpoint and non-execution stream endpoint
- [ ] `web/control-tower/app/page.tsx` — render right-side assistant panel with message history
- [ ] `tests/control_tower/test_v1_assistant_tools.py` — prove read limits, no mutation, no command execution, and redaction
- ~~not in scope: privileged action request execution~~
- ~~not in scope: direct shell tool~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Assistant context uses `ASSISTANT_ANSWER_CONTEXT` and bounded read tools only (unit test)
- [ ] Read tools enforce max file listing, max depth, max bytes, max log lines, and max search matches (unit test)
- [ ] Assistant cannot call write, Maven, shell, approval, or worker execution tools (unit test)
- [ ] Tool results are redacted and summarized before follow-up model calls when over budget (unit test)
- [ ] UI assistant panel displays responses and citations to evidence refs, not raw secret content (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing actor attribution only
- model: `gpt-5-mini` assistant through registered model profile
- token budget: 6,000 input / 1,500 output for assistant answers; 4,000/1,000 for tool-result summaries
- do NOT touch: privileged action execution code

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| max_file_window_bytes | `64 KB` |
| max_log_window_lines | `500` |
| max_search_matches | `100` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "assistant_message_id": "msg-...",
  "job_id": "job-...",
  "role": "assistant",
  "content": "...",
  "evidence_refs": [],
  "can_execute": false
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-15` |
| blocks | `V1-17` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Request privileged typed actions
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `assistant | privileged actions | approval cards | worker commands`
- stack: `FastAPI | SQLite | Windows worker | Maven`
- related: `V1-16`

## goal
<!-- One sentence. Start with a verb. -->
> Implement typed pending privileged actions that require backend policy validation and developer approval before execution.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0017_v1_privileged_actions.sql` — create `privileged_actions` table and action links
- [ ] `migration_factory/control_tower/application/action_policy.py` — implement allowlist for Maven compile/tests/dependency tree/effective POM/OpenRewrite preview, patch/write actions, rerun, rollback, continue stage
- [ ] `migration_factory/control_tower/application/services.py` — create, approve, reject, and execute pending actions through worker commands
- [ ] `migration_factory/control_tower/application/read_tools.py` — expose request tools that create pending actions only
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add action list/detail/approve/reject/execute endpoints
- [ ] `web/control-tower/app/page.tsx` — render dedicated privileged action cards separate from assistant messages
- [ ] `tests/control_tower/test_v1_privileged_actions.py` — test unsafe rejection, approval checksum, JDK selection, and shell disabled
- ~~not in scope: arbitrary shell execution~~
- ~~not in scope: deployment/git push/install software actions~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Assistant/tool request creates `PENDING` privileged action and does not execute it (unit test)
- [ ] Backend policy rejects arbitrary PowerShell, arbitrary cmd, arbitrary Maven goals, path escapes, secret reads, legacy source writes, install software, git push, deployment, and model switching (unit test)
- [ ] Developer approval requires exact action checksum and current job/stage version (unit test)
- [ ] Approved Maven action runs under selected stage JDK via worker command (unit test)
- [ ] Shell diagnostic action is `DISABLED` by default (unit test)
- [ ] UI action card is separate from assistant chat and shows exact action/checksum before approval (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing actor attribution only
- model: `gpt-5-mini` may request; no model may execute
- token budget: 6,000 input / 1,500 output when action requested from assistant
- do NOT touch: shell enablement; keep shell disabled

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| disabled_action | `RUN_SANDBOX_SHELL_DIAGNOSTIC` |
| allowed_maven_actions | `RUN_MAVEN_COMPILE, RUN_MAVEN_TESTS, RUN_DEPENDENCY_POLICY, RUN_EFFECTIVE_POM, RUN_DEPENDENCY_TREE` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "action_id": "action-...",
  "action_type": "RUN_MAVEN_TESTS",
  "state": "PENDING | APPROVED | REJECTED | EXECUTED | FAILED",
  "checksum": "sha256:<hex>",
  "requires_developer_approval": true
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-16` |
| blocks | `V1-18` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->

# [feat] Render full V1 cockpit
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `Next.js Control Tower UI | API contracts | SSE`
- stack: `Next.js App Router | React | FastAPI SSE`
- related: `V1-17`

## goal
<!-- One sentence. Start with a verb. -->
> Implement the V1 operator cockpit for job creation, stage timeline, approvals, repairs, actions, assistant, artifacts, and proof.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `web/control-tower/app/page.tsx` or route split under `web/control-tower/app/jobs/*` — implement `/jobs/new` and `/jobs/[jobId]` UX flow as supported by current routing conventions
- [ ] `web/control-tower/lib/contracts.ts` — consolidate DTOs for capabilities, runner readiness, model readiness, stages, approvals, repairs, actions, assistant, artifacts, and proof
- [ ] `web/control-tower/lib/controlTowerApi.ts` — add client methods for all V1 cockpit endpoints
- [ ] `web/control-tower/lib/eventReplay.ts` — keep migration event stream separate from assistant stream
- [ ] `web/control-tower/tests/*.test.tsx` — add component/contract tests for create job, stage timeline, approval card, repair card, action card, assistant, and SSE replay
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — ensure cockpit endpoints return stable contracts already implemented in prior issues
- ~~not in scope: adding new backend workflows not already exposed by prior issues~~
- ~~not in scope: changing execution policy from the UI~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] `/jobs/new` shows source/output selectors, pipeline selector, runner readiness, model readiness, target proof level, and policy summary (web test)
- [ ] `/jobs/[jobId]` shows stage timeline, current command, approvals, plan revisions, repair panel, privileged action cards, logs/events/artifacts, proof gates, final report placeholder, and assistant panel (web test)
- [ ] Event stream and assistant stream are represented as separate client paths/contracts (web test)
- [ ] UI never exposes raw env editor, raw shell command, raw Maven goal, raw model ID editor, or arbitrary working directory editor (web test)
- [ ] `npm run type-check`, `npm test`, and `npm run build` pass (log line)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing local/dev API security only
- model: none in UI tests
- token budget: none
- do NOT touch: worker execution policy; UI must not invent new backend authority

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| event_stream | `GET /v1/jobs/{job_id}/events/stream` |
| assistant_stream | `GET /v1/jobs/{job_id}/assistant/stream` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```text
PR with typed V1 cockpit UI, API client contracts, and web tests for all visible V1 panels.
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-17` |
| blocks | `V1-19` |

## effort
`XL`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests
TOOLS_FORBIDDEN: delete_repo | push_to_main | call_llm
-->

# [feat] Generate deterministic proof reports
<!-- TYPE: feat | fix | chore | refactor | spike | doc -->

## ctx
<!-- 1-3 lines max. What exists NOW that makes this necessary. No history. -->
- component: `proof gates | artifacts | final report | cockpit`
- stack: `Maven | SQLite | FastAPI | Next.js`
- related: `V1-18`

## goal
<!-- One sentence. Start with a verb. -->
> Generate final three-stage proof and redacted reports from deterministic command evidence.

## scope
<!-- Bullet = in. Strike = explicitly out. -->
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/0018_v1_final_reports.sql` — create `final_reports` and complete proof/report linkage if not already present
- [ ] `migration_factory/control_tower/application/proof.py` — compute proof gates only from command results/artifacts, not model summaries
- [ ] `migration_factory/control_tower/application/services.py` — generate final report artifact once all three stages pass required gates
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` — add `GET /v1/jobs/{job_id}/proof` and final report endpoints
- [ ] `web/control-tower/app/page.tsx` — show proof gates and final report link/download when available
- [ ] `tests/control_tower/test_v1_proof_reports.py` — test three-stage proof, redaction, model summary separation, failed-gate behavior
- ~~not in scope: model-created proof~~
- ~~not in scope: changing Maven/test pass criteria~~

## acceptance
<!-- Binary checklist. Each line must be verifiable by the agent alone. -->
- [ ] Final proof requires Stage 1, Stage 2, and Stage 3 required gates to pass (unit test)
- [ ] Proof gates are created only from deterministic command/artifact evidence (unit test)
- [ ] Model call summaries may appear in report but cannot create or override proof gates (unit test)
- [ ] Final report redacts secrets, raw prompts, API keys, and local sensitive paths (unit test)
- [ ] `GET /v1/jobs/{job_id}/proof` returns deterministic proof state and evidence refs (API response)
- [ ] UI shows proof status and final report artifact link only when report exists (web test)
- [ ] No regressions: existing tests green

## constraints
<!-- Hard limits the agent MUST NOT violate. Skip if none. -->
- auth: existing local/dev API security only
- model: none required; optional summary only from audited model calls
- token budget: final report explanation ≤6,000 input / ≤1,500 output if model summary is used
- do NOT touch: command result history or proof evidence mutability

## inputs
<!-- Only list what the agent needs and doesn't have. -->
| key | value / path |
|-----|-------------|
| proof_endpoint | `GET /v1/jobs/{job_id}/proof` |
| required_stage_count | `3` |

## output contract
<!-- What the agent must produce. Format: file | JSON schema | API call | PR. -->
```json
{
  "job_id": "job-...",
  "proof_status": "PASSED | FAILED | INCOMPLETE",
  "stages": [
    {"stage_index": 1, "required_gates_passed": true},
    {"stage_index": 2, "required_gates_passed": true},
    {"stage_index": 3, "required_gates_passed": true}
  ],
  "final_report_artifact_id": "artifact-..."
}
```

## deps
<!-- Blocked by / blocks. Delete row if none. -->
| relation | issue |
|----------|-------|
| blocked_by | `V1-18` |

## effort
`L`
<!-- XS<1h S<4h M<1d L<3d XL>3d -->

---
<!-- Agent instructions (strip before human review if needed) -->
<!--
AGENT_MODE: autonomous
STOP_IF: acceptance not met after 3 attempts → open sub-issue
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm
TOOLS_FORBIDDEN: delete_repo | push_to_main
-->
