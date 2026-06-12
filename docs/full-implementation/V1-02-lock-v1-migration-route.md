# [feat] Lock V1 migration route

## implementation id
`V1-02`

## source mapping
- original issue: `V1-02`
- split from: `none`
- source files:
  - `docs/ai_migration_control_tower_v1_issues.md`
  - `docs/CODEXSUGGESTING.md`

## ctx
- component: `V1 route contract, fixtures, pipeline registration, and runner fixtures`
- stack: `Python | SQLite | FastAPI | pytest | TypeScript contracts where applicable`
- related: `V1-03A,V1-03B,V1-04`

## current code evidence
- `tests/control_tower/_helpers.py` - default helper data still uses pipeline-default and 3.5.14.
- `modernizer-solution-ai-hub/profiles and catalogs/openrewrite` - V1 profiles exist alongside historical Boot 4 and 3.5.14-related assets.
- `migration_factory/control_tower/schemas/pipeline_definition.py` - current schema supports stages, command_jdk, target metadata, and input_source kind legacy_source/previous_stage; the exact V1 previous_stage_sandbox term is not present.
- `migration_factory/control_tower/schemas/runner_profile.py` - RunnerProfile currently stores raw python_executable, Maven executable_path, JDK java_home, filesystem roots, network policy, and ai_profile reference.
- `migration_factory/control_tower/application/services.py` - CreateMigrationJobService creates MigrationJobRecord, RunConfigurationRecord, and StageRunRecord rows; start flow queues foundation diagnostic work, not V1 stage execution.
- `migration_factory/control_tower/domain/entities.py` - no V1 ledger, approval, model invocation, context pack, repair, privileged action, or proof records exist yet.
- `migration_factory/control_tower/application/ports.py` - UnitOfWork exposes current repositories but no V1-specific repositories yet.

## goal
> Deliver `V1-02` by making `Lock V1 migration route` concrete in the files listed below, with focused tests and no adjacent V1 behavior.

## scope
- [ ] `modernizer-solution-ai-hub/profiles/*.yaml` and `catalogs/openrewrite/*.yaml` - lock the V1 route and keep Boot 4/3.5.14 non-selectable
- [ ] `migration_factory/control_tower/infrastructure/sqlite/migrations/<next_v1_migration>.sql` - add only append-only persistence required by this issue; never edit applied migrations 0001-0006
- [ ] `migration_factory/control_tower/adapters/fastapi/app.py` - add only the issue-owned V1 endpoint if a public API is required; route handlers must not execute worker/model/write behavior directly
- [ ] `tests/control_tower/test_v1_02_*.py` - add focused tests for this issue plus affected regression coverage
- ~~not in scope: files, workflows, endpoints, migrations, UI panels, or model/action behavior not named in this issue scope or dependency table~~

## acceptance
- [ ] V1 route exposes only the three-stage pipeline.
- [ ] Boot 4 and 3.5.14 remain non-execution assets.
- [ ] Locked route remains `springboot-216-to-356-java21-three-stage` with Stage 1 Java 11/Boot 2.7.18, Stage 2 Java 17/Boot 3.5.6 from Stage 1 sandbox, and Stage 3 Java 21/Boot 3.5.6 from Stage 2 sandbox.
- [ ] Boot 4 is not selectable and `3.5.14` is not execution-relevant for V1.
- [ ] Browser payloads cannot choose raw paths, Maven goals, shell commands, working directories, or model deployments.
- [ ] LLM flows cannot execute commands, approve decisions, or write files directly.
- [ ] Focused and affected regression commands in `## test plan` pass with real output.

## constraints
- auth: `existing actor attribution where mutating; none for read-only/dev endpoints`
- model: `none`
- token budget: `none`
- do NOT touch:
  - adjacent V1 workflows not listed in this issue scope
  - intentionally deleted historical docs outside `docs/full-implementation/`
  - generated Graphify artifacts under `graphify-out/`
  - unrelated `.control-tower-dev/` runtime databases except `V1-01` git-index hygiene
  - secrets, `.env` files, local logs, and developer-specific config
- forbidden behavior:
  - `Spring Boot 4 selection in the V1 route`
  - `3.5.14 as an execution-relevant V1 target`
  - `browser-selected raw executable paths, Maven goals, shell commands, or model deployment IDs`
  - `LLM execution authority, approval authority, or direct file writes`
  - `restoring unrelated deleted docs`

## recommended skills
- required: `test-discipline` - use for focused tests, affected regressions, and final evidence reporting.
- optional: `graphify` - use before broad code navigation; confirm hints against source/tests.

## inputs
| key | value / path |
|-----|-------------|
| `pipeline_id` | `springboot-216-to-356-java21-three-stage` |
| `stage1` | `springboot-2.1.6-to-2.7-java11 / Spring Boot 2.7.18 / Java 11 / java11` |
| `stage2` | `springboot-2.7-to-3.5-java17 / Spring Boot 3.5.6 / Java 17 / java17` |
| `stage3` | `springboot-3.5-java17-to-java21 / Spring Boot 3.5.6 / Java 21 / java21` |

## output contract
```text
Future PR for V1-02 changes only issue-owned implementation files, includes focused and affected regression evidence, and leaves unrelated deleted docs untouched.
```

## deps
| relation   | issue             |
| ---------- | ----------------- |
| blocked_by | `V1-00B` |
| blocks     | `V1-03A,V1-03B,V1-04` |

## test plan
```powershell
py -m pytest -q tests/control_tower/test_v1_02_*.py -rs --tb=short
py -m pytest -q tests/control_tower -rs --tb=short
git diff --check
git diff --cached --check
```

## implementation notes
* Use Graphify for navigation when `graphify-out/graph.json` exists, then confirm against actual source and tests.
* Preserve existing M2 behavior unless this issue explicitly owns the change.
* Pipeline ID must remain `springboot-216-to-356-java21-three-stage`.
* Stage 1 is Java 11 / Spring Boot 2.7.18 from original legacy source.
* Stage 2 is Java 17 / Spring Boot 3.5.6 from the Stage 1 sandbox.
* Stage 3 is Java 21 / Spring Boot 3.5.6 from the Stage 2 sandbox.
* Boot 4 is not selectable; `3.5.14` is not execution-relevant for V1.
* Shell stays disabled by default; Maven/write actions require typed privileged actions after policy and approval.
* LLM output can request or explain; it cannot execute, approve, or write.
* Browser payloads cannot choose raw paths, Maven goals, model deployments, shell commands, or arbitrary working directories.
* Stage only issue-owned files by explicit path because the worktree may contain unrelated deleted docs.

## stop rules
* Stop if acceptance cannot be met after 3 attempts.
* Stop if implementation requires changing V1 route invariants.
* Stop if implementation requires enabling arbitrary shell execution.
* Stop if implementation requires model execution authority.
* Stop if unrelated deleted docs would need to be restored.
* Stop if required dependencies are not implemented.

## effort
`M`

---

<!--
AGENT_MODE: autonomous
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm when issue explicitly allows it
TOOLS_FORBIDDEN: delete_repo | push_to_main | arbitrary_shell | restore_deleted_docs
-->

