# Operator Pipeline

This document describes the current AI Migration Factory operator flow from launch through final reporting. The orchestrator and run artifacts are the source of truth. The TUI is an operator console around the same backend commands and run directory artifacts.

## Source Of Truth

- Backend entrypoint: `python -m migration_factory.orchestrator.runner`
- Resume entrypoint: `python -m migration_factory.orchestrator.resume`
- Run root: `<modernized_app>/.migration/runs/<run_id>/`
- Authoritative status: `orchestration/orchestration_summary.json` plus phase artifacts under the same run root
- TUI role: collects config, validates paths, launches/resumes the backend, polls run artifacts, and renders status/history. It does not define pipeline gates or mutate source-of-truth rules.

## Pipeline Steps

### 1. Operator Setup And Launch

- Purpose: choose the legacy app, modernized output root, AI Hub path, migration profile, run ID, and mode.
- Input artifacts: operator config or CLI arguments; profile file at `modernizer-solution-ai-hub/profiles/<profile_id>.yaml`.
- System action: builds initial state with run directories under `<modernized_app>/.migration/runs/<run_id>/`.
- Output artifacts: run directory path in state; no phase artifacts yet.
- Stop/fail condition: missing CLI/config values, unsupported mode, missing legacy path, uncreatable modernized path, missing AI Hub, missing profile, or LangGraph thread ID mismatch.
- Human role: operator supplies config and starts the run.

### 2. Preflight

- Purpose: fail fast before graph execution if required paths, profile, mode, or checkpoint identity are invalid.
- Input artifacts: initial state and AI Hub profile.
- System action: validates `run_id`, mode, legacy path, modernized path, AI Hub path, profile file, and `thread_id == run_id`.
- Output artifacts: none; this is a gate before phase execution.
- Stop/fail condition: `PreflightError`; runner exits before analysis.
- Human role: fix config/path/profile and relaunch.

### 3. Analysis

- Purpose: inspect the legacy app and prove the source was not modified.
- Input artifacts: legacy app, modernized run root, AI Hub profile.
- System action: runs the analysis agent, then validates required analysis artifacts and schemas.
- Output artifacts: `analysis/analysis_report.json`, `analysis/dependency_graph.json`, `analysis/test_inventory.json`, `analysis/analysis_summary.md`, `analysis/read_only_verification.json`, plus optional analysis artifacts.
- Stop/fail condition: analysis status is not `PASS`, required artifacts are missing/invalid, or `read_only_verification.json` does not report `source_modified: false`.
- Human role: review failures or warnings if analysis cannot pass.

### 4. Planning

- Purpose: produce a deterministic migration plan, migration units, and approval package.
- Input artifacts: validated analysis artifacts and selected AI Hub profile.
- System action: runs the planning node, then validates required planning artifacts and schemas.
- Output artifacts: `planning/migration_plan.yaml`, `planning/migration_units.yaml`, `planning/plan_summary.md`, `planning/approval_request.json`, `planning/plan_validation_report.json`.
- Stop/fail condition: planning status is not `PASS`, required artifacts are missing/invalid, or plan validation produces blockers.
- Human role: review planning blockers or update inputs/profile if needed.

### 5. Assessment

- Purpose: check approval readiness while preserving read-only behavior before any transform/build/test execution.
- Input artifacts: analysis and planning outputs.
- System action: writes assessment artifacts and validates readiness and execution claims.
- Output artifacts: `assessment/assessment_report.json`, `assessment/assessment_summary.md`.
- Stop/fail condition: assessment status is not `PASS`, required assessment artifacts are missing/invalid, `approval_readiness` is not `READY_FOR_REVIEW`, or assessment claims any transform/build/test/final migration execution.
- Human role: review assessment summary and blockers before approval.

### 6. Human Approval Interrupt

