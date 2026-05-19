# Milestone 3 Orchestrator Design

Milestone 3 scope is:

1. Analysis
2. Planning
3. Assessment
4. Human approval interrupt
5. Stop

The graph must not execute Transformation, OpenRewrite apply, source writes, migrated builds, migrated tests, or final migration.

## Recommended Architecture

Use a simple `StateGraph` with explicit phase nodes and a thin orchestrator service layer around the existing runners:

`START -> analysis -> analysis_gate -> planning -> planning_gate -> assessment -> assessment_gate -> approval -> END`

The phase nodes should call small wrapper functions owned by `migration_factory/orchestrator`, not embed runner details directly in `graph.py`. Each wrapper should:

- invoke the existing phase implementation or a test double,
- normalize the result into `MigrationState`,
- validate required artifacts before returning `PASS`,
- return `FAIL` with concrete blockers when artifacts are missing or invalid,
- avoid claiming success from runner status alone.

This keeps LangGraph routing small and testable while isolating runner import, subprocess, and artifact validation details. It also handles environments where the real legacy app is absent: tests and VM demos can seed Analysis artifacts and use wrappers/test doubles without weakening the production artifact gates.

## Rejected Options

### Direct graph nodes wrapping real runners

This is the smallest code change: replace the stub `analysis_node`, add an `assessment_node`, and wire conditional edges. It is viable for a prototype, but it couples LangGraph nodes to runner import quirks and filesystem behavior. The Analysis runner currently lives under a nested directory and uses local imports, so direct import from the orchestrator is fragile unless that package shape is cleaned up first.

Safety is acceptable only if every node also validates artifacts. Without the wrapper boundary, tests will need to monkeypatch runner internals or real files more often.

### Service/wrapper layer around runners

This is the recommended option. The graph remains simple, while wrapper functions such as `run_analysis_phase`, `run_planning_phase`, and `run_assessment_phase` own runner calls and artifact validation. Production can use real runners, while tests can inject deterministic wrapper functions into `build_graph(...)`.

This option best balances safety, testability, and future Transformer compatibility. The future Transformer can become another phase wrapper with the same gate pattern, but it is intentionally absent from the Milestone 3 graph.

### Subgraph per phase

Subgraphs are viable once phases contain multiple internal steps or retries. They are not needed for Milestone 3 because the required routing is linear with hard stops. Introducing subgraphs now would increase LangGraph surface area without improving safety.

## State Model

Recommended state fields:

- `run_id: str`
- `legacy_app_path: str`
- `modernized_app_path: str`
- `ai_hub_path: str`
- `profile: str`
- `current_phase: Literal["init", "analysis", "planning", "assessment", "approval", "stopped"]`
- `analysis_status: Literal["PENDING", "PASS", "FAIL", "WARNING", "SKIPPED"]`
- `planning_status: Literal["PENDING", "PASS", "FAIL", "WARNING", "SKIPPED"]`
- `assessment_status: Literal["PENDING", "PASS", "FAIL", "WARNING", "SKIPPED"]`
- `approval_status: Literal["PENDING", "INTERRUPTED", "APPROVED", "REJECTED", "REPLAN_REQUIRED"]`
- `stop_reason: str`
- `errors: list[str]`
- `blockers: list[str]`
- `warnings: list[str]`
- `artifact_refs: dict[str, str]`
- `analysis_artifacts_valid: bool`
- `planning_artifacts_valid: bool`
- `assessment_artifacts_valid: bool`
- `approval_payload: dict`

Keep contract decision values aligned with `APPROVAL_DECISION_VALUES`: `approved`, `rejected`, `replan_required`. Avoid the current mixed values `approve`, `reject`, and `replan` inside persisted state.

## Graph Routing

Routing should be based on normalized state, not phase assumptions:

- After Analysis: continue only when `analysis_status == "PASS"` and `analysis_artifacts_valid is True`; otherwise `END`.
- After Planning: continue only when `planning_status == "PASS"` and `planning_artifacts_valid is True`; otherwise `END`.
- After Assessment: continue only when `assessment_status == "PASS"`, `assessment_artifacts_valid is True`, and `approval_readiness.status == "READY_FOR_REVIEW"`; otherwise `END`.
- After Approval: always `END` for Milestone 3.

Current unsafe behavior to remove:

- `analysis_node` returns `PASS` without running Analysis or validating artifacts.
- `graph.py` routes Planning to Approval unconditionally.
- `graph.py` routes Approval to Transformation.
- `transformation_node` can return `PASS` after approval even if Planning failed.

Milestone 3 should not include a Transformation node in the compiled graph.

## Human Approval Flow

Use `interrupt()` only in the approval node. The approval node must perform no file writes and no external side effects before the interrupt because LangGraph may re-run code before `interrupt()` on resume.

The interrupt payload must be JSON-serializable. Recommended shape:

```json
{
  "type": "human_approval_required",
  "run_id": "run-123",
  "phase": "approval",
  "message": "Review assessment and choose a decision.",
  "decision_options": ["approved", "rejected", "replan_required"],
  "approval_request_ref": ".migration/runs/run-123/planning/approval_request.json",
  "assessment_report_ref": ".migration/runs/run-123/assessment/assessment_report.json",
  "assessment_summary_ref": ".migration/runs/run-123/assessment/assessment_summary.md",
  "blockers": [],
  "warnings": [],
  "units_to_execute": ["baseline", "java-17"]
}
```

Resume with `Command(resume={"decision": "approved"})`, `Command(resume={"decision": "rejected"})`, or `Command(resume={"decision": "replan_required"})`. Invalid values should normalize to `REJECTED` or `FAIL` with an error, and stop.

For Milestone 3:

- `approved` records `approval_status = "APPROVED"` and stops safely.
- `rejected` records `approval_status = "REJECTED"` and stops.
- `replan_required` records `approval_status = "REPLAN_REQUIRED"` and stops.

No approval outcome routes to Transformation in this milestone.

## Checkpointing Choice

Compile the graph with a checkpointer.

Local development and unit tests should use `InMemorySaver` or `MemorySaver`, depending on the installed LangGraph version. This is enough to test interrupts and `Command(resume=...)`.

Production should use a durable checkpointer, preferably SQLite for single-VM/local deployments or Postgres for shared/server deployments. Human approval requires `config.configurable.thread_id`; invocations without a thread id should fail fast before graph execution.

Recommended public API:

- `build_graph(checkpointer: BaseCheckpointSaver | None = None, phase_services: PhaseServices | None = None)`
- default local checkpointer when none is supplied,
- CLI always passes `{"configurable": {"thread_id": run_id}}`,
- resume path uses the same thread id and `Command(resume=...)`, not manual mutation of persisted state.

## Test Plan

Add orchestrator tests with fake phase services and temporary artifact directories:

- `analysis failure stops`: fake Analysis returns `FAIL`; Planning, Assessment, and Approval are not called.
- `missing artifacts stops`: fake Analysis returns success but required Analysis artifacts are absent; graph stops before Planning.
- `planning failure stops`: Analysis passes and Planning returns `FAIL`; Assessment and Approval are not called.
- `assessment failure stops`: Analysis and Planning pass, Assessment returns `FAIL` or `approval_readiness.status == "BLOCKED"`; Approval is not called.
- `approval interrupt emitted`: successful Analysis, Planning, and Assessment emits an interrupt with JSON-serializable payload and expected artifact refs.
- `rejected stops`: resume with `{"decision": "rejected"}` sets `approval_status = "REJECTED"` and ends.
- `replan_required stops`: resume with `{"decision": "replan_required"}` sets `approval_status = "REPLAN_REQUIRED"` and ends. Do not route back to Planning until a later milestone explicitly implements replan.
- `approved stops safely without Transformation`: resume with `{"decision": "approved"}` sets `approval_status = "APPROVED"`, `current_phase = "approval"`, and no transformation state or source changes exist.

Also keep focused contract tests for:

- approval decision enum matches `["approved", "rejected", "replan_required"]`,
- assessment report `execution_claims` remains all false,
- approval interrupt payload contains only JSON-safe primitives, lists, and dicts.

## Implementation Steps

1. Add `assessment_status` and normalized approval values to `MigrationState`.
2. Add artifact validation helpers or wrapper return types under `migration_factory/orchestrator`.
3. Replace the Analysis stub with a wrapper that runs real Analysis only when requested and validates required Analysis artifacts.
4. Add an Assessment wrapper around `write_assessment_artifacts`.
5. Change `build_graph` to accept checkpointer and phase service injection.
6. Add conditional edges after Analysis, Planning, and Assessment.
7. Replace the approval node payload and decision handling with contract enum values.
8. Remove Transformation from the Milestone 3 graph.
9. Update CLI run/resume to use `Command(resume=...)` and require `thread_id`.
10. Add the orchestrator tests listed above before broad integration tests.

## Blockers, Warnings, And Safest Sequence

Blockers:

- The current Analysis orchestrator node is a stub and must not be used for Milestone 3 acceptance.
- The current graph includes Transformation and unconditional routing.
- The current CLI resumes by mutating persisted state instead of using `Command(resume=...)`.

Warnings:

- The Analysis runner package shape may need cleanup or a subprocess wrapper because `main.py` uses local imports from its nested directory.
- VM environments without a real legacy app need seeded artifacts or fake phase services; do not weaken artifact validation to accommodate that.
- Approval code before `interrupt()` must remain side-effect free.

Safest implementation sequence:

1. Write failing orchestrator routing and interrupt tests with injected fake services.
2. Add state fields and wrapper interfaces.
3. Wire the simple graph with conditional stops and no Transformation node.
4. Add real runner wrappers and artifact validators.
5. Update CLI resume semantics.
6. Run narrow orchestrator tests, then existing planning and assessment contract tests.
