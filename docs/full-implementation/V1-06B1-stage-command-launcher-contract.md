# [feat] Define stage command launcher contract

## implementation id
`V1-06B1`

## source mapping
- original issue: `V1-06B`
- split from: `V1-06B`
- source files:
  - `docs/ai_migration_control_tower_v1_issues.md`
  - `docs/CODEXSUGGESTING.md`

## ctx
- component: `stage command contract, checksum ownership, and worker-launch payload boundaries`
- stack: `Python services | dataclasses | checksum policy | pytest`
- related: `V1-06A,V1-06B2`

## current code evidence
- `migration_factory/control_tower/domain/manifests.py` - CommandManifest needs the stage command type, checksum inputs, and ownership boundaries.
- `migration_factory/control_tower/application/commands.py` - command-building code exists but does not yet distinguish contract-only launch payloads from actual process execution.
- `migration_factory/control_tower/application/services.py` - queueing flow exists and can be wired to the contract without starting a process here.
- `migration_factory/control_tower/domain/entities.py` - no stage command record yet carries the full checksum-bound argv/env contract.

## goal
> Deliver `V1-06B1` by making `Define stage command launcher contract` concrete in the files listed below, with focused tests and no adjacent V1 behavior.

## scope
- [ ] `migration_factory/control_tower/domain/manifests.py` and `application/commands.py` - define the stage command type and manifest contract, including argv/env ownership and checksum inputs
- [ ] `migration_factory/control_tower/application/services.py` - bind the manifest contract to queueing logic without starting a process
- [ ] `tests/control_tower/test_v1_06b1_*.py` - add focused tests for checksum coverage, argv/env ownership, and no-exec behavior
- ~~not in scope: real process launch, worker startup, public endpoints, runtime migrations, UI panels, or any adjacent V1 workflow~~

## acceptance
- [ ] Manifest checksum covers ledger, JDK, profile, catalog, sandbox, argv, and env references.
- [ ] The command payload records backend-owned argv/env ownership, but no process is started in this issue.
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
  - `shell/process launch in this contract-only slice`
  - `LLM execution authority, approval authority, or direct file writes`
  - `browser-selected raw executable paths, Maven goals, shell commands, or model deployment IDs`
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
Future PR for V1-06B1 changes only issue-owned implementation files, includes focused and affected regression evidence, and leaves unrelated deleted docs untouched.
```

## deps
| relation   | issue             |
| ---------- | ----------------- |
| blocked_by | `V1-06A` |
| blocks     | `V1-06B2` |

## test plan
```powershell
py -m pytest -q tests/control_tower/test_v1_06b1_*.py -rs --tb=short
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
* Shell stays disabled by default; actual launch happens in `V1-06B2`.
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

