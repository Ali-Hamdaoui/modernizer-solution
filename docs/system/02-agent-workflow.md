# Agent Workflow

This document describes each agent or agent-like phase in the current factory.

## Analysis Agent

Purpose:

- Read legacy source and generated run context.
- Detect source Java, Spring Boot, build tool, modules, imports, config, tests, dependency graph, and OpenRewrite preview impact.
- Prove source was not modified.

Inputs:

- `run_id`
- `legacy_app_path`
- `modernized_app_path`
- `ai_hub_path`
- `profile_id`
- AI Hub profile and OpenRewrite catalog when configured.

Outputs:

- `analysis/analysis_report.json`
- `analysis/dependency_graph.json`
- `analysis/test_inventory.json`
- `analysis/analysis_summary.md`
- Optional: `config_inventory.json`, `rewrite_plugin_plan.json`, `rewrite_preview.json`, `rewrite_dry_run.patch`, `rewrite_impact_summary.json`, `copilot_assist.json`
- Current code also writes `analysis/read_only_verification.json`; orchestrator validation requires it.

State fields used/modified:

- Reads `run_id`, `legacy_app_path`, `modernized_app_path`, `ai_hub_path`, `profile_id`.
- Sets `analysis_status`, `current_unit`, `errors`, `blockers`, `warnings`, `artifact_refs`.
- Orchestrator adds `analysis_artifacts_valid`.

Modules involved:

- `migration_factory/orchestrator/phase_services.py`
- `migration_factory/agents/analysis_agent/analysis_agent/main.py`
- `context_manager.py`
- `maven_scanner.py`
- `dependency_adapter.py`
- `import_scanner.py`
- `config_scanner.py`
- `test_scanner.py`
- `surefire_parser.py`
- `openrewrite_adapter.py`
- `rewrite_catalog_loader.py`
- `rewrite_impact_analyzer.py`
- `rewrite_plugin_plan_writer.py`
- `readonly_verifier.py`
- `report_assembler.py`
- `summary_generator.py`

Failure modes:

- Invalid or escaping paths raise `SecurityViolationError`.
- Missing or unreadable `pom.xml` produces warnings or scan fallback.
- Maven dependency tree failure writes an unavailable graph with warning.
- OpenRewrite dry-run failure writes diagnostic data and blocked impact summary.
- Dry-run source mutation fails analysis through read-only verification.
- Missing required artifacts or schema violations fail orchestrator validation.

Tests:

- `migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py`
- `test_maven_scanner.py`
- `test_dependency_adapter.py`
- `test_import_scanner.py`
- `test_config_scanner.py`
- `test_test_scanner.py`
- `test_surefire_parser.py`
- `test_openrewrite_adapter.py`
- `test_rewrite_catalog_loader.py`
- `test_rewrite_impact_analyzer.py`
- `test_readonly_verifier.py`
- `test_path_safety.py`
- `test_artifact_schemas.py`
- Orchestrator validation in `tests/orchestrator/test_artifact_validation.py`

Workflow position:

- First LangGraph phase after preflight.
- Routes to planning on `PASS` plus valid artifacts, or stops/sidecars to Copilot according to assist mode.

## Planning Agent

Purpose:

- Convert analysis facts and AI Hub profile into deterministic migration plan artifacts.
- Validate source/profile compatibility.
- Classify risks.
- Produce migration unit order and human approval request.
- Optionally merge advisory-only Copilot planning suggestions.

Inputs:

- Analysis artifacts from `analysis/`.
- AI Hub profile from `modernizer-solution-ai-hub/profiles/<profile_id>.yaml`.
- Optional `agents/copilot-assist.yaml` planning config.

Outputs:

- `planning/migration_plan.yaml`
- `planning/migration_units.yaml`
- `planning/plan_summary.md`
- `planning/approval_request.json`
- `planning/plan_validation_report.json`
- Optional audit artifact: `planning/copilot_assist.json`

State fields used/modified:

- Reads `run_id`, `legacy_app_path`, `modernized_app_path`, `ai_hub_path`, `profile_id` or `profile`.
- Sets `planning_status`, `current_unit`, `errors`, `blockers`, `warnings`, `planning_output_artifacts`, `planning_validation_status`, `risks`, `migration_units`, `planning_approval_summary`, `planning_operator_notes`, `planning_risk_explanations`, `planning_assist_status`, `planning_assist_error`, `planning_assist_warnings`.
- Orchestrator adds `planning_artifacts_valid`.

