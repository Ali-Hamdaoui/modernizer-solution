# Detailed Migration Report

## Executive Summary

This migration moved the application from **Spring Boot 2.1 / Java 11** to **Spring Boot 4.0 / Java 21**.

| Metric | Value |
|---|---|
| Outcome | completed |
| Duration | 11h 52m 27s |
| Migration stages | 4 |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Tests executed | 0 |
| Tests passed | 0 |
| Repair attempts | 0 |

## Migration Story

The migration began with a job created at 2026-07-10T01:02:58Z and executed as a four-stage, linear upgrade path from the source profile "Spring Boot 2.1 / Java 11" toward the target "Spring Boot 4.0 / Java 21". Stage 1 (2.1→2.7 on Java 11) ran first: analysis, planning, and assessment phases completed within the initial window (analysis completed ~01:07:57Z), producing a full set of planning and analysis artifacts. Stage 1 runtime extended until completion at 2026-07-10T11:17:53Z (duration ~10.25 hours), during which the orchestrator generated analysis_report(s), dependency_graph, migration_plan.yaml, rewrite_preview and related rewrite artifacts, a target_dependency_plan, and numerous summaries and inventories.

Technically, Stage 1 focused on discovery and automated rewrite preparation: analysis and planning outputs plus a rewrite_dry_run.patch and rewrite_patch were produced as evidence of intended code edits. No build or test results are captured for this stage (build_status and test_status: not captured). Change metrics recorded zero files and zero line edits in the summary and per-stage change_metrics, indicating that no source modifications were applied by the backend during the run (files_changed: 0, lines_added/changed/deleted: 0). Repair attempts for Stage 1 are zero.

Human approval gating occurred at the end of Stage 1: the orchestrator paused and reported "Human approval required" shortly after assessment. Auto Approval was enabled later (2026-07-10T11:13:43Z) which auto-approved the gate; approval decisions were recorded and the sandbox transform was subsequently started and completed (sandbox transform completed at 2026-07-10T11:17:48Z). Artifacts reflecting the approval and finalization of Stage 1 (approval_decision, approved_plan_lock, final reports, and repeated analysis/assessment artifacts) were written as the stage concluded.

Stages 2–4 executed sequentially and completed quickly in the same overall migration window. Stage 2 (2.7→3.5 on Java 11) ran from 11:17:53Z to 12:33:59Z (~1.27 hours), Stage 3 (3.5 Java 17→3.5 Java 21) ran from 12:33:59Z to 12:41:46Z (~7.8 minutes), and Stage 4 (3.5→4.0 on Java 21) ran from 12:41:46Z to 12

## Migration Scope

- Source profile: Spring Boot 2.1 / Java 11
- Target profile: Spring Boot 4.0 / Java 21
- Included stages: 1, 2, 3, 4
- Skipped earlier stages: none
- Excluded later stages: none

## Stage-by-Stage Technical Details

### Stage 1: Spring Boot 2.1 / Java 11 to Spring Boot 2.7 / Java 11

| Metric | Value |
|---|---|
| Status | manifest_ready |
| Duration | 10h 14m 55s |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Transform | not captured |
| Build | not captured |
| Tests | not captured |
| Proof | not captured |
| Test total / passed / failed | 0 / 0 / 0 |
| Repair attempts | 0 |

### Stage 2: Spring Boot 2.7 / Java 11 to Spring Boot 3.5 / Java 17

| Metric | Value |
|---|---|
| Status | manifest_ready |
| Duration | 1h 16m 6s |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Transform | not captured |
| Build | not captured |
| Tests | not captured |
| Proof | not captured |
| Test total / passed / failed | 0 / 0 / 0 |
| Repair attempts | 0 |

### Stage 3: Spring Boot 3.5 / Java 17 to Spring Boot 3.5 / Java 21

| Metric | Value |
|---|---|
| Status | manifest_ready |
| Duration | 7m 47s |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Transform | not captured |
| Build | not captured |
| Tests | not captured |
| Proof | not captured |
| Test total / passed / failed | 0 / 0 / 0 |
| Repair attempts | 0 |

### Stage 4: Spring Boot 3.5 / Java 21 to Spring Boot 4.0 / Java 21

| Metric | Value |
|---|---|
| Status | manifest_ready |
| Duration | 13m 39s |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Transform | not captured |
| Build | not captured |
| Tests | not captured |
| Proof | not captured |
| Test total / passed / failed | 0 / 0 / 0 |
| Repair attempts | 0 |

## Migration Process Timeline

