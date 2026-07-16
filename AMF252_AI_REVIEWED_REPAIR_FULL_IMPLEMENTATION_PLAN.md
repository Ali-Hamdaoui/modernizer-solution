# AMF-252 AI Reviewed Repair — Full Implementation Plan

## Second-pass review corrections

This second-pass static review re-opened the current source and supersedes ambiguous statements below. It made no application, schema, migration, database, model, or runtime changes.

| Criticism | Verdict | Plan change |
| --- | --- | --- |
| Test-agent role imprecise | **CONFIRMED** | `run_build_agent()` executes the selected command; `run_test_agent()` only parses resulting Surefire XML and writes evidence. All target diagrams now say so. |
| Validation context too vague | **CONFIRMED** | Adds the minimal `ValidationExecutionContext` contract and same-profile invariant. |
| Continuation not fully proven | **CONFIRMED** | Separates creation of `stage_completion_review` from actual continuation; current repair-success → next migration execution is **PARTIALLY PROVEN**. |
| Reviewer revise/reject semantics incomplete | **CONFIRMED** | Recommends persisted non-actionable truthful outcomes and explicit human regeneration for `revise`; no automatic LLM loop. |
| Direct-vs-gate consolidation needs a behavior matrix | **CONFIRMED** | Adds a matrix; consolidate shared mechanics only, not unchosen product semantics. |
| `deterministic_rule_id` fallback corruption | **CONFIRMED** | Direct runtime resolver falls back to base-state checksum/diff checksum/`repair_apply`; add P1 fail-closed correction before Apply rollout. |
| `TESTS_NOT_FOUND` proof semantics | **PARTIALLY CONFIRMED** | Repair validation accepts it, V2 runner accepts it for success, while orchestration summary’s strongest claim requires `TEST_PASSED`. Add explicit qualified proof presentation. |
| Idempotency key may be unused | **CONFIRMED** for direct proposal Apply | Direct endpoint requires but does not use/persist its key; gate actions have a separate persisted idempotency mechanism. Add claim/idempotency protocol before action expansion. |
| Transaction split should move earlier | **CONFIRMED** | Transaction/idempotency is Phase 2, before more repair Apply/action behavior. |
| Full lineage plan may overuse DB columns | **CONFIRMED** | Recommend a hybrid immutable lineage manifest plus minimal indexed/action columns, not one column per artifact. |
| Event plan may be over-expanded | **CONFIRMED** | Limit new events to externally observable state transitions; avoid generic events masking precise causes. |

### Second-pass authoritative status

* The hybrid design and no-new-repair-subgraph recommendation remain **PROVEN by current repository structure**, not by a limitation of LangGraph. The graph state/checkpoints are migration approval/resume-specific, build/test are invoked inside transformation services rather than graph nodes, and V2 repair already has its own records/gates/API/events/UI. Moving repair now would duplicate durable state without improving reuse.
* Projection loss remains **PROVEN** at the three FastAPI `build_reviewed_diff_proposal_from_record(...)` calls.
* A stage-completion gate after successful repair validation is **PROVEN**. That this gate actually queues/resumes the patched sandbox migration from the direct repair success path is **NOT PROVEN**; see “Second-pass continuation trace.”
* End-to-end reviewed repair is **NOT PROVEN**.

## 1. Executive verdict

**Static-audit verdict (2026-07-09):** the reviewed-repair capability is substantially present, but it is not end-to-end complete or runtime-proven.

* **STATICALLY PRESENT:** deterministic failure evidence/context; proposer → primary validation → independent reviewer; raw Git-unified-diff artifacts; patch policy; sandbox-only apply; build-command reuse plus test-evidence parsing; proposal persistence; safe diff API/UI; attempt timeline; V2 SSE.
* **PROVEN defect:** all three FastAPI persisted-proposal projections omit `reviewer_decision` and `risk`. The projection defaults the former to `unknown`; the UI therefore renders `unknown` despite a stored reviewer decision.
* **Partial/incomplete:** direct (Option-A) proposals omit several durable lineage bindings, cannot support their visible revision action, have no working reject action, use a repair validation adapter with narrower semantics than the migration validation path, require but do not consume its direct-Apply idempotency key, and expose an endpoint which holds `BEGIN IMMEDIATE` across patching, Maven/tests, and sometimes a further model call.
* **Recommended architecture:** retain a hybrid boundary. The LangGraph migration graph remains responsible for migration phases; V2 repair services own proposal/review/governance/persistence; one shared, parameterized validation service invokes the existing build and test agents. Do not add a repair LangGraph node/subgraph or duplicate Maven/test code.

Maturity classification: **STATICALLY FIXED** only after contract tests prove the projection correction; all other implementation claims here are **STATICALLY PRESENT** or **NOT PROVEN** at runtime. No migration, database, model, or patch was executed for this audit.

## 2. Current architecture map

```text
Migration worker subprocess
  -> V2OrchestratorRunner._handle_exit()
  -> deterministic failure evidence + repair context files
  -> injected repair diagnosis callback
  -> V2RepairGateService.create_reviewed_repair_proposal_on_failure()
  -> produce_repair_review_chain()
       primary proposer -> semantic validation -> independent reviewer
  -> V2RepairProposalRecord / SQLite
  -> FastAPI reviewed-proposal projection
  -> MigrationCockpit / RepairProposalPanel
  -> human revision / approval action
  -> patch gate -> sandbox-only apply
  -> repair_loop.validation_runner: build agent executes validation; test agent parses generated reports
  -> persisted validation result / bounded next proposal or completion gate
```

The actual graph is adjacent to this path, not its host. `V2OrchestratorRunner` is the bridge from the worker result to the V2 repair callback; `migration_factory/orchestrator/graph.py` does not call the repair chain.

## 3. Current LangGraph graph

**PROVEN graph:** `START → analysis → planning → assessment → approval → approval_record → sandbox_transform → final_report → END` in `migration_factory/orchestrator/graph.py:33-129`.