Modules involved:

- `migration_factory/agents/planning_agent/node.py`
- `artifact_reader.py`
- `analysis_validator.py`
- `profile_reader.py`
- `profile_compatibility.py`
- `risk_classifier.py`
- `unit_builder.py`
- `plan_writer.py`
- `approval_writer.py`
- `summary_writer.py`
- `output_validator.py`
- `assist_config.py`
- `copilot_assist_client.py`
- `assist_output_validator.py`
- `assist_merge.py`
- `assist_artifact_writer.py`

Failure modes:

- Required analysis artifacts missing or invalid.
- AI Hub profile missing or invalid.
- Source stack incompatible with selected profile.
- Risk classifier produces blockers.
- Generated planning artifacts fail validation or schema checks.
- Copilot planning assist is fail-open and cannot block deterministic planning unless deterministic output validation fails.

Tests:

- `tests/agents/planning_agent/test_full_planning_flow_integration.py`
- `test_planning_missing_inputs.py`
- `test_profile_compatibility_source_stack.py`
- `test_risk_classifier_and_executable.py`
- `test_unit_builder_deterministic.py`
- `test_approval_and_summary_outputs.py`
- `test_openrewrite_planner_contract.py`
- `test_assist_config.py`
- `test_assist_contracts.py`
- `test_assist_output_validator.py`
- `test_copilot_assist_client.py`
- `test_copilot_auth.py`
- `test_copilot_model.py`
- `test_copilot_guardrails.py`
- `test_staged_boot216_profiles.py`
- `test_library_experimental_profile.py`
- `test_library_jakarta_java17_minimal_profile.py`

Workflow position:

- Runs after analysis passes.
- Routes to assessment on `PASS` plus valid artifacts.

## Assessment Agent

Purpose:

- Combine analysis and planning outputs into a readiness report.
- Ensure the run is ready for human review, not execution.
- Preserve enterprise compatibility warnings.

Inputs:

- Required analysis artifacts from `migration_factory/contracts/assessment_artifacts.py`.
- Required planning artifacts from `migration_factory/contracts/assessment_artifacts.py`.
- Optional read-only and Copilot assist artifacts.

Outputs:

- `assessment/assessment_report.json`
- `assessment/assessment_summary.md`

State fields used/modified:

- Reads `modernized_app_path`, `run_id`.
- Sets `assessment_status`, `current_unit`, and artifact refs through `phase_services.py`.
- Orchestrator adds `assessment_artifacts_valid`.

Modules involved:

- `migration_factory/assessment/writer.py`
- `migration_factory/assessment/runner.py`
- `migration_factory/contracts/assessment_artifacts.py`
- `migration_factory/contracts/schema_validation.py`

Artifacts written:

- `assessment_report.json` includes `approval_readiness`, `execution_claims`, `enterprise_compatibility`, `openrewrite_dry_run`, `read_only_verification`, and `copilot`.
- `assessment_summary.md` explicitly states that transformation, OpenRewrite apply, migrated build/tests, and final migration were not executed.

Failure modes:

- Missing required inputs raises `AssessmentArtifactError`.
- Required input schema violations become blockers.
- Failed read-only verification blocks approval readiness.
- Non-empty approval/plan blockers block readiness.
- Execution claims set to true are blocked by orchestrator validation.

Tests:

- `tests/assessment/test_assessment_writer.py`
- `tests/assessment/test_assessment_runner.py`
- `tests/orchestrator/test_artifact_validation.py`

Workflow position:

- Runs after planning passes.
- Routes to human approval only if artifacts validate and `approval_readiness.status` is `READY_FOR_REVIEW`.

## Human Approval Gate

Purpose:

- Interrupt the graph and require a human decision before source-changing work.
- Record approval decisions and hash-lock approved artifacts on resume.

Inputs:

- Orchestrator state and `artifact_refs`.
- Phase 1 artifacts.
- Resume payload: `decision`, `approved_by`, `comments`.

Outputs:

- Interrupt payload returned from runner.
- `approval/approval_decision.json`
- `approval/approved_plan_lock.json` only when decision is `approved`.
- `orchestration/approval_interrupt_state.json`

State fields used/modified:

