# [feat] Render assistant panel

## implementation id
`V1-18F`

## source mapping
- original issue: `V1-18`
- split from: `V1-18`
- source files:
  - `docs/ai_migration_control_tower_v1_issues.md`
  - `docs/CODEXSUGGESTING.md`

## ctx
- component: `web/control-tower cockpit UI and TypeScript contracts`
- stack: `Next.js App Router | React | TypeScript | FastAPI client contracts`
- related: `V1-18G`

## current code evidence
- `migration_factory/control_tower/application/queries.py` - bounded command output windows can be reused by read-only tools.
- `web/control-tower` - no assistant panel or assistant stream exists.
- `migration_factory/control_tower/schemas/pipeline_definition.py` - current schema supports stages, command_jdk, target metadata, and input_source kind legacy_source/previous_stage; the exact V1 previous_stage_sandbox term is not present.
- `migration_factory/control_tower/schemas/runner_profile.py` - RunnerProfile currently stores raw python_executable, Maven executable_path, JDK java_home, filesystem roots, network policy, and ai_profile reference.
- `migration_factory/control_tower/application/services.py` - CreateMigrationJobService creates MigrationJobRecord, RunConfigurationRecord, and StageRunRecord rows; start flow queues foundation diagnostic work, not V1 stage execution.
- `migration_factory/control_tower/domain/entities.py` - no V1 ledger, approval, model invocation, context pack, repair, privileged action, or proof records exist yet.
- `migration_factory/control_tower/application/ports.py` - UnitOfWork exposes current repositories but no V1-specific repositories yet.

## goal
> Deliver `V1-18F` by making `Render assistant panel` concrete in the files listed below, with focused tests and no adjacent V1 behavior.

## scope
- [ ] `web/control-tower/lib/contracts.ts` - add typed DTOs for this panel.
- [ ] `web/control-tower/lib/controlTowerApi.ts` - add client calls for prerequisite backend endpoints.
- [ ] `web/control-tower/app/jobs/new/CreateDiagnosticJobForm.tsx` or `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx` - render the owned panel without backend authority.
- [ ] `web/control-tower/tests/*.test.tsx` - cover visible, empty, loading, error, and forbidden-control states.
- ~~not in scope: backend workflows, shell/Maven/model/path editors, or UI-side execution decisions~~

## acceptance
- [ ] Owned panel covers loading/empty/success/error states.
- [ ] Web tests prove no raw shell/Maven/path/model controls.
- [ ] Locked route remains `springboot-216-to-356-java21-three-stage` with Stage 1 Java 11/Boot 2.7.18, Stage 2 Java 17/Boot 3.5.6 from Stage 1 sandbox, and Stage 3 Java 21/Boot 3.5.6 from Stage 2 sandbox.
- [ ] Boot 4 is not selectable and `3.5.14` is not execution-relevant for V1.
- [ ] Browser payloads cannot choose raw paths, Maven goals, shell commands, working directories, or model deployments.
- [ ] LLM flows cannot execute commands, approve decisions, or write files directly.
- [ ] Focused and affected regression commands in `## test plan` pass with real output.

## constraints
- auth: `existing actor attribution where mutating; none for read-only/dev endpoints`
- model: `gpt-5-mini assistant through registered profile; fake provider in tests`
- token budget: `6000 input / 1500 output`
- do NOT touch:
  - backend workflow services, SQLite migrations, worker launch policy, and model/action authority
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
Future PR for V1-18F changes only issue-owned implementation files, includes focused and affected regression evidence, and leaves unrelated deleted docs untouched.
```

## deps
| relation   | issue             |
| ---------- | ----------------- |
| blocked_by | `V1-16B` |
| blocks     | `V1-18G` |

## test plan
```powershell
Push-Location web/control-tower; npm run type-check; npm test; Pop-Location
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