`copilot_phase_assist` and `copilot_final_report` are registered but unreachable because `_should_route_to_copilot_assist()` returns `False` (`graph.py:229-231`). Conditional routes validate phase artifacts, route only a completed approval in `full_sandbox_migration` mode to the transform, and terminate otherwise.

| Node | Function / side effect | Inputs / outputs |
| --- | --- | --- |
| analysis, planning, assessment | `_phase_node` around `PhaseServices`; validates artifacts | phase/status, artifact refs, blockers/warnings |
| approval | `approval_node` | approval interrupt/decision state |
| approval_record | `record_approval_decision_phase` | persisted approval artifact |
| sandbox_transform | `run_sandbox_transform_phase` | sandbox, transform, build/test state/artifacts |
| final_report | `finalize_orchestration_state` | final report and status |

`MigrationState` is the `TypedDict` in `migration_factory/orchestrator/state.py:51-137`. Relevant existing keys are `sandbox_path`, `transform_status`, `build_status`, `test_status`, test evidence paths/totals, `approval_*`, `artifact_refs`, and legacy repair flags. It has no authoritative current repair evidence/context/diff/reviewer fields. LangGraph persistence is an approval/checkpoint mechanism (`orchestrator/checkpointing.py`, `resume.py`), not a repair-retry system.

## 4. Existing build/test execution inventory

| File / symbol | Responsibility and callers | Evidence / reuse verdict |
| --- | --- | --- |
| `agents/build_agent/agent.py:run_build_agent` | Canonical build executor. Detects Maven/Gradle, selects wrapper/system command, JDK gate, startup/plan/reactor modes; calls process runners. Used by transform and repair validation. | **Authoritative reusable primitive.** Emits build error contract and updates ledger. |
| `agents/build_agent/runner.py:run_until_exit`, `run_until_build_result` | Subprocess execution. | Reuse only through build agent. |
| `agents/build_agent/detection.py:full_validation_command` | Maven/Gradle full-validation command selection. | Reuse when parameterizing repair validation. |
| `agents/test_agent/agent.py:run_test_agent` | Parses existing Surefire XML, writes JSON/Markdown/log test evidence; does not execute a new test command. | **Authoritative test-evidence primitive.** |
| `transform_v1_after_approval.py:_run_transformer_with_build_validation` | Existing migration sandbox path: transforms units, invokes build agent per validation unit, then test agent at finalization. | Source of original command/profile semantics. |
| `repair_loop/validation_runner.py:run_validation_after_patch` | Repair adapter invokes the same build/test agents, optional H2. | Reuse adapter only after it receives the original stage validation profile/command. It currently hardcodes `['mvn','test']` and `require_test_reports=False`. |

Build and test are **not LangGraph nodes**. Re-entering the graph would not reuse a missing node; it would re-run an approval-oriented graph with unrelated checkpoints. The precise existing reuse boundary is `run_build_agent` + `run_test_agent`, reached through a single shared validation adapter which carries normal stage execution metadata.

## 5. Current reviewed-repair flow

1. `V2OrchestratorRunner._maybe_write_repair_failure_context` (`v2_orchestrator_runner.py:1219-1356`) derives sandbox/root, normalizes compiler evidence, builds `FailureEvidence` and `RepairContextPack`, writes JSON artifacts/checksums, and emits evidence/context events.
2. The injected callback from `create_repair_gate_diagnosis_callback` (`v2_repair_gate_service.py:1512-1603`) selects direct reviewed-proposal creation when refs are present.
3. `produce_repair_review_chain` (`orchestrator/repair_review_chain.py:553-843`) writes deterministic artifact; calls proposer; parses and validates required root cause, strategy, files, canonical diff, risk, confidence and rationale; only then calls reviewer; writes raw primary/reviewer/final artifacts and `.diff`.
4. `V2RepairGateService._create_reviewed_repair_proposal_from_refs` (`v2_repair_gate_service.py:471-729`) persists a direct record only on `reviewer_decision == 'accept'`; it emits `repair_proposal_ready` otherwise `reviewed_repair_unavailable`/`repair_completed`.
5. The V2 SQLite repository restores the record; the FastAPI proposal endpoints project a redacted, checksum-checked diff; the migration cockpit reads it and its safe diff separately.

Reviewer reachability after primary semantic validation is **PROVEN**. Non-accept output fails closed, but `revise` is normalized then treated as non-accept and is not persisted as a usable revision state—**partial** behavior.

## 6. Reviewer-decision lineage verdict

### PROVEN LOSS POINT

```text
reviewer_output['decision']
 -> review_chain['reviewer_decision']              repair_review_chain.py:799-826
 -> V2RepairProposalRecord.reviewer_decision       v2_repair_gate_service.py:686-714
 -> reviewer_decision SQLite column + row mapper   v2_repair_repository.py:76-140, 281-326
 -> omitted FastAPI builder argument                app.py:3609, 3662, 3932
 -> builder default 'unknown'                       v2_repair_projection.py:491-575
 -> ReviewerVerdictProjection/UI                    RepairProposalPanel.tsx:276-280
```

The same omission loses persisted `risk` at all three call sites:

* `GET /v1/v2/jobs/{job_id}/repair/proposals/current` — `app.py:3609-3629`.
* `GET /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}` — `app.py:3662-3682`.
* revision-response projection — `app.py:3932-3951`.

Pass `reviewer_decision=getattr(record, 'reviewer_decision', None)` and `risk=getattr(record, 'risk', None)` at each call. Add a record-to-endpoint-to-React regression test. The direct producer also stores no reviewer verdict ID/reasoning, so the displayed opinion is not yet complete even after decision projection is fixed.

## 7. Reuse inventory

