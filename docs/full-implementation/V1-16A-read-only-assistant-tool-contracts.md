# [feat] Define read-only assistant tool contracts

## implementation id
`V1-16A`

## source mapping
- original issue: `V1-16`
- split from: `V1-16`
- source files:
  - `docs/ai_migration_control_tower_v1_issues.md`
  - `docs/CODEXSUGGESTING.md`

## ctx
- component: `assistant/read-tool schemas, allowlist, and bounded limits`
- stack: `SQLite | FastAPI | audited model gateway | structured outputs | pytest`
- related: `V1-10,V1-11C,V1-16B`

## current code evidence
- `migration_factory/control_tower/application/queries.py` - bounded command output windows can be reused by read-only tools.
- `web/control-tower` - no assistant panel or assistant stream exists.
- `migration_factory/control_tower/schemas/pipeline_definition.py` - current schema supports stages, command_jdk, target metadata, and input_source kind legacy_source/previous_stage; the exact V1 previous_stage_sandbox term is not present.
- `migration_factory/control_tower/schemas/runner_profile.py` - RunnerProfile currently stores raw python_executable, Maven executable_path, JDK java_home, filesystem roots, network policy, and ai_profile reference.
- `migration_factory/control_tower/application/services.py` - current start flow queues foundation diagnostic work, not assistant tool execution.
- `migration_factory/control_tower/application/ports.py` - UnitOfWork exposes current repositories but no V1-specific repositories yet.

## goal
> Deliver `V1-16A` by making `Define read-only assistant tool contracts` concrete in the files listed below, with focused tests and no adjacent V1 behavior.

## scope
- [ ] `migration_factory/control_tower/application/assistant_tools.py` and `redaction.py` - define bounded read-only assistant tool schemas, allowlists, and limits
- [ ] `tests/control_tower/test_v1_16a_*.py` - add focused tests for allowlists, limits, no mutation, and no execution behavior
- ~~not in scope: streaming, assistant message flow, UI panels, model behavior, or any adjacent V1 workflow~~

## acceptance
- [ ] Assistant tools are read-only and allow-listed.
- [ ] Assistant cannot approve, execute, write, or choose deployments.
- [ ] Tool schemas cap output windows and redact tool inputs and outputs.
- [ ] No streaming UI or model behavior is introduced in this issue.
- [ ] Focused and affected regression commands in `## test plan` pass with real output.

## constraints
- auth: `existing actor attribution where mutating; none for read-only/dev endpoints`
- model: `none`
- token budget: `none`
- do NOT touch:
  - raw prompts, raw provider secrets, raw deployment IDs, unredacted context packs, and model-selected execution
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
Future PR for V1-16A changes only issue-owned implementation files, includes focused and affected regression evidence, and leaves unrelated deleted docs untouched.
```

## deps
| relation   | issue             |
| ---------- | ----------------- |
| blocked_by | `V1-00D,V1-10,V1-11C` |
| blocks     | `V1-16B` |

## test plan
```powershell
py -m pytest -q tests/control_tower/test_v1_16a_*.py -rs --tb=short
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
* Shell stays disabled by default; this issue stays read-only.
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