- Reads phase statuses, artifact refs, blockers, warnings, mode.
- Sets `approval_status`, `approval_decision`, `approved_by`, `approval_comments`, `current_phase`, `stop_reason`.
- Approval recording sets `orchestration_status`, `artifact_refs`, and final stop status for rejected/replan decisions.

Modules involved:

- `migration_factory/orchestrator/approval.py`
- `migration_factory/orchestrator/resume.py`
- `migration_factory/orchestrator/phase_services.py`
- `migration_factory/approval/approve_run.py`
- `migration_factory/approval/artifacts.py`

Failure modes:

- Invalid decision.
- Missing Phase 1 artifacts.
- Schema invalid Phase 1 artifacts.
- Read-only verification failure.
- Assessment not `READY_FOR_REVIEW`.
- Assessment blockers present.
- Assessment claims execution already happened.
- Lock hash mismatch on transform.

Tests:

- `tests/test_approval_cli.py`
- `tests/orchestrator/test_approval.py`
- `tests/orchestrator/test_full_sandbox_migration.py`
- `tests/orchestrator/test_checkpointing.py`

Workflow position:

- Always after assessment.
- In `read_only_assessment`, stops after interrupt or decision.
- In `full_sandbox_migration`, approved resume continues to sandbox transform.

## Transform Agent

Purpose:

- Apply approved migration units to sandbox only.
- Run OpenRewrite and deterministic patch transformations.
- Pause after each unit for Build Agent validation.

Inputs:

- Approved and locked run artifacts.
- `transformation/transformation_execution_plan.yaml`.
- `transformation/openrewrite-plugin.xml`.
- Sandbox workspace path.
- AI Hub profile/catalog apply settings.

Outputs:

- Sandbox source changes under `workspaces/sandbox/`.
- Sandbox ledger: `workspaces/sandbox/.migration/ledger.json`.
- Transformation log: `logs/phase2_transform.log`.
- Updated timing artifacts.

State fields used/modified through wrapper:

- Sets `transform_status`, `build_status`, `test_status`, `test_totals`, `sandbox_path`, `transform_log_path`, `test_report_path`, `test_summary_path`, `test_log_path`, `test_phase`, `artifact_refs`, `final_status`, `stop_reason`.

Modules involved:

- `migration_factory/transform_v1_after_approval.py`
- `migration_factory/agents/transformation_agent/agent.py`
- `execution_plan.py`
- `plan.py`
- `workspace.py`
- `rewrite.py`
- `executor.py`
- `pom_patches.py`
- `migration_factory/contracts/migration/ledger.py`

Failure modes:

- Approval artifacts missing, invalid, not approved, or not matching `approved_by`.
- Approved plan lock hash mismatch.
- Profile guardrails block source-changing transform.
- Sandbox cleanup/copy failure or unsafe symlink.
- Missing OpenRewrite plugin/catalog.
- OpenRewrite command failure.
- Required deterministic patch not applied.
- Build Agent failure after a unit.
- Transformer resume loop repeats same unit or exceeds max runs.
- Test Agent reports failure/error after transform completion.

Tests:

- `tests/test_transformation_agent.py`
- `tests/orchestrator/test_full_sandbox_migration.py`
- `tests/orchestrator/test_profile_guardrails.py`

Workflow position:

- Only after approved resume in `full_sandbox_migration`.

## Build Agent

Purpose:

- Validate build/start/test command for sandbox units.
- Detect Java project type and command.
- Classify failures and update ledger.

Inputs:

- `project_path`
- Optional `ledger_file`
- Optional `validation_unit_id`
- Optional validation command from migration unit checks.
- Optional `source_jdk_home_env` and `target_jdk_home_env` profile fields.

Outputs:

- `BuildRunResult`.
- Failure contract JSON under configured `output_dir`, usually `run_dir/build/`.
- Ledger build validation entry.

State fields used/modified:

- Not directly a graph node. Wrapper records `build_status`, build command timing, and ledger updates.

Modules involved:

- `migration_factory/agents/build_agent/agent.py`
- `detection.py`
- `runner.py`
- `classifier.py`
- `migration_factory/contracts/build/schemas.py`
- `migration_factory/contracts/migration/ledger.py`

Failure modes:

- Project path invalid or no Maven/Gradle markers.
- Build command missing or not executable.
- Dependency resolution failure.
- Compilation failure.
- Java version/runtime mismatch.
- Port already in use.
- Main class not found.
- Missing config or bean creation failure.
- Startup timeout.
- Java 21 target runtime gate failure.
- Spring Boot 4 Maven version gate failure.