| Capability | Existing file/symbol | Current usage | Reusable? | Change needed |
| --- | --- | --- | --- | --- |
| Failure evidence/compiler parsing | `v2_orchestrator_runner.py`, `repair_loop/failure_evidence.py` | failure callback | Yes | Preserve normalized/raw refs/checksums in record |
| Source context | `repair_loop/repair_context.py` | proposer context | Yes | Persist context checksum/binding |
| Proposer/reviewer/schema | `repair_review_chain.py`, `v2_assistant_model_client.py`, `v2_model_*` | direct chain | Yes | lifecycle events; preserve verdict/opinion refs |
| Diff validation/preview | `patch_gate.py`, `safe_diff_preview.py` | API/apply | Yes | retain raw vs public separation |
| Rule/risk policy | `rule_registry.py`, `patch_gate.py` | apply eligibility | Yes | remove LOW/default rule fallbacks; fail closed |
| Proposal/attempt persistence | `v2_repair_repository.py` | V2 records | Yes | fill full lineage and action fields |
| Sandbox apply/rollback | `patch_apply.py`, `v2_repair_flow.py` | two routes | Yes | one authoritative adapter/endpoint |
| Build/test | build/test agents, `validation_runner.py` | transform and repair | Yes | parameterize original validation profile, no duplicate command logic |
| Human gate | `V2GateActionService`, `V2PhaseGateService` | gate-backed flow | Partly | direct route needs supported revision/reject lifecycle, not a second approval system |
| Events/SSE | V2 event repo, Cockpit EventSource | V2 cockpit | Yes | complete event vocabulary/listeners |
| Repair UI | migration `RepairProposalPanel` | reviewed V2 proposal | Yes | render risk/opinion/status; working actions |

## 8. Duplication audit

| Overlap | Assessment | Decision |
| --- | --- | --- |
| Transform validation vs `validation_runner` | Both call build/test agents; repair wrapper changes command semantics. | Keep shared agents; extract/parameterize validation profile only. |
| `/gates/{gate}/approve-reviewed-repair` vs `/repair/proposals/{proposal}/approve` | Parallel gate-backed and direct apply flows. | Choose one authoritative V2 public path; make other internal/legacy-compatible, do not add third path. |
| `V2RepairFlowService.apply_patch` vs direct FastAPI apply orchestration | Same apply/gate/validation responsibility. | Consolidate behind an application service after behavior is contract-tested. |
| V1 `app/jobs/.../RepairPanel` and fake-repair APIs vs V2 reviewed panel/APIs | Intentional legacy diagnostic vs reviewed repair divergence. | Do not merge state/UI; label/deprecate only when safe. |
| raw canonical-JSON diff checksum vs raw-byte diff SHA-256 | Different binding domains, both legitimate. | Persist/name separately; never compare cross-domain. |

## 9. Architecture options compared

| Option | Assessment |
| --- | --- |
| 1. Minimal direct-service extension | Lowest change size; keeps current authoritative callback/UI route. Requires full binding record, actions, transaction split, validation-profile adapter. **Good.** |
| 2. Repair LangGraph subgraph | Poor reuse: graph has no build/test nodes and approval/checkpoints are migration-specific. Adds human-wait/checkpoint coupling. **Reject.** |
| 3. Hybrid: graph for migration; repair service for governance; shared validation primitive | Best safety/reuse boundary; supports durable repair attempts independent of graph resume. **Recommended.** |

Rank: Option 3 highest for safety, reuse, SQLite concurrency, migration compatibility and frontend simplicity; Option 1 is its incremental delivery plan; Option 2 has highest regression risk and duplicates state.

## 10. Recommended target architecture

```text
Migration graph / worker result
        ↓
existing failure evidence + context construction
        ↓
V2 reviewed-repair service (propose -> validate -> review -> persist)
        ↓
one persisted, checksum-bound proposal/attempt record
        ↓
human: reject | request revision | approve
        ↓
existing patch gate -> sandbox-only patch apply
        ↓
shared validation adapter -> build agent executes selected command -> test agent parses generated reports
        ↓
short persistence/event transaction
        ├─ pass: stage-completion gate; continuation bridge still required/proven separately
        └─ fail: new deterministic evidence/context + bounded next attempt
```

No new LangGraph node/subgraph is justified. Human waiting remains durable V2 record/gate state; LangGraph approval resume remains unchanged.

## 11. Backend implementation plan

### Phase 0 — projection correctness

* **Files/symbols:** `app.py` three `build_reviewed_diff_proposal_from_record` calls; projection/API tests.
* **Reuse/new:** reuse projection; pass two existing fields, no schema/migration.
* **Acceptance:** exact stored reviewer decision/risk reaches each endpoint and UI; unknown never occurs merely because an argument was omitted.

### Phase 1 — complete proposal lineage and lifecycle

* **Files:** `v2_repair_gate_service.py`, `v2_repair_repository.py`, SQLite migration, `v2_repair_projection.py`.
* **Objective:** persist immutable bindings for failure evidence, context, primary/reviewer/final artifact, reviewer output, policy validation, raw diff SHA-256, reviewer-bound diff checksum, base repo state, rule/risk, attempt/gate/action states.
* **New code:** one explicit lineage contract/manifest and required-field validation before `repair_proposal_ready`; not a second repair model/service.
* **Risks:** migration/backfill and existing direct records. Make nullable legacy-compatible then require fields for new records.

### Phase 2 — shared action mechanics after lifecycle decision

* **Files:** `v2_repair_flow.py`, `v2_repair_gate_service.py`, `app.py`.
* **Objective:** share only server-side reload, binding checks, policy, sandbox apply, validation invocation and event persistence; retain gate coupling, rollback, revision and continuation semantics until Phase 1 decides them.
* **Reuse:** `evaluate_patch_proposal`, `apply_patch_to_sandbox`, `rollback_patch`, existing V2 gate/revision records.
* **Acceptance:** client never supplies raw diff/path; rejected/superseded proposals cannot apply; direct revision no longer 409s because its required binding was never persisted.

### Phase 3 — validation reuse and bounded next attempt

* **Files:** `repair_loop/validation_runner.py`, transform validation metadata producer, V2 repair service.
* **Objective:** parameterize validation with original stage command/profile/JDK/reactor metadata and retain existing agents/evidence. On fail, create new evidence/context from actual rerun results and a bounded proposal; on pass hand off to the existing stage continuation/completion mechanism.
* **No new Maven/Gradle subprocess implementation.**

