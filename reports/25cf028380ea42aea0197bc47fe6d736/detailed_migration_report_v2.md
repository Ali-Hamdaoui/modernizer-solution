# Detailed Migration Report

## Executive Summary

This migration moved the application from **Spring Boot 2.1 / Java 11** to **Spring Boot 4.0 / Java 21**.

### Key Metrics

| Metric | Value |
|---|---|
| Outcome | completed |
| Duration | 56m 4s |
| Migration stages | 4 |
| Files changed | 210 |
| Lines added | 2963 |
| Lines deleted | 1146 |
| Total lines changed | 4109 |
| Tests executed | 0 |
| Tests passed | 0 |
| Repair attempts | 0 |

## Migration Story

The migration targeted an upgrade path from Spring Boot 2.1 on Java 11 to Spring Boot 4.0 on Java 21, executed as four sequential stages covering intermediate platform baselines (2.7/11, 3.5/17, 3.5/21) before reaching the declared target. Scope included all four stages and the run produced a consolidated source-tree impact of 210 files changed with 2,963 lines added, 4,109 lines changed and 1,146 lines deleted; per-stage deltas show the largest structural work in Stage 2 (157 files changed, 757 lines added, 702 lines deleted) and the bulk of net line churn across the pipeline.

Stage 1 transitioned the codebase from Spring Boot 2.1 / Java 11 to Spring Boot 2.7 / Java 11. It ran for approximately 13 minutes and produced 2 files touched with 1,770 lines added and 12 lines deleted, completing in a manifest-ready state. An analysis and planning pass created a wide set of artifacts (analysis reports, dependency graphs, migration_plan.yaml, rewrite previews and patches) used to drive the changes; sandbox transformation completed and a stage final report was written. Build, test, and proof-level outcomes are not captured for this stage.

Stage 2 implemented the larger migration to Spring Boot 3.5 / Java 17 and represents the most substantial code edits: 157 files changed, 757 lines added, 702 lines deleted across ~14.6 minutes. As with Stage 1, the stage reached manifest_ready and generated detailed artifacts (including target_dependency_plan and rewrite outputs) to document planned rewrites and dependency decisions. Recording and recording of human approvals occurred here; Auto Approval was enabled early and approval decisions were recorded to permit sandbox transforms to proceed. Explicit test execution and build results are not captured.

Stage 3 and Stage 4 completed the remaining baseline and target transitions (3.5/Java 17 → 3.5/Java 21, then 3.5/Java 21 → 4.0/Java 21). Stage 3 made smaller, focused changes across 8 files (321 lines added, 321 deleted), while Stage 4 touched 43 files with modest net additions (115 added, 111 deleted). Each stage completed in manifest_ready status with sandbox transform and final report artifacts produced. Across all stages there were zero recorded repair attempts and no recorded test totals—test counts are zero and test_status is not captured—so runtime verification and QA validation are outstanding.

Approval and orchestration flowed through both automated and human gates: Auto Approval was enabled, an approval gate

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
| Duration | 13m 12s |
| Files changed | 2 |
| Lines added | 1770 |
| Lines deleted | 12 |
| Total lines changed | 1782 |
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
| Duration | 14m 39s |
| Files changed | 157 |
| Lines added | 757 |
| Lines deleted | 702 |
| Total lines changed | 1459 |
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
| Duration | 9m 32s |
| Files changed | 8 |
| Lines added | 321 |
| Lines deleted | 321 |
| Total lines changed | 642 |
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
| Duration | 18m 40s |
| Files changed | 43 |
| Lines added | 115 |
| Lines deleted | 111 |
| Total lines changed | 226 |
| Transform | not captured |
| Build | not captured |
| Tests | not captured |
| Proof | not captured |
| Test total / passed / failed | 0 / 0 / 0 |
| Repair attempts | 0 |

## Migration Process Timeline