- Purpose: stop before source-changing sandbox work and require an explicit human decision.
- Input artifacts: validated analysis, planning, and assessment artifacts; approval request.
- System action: writes `orchestration/approval_interrupt_state.json`, emits an interrupt payload with artifact refs, blockers, warnings, and decision options.
- Output artifacts: approval interrupt checkpoint; runner console JSON with `status: human_approval_required` and `approval_status: INTERRUPTED`.
- Stop/fail condition: run pauses for a decision. Invalid resume decision sets approval failure.
- Human role: choose `approved`, `rejected`, or `replan_required`. The TUI can submit this, or the operator can use the resume command.

## Mode Branches

### read_only_assessment

- Purpose: analysis, planning, assessment, and approval readiness only.
- Input artifacts: phase artifacts through assessment and approval interrupt state.
- System action: stops at approval interrupt. If later resumed, approval may complete, but the graph does not route to approval recording or sandbox transform in this mode.
- Output artifacts: `orchestration/orchestration_summary.json`, timing artifacts under `performance/`, and the read-only phase artifacts listed above.
- Stop/fail condition: any earlier gate failure, approval interrupt, invalid approval decision, or human decision that ends the run.
- Human role: review readiness artifacts. Do not expect transform/build/test/final migration report artifacts from this mode.

### full_sandbox_migration

- Purpose: after successful read-only gates and human approval, create a sandbox candidate and validate it.
- Input artifacts: all read-only phase artifacts plus approval decision data from resume.
- System action: if decision is `approved`, records approval and locks the plan; if decision is `rejected` or `replan_required`, records the decision and stops.
- Output artifacts for approval: `approval/approval_decision.json`; for approved runs, `approval/approved_plan_lock.json`.
- Stop/fail condition: cannot record approval, decision is not `approved`, errors/blockers exist, or orchestration status is `FAIL`.
- Human role: provide `approved_by` and optional comments; approval is the only path to sandbox transform.

### 7. Sandbox Transform, Build, And Test

- Purpose: apply approved migration units only inside a sandbox and validate the migrated candidate.
- Input artifacts: `approval/approval_decision.json`, `approval/approved_plan_lock.json`, planning artifacts, legacy app, AI Hub profile.
- System action: creates/uses sandbox workspace, applies approved transform, records ledger, runs build validation, parses post-transform test results.
- Output artifacts: `transformation/transformation_execution_plan.yaml`, `transformation/openrewrite-plugin.xml` when produced, `workspaces/sandbox/.migration/ledger.json`, `logs/phase2_transform.log`, `test/post_transform/test_report.json`, `test/post_transform/test_summary.md`, `test/post_transform/test_agent.log`, sandbox path in state.
- Stop/fail condition: transform exit code is non-zero, transform status is not `TRANSFORM_APPLIED_IN_SANDBOX`, sandbox path is missing, build does not pass, tests do not pass, or any phase exception occurs.
- Human role: review logs and sandbox output; original legacy app root is not the mutation target.

### 8. Orchestration Summary And Timing

- Purpose: persist the run-level status and artifact references.
- Input artifacts: current orchestrator state and phase outputs.
- System action: writes timing reports and `orchestration/orchestration_summary.json`.
- Output artifacts: `orchestration/orchestration_summary.json`, `performance/timing_report.json`, `performance/timing_summary.md`.
- Stop/fail condition: non-successful full sandbox runs stop here without deterministic final migration report generation.
- Human role: use summary and timing artifacts as the primary operational status.

### 9. Deterministic Final Migration Report

- Purpose: produce authoritative final report artifacts for a successful sandbox migration.
- Input artifacts: approval decision, approved plan lock, transformation execution plan, migration ledger, orchestration summary, post-transform test report, assessment report, and migration plan.
- System action: writes deterministic final JSON and Markdown report from run facts.
- Output artifacts: `final/migration_report.json`, `final/migration_summary.md`.
- Stop/fail condition: generated only when mode is `full_sandbox_migration` and approval, transform, build, tests, and final status all match the successful sandbox values. Missing required report inputs blocks final report and flips orchestration failure.
- Human role: review final report before any manual promotion or PR work outside this factory run.