### Phase 4 — transaction-safe orchestration and events

* **Files:** `app.py`, callback/repair services, UoW-facing adapters.
* **Objective:** short read/claim transaction → external model/file/apply/build/test work without UoW → short compare-and-persist transaction.
* **New code:** idempotency/lease claim with state/version/checksum recheck. Do not hold writer while human waits.

## 12. LangGraph/orchestrator plan

Keep `graph.py`, its edges, and approval/checkpoint behavior unchanged. Reuse `V2OrchestratorRunner` failure evidence/context creation and diagnostic callback. Do not add nodes. Carry `ValidationExecutionContext` into the repair proposal/runtime context, then call the shared validation adapter after patch apply. Repair attempt limit remains V2 repair state (`DEFAULT_MAX_REPAIR_ATTEMPTS = 3`), not LangGraph retry. A successful rerun currently creates a stage-completion gate but does **not** yet have a fully traced direct path to queue/resume migration; Phase 5 must supply and prove that bridge. A failed rerun persists a next repair cycle or terminal exhausted state.

## 13. Frontend plan

Use `app/migrations/[jobId]/RepairProposalPanel.tsx`, `ReviewedDiffTabs.tsx`, `RepairActionsBar.tsx`, `RepairAttemptTimeline.tsx`, and existing `controlTowerApi.ts`/`contracts.ts`.

* Render risk, deterministic rule identifier (safe display value), reviewer decision and redacted reviewer opinion, source/redaction indicator, apply/rerun/final statuses.
* Preserve safe diff/files/attempt components; do not introduce a second repair client state model.
* Make revision visible only when endpoint/state supports it; currently direct `gate_id=None` / `reviewer_verdict_id=None` makes the visible action fail and the UI swallows the error.
* Wire reject to the authoritative V2 mutation and show safe mutation errors. It is currently permanently disabled.
* Drive refresh from existing event stream; include repair start/completion events in `AMF252_REPAIR_EVENTS`; keep post-action refetch.
* Do not extend legacy `app/jobs/[jobId]/RepairPanel.tsx`.

## 14. Data lineage and contract plan

| Field | Current fate | Required plan |
| --- | --- | --- |
| `reviewer_decision`, `risk` | born chain, persisted; lost only at three projections | pass through now; contract-test |
| `deterministic_rule_id` | persisted, policy uses it; not projected | include safe display projection if required |
| `diff_checksum` | raw-byte SHA-256 persisted/API | retain as apply checksum |
| reviewer-bound diff checksum | canonical JSON chain checksum | persist distinctly; bind reviewer verification |
| failure/context checksums | artifacts exist, direct record incomplete | persist immutable refs/checksums |
| primary/reviewer/policy checksums | partly artifacts/legacy gate refs; direct path incomplete | require lineage manifest/columns |
| attempt/proposal/gate IDs | persistence exists | single authoritative action state machine |
| apply/rerun statuses | stored and timeline-projected | render and event-update |

Raw authoritative diff/artifacts must remain server-side. Public projection remains safe preview/redacted summaries only.

## 15. Events/SSE/state plan

Existing V2 events and append-only sequence repository are reusable (`v2_event_repository.py:27-81`). Cockpit opens at `after=0`, dedupes by sequence, and refreshes its panel by a repair key. It has no repair polling loop.

Add only precise missing lifecycle events: `repair_evidence_ready`, proposer/reviewer started/completed/failed, `repair_revision_requested`, `repair_apply_started/completed/failed`, `repair_validation_started`, and one terminal `repair_attempt_*` event. Add listeners and the repair-refresh set for every emitted event; current listener lists miss `repair_revision_requested` and `repair_approve_apply_failed`. Do not emit a generic later `repair_completed` after a more precise unavailable/reviewer result, because the event reducer currently lets it mask the reason. Deduplicate producer emissions in the post-validation retry helper.

## 16. SQLite transaction-boundary review

**PROVEN:** write UoW begins `BEGIN IMMEDIATE` (`unit_of_work.py:162-174`). Current callback can hold it during proposer/reviewer; revision endpoint holds it during regeneration; direct approval endpoint (`app.py:4001+`) holds it over patch gate/apply, `run_validation_after_patch`, and possibly a next model chain. This violates the required short-transaction lifecycle and can recreate database locks.

Smallest correction: persist a pending/claimed action with idempotency token in a short transaction; close it; perform external work; reopen transaction, reload record, compare proposal/checksums/state, persist outcome/events; release/terminalize claim. Use read UoWs for all projection/SSE reads. Do not broadly refactor unrelated UoWs.

## 17. Exact file-change matrix

| File | Current responsibility | Change? | Why / type |
| --- | --- | ---: | --- |
| `control_tower/adapters/fastapi/app.py` | projections/actions/events | Yes | projection fields, short transactions, endpoint consolidation/events |
| `application/v2_repair_projection.py` | safe projection | Possibly | safe rule/status/lineage projection |
| `application/v2_repair_gate_service.py` | chain/gate lifecycle | Yes | full bindings, revision/reject, events |
| `application/v2_repair_flow.py` | apply lifecycle | Yes | become shared action service |
| `repair_loop/validation_runner.py` | repair validation adapter | Yes | accept original validation profile; keep agents |
| `infrastructure/sqlite/v2_repair_repository.py` + migration | repair persistence | Yes | complete lineage/action claim fields |
| `v2_orchestrator_runner.py` | failure evidence bridge | Possibly | carry validation metadata, lifecycle event payload |
| `web/.../RepairProposalPanel.tsx` | reviewed repair UI | Yes | risk/status/actions/error rendering |
| `web/.../MigrationCockpit.tsx` | V2 SSE/reducer | Yes | complete repair event subscriptions/refresh |
| `web/lib/contracts.ts`, `controlTowerApi.ts` | V2 contract/client | Yes | new safe fields/actions |
| focused Python/TS tests | proof | Yes | specified below |

## 18. Files that must not be changed for this feature