Tests:

- `tests/test_build_agent.py`

Workflow position:

- Called by `transform_v1_after_approval.py` each time the Transform Agent marks a unit `awaiting_build_agent`.

## Test Agent

Purpose:

- Parse existing Surefire XML reports after post-transform build/test validation.
- Produce test evidence artifacts.

Inputs:

- `sandbox_path`
- `run_dir`
- `run_id`
- `source_log_path`
- Build command/cwd/status/exit code
- `require_test_reports`

Outputs:

- `test/post_transform/test_report.json`
- `test/post_transform/test_summary.md`
- `test/post_transform/test_agent.log`

State fields used/modified:

- Wrapper records `test_status`, `test_totals`, paths, and ledger `test_validation`.

Modules involved:

- `migration_factory/agents/test_agent/agent.py`
- `migration_factory/transform_v1_after_approval.py`

Failure modes:

- Invalid sandbox path.
- Build status was not passed.
- Surefire reports missing.
- Surefire XML parse failure.
- Failures/errors in Surefire reports.
- Tests not runnable or not discovered, currently may be `PASS_WITH_WARNINGS` when build passed and reports are not required.

Tests:

- `tests/test_test_agent.py`

Workflow position:

- Called after Transform Agent completes all units or reaches final unit.

## Quality/Security/Report Logic

Purpose:

- Classify compatibility and security risks.
- Produce final deterministic and advisory reports.
- Redact secrets and make proof levels explicit.

Inputs:

- Phase artifacts and final state.
- Timing and ledger artifacts.

Outputs:

- `final/migration_report.json`
- `final/migration_summary.md`
- `final/report_context.json`
- `performance/timing_report.json`
- `performance/timing_summary.md`
- Optional Copilot statement/report/docs.

Modules involved:

- `migration_factory/assessment/writer.py`
- `migration_factory/agents/build_agent/classifier.py`
- `migration_factory/final_report/writer.py`
- `migration_factory/final_report/context_builder.py`
- `migration_factory/orchestrator/summary.py`
- `migration_factory/agents/copilot_doc_agent/agent.py`

Failure modes:

- Final report blocked if required success refs are missing.
- Successful full sandbox orchestration invalid if required statuses/artifact refs are missing.
- Copilot final report failures become warnings/fallback responses, not official status changes.

Tests:

- `tests/test_final_report.py`
- `tests/reporting/test_report_context.py`
- `tests/reporting/test_copilot_final_report.py`
- `tests/orchestrator/test_summary.py`

Workflow position:

- Finalization after sandbox transform success.
- Copilot docs run only after successful sandbox validation.

## Copilot Assist And Reporting Logic

Purpose:

- Provide advisory phase assistance and final migration documentation.
- Never mutate official state or source.

Inputs:

- Orchestrator state snapshots.
- `final/report_context.json`.
- AI Hub Copilot configs and templates.

Outputs:

- Phase sidecars: `<phase>/copilot_assist.json`, `<phase>/copilot_assist.md`.
- Final sidecars: `final/copilot_report_request.json`, `final/copilot_report_response.json`, `final/copilot_migration_report.md`.
- Documentation package: `final/copilot_docs/*.md`.
- Optional advisory statement: `final/copilot_migration_statement.json`, `.md`.

State fields used/modified:

- Only `copilot_phase_statuses`, `copilot_artifact_refs`, `copilot_warnings`, `copilot_errors`, `copilot_fallback_used`, plus graph routing helpers.
- `migration_factory/orchestrator/copilot_assist.py` snapshots and restores official state fields.

Modules involved:

- `migration_factory/orchestrator/copilot_assist.py`
- `migration_factory/copilot_assist/service.py`
- `migration_factory/copilot_assist/providers/cli_provider.py`
- `migration_factory/copilot_assist/providers/deterministic_provider.py`
- `migration_factory/final_report/copilot.py`
- `migration_factory/agents/copilot_doc_agent/agent.py`

Tests:

- `tests/orchestrator/test_copilot_assist_routing.py`
- `tests/orchestrator/test_copilot_state_safety.py`
- `tests/reporting/test_copilot_final_report.py`
- `tests/test_final_report.py`
- `tests/tui/test_copilot_status.py`