### 10. Optional Copilot Sidecars

- Purpose: produce advisory human-readable material from deterministic artifacts.
- Input artifacts: deterministic final report, orchestration summary, approval artifacts, post-transform test report, timing/ledger/transform artifacts where available.
- System action: if enabled, writes Copilot final report request/response/report artifacts; after final report generation, also attempts Copilot documentation package generation.
- Output artifacts: optional `final/copilot_report_request.json`, `final/copilot_report_response.json`, `final/copilot_migration_report.md`, and optional files under `final/copilot_docs/`.
- Stop/fail condition: Copilot unavailable, disabled, skipped, or failed is recorded as a warning/sidecar result and does not change deterministic approval, transform, build, test, or orchestration status.
- Human role: read as advisory only. Copilot cannot approve, transform, change gates, mutate source, create PRs, deploy, merge, or override deterministic statuses.

## Operator End States

- Read-only assessment complete: the run reaches approval readiness/interrupt with analysis, planning, assessment, summary, and timing artifacts only.
- Full sandbox rejected or replan required: approval decision is recorded and the run stops before sandbox transform.
- Full sandbox success: approval is recorded, plan is locked, sandbox transform/build/test pass, final deterministic report is generated, optional Copilot sidecars may be present.
- Failure: the run stops at the first failed phase gate or validation blocker, with blockers/errors recorded in orchestration summary when finalization occurs.

## Files Inspected

- `migration_factory/orchestrator/runner.py`
- `migration_factory/orchestrator/resume.py`
- `migration_factory/orchestrator/graph.py`
- `migration_factory/orchestrator/state.py`
- `migration_factory/orchestrator/preflight.py`
- `migration_factory/orchestrator/phase_services.py`
- `migration_factory/orchestrator/approval.py`
- `migration_factory/orchestrator/artifact_validation.py`
- `migration_factory/orchestrator/summary.py`
- `migration_factory/final_report/writer.py`
- `migration_factory/final_report/copilot.py`
- `migration_factory/tui/app.py`
- `migration_factory/tui/runner_adapter.py`
- `migration_factory/tui/config.py`
- `migration_factory/tui/parser.py`
- `migration_factory/tui/validation.py`
- `migration_factory/tui/history.py`
- `modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml`
- `modernizer-solution-ai-hub/profiles/springboot-2-java8-to-boot4-java21.yaml`
- `modernizer-solution-ai-hub/templates/reports/copilot_final_migration_report_v1.yaml`
- `modernizer-solution-ai-hub/templates/reports/copilot_final_migration_report_v1.md`
- `README.md`
- `docs/copilot-documentation-agent.md`
- `docs/milestone-3-orchestrator-design.md`

## Unclear Or Missing Parts

- The exact internal behavior of the analysis agent, planning node, assessment writer, approval writer, and sandbox transform implementation is intentionally summarized from orchestrator-facing contracts only.
- Profile-level `openrewrite.apply_allowed: false` coexists with full sandbox transform behavior; this doc treats the orchestrator and transform service as authoritative for when sandbox work is allowed.
- Replan is a terminal recorded decision in the inspected orchestrator flow; no automatic route back to planning is implemented here.

## Risks And Assumptions

- Assumption: operators should treat `orchestration_summary.json` and deterministic final artifacts as authoritative even when the TUI display is stale or unavailable.
- Risk: optional Copilot artifacts can look polished, but they are advisory only and must not be treated as approval or validation evidence beyond the deterministic facts they cite.
- Risk: full sandbox success requires several exact status strings; downstream tooling should not infer success from the presence of a sandbox directory alone.
- Risk: approval resume depends on checkpoint/snapshot artifacts in the run directory; missing or mismatched run IDs block resume.