Do not alter `orchestrator/graph.py` graph topology, approval checkpoint/resume internals, raw diff redaction boundaries, `patch_gate.py` containment/allowlist behavior, `patch_apply.py` sandbox containment, build/test agent command/evidence implementations, or the V1 fake-repair API/UI merely to make V2 UI appear complete. Changes to these are justified only by independently proven defects.

## 19. Test strategy

| Level | Proof |
| --- | --- |
| Unit | primary invalid output never invokes reviewer; decision/risk/no-safe-rule/missing risk fail closed; checksum-domain rules |
| Repository | full lineage round-trips, action claim/state transitions, legacy null compatibility |
| API contract | all 3 projections return persisted decision/risk; unknown cannot enable apply; direct revise/reject/approve state matrix; raw values never accepted |
| Frontend | persisted `accept`/risk/opinion/status render; error appears; buttons match allowed actions; no Apply for unknown/unsafe |
| Orchestrator | failure callback carries evidence/context/original validation profile without invoking models in test |
| Integration | fake model outputs + temp sandbox use shared agents/mocked subprocess contracts; persist apply/rerun/next attempt |
| Controlled runtime/E2E | real failing sandbox → evidence → real reviewed diff → human action → existing build/test evidence → success or bounded terminal. No claim before this is runtime-proven. |

Extend `tests/control_tower/test_v2_repair_proposal_api.py`, `test_v2_repair_presentation_contract.py`, `test_v2_repair_review_chain_producer.py`, `test_v2_repair_gate_service.py`, `test_v2_repair_rerun.py`, `test_v2_cockpit_events.py`, `test_sqlite_uow_read_mode.py`; and frontend `reviewedDiffProposal.test.tsx`, `repairPanel.test.tsx`, `migrationCockpit.test.tsx`, `controlTowerApi.test.ts`. Run focused Windows commands from the repository test discipline guidance, then affected suites; report baseline separately if needed.

## 20. Original phased implementation sequence — superseded by second-pass dependency order

The table below is retained for audit history only. The authoritative ordering is “Corrected dependency-ordered implementation phases,” which moves transaction/idempotency safety before lifecycle/action expansion and separates continuation proof.

| Phase | GO / proof | NO-GO / rollback |
| --- | --- | --- |
| 0 Projection | 3 API tests + UI decision/risk test pass | revert only projection calls/tests |
| 1 Lineage/actions | new records validate full bindings; reject/revise work | retain legacy reads; do not make new contract mandatory for legacy records |
| 2 Shared validation boundary | same agent commands/evidence as original stage profile | no duplicate process runner; retain adapter fallback behind explicit compatibility flag |
| 3 Apply/rerun transaction split | concurrency/idempotency tests show no writer during external work | preserve existing endpoint response contract while internal service changes |
| 4 UI/events | mutation errors/action gating/event refresh tests pass | UI is read-only safe if action rollout is held |
| 5 bounded retry/runtime | controlled runtime succeeds or reaches explainable exhausted state | never auto-apply/auto-approve to force a demo |

## 21. Acceptance criteria

Feature completion requires a controlled end-to-end proof that: real build/test failure produces structured evidence/context; proposer returns a canonical raw Git diff; primary validation and reviewer execute in order; all reviewer/risk/checksum lineage is persisted and projected; UI shows failure/diff/opinion/risk/files/attempt state; unknown/unreviewed/unsafe proposals cannot apply; human can reject/revise/approve only when allowed; patch gate applies only inside sandbox; existing build and test agents run and persist evidence; pass reaches continuation/terminal success; failure creates at most the configured bounded next attempt or terminal blocked state; no reviewer bypass, fake evidence, duplicate executor, or writer lock across external model/build/test/human waits occurs; public data stays redacted while raw authoritative diff remains server-side.

## 22. Final recommended decision

**RECOMMENDED ARCHITECTURE:** hybrid V2 repair governance outside LangGraph, with a single shared validation adapter over existing build/test agents.

**WHY:** it matches the actual callback/persistence/UI architecture, avoids graph/checkpoint misuse, and requires the smallest justified changes.

**EXACT REUSE BOUNDARY:** `V2OrchestratorRunner` evidence/context creation; `produce_repair_review_chain`; V2 repository/event/SSE/UI; `evaluate_patch_proposal`/`apply_patch_to_sandbox`; `run_build_agent` and `run_test_agent` through a parameterized `run_validation_after_patch`.

**NEW CODE ACTUALLY REQUIRED:** projection arguments and tests; complete durable lineage contract; supported direct revision/rejection and unified action orchestration; validation-profile handoff; short transaction/claim protocol; minimal lifecycle events/UI rendering.

**CODE THAT MUST NOT BE DUPLICATED:** build/test subprocess execution, test parsing, patch policy/containment, sandbox patching, approval state, SSE infrastructure, or repair UI state.

**CURRENT FIRST FIX:** pass persisted `reviewer_decision` and `risk` into all three `build_reviewed_diff_proposal_from_record` calls and prove it through API/UI tests.

**BIGGEST RISKS:** SQLite writer lock held across external work; mixing raw-byte and reviewer-bound checksum domains; direct/gate-backed behavioral drift; falsely treating static presence as runtime proof.

**GO / NO-GO:** go after Phase 0 contract proof and a design decision for the one authoritative apply/revision route. No-go for runtime rollout until transaction boundaries, full lineage, action gating, shared validation semantics, and controlled end-to-end evidence are proven.

## Evidence notes and unresolved patch-quality question

Evidence classifications in this plan are **PROVEN** only where static source paths were traced. The current checkout contains no Java/Kotlin source files and no migration-run repair artifacts; the only `Sort` patch is a generic fixture/example in `repair_review_chain.py:147-156`. Therefore the reported broad `Object`/`instanceof List` repair and actual DTO getter contracts are **UNKNOWN** in this workspace. Before approving any such patch, obtain the originating sandbox/artifacts and prove the return type, compiler diagnostic, and smallest strongly typed fix.

## Second-pass validation execution contract

### Actual execution semantics — PROVEN

`run_build_agent()` is the executor. It detects project/build tool and invokes `run_until_exit()` or `run_until_build_result()` (`agents/build_agent/agent.py:48-255`). Its selected command can itself execute tests and generate reports:

| Selected mode | Current behavior |
| --- | --- |
| explicit `mvn test` / Gradle equivalent | build agent executes that exact normalized plan command when `PLAN_COMMAND` applies. |
| explicit Maven `clean test` | in a multi-module, source-changing unit the agent permits it; otherwise it can select the full validation command. |
| Maven multi-module source-changing validation | `REACTOR_TEST` selects `full_validation_command`, normally reactor `clean test`. |
| startup validation | build agent uses the startup runner and can stop after startup. |
| no explicit command | build agent derives startup/build command from the detected project. |

`run_test_agent()` **does not execute a test command**. It parses existing `target/surefire-reports/TEST-*.xml`, classifies results, and writes JSON/Markdown/log evidence (`agents/test_agent/agent.py:35-168`). Therefore tests are normally generated by the command which `run_build_agent()` executes, not by a separate test executor.

The repair adapter currently violates same-profile reuse: `run_validation_after_patch()` supplies `validation_unit_id='repair-attempt-{n}'`, `source_changing_unit=True`, and `validation_command=['mvn', 'test']` (`repair_loop/validation_runner.py:32-56`). It accepts `TEST_PASSED`, `PASS_WITH_WARNINGS`, and `TESTS_NOT_FOUND` (`:98-101`).

### Required `ValidationExecutionContext`

Implement one immutable, server-owned context captured at the **original failing build execution boundary** and referenced from the failure evidence/repair lineage manifest. It must contain only fields presently consumed by build/test execution or needed to identify the same execution:

| Field | Why it is required / current consumer |
| --- | --- |
| `job_id`, `command_id`, `stage_index`, `route_step_index` | identifies the failing stage/command and binds persistence/continuation. |
| `sandbox_path` / working directory identity | build agent’s `project_path`; must resolve to the patched sandbox. |
| `validation_command` | reaches `run_build_agent(validation_command=...)`; preserves Maven/Gradle/wrapper, module flags and explicit command. |
| `validation_unit_id`, `source_changing_unit` | selects `REACTOR_TEST` vs `PLAN_COMMAND` / startup behavior. |
| `module`, `main_class` | direct `run_build_agent` inputs when normal path supplies them. |
| `source_jdk_home_env`, `target_jdk_home_env` | existing build agent selects JAVA_HOME from these based on unit. |
| `build_timeout_seconds`, `stop_after_start` | current execution controls. |
| `require_test_reports` | controls how test parser treats missing Surefire evidence. |
| `h2_required`, `h2_enabled` | current repair validation inputs. |
| `source_profile`, `target_profile`, runtime/profile identifier | audit identity and deterministic route/JDK source; do not use as a substitute for command/JDK env fields. |

`build_tool`, wrapper/system choice, reactor scope, and original effective command are **derived evidence**, not separate authoritative inputs: the existing detector derives them from `project_path` and `validation_command`. Persist the original effective/resolved command and build-tool result in the immutable context/artifact for audit and stale-context checks, but do not create a second command selector.

**Invariant:** if migration failure occurred under validation execution profile X, repair validation must rerun the same relevant execution contract X unless a deterministic, documented policy selects a broader profile. Such a policy must be persisted with its reason and shown in validation evidence. The repair apply service reads the context from the lineage manifest, changes only the working sandbox to the patched sandbox, passes its supported values to `run_validation_after_patch()`, which passes them to `run_build_agent()`, then calls `run_test_agent()` only to parse resulting evidence.

## Second-pass continuation trace

### What current code proves

1. Direct proposal Apply calls `run_validation_after_patch()` (`app.py:4203-4211`).
2. On validation PASS it calls `V2RepairGateService.handle_repair_validation_result()` (`app.py:4221-4258`).
3. That method creates an open `stage_completion_review` gate with a validation/sandbox checksum binding and returns `stage_completion_gate_created` (`v2_repair_gate_service.py:1100-1169`). The direct endpoint persists `approved_applied` / `rerun_status='passed'` and emits `repair_validation_passed`.
4. Generic V2 gate API exposes gates and accepts `GateDecision.CONTINUE` at `POST /v1/v2/jobs/{job_id}/gates/{gate_id}/actions`, routed to `V2GateActionService.continue_from_gate()` (`app.py:1851-2015`). Gate decisions have a repository-backed idempotency mechanism.
5. `V2StageProgressionService.queue_next_stage()` can construct a next-stage command manifest from a supplied patched `sandbox_path`, preserve it as the next stage’s `--legacy` input, and select the next route profile/JDK (`v2_stage_progression.py:738-1030`). `V2OrchestratorRunner.start()` can run queued command manifests.

### Missing current bridge

`continue_from_gate()` records/resolves the gate but explicitly comments that `stage_completion_review + CONTINUE` progression is “handled by the caller” (`v2_gate_action_service.py:1851-1856`). The generic gate endpoint shown above does not call `queue_next_stage()` or runner launch after this action. The direct repair success endpoint returns `allowed_next_actions=('view_result', 'continue_migration')`, but the reviewed-repair frontend has no continuation handler and no matching repair continuation endpoint. Thus the following classifications are authoritative:

| Claim | Classification |
| --- | --- |
| Stage completion gate exists | **PROVEN** |
| Repair validation creates it | **PROVEN** |
| a generic `continue` gate action is exposed | **PROVEN** |
| direct repair’s `continue_migration` is exposed as an executable frontend action | **NOT PROVEN** |
| that action queues/resumes next migration execution | **NOT PROVEN** |
| `queue_next_stage()` can preserve patched sandbox when called correctly | **PROVEN in isolation** |
| direct repair-success → migration-continuation | **PARTIALLY PROVEN** |

Phase 5 must add or explicitly wire one backend-owned continuation bridge: after an accepted `stage_completion_review` continue decision, reload the repair result/validation context, call `queue_next_stage()` with the patched sandbox and successful stage result, persist the returned command ID in the gate decision/repair record, and launch it outside the committing UoW using the established runner launch pattern. It must not guess a route step or regenerate an unrelated sandbox. This is required before claiming repair success continues migration.