| Time | Stage | Event | Status | Detail |
|---|---|---|---|---|
| 2026-07-10T01:02:58.715000Z |  | Job Created | created | V2 migration job created. |
| 2026-07-10T01:02:58.764522Z | 1 | Stage Queued | queued | Stage 1 command manifest queued for real orchestrator execution. |
| 2026-07-10T01:02:58.832738Z | 1 | Stage Started | running | Stage 1 real orchestrator started. |
| 2026-07-10T01:02:58.872972Z | 1 | Command Started | running | Backend-owned orchestrator manifest launched. |
| 2026-07-10T01:02:58.941501Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T01:03:00.347155Z | 1 | Analysis Started | running | analysis phase started. |
| 2026-07-10T01:07:57.789219Z | 1 | Analysis Completed | completed | analysis phase completed. |
| 2026-07-10T01:07:57.828596Z | 1 | Planning Started | running | planning phase started. |
| 2026-07-10T01:07:57.975604Z | 1 | Planning Completed | completed | planning phase completed. |
| 2026-07-10T01:07:58.022344Z | 1 | Assessment Started | running | assessment phase started. |
| 2026-07-10T01:07:58.059459Z | 1 | Assessment Completed | completed | assessment phase completed. |
| 2026-07-10T01:07:58.126496Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T01:07:58.526586Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T01:07:58.570717Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T01:07:58.624281Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T01:07:58.669504Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T01:07:58.719827Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T01:07:58.758292Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T01:07:58.814127Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T01:07:58.860567Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T01:07:58.920830Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T01:07:58.953944Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T01:07:58.985497Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-10T01:07:59.020253Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-10T01:07:59.088064Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-10T01:07:59.140556Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-10T01:07:59.183019Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-10T01:07:59.234133Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-10T01:07:59.294013Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-10T01:07:59.335038Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-10T01:07:59.392400Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-10T01:07:59.429467Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-10T01:07:59.473478Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-10T01:07:59.514585Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-10T01:07:59.562073Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-10T01:07:59.595465Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-10T01:07:59.650937Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-10T01:07:59.684486Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-10T01:07:59.718163Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-10T01:07:59.752418Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-10T01:07:59.790474Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-10T01:07:59.839453Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-10T01:07:59.878952Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-10T01:07:59.914248Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-10T01:07:59.953179Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-10T01:07:59.990728Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-10T01:08:00.059433Z | 1 | Approval Required | blocked | Orchestrator paused for human approval review. |
| 2026-07-10T01:08:00.093481Z | 1 | Stage Blocked For Approval | blocked | Stage is blocked until exact checksum approval-review confirmation. |
| 2026-07-10T11:13:43.619992Z |  | Approval Mode Updated | updated | Auto Approval enabled. |
| 2026-07-10T11:13:43.664896Z | 1 | Approval Auto Approved | completed | Approval gate auto-approved because Auto Approval is enabled. |
| 2026-07-10T11:13:43.765711Z | 1 | Approval Resume Queued | started | Auto Approval accepted; backend-owned resume command started. |
| 2026-07-10T11:13:43.841287Z | 1 | Approval Started | running | Approval accepted; orchestrator resume process starting. |
| 2026-07-10T11:13:43.946909Z | 1 | Resume Started | running | Stage 1 real orchestrator resume started. |
| 2026-07-10T11:13:44.140377Z | 1 | Command Started | running | Backend-owned approval resume command launched. |
| 2026-07-10T11:13:44.497258Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T11:13:46.565485Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-10T11:13:46.610001Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T11:13:46.655716Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T11:13:46.710734Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-10T11:13:46.760519Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T11:13:47.127432Z | 1 | Approval Completed | completed | Human approval phase complete; sandbox transform has started. |
| 2026-07-10T11:13:47.178669Z | 1 | Sandbox Transform Started | running | Sandbox transform started. |
| 2026-07-10T11:17:48.223883Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-10T11:17:48.293419Z | 1 | Stage Report Started | running | Final report generation started. |
| 2026-07-10T11:17:48.415864Z | 1 | Stage Report Completed | completed | Final report written. |
| 2026-07-10T11:17:48.990450Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T11:17:49.048976Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T11:17:49.108851Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T11:17:49.176726Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T11:17:49.234331Z | 1 | Artifact Written | completed | Artifact written: approval_decision |
| 2026-07-10T11:17:49.291152Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T11:17:49.352693Z | 1 | Artifact Written | completed | Artifact written: approved_plan_lock |
| 2026-07-10T11:17:49.420131Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T11:17:49.480193Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T11:17:49.542367Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T11:17:49.601566Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T11:17:49.703239Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T11:17:49.764429Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-10T11:17:49.818720Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-10T11:17:49.898860Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-10T11:17:49.967163Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_request |
| 2026-07-10T11:17:50.017000Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_response |
| 2026-07-10T11:17:50.070673Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-10T11:17:50.138340Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-10T11:17:50.190474Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_report |
| 2026-07-10T11:17:50.245909Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_summary |
| 2026-07-10T11:17:50.311778Z | 1 | Artifact Written | completed | Artifact written: dependency_repair_plan |
| 2026-07-10T11:17:50.376978Z | 1 | Artifact Written | completed | Artifact written: migration_ledger |
| 2026-07-10T11:17:50.432939Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-10T11:17:50.476298Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-10T11:17:50.564260Z | 1 | Artifact Written | completed | Artifact written: openrewrite_plugin_xml |
| 2026-07-10T11:17:50.623059Z | 1 | Artifact Written | completed | Artifact written: orchestration_summary |
| 2026-07-10T11:17:50.673824Z | 1 | Artifact Written | completed | Artifact written: phase2_log |
| 2026-07-10T11:17:50.729471Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-10T11:17:50.795425Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-10T11:17:50.846767Z | 1 | Artifact Written | completed | Artifact written: policy_patch_plan |
| 2026-07-10T11:17:50.897397Z | 1 | Artifact Written | completed | Artifact written: policy_patch_result |
| 2026-07-10T11:17:50.955381Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_log |
| 2026-07-10T11:17:51.021461Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_report |
| 2026-07-10T11:17:51.083542Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_summary |
| 2026-07-10T11:17:51.136135Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-10T11:17:51.199497Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-10T11:17:51.256580Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-10T11:17:51.325998Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-10T11:17:51.389520Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-10T11:17:51.462070Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-10T11:17:51.524091Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-10T11:17:51.589449Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-10T11:17:51.653365Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-10T11:17:51.714016Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-10T11:17:51.781994Z | 1 | Artifact Written | completed | Artifact written: sandbox |
| 2026-07-10T11:17:51.836760Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-10T11:17:51.899325Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-10T11:17:51.979499Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-10T11:17:52.040898Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-10T11:17:52.109812Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-10T11:17:52.185491Z | 1 | Artifact Written | completed | Artifact written: timing_report |
| 2026-07-10T11:17:52.277168Z | 1 | Artifact Written | completed | Artifact written: timing_summary |
| 2026-07-10T11:17:52.344282Z | 1 | Artifact Written | completed | Artifact written: transformation_execution_plan |
| 2026-07-10T11:17:52.417301Z | 1 | Artifact Written | completed | Stage sandbox output registered. |
| 2026-07-10T11:17:52.477111Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-10T11:17:52.534803Z | 1 | Build Completed | completed | Sandbox build completed. |
| 2026-07-10T11:17:52.593913Z | 1 | Test Completed | completed | Sandbox tests accepted with status: PASS_WITH_WARNINGS. |
| 2026-07-10T11:17:52.781802Z | 1 | Proof Updated | completed | Orchestrator result parsed into deterministic evidence. |
| 2026-07-10T11:17:52.973163Z | 1 | Stage Completed | completed | Stage 1 real orchestrator completed. |
| 2026-07-10T11:17:53.237042Z | 1 | Stage Report Started | running | Stage 1 report started. |
| 2026-07-10T11:17:53.324621Z | 1 | Stage Report Completed | completed | Stage 1 report completed. |
| 2026-07-10T11:17:53.375898Z | 2 | Next Stage Queued | queued | Stage 2 route step command manifest queued for real orchestrator execution. |
| 2026-07-10T11:17:53.890534Z | 2 | Stage Started | running | Stage 2 real orchestrator started. |
| 2026-07-10T11:17:53.964628Z | 2 | Command Started | running | Backend-owned orchestrator manifest launched. |
| 2026-07-10T11:17:54.129477Z | 2 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T11:17:55.635202Z | 2 | Analysis Started | running | analysis phase started. |
| 2026-07-10T12:27:52.705418Z | 2 | Analysis Completed | completed | analysis phase completed. |
| 2026-07-10T12:27:52.765671Z | 2 | Planning Started | running | planning phase started. |
| 2026-07-10T12:27:52.896785Z | 2 | Planning Completed | completed | planning phase completed. |
| 2026-07-10T12:27:52.951690Z | 2 | Assessment Started | running | assessment phase started. |
| 2026-07-10T12:27:53.012817Z | 2 | Assessment Completed | completed | assessment phase completed. |
| 2026-07-10T12:27:53.067100Z | 2 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T12:27:53.553075Z | 2 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T12:27:53.605732Z | 2 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T12:27:53.662507Z | 2 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T12:27:53.714814Z | 2 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T12:27:53.769630Z | 2 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T12:27:53.838713Z | 2 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T12:27:53.888968Z | 2 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T12:27:53.948119Z | 2 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T12:27:54.006086Z | 2 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T12:27:54.062806Z | 2 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T12:27:54.122804Z | 2 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-10T12:27:54.172964Z | 2 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-10T12:27:54.221596Z | 2 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-10T12:27:54.278318Z | 2 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-10T12:27:54.334532Z | 2 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-10T12:27:54.391562Z | 2 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-10T12:27:54.451257Z | 2 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-10T12:27:54.506227Z | 2 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-10T12:27:54.560196Z | 2 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-10T12:27:54.608593Z | 2 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-10T12:27:54.659872Z | 2 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-10T12:27:54.711496Z | 2 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-10T12:27:54.775022Z | 2 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-10T12:27:54.830466Z | 2 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-10T12:27:54.884726Z | 2 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-10T12:27:54.941252Z | 2 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-10T12:27:54.991885Z | 2 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-10T12:27:55.041512Z | 2 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-10T12:27:55.086029Z | 2 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-10T12:27:55.141160Z | 2 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-10T12:27:55.206210Z | 2 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-10T12:27:55.263376Z | 2 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-10T12:27:55.354758Z | 2 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-10T12:27:55.439150Z | 2 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-10T12:27:55.553007Z | 2 | Approval Auto Approved | completed | Approval gate auto-approved because Auto Approval is enabled. |
| 2026-07-10T12:27:55.627235Z | 2 | Approval Started | running | Approval accepted; orchestrator resume process starting. |
| 2026-07-10T12:27:55.678538Z | 2 | Resume Started | running | Stage 2 real orchestrator resume started. |
| 2026-07-10T12:27:55.732518Z | 2 | Command Started | running | Backend-owned approval resume command launched. |
| 2026-07-10T12:27:55.850870Z | 2 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T12:27:57.187875Z | 2 | Approval Started | running | Recording approval decision. |
| 2026-07-10T12:27:57.234836Z | 2 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T12:27:57.289955Z | 2 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T12:27:57.352675Z | 2 | Approval Started | running | Recording approval decision. |
| 2026-07-10T12:27:57.403390Z | 2 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T12:27:57.630661Z | 2 | Approval Completed | completed | Human approval phase complete; sandbox transform has started. |
| 2026-07-10T12:27:57.683652Z | 2 | Sandbox Transform Started | running | Sandbox transform started. |
| 2026-07-10T12:33:54.897960Z | 2 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-10T12:33:54.956976Z | 2 | Stage Report Started | running | Final report generation started. |
| 2026-07-10T12:33:55.012577Z | 2 | Stage Report Completed | completed | Final report written. |
| 2026-07-10T12:33:55.491932Z | 2 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T12:33:55.568971Z | 2 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T12:33:55.630621Z | 2 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T12:33:55.687834Z | 2 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T12:33:55.737151Z | 2 | Artifact Written | completed | Artifact written: approval_decision |
| 2026-07-10T12:33:55.793001Z | 2 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T12:33:55.852994Z | 2 | Artifact Written | completed | Artifact written: approved_plan_lock |
| 2026-07-10T12:33:55.907937Z | 2 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T12:33:55.974274Z | 2 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T12:33:56.047242Z | 2 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T12:33:56.112846Z | 2 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T12:33:56.172339Z | 2 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T12:33:56.231052Z | 2 | Artifact Written | completed | Artifact written: config_inventory.json |