| Time | Stage | Event | Status | Detail |
|---|---|---|---|---|
| 2026-07-11T15:50:42.432837Z |  | Job Created | created | V2 migration job created. |
| 2026-07-11T15:50:42.504359Z | 1 | Stage Queued | queued | Stage 1 command manifest queued for real orchestrator execution. |
| 2026-07-11T15:50:42.581760Z | 1 | Stage Started | running | Stage 1 real orchestrator started. |
| 2026-07-11T15:50:42.634675Z | 1 | Command Started | running | Backend-owned orchestrator manifest launched. |
| 2026-07-11T15:50:42.732522Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-11T15:50:44.776540Z | 1 | Analysis Started | running | analysis phase started. |
| 2026-07-11T15:50:47.912530Z |  | Approval Mode Updated | updated | Auto Approval enabled. |
| 2026-07-11T15:59:43.785550Z | 1 | Analysis Completed | completed | analysis phase completed. |
| 2026-07-11T15:59:43.859135Z | 1 | Planning Started | running | planning phase started. |
| 2026-07-11T15:59:44.020183Z | 1 | Planning Completed | completed | planning phase completed. |
| 2026-07-11T15:59:44.119981Z | 1 | Assessment Started | running | assessment phase started. |
| 2026-07-11T15:59:44.202384Z | 1 | Assessment Completed | completed | assessment phase completed. |
| 2026-07-11T15:59:44.296364Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-11T15:59:44.832488Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-11T15:59:44.902943Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-11T15:59:44.963339Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-11T15:59:45.038554Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-11T15:59:45.073682Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-11T15:59:45.126970Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-11T15:59:45.193515Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-11T15:59:45.257169Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-11T15:59:45.440019Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-11T15:59:45.494329Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-11T15:59:45.610610Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-11T15:59:45.669498Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-11T15:59:45.720886Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-11T15:59:45.777002Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-11T15:59:45.831236Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-11T15:59:45.893128Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-11T15:59:45.936659Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-11T15:59:45.990230Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-11T15:59:46.061946Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-11T15:59:46.115121Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-11T15:59:46.163984Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-11T15:59:46.252584Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-11T15:59:46.299796Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-11T15:59:46.353626Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-11T15:59:46.407778Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-11T15:59:46.469590Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-11T15:59:46.536715Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-11T15:59:46.615176Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-11T15:59:46.671913Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-11T15:59:46.745845Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-11T15:59:46.799815Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-11T15:59:46.880436Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-11T15:59:46.934096Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-11T15:59:46.992107Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-11T15:59:47.117829Z | 1 | Approval Auto Approved | completed | Approval gate auto-approved because Auto Approval is enabled. |
| 2026-07-11T15:59:47.191986Z | 1 | Approval Started | running | Approval accepted; orchestrator resume process starting. |
| 2026-07-11T15:59:47.246909Z | 1 | Resume Started | running | Stage 1 real orchestrator resume started. |
| 2026-07-11T15:59:47.295121Z | 1 | Command Started | running | Backend-owned approval resume command launched. |
| 2026-07-11T15:59:47.546897Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-11T15:59:49.724896Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-11T15:59:49.788606Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-11T15:59:49.862998Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-11T15:59:49.918613Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-11T15:59:49.986186Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-11T15:59:50.429111Z | 1 | Approval Completed | completed | Human approval phase complete; sandbox transform has started. |
| 2026-07-11T15:59:50.497481Z | 1 | Sandbox Transform Started | running | Sandbox transform started. |
| 2026-07-11T16:03:49.886401Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-11T16:03:49.952961Z | 1 | Stage Report Started | running | Final report generation started. |
| 2026-07-11T16:03:50.048047Z | 1 | Stage Report Completed | completed | Final report written. |
| 2026-07-11T16:03:50.566410Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-11T16:03:50.635521Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-11T16:03:50.691534Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-11T16:03:50.759422Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-11T16:03:50.821905Z | 1 | Artifact Written | completed | Artifact written: approval_decision |
| 2026-07-11T16:03:50.881560Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-11T16:03:50.949037Z | 1 | Artifact Written | completed | Artifact written: approved_plan_lock |
| 2026-07-11T16:03:50.994810Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-11T16:03:51.059398Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-11T16:03:51.121305Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-11T16:03:51.174382Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-11T16:03:51.231013Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-11T16:03:51.294302Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-11T16:03:51.346587Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-11T16:03:51.397016Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-11T16:03:51.445233Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_request |
| 2026-07-11T16:03:51.513390Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_response |
| 2026-07-11T16:03:51.592041Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-11T16:03:51.648280Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-11T16:03:51.704929Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_report |
| 2026-07-11T16:03:51.763325Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_summary |
| 2026-07-11T16:03:51.813000Z | 1 | Artifact Written | completed | Artifact written: dependency_repair_plan |
| 2026-07-11T16:03:51.881413Z | 1 | Artifact Written | completed | Artifact written: migration_ledger |
| 2026-07-11T16:03:51.948954Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-11T16:03:52.014811Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-11T16:03:52.083816Z | 1 | Artifact Written | completed | Artifact written: openrewrite_plugin_xml |
| 2026-07-11T16:03:52.134874Z | 1 | Artifact Written | completed | Artifact written: orchestration_summary |
| 2026-07-11T16:03:52.192251Z | 1 | Artifact Written | completed | Artifact written: phase2_log |
| 2026-07-11T16:03:52.253653Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-11T16:03:52.319187Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-11T16:03:52.377619Z | 1 | Artifact Written | completed | Artifact written: policy_patch_plan |
| 2026-07-11T16:03:52.442349Z | 1 | Artifact Written | completed | Artifact written: policy_patch_result |
| 2026-07-11T16:03:52.507000Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_log |
| 2026-07-11T16:03:52.557132Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_report |
| 2026-07-11T16:03:52.623377Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_summary |
| 2026-07-11T16:03:52.686767Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-11T16:03:52.749063Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-11T16:03:52.807799Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-11T16:03:52.873532Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-11T16:03:52.931429Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-11T16:03:52.982086Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-11T16:03:53.036928Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-11T16:03:53.108072Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-11T16:03:53.159943Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-11T16:03:53.218971Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-11T16:03:53.280074Z | 1 | Artifact Written | completed | Artifact written: sandbox |
| 2026-07-11T16:03:53.329170Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-11T16:03:53.381797Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-11T16:03:53.440671Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-11T16:03:53.499462Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-11T16:03:53.550854Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-11T16:03:53.620536Z | 1 | Artifact Written | completed | Artifact written: timing_report |
| 2026-07-11T16:03:53.679654Z | 1 | Artifact Written | completed | Artifact written: timing_summary |
| 2026-07-11T16:03:53.736753Z | 1 | Artifact Written | completed | Artifact written: transformation_execution_plan |
| 2026-07-11T16:03:53.806578Z | 1 | Artifact Written | completed | Stage sandbox output registered. |
| 2026-07-11T16:03:53.852768Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-11T16:03:53.916630Z | 1 | Build Completed | completed | Sandbox build completed. |
| 2026-07-11T16:03:54.125506Z | 1 | Test Completed | completed | Sandbox tests accepted with status: PASS_WITH_WARNINGS. |
| 2026-07-11T16:03:54.251091Z | 1 | Proof Updated | completed | Orchestrator result parsed into deterministic evidence. |
| 2026-07-11T16:03:54.359636Z | 1 | Stage Completed | completed | Stage 1 real orchestrator completed. |
| 2026-07-11T16:03:54.630644Z | 1 | Stage Report Started | running | Stage 1 report started. |
| 2026-07-11T16:03:54.744701Z | 1 | Stage Report Completed | completed | Stage 1 report completed. |
| 2026-07-11T16:03:54.822627Z | 2 | Next Stage Queued | queued | Stage 2 route step command manifest queued for real orchestrator execution. |
| 2026-07-11T16:03:55.333473Z | 2 | Stage Started | running | Stage 2 real orchestrator started. |
| 2026-07-11T16:03:55.404381Z | 2 | Command Started | running | Backend-owned orchestrator manifest launched. |
| 2026-07-11T16:03:55.535489Z | 2 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-11T16:03:56.803082Z | 2 | Analysis Started | running | analysis phase started. |
| 2026-07-11T16:11:26.152316Z | 2 | Analysis Completed | completed | analysis phase completed. |
| 2026-07-11T16:11:26.210629Z | 2 | Planning Started | running | planning phase started. |
| 2026-07-11T16:11:26.454607Z | 2 | Planning Completed | completed | planning phase completed. |
| 2026-07-11T16:11:26.582684Z | 2 | Assessment Started | running | assessment phase started. |
| 2026-07-11T16:11:26.816506Z | 2 | Assessment Completed | completed | assessment phase completed. |
| 2026-07-11T16:11:26.898444Z | 2 | Approval Blocked | blocked | Human approval required. |
| 2026-07-11T16:11:27.656714Z | 2 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-11T16:11:27.903152Z | 2 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-11T16:11:27.963405Z | 2 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-11T16:11:28.016286Z | 2 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-11T16:11:28.078606Z | 2 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-11T16:11:28.128633Z | 2 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-11T16:11:28.188535Z | 2 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-11T16:11:28.269646Z | 2 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-11T16:11:28.327841Z | 2 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-11T16:11:28.382482Z | 2 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-11T16:11:28.445022Z | 2 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-11T16:11:28.551016Z | 2 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-11T16:11:28.608151Z | 2 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-11T16:11:28.678988Z | 2 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-11T16:11:28.731868Z | 2 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-11T16:11:28.795891Z | 2 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-11T16:11:28.867446Z | 2 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-11T16:11:28.929171Z | 2 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-11T16:11:29.002022Z | 2 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-11T16:11:29.076767Z | 2 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-11T16:11:29.137422Z | 2 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-11T16:11:29.207877Z | 2 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-11T16:11:29.263004Z | 2 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-11T16:11:29.325860Z | 2 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-11T16:11:29.376791Z | 2 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-11T16:11:29.438654Z | 2 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-11T16:11:29.504168Z | 2 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-11T16:11:29.569103Z | 2 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-11T16:11:29.642380Z | 2 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-11T16:11:29.700690Z | 2 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-11T16:11:29.777250Z | 2 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-11T16:11:29.833443Z | 2 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-11T16:11:29.897371Z | 2 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-11T16:11:29.962043Z | 2 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-11T16:11:30.078125Z | 2 | Approval Auto Approved | completed | Approval gate auto-approved because Auto Approval is enabled. |
| 2026-07-11T16:11:30.162231Z | 2 | Approval Started | running | Approval accepted; orchestrator resume process starting. |
| 2026-07-11T16:11:30.449360Z | 2 | Resume Started | running | Stage 2 real orchestrator resume started. |
| 2026-07-11T16:11:30.487118Z | 2 | Command Started | running | Backend-owned approval resume command launched. |
| 2026-07-11T16:11:30.625523Z | 2 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-11T16:11:33.716913Z | 2 | Approval Started | running | Recording approval decision. |
| 2026-07-11T16:11:33.785427Z | 2 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-11T16:11:33.941494Z | 2 | Approval Blocked | blocked | Human approval required. |
| 2026-07-11T16:11:34.009303Z | 2 | Approval Started | running | Recording approval decision. |
| 2026-07-11T16:11:34.079566Z | 2 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-11T16:11:35.007789Z | 2 | Approval Completed | completed | Human approval phase complete; sandbox transform has started. |
| 2026-07-11T16:11:35.072533Z | 2 | Sandbox Transform Started | running | Sandbox transform started. |
| 2026-07-11T16:18:28.402023Z | 2 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-11T16:18:28.465786Z | 2 | Stage Report Started | running | Final report generation started. |
| 2026-07-11T16:18:28.528649Z | 2 | Stage Report Completed | completed | Final report written. |
| 2026-07-11T16:18:29.122862Z | 2 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-11T16:18:29.185825Z | 2 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-11T16:18:29.253178Z | 2 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-11T16:18:29.321111Z | 2 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-11T16:18:29.423021Z | 2 | Artifact Written | completed | Artifact written: approval_decision |
| 2026-07-11T16:18:29.494361Z | 2 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-11T16:18:29.537651Z | 2 | Artifact Written | completed | Artifact written: approved_plan_lock |
| 2026-07-11T16:18:29.600671Z | 2 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-11T16:18:29.672874Z | 2 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-11T16:18:29.740901Z | 2 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-11T16:18:29.815753Z | 2 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-11T16:18:29.876183Z | 2 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-11T16:18:29.946767Z | 2 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-11T16:18:30.009257Z | 2 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-11T16:18:30.077500Z | 2 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-11T16:18:30.159684Z | 2 | Artifact Written | completed | Artifact written: dependency_graph |

## Event Coverage

| Event Type | Count |
|---|---|
| Analysis Completed | 4 |
| Analysis Started | 4 |
| Approval Auto Approved | 4 |
| Approval Blocked | 8 |
| Approval Completed | 12 |
| Approval Mode Updated | 1 |
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

- Report generated at: 2026-07-11T19:05:07Z
- Migration job: 25cf028380ea42aea0197bc47fe6d736