## Second-pass reviewer product semantics

Current direct behavior is **CONFIRMED**: `accept` is persisted as a proposal; `revise` and `reject` return unavailable after chain production because `_create_reviewed_repair_proposal_from_refs()` permits only `reviewer_decision == 'accept'` (`v2_repair_gate_service.py:579-626`). The decision/reasoning is therefore not a durable reviewed outcome.

Recommended minimal product contract:

| Reviewer decision | Persisted target state | Allowed human actions | Rationale |
| --- | --- | --- | --- |
| `accept` | `user_review_required` / actionable only after rule, LOW-risk and diff checks | inspect, reject, request revision, approve when `allowed_actions` says so | retains human authority. |
| `revise` | first-class non-actionable `reviewer_revision_required` (exact enum/name chosen to fit schema) | inspect reviewer opinion; explicit human `request_revision` | no unobserved/model-costly automatic loop; bounded human-governed regeneration. |
| `reject` | first-class non-actionable `reviewer_rejected` | inspect; optionally terminal human acknowledgement, never Apply | preserves truth and prevents actionability. |

Persist a safe reviewer opinion/refs and decision for all three outcomes. Do not create an automatic proposer-reviewer loop in this MVP. A human-requested regeneration consumes the existing bounded attempt policy and must create a new immutable lineage manifest.

## Second-pass direct versus gate-backed matrix

| Behavior | Direct Option A | Gate-backed path | Recommended target decision / classification |
| --- | --- | --- | --- |
| Proposal trigger | failure callback with evidence/context refs | failure opens `repair_review` gate; reviewed chain may create gate | Keep trigger distinction until lifecycle decision; **intentional/legacy difference**. |
| Reviewer binding/decision | chain checks reviewer; only accept record persisted | gate path binds review checksums and accepts review gate | Shared reviewer-binding verifier; direct non-accept persistence required. |
| Gate/human approval | `gate_id=None`; direct `/approve` checks record | repair gate actions use V2 gate decision | Do not force a new second gate; choose one human-action contract after design gate. |
| Revision/rejection | UI revision currently cannot meet required gate/verdict IDs; reject disabled | `V2GateActionService` supports gate revise/reject | Direct behavior **unsafe divergence**; implement explicit supported direct semantics or route direct outcomes through existing gate contract. |
| Eligibility/rule/risk | record accept + LOW + allowlist + safe diff; resolver has invalid rule fallback | policy validation/checksum gate bindings; risk fallback may default LOW in legacy resolver | Share fail-closed rule/risk policy; remove fallbacks. |
| Diff/base-state binding | raw-byte diff hash checked; incomplete direct durable bindings | gate refs include broader chain/base/policy checksums | Hybrid lineage manifest for direct; **unsafe divergence** until fixed. |
| Idempotency/concurrency | request key is required but unused; large transaction serializes incidentally | gate decisions persist/request-check idempotency | Shared Apply claim is required; **unsafe divergence**. |
| Apply/rollback primitive | direct `apply_patch_to_sandbox`; no rollback on validation failure | `V2RepairFlowService` applies and includes rollback behavior | Share patch mechanics; leave rollback-on-validation policy explicit until product decision. |
| Validation | same `run_validation_after_patch`, currently hardcoded Maven test | same wrapper | shared mechanics; both need `ValidationExecutionContext`. |
| Build/test evidence | build agent executes; test agent parses | same | shared mechanics. |
| Next attempt/exhaustion | direct helper regenerates proposal / emits events | gate service creates repair gate / tracks attempts | keep policy distinction until chosen; normalize outcome contract later. |
| Success completion | direct creates completion gate and returns string action | gate model has completion gate capability | continuation bridge missing in direct path. |
| Events/API/frontend | V2 repair proposal panel/endpoints | V2 gates/endpoints and legacy reviewed-gate endpoint | reuse event/repository helpers; do not merge UI state prematurely. |

Consolidate **only shared mechanics**: server-side reload, checksum recomputation, reviewer binding verification, rule/risk validation, patch gate/containment/application, validation invocation, event append helper, and new Apply claim. Keep gate coupling, rollback-after-validation, revision policy, next-attempt policy, and continuation behavior distinct until Phase 1 selects a lifecycle contract.

## Second-pass safety and proof corrections

### Deterministic rule ID — P1, CONFIRMED

`_resolve_repair_proposal_runtime_context()` in `app.py:12555-12568` falls back from stored/context rule ID to `base_repo_state_checksum`, then `diff_checksum`, then `repair_apply`. Those values are not rule IDs. Although `evaluate_patch_proposal()` subsequently allowlists rule IDs, the resolver must not manufacture safety metadata. Required change: accept only persisted/context rule IDs; return structured `DETERMINISTIC_RULE_ID_MISSING` or `DETERMINISTIC_RULE_ID_INVALID`; preserve `no_safe_rule` as non-actionable. This is required before direct Apply rollout.

### Test-proof semantics — P1, PARTIALLY CONFIRMED

`run_test_agent()` originates `TESTS_NOT_FOUND` when no Surefire reports exist. Repair validation treats it as pass; `V2OrchestratorRunner` also includes it among accepted success statuses (`v2_orchestrator_runner.py:98-101`). In contrast, `orchestrator/summary.py:224-245` grants its strongest full-sandbox/test-executed claim only for `TEST_PASSED`. The target contract must expose one of these qualified proof states (exact names schema-compatible): `BUILD_VERIFIED`, `BUILD_AND_TEST_VERIFIED`, `BUILD_VERIFIED_TEST_EVIDENCE_NOT_FOUND`, and `BUILD_AND_TEST_VERIFIED_WITH_WARNINGS`. Migration may progress under a documented policy, but UI/API/final proof must never describe missing evidence as “tests passed.”

### Lineage storage — hybrid, not column proliferation

