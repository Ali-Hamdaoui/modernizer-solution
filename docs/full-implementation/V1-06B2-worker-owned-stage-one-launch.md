# [feat] Launch worker-owned Stage One

## implementation id
`V1-06B2`

## source mapping
- original issue: `V1-06B`
- split from: `V1-06B`
- source files:
  - `docs/ai_migration_control_tower_v1_issues.md`
  - `docs/CODEXSUGGESTING.md`

## ctx
- component: `Control Tower stage launch execution, worker-owned argv/env mapping, and fail-closed platform handling`
- stack: `Python services | SQLite | worker launcher | Maven/JDK policy | pytest`
- related: `V1-07A,V1-08B`

## current code evidence
- `migration_factory/control_tower/domain/manifests.py` - the stage command manifest needs to be consumed as a launch contract.
- `migration_factory/orchestrator/runner.py` - runner module exists but is not launched by Control Tower stage commands.
- `migration_factory/control_tower/schemas/pipeline_definition.py` - current schema supports stages, command_jdk, target metadata, and input_source kind legacy_source/previous_stage; the exact V1 previous_stage_sandbox term is not present.
- `migration_factory/control_tower/schemas/runner_profile.py` - RunnerProfile currently stores raw python_executable, Maven executable_path, JDK java_home, filesystem roots, network policy, and ai_profile reference.
- `migration_factory/control_tower/application/services.py` - start flow queues foundation diagnostic work, not V1 stage execution.
- `migration_factory/control_tower/application/ports.py` - UnitOfWork exposes current repositories but no V1-specific repositories yet.

## goal
> Deliver `V1-06B2` by making `Launch worker-owned Stage One` concrete in the files listed below, with focused tests and no adjacent V1 behavior.

## scope
- [ ] `migration_factory/control_tower/application/commands.py`, `application/services.py`, and `migration_factory/orchestrator/runner.py` - execute the already-defined stage command contract for Stage 1
- [ ] `migration_factory/control_tower/application/services.py` - map Stage 1 to backend-owned argv/env and JAVA11 behavior
- [ ] `tests/control_tower/test_v1_06b2_*.py` - add focused tests for launch behavior and fail-closed handling
- ~~not in scope: stage-command schema design, assistant tools, approvals, model routing, UI panels, or any adjacent V1 workflow~~

## acceptance
- [ ] Stage 1 launch uses backend-owned argv/env and `shell=False`.
- [ ] Stage 1 uses the `JAVA11` mapping for the worker-owned launch path.
- [ ] Unsupported platform or runtime conditions fail closed without launching a process.
- [ ] Browser payloads cannot choose raw executable paths, Maven goals, shell commands, working directories, or model deployments.
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
- optional: `requesting-code-review` - use before finishing security, execution, approval, redaction, model, action, patch, or proof work.
- optional: `triage` - use if dependency state, readiness, or risk boundaries are unclear.

## inputs
| key | value / path |
|-----|-------------|
| `pipeline_id` | `springboot-216-to-356-java21-three-stage` |
| `stage1` | `springboot-2.1.6-to-2.7-java11 / Spring Boot 2.7.18 / Java 11 / java11` |
| `stage2` | `springboot-2.7-to-3.5-java17 / Spring Boot 3.5.6 / Java 17 / java17` |
| `stage3` | `springboot-3.5-java17-to-java21 / Spring Boot 3.5.6 / Java 21 / java21` |

## output contract
```text
Future PR for V1-06B2 changes only issue-owned implementation files, includes focused and affected regression evidence, and leaves unrelated deleted docs untouched.
```

## deps
| relation   | issue             |
| ---------- | ----------------- |
| blocked_by | `V1-06B1` |
| blocks     | `V1-07A` |

## test plan
```powershell
py -m pytest -q tests/control_tower/test_v1_06b2_*.py -rs --tb=short
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
* Shell stays disabled by default; backend-owned launch logic belongs here.
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
`L`

---

<!--
AGENT_MODE: autonomous
TOOLS_ALLOWED: read_file | write_file | run_tests | call_llm when issue explicitly allows it
TOOLS_FORBIDDEN: delete_repo | push_to_main | arbitrary_shell | restore_deleted_docs
-->