## Event Coverage

| Event Type | Count |
|---|---|
| Analysis Completed | 4 |
| Analysis Started | 4 |
| Approval Auto Approved | 4 |
| Approval Blocked | 8 |
| Approval Completed | 12 |
| Approval Mode Updated | 1 |
| Approval Required | 1 |
| Approval Resume Queued | 1 |
| Approval Started | 12 |
| Artifact Written | 347 |
| Assessment Completed | 4 |
| Assessment Started | 4 |
| Build Completed | 4 |
| Command Started | 8 |
| Final Report Completed | 1 |
| Final Report Started | 1 |
| Job Created | 1 |
| Next Stage Queued | 3 |
| Planning Completed | 4 |
| Planning Started | 4 |
| Process Started | 8 |
| Proof Updated | 4 |
| Resume Started | 4 |
| Sandbox Transform Completed | 8 |
| Sandbox Transform Started | 4 |
| Stage Blocked For Approval | 1 |
| Stage Completed | 5 |
| Stage Queued | 1 |
| Stage Report Completed | 5 |
| Stage Report Started | 5 |
| Stage Started | 4 |
| Stdout | 8 |
| Test Completed | 4 |

Console output events omitted from the narrative timeline: 8. Their aggregate count remains above.

## Report Provenance and Limitations

- Narrative generation: azure_openai (live_ok)
- Line metrics exclude binary files, generated build output, dependency caches, and files larger than 5 MiB.
- LLM narrative is advisory; deterministic metrics and persisted stage evidence are authoritative.
- The report describes sandbox migration execution and does not claim production deployment or production validation.

- Report generated at: 2026-07-10T13:20:34Z
- Migration job: 0cf11dda403b4f81a7856fe4e7c2a956