Use an immutable lineage-manifest artifact as the canonical bundle of failure/context/primary/reviewer/final refs and checksums, reviewer-bound diff checksum, raw apply diff hash, base state, rule/risk, and validation-context checksum. Persist only minimal query/concurrency columns: proposal/attempt identity, status, reviewer decision, raw apply diff checksum, manifest ref/checksum, rule/risk, apply claim/idempotency/version, and terminal apply/rerun fields. This protects binding/auditability without duplicating reconstructable artifact data into many columns. UI consumes only safe projected fields; Apply reloads and verifies manifest plus record.

### Events — minimum necessary set

Retain existing evidence/context, proposal-ready/unavailable, validation pass/fail and attempt-exhausted events. Add only (a) `repair_outcome_persisted` with exact reviewer decision/status when needed to refresh truthful non-accept UI, (b) `repair_apply_claimed`/terminal apply outcome if UI needs progress, and (c) continuation queued/started once Phase 5 exists. Do not add separate proposer/reviewer start/completion events unless an actual consumer/audit requirement is established. Never append generic `repair_completed` after a precise unavailable cause; reducer should prefer the latest state-bearing outcome rather than a generic terminal marker.

## Corrected target architecture

```text
MIGRATION LANGGRAPH (migration-specific phases, approval/checkpoints)
   -> existing transform validation: run_build_agent executes selected command
   -> failure evidence + ValidationExecutionContext + repair context
   -> V2 reviewed-repair service: proposer -> primary validation -> reviewer
   -> durable reviewed outcome (accept / revise / reject)
        accept -> human review -> short Apply claim transaction
                -> patch gate -> sandbox-only apply (no writer held)
                -> shared validation service
                     -> run_build_agent executes original relevant contract
                     -> run_test_agent parses generated report evidence
                -> PASS: completion gate -> explicit continuation bridge -> queued next stage
                -> FAIL: bounded next outcome or exhausted terminal state
        revise/reject -> truthful non-actionable persisted outcome; no Apply
```

## Corrected dependency-ordered implementation phases

| Phase | Scope and proof | GO / NO-GO |
| --- | --- | --- |
| 0 — Projection truth | Pass persisted `reviewer_decision` and `risk` at current/by-ID/revision projections; API + UI accept/LOW and true-null tests. | **GO now.** Isolated, no schema/lifecycle change. |
| 1 — Lifecycle design gate | Decide direct/gate action semantics, reviewer outcome states, rollback/attempt/continuation contract using the matrix above. | **GO for design only.** No Apply expansion until approved. |
| 2 — Transaction/idempotency safety | Short claim → external work → compare/persist protocol; direct Apply key is persisted/unique/replayed; concurrency tests. | **Required before** new Apply/action behavior. |
| 3 — Validation context reuse | Capture/persist/reference `ValidationExecutionContext`; parameterize existing repair wrapper; qualified proof state. | No new executor. |
| 4 — Complete lifecycle | Persist all reviewer outcomes, minimal lineage manifest, direct actions aligned to selected contract, bounded attempts. | No automatic reviewer loop. |
| 5 — Continuation | Wire completion-gate CONTINUE to `queue_next_stage` and runner launch outside UoW; preserve patched sandbox. | No success-continuation claim before tests prove it. |
| 6 — Frontend/events | Show only supported state/actions; errors visible; limited state-bearing events. | Backend `allowed_actions` remains authoritative. |
| 7 — Controlled runtime | Real failure → reviewed outcome → human action → reused validation → continuation or bounded terminal. | Only point for end-to-end claim. |

## Second-pass proof matrix

| Capability | Status / maturity | Evidence |
| --- | --- | --- |
| Reviewer decision born and persisted | **PROVEN / STATICALLY PRESENT** | review chain, gate service, SQLite mapper |
| Reviewer decision and risk correctly projected | **DISPROVEN / NOT PROVEN** | three FastAPI calls omit both fields |
| Non-accept reviewed outcomes preserved | **DISPROVEN / NOT PROVEN** | direct chain returns unavailable rather than record |
| Human direct revision/rejection works | **DISPROVEN / NOT PROVEN** | missing direct bindings; reject disabled |
| Gate action idempotency | **PROVEN / STATICALLY PRESENT** | V2 gate decision repository/service |
| Direct Apply idempotency/concurrent-apply protection | **DISPROVEN / NOT PROVEN** | key required but unused; no claim/version/CAS |
| No writer during model/Maven/tests | **DISPROVEN / NOT PROVEN** | write UoW spans external work |
| Original validation semantics preserved | **DISPROVEN / NOT PROVEN** | hardcoded `['mvn','test']` repair context |
| Build command reuse | **PROVEN / STATICALLY PRESENT** | repair wrapper calls build agent |
| Test-agent role accurately represented | **PROVEN** | parser only; build command produces reports |
| `TESTS_NOT_FOUND` truthfully qualified | **PARTIALLY PROVEN** | accepted in repair/V2, strongest summary claim excludes it |
| Missing deterministic rule fails closed | **DISPROVEN / NOT PROVEN** | invalid fallback chain exists |
| Stage completion gate after validation pass | **PROVEN / STATICALLY PRESENT** | repair gate service |
| Actual migration continuation after repair success | **PARTIALLY PROVEN** | pieces exist; direct bridge/UI handler not traced |
| Failed validation bounded outcome | **PARTIALLY PROVEN** | helpers/limits exist; direct/gate semantics diverge |
| Raw authoritative diff separated from UI preview | **PROVEN / STATICALLY PRESENT** | chain artifacts and safe diff projection |
| Full reviewed repair end-to-end | **NOT PROVEN** | no controlled runtime proof |

## Final second-pass GO / NO-GO

**GO NOW:** Phase 0 projection truth.

**GO FOR DESIGN/PREPARATION:** lifecycle decision gate, direct-vs-gate matrix, validation execution contract, completion continuation bridge design, and Apply claim/idempotency protocol.

**NO-GO UNTIL PROVEN:** direct Apply expansion, large action-service consolidation, live Apply runtime, automatic reviewer revision loop, a broad database migration, a repair LangGraph subgraph, and any claim of end-to-end repair success.
