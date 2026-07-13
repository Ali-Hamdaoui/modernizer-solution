# Detailed Migration Report

## Executive Summary

This migration moved the application from **Spring Boot 2.1 / Java 11** to **Spring Boot 2.7 / Java 11**.

| Metric | Value |
|---|---|
| Outcome | completed |
| Duration | 12m 13s |
| Migration stages | 1 |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Tests executed | 0 |
| Tests passed | 0 |
| Repair attempts | 0 |

## Migration Story

The migration ran a single included stage (Stage 1) to move from the source profile "Spring Boot 2.1 / Java 11" to the target profile "Spring Boot 2.7 / Java 11." Stage 1 started at 2026-07-10T14:34:12Z and completed at 2026-07-10T14:46:25Z, running for ~733 seconds. The stage reached status manifest_ready and the overall migration_completed event is recorded. No subsequent stages were included in this run (excluded_stages: [2,3,4]).

The work began with automated analysis (analysis_started → analysis_completed) followed immediately by planning and assessment phases; all three phases completed in-sequence for Stage 1. The tooling produced a comprehensive set of migration artifacts during these phases: analysis_report, analysis_summary, assessment_report and summaries, dependency_graph, migration_plan.yaml and migration_units.yaml, target_dependency_plan, rewrite_preview and rewrite_patch, rewrite_impact_summary, plan_validation_report, test_inventory, and several related JSON artifacts. These artifacts form the technical evidence for proposed edits and impact assessment.

Approval activity was recorded multiple times. Auto Approval was enabled early in the run and an approval gate was auto-approved because of that setting. Human approval events were also required and recorded: the timeline shows approval_blocked entries followed by approval_started and approval_completed entries, concluding with “Human approval phase complete; sandbox transform has started.” The system therefore progressed under a mix of auto and recorded human approvals before performing transformations.

Sandbox transform work ran after approvals; sandbox_transform_started and sandbox_transform_completed are both present and the final report generation and stage_report_completed events were written. The run generated rewrite artifacts (rewrite_dry_run.patch, rewrite_patch, rewrite_preview) and a rewrite_plugin_plan — indicating code-modification proposals were prepared and a dry-run/preview produced. However, change metrics show files_changed: 0 and lines_added/changed/deleted: 0; no edits were applied to source files in this execution (line-change impact: zero).

Validation and testing results are not captured in detail: test_totals show zero tests run and test_status is listed as not captured. Proof_level and transform_status are marked not captured. Repair_attempts are zero and there is no recorded build status in the stage details (build_status: not captured), so any required

## Migration Scope

- Source profile: Spring Boot 2.1 / Java 11
- Target profile: Spring Boot 2.7 / Java 11
- Included stages: 1
- Skipped earlier stages: none
- Excluded later stages: 2, 3, 4

## Stage-by-Stage Technical Details

### Stage 1: Spring Boot 2.1 / Java 11 to Spring Boot 2.7 / Java 11

| Metric | Value |
|---|---|
| Status | manifest_ready |
| Duration | 12m 13s |
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
| 2026-07-10T14:34:12.061459Z |  | Job Created | created | V2 migration job created. |
| 2026-07-10T14:34:12.131663Z | 1 | Stage Queued | queued | Stage 1 command manifest queued for real orchestrator execution. |
| 2026-07-10T14:34:12.200842Z | 1 | Stage Started | running | Stage 1 real orchestrator started. |
| 2026-07-10T14:34:12.241140Z | 1 | Command Started | running | Backend-owned orchestrator manifest launched. |
| 2026-07-10T14:34:12.315464Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T14:34:14.343633Z | 1 | Analysis Started | running | analysis phase started. |
| 2026-07-10T14:34:18.965947Z |  | Approval Mode Updated | updated | Auto Approval enabled. |
| 2026-07-10T14:43:10.681963Z | 1 | Analysis Completed | completed | analysis phase completed. |
| 2026-07-10T14:43:10.722923Z | 1 | Planning Started | running | planning phase started. |
| 2026-07-10T14:43:10.845696Z | 1 | Planning Completed | completed | planning phase completed. |
| 2026-07-10T14:43:10.892303Z | 1 | Assessment Started | running | assessment phase started. |
| 2026-07-10T14:43:10.926829Z | 1 | Assessment Completed | completed | assessment phase completed. |
| 2026-07-10T14:43:10.961429Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T14:43:11.379880Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T14:43:11.416311Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T14:43:11.459667Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T14:43:11.506696Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T14:43:11.556417Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T14:43:11.585649Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T14:43:11.619331Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T14:43:11.651516Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T14:43:11.686550Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T14:43:11.743627Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T14:43:11.798974Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-10T14:43:11.834606Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-10T14:43:11.880389Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-10T14:43:11.944424Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-10T14:43:11.991453Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-10T14:43:12.027311Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-10T14:43:12.062325Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-10T14:43:12.103720Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-10T14:43:12.139980Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-10T14:43:12.188456Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-10T14:43:12.236662Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-10T14:43:12.276250Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-10T14:43:12.334528Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-10T14:43:12.382471Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-10T14:43:12.428310Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-10T14:43:12.477953Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-10T14:43:12.521284Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-10T14:43:12.565252Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-10T14:43:12.612716Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-10T14:43:12.655991Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-10T14:43:12.705620Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-10T14:43:12.747162Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-10T14:43:12.809870Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-10T14:43:12.859244Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-10T14:43:12.937095Z | 1 | Approval Auto Approved | completed | Approval gate auto-approved because Auto Approval is enabled. |
| 2026-07-10T14:43:12.998475Z | 1 | Approval Started | running | Approval accepted; orchestrator resume process starting. |
| 2026-07-10T14:43:13.040883Z | 1 | Resume Started | running | Stage 1 real orchestrator resume started. |
| 2026-07-10T14:43:13.076019Z | 1 | Command Started | running | Backend-owned approval resume command launched. |
| 2026-07-10T14:43:13.174841Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T14:43:15.282208Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-10T14:43:15.317154Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T14:43:15.358186Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T14:43:15.392800Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-10T14:43:15.448036Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T14:43:15.908825Z | 1 | Approval Completed | completed | Human approval phase complete; sandbox transform has started. |
| 2026-07-10T14:43:15.947577Z | 1 | Sandbox Transform Started | running | Sandbox transform started. |
| 2026-07-10T14:46:21.574142Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-10T14:46:21.614337Z | 1 | Stage Report Started | running | Final report generation started. |
| 2026-07-10T14:46:21.648164Z | 1 | Stage Report Completed | completed | Final report written. |
| 2026-07-10T14:46:22.101044Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T14:46:22.152520Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T14:46:22.204210Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T14:46:22.258424Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T14:46:22.320554Z | 1 | Artifact Written | completed | Artifact written: approval_decision |
| 2026-07-10T14:46:22.368831Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T14:46:22.418757Z | 1 | Artifact Written | completed | Artifact written: approved_plan_lock |
| 2026-07-10T14:46:22.469084Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T14:46:22.513152Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T14:46:22.559230Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T14:46:22.605552Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T14:46:22.653523Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T14:46:22.690836Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-10T14:46:22.735089Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-10T14:46:22.784782Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-10T14:46:22.832335Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_request |
| 2026-07-10T14:46:22.878305Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_response |
| 2026-07-10T14:46:22.939618Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-10T14:46:22.987838Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-10T14:46:23.031816Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_report |
| 2026-07-10T14:46:23.091501Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_summary |
| 2026-07-10T14:46:23.150928Z | 1 | Artifact Written | completed | Artifact written: dependency_repair_plan |
| 2026-07-10T14:46:23.198388Z | 1 | Artifact Written | completed | Artifact written: migration_ledger |
| 2026-07-10T14:46:23.248206Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-10T14:46:23.293359Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-10T14:46:23.340454Z | 1 | Artifact Written | completed | Artifact written: openrewrite_plugin_xml |
| 2026-07-10T14:46:23.398451Z | 1 | Artifact Written | completed | Artifact written: orchestration_summary |
| 2026-07-10T14:46:23.464809Z | 1 | Artifact Written | completed | Artifact written: phase2_log |
| 2026-07-10T14:46:23.509109Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-10T14:46:23.571912Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-10T14:46:23.623321Z | 1 | Artifact Written | completed | Artifact written: policy_patch_plan |
| 2026-07-10T14:46:23.663399Z | 1 | Artifact Written | completed | Artifact written: policy_patch_result |
| 2026-07-10T14:46:23.704944Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_log |
| 2026-07-10T14:46:23.758592Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_report |
| 2026-07-10T14:46:23.805681Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_summary |
| 2026-07-10T14:46:23.871061Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-10T14:46:23.927384Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-10T14:46:23.984380Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-10T14:46:24.045643Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-10T14:46:24.097597Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-10T14:46:24.149521Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-10T14:46:24.201423Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-10T14:46:24.259439Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-10T14:46:24.303760Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-10T14:46:24.353785Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-10T14:46:24.397300Z | 1 | Artifact Written | completed | Artifact written: sandbox |
| 2026-07-10T14:46:24.443588Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-10T14:46:24.479826Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-10T14:46:24.540503Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-10T14:46:24.600951Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-10T14:46:24.667465Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-10T14:46:24.723547Z | 1 | Artifact Written | completed | Artifact written: timing_report |
| 2026-07-10T14:46:24.774121Z | 1 | Artifact Written | completed | Artifact written: timing_summary |
| 2026-07-10T14:46:24.830529Z | 1 | Artifact Written | completed | Artifact written: transformation_execution_plan |
| 2026-07-10T14:46:24.871761Z | 1 | Artifact Written | completed | Stage sandbox output registered. |
| 2026-07-10T14:46:24.930915Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-10T14:46:24.986531Z | 1 | Build Completed | completed | Sandbox build completed. |
| 2026-07-10T14:46:25.030472Z | 1 | Test Completed | completed | Sandbox tests accepted with status: PASS_WITH_WARNINGS. |
| 2026-07-10T14:46:25.092493Z | 1 | Proof Updated | completed | Orchestrator result parsed into deterministic evidence. |
| 2026-07-10T14:46:25.135109Z | 1 | Stage Completed | completed | Stage 1 real orchestrator completed. |
| 2026-07-10T14:46:25.187940Z | 1 | Stage Report Started | running | Stage 1 report started. |
| 2026-07-10T14:46:25.241848Z | 1 | Stage Report Completed | completed | Stage 1 report completed. |
| 2026-07-10T14:46:25.288213Z | 1 | Migration Completed | completed | Selected target profile 'springboot-2.7-java11' reached. Migration completed. |

## Event Coverage

| Event Type | Count |
|---|---|
| Analysis Completed | 1 |
| Analysis Started | 1 |
| Approval Auto Approved | 1 |
| Approval Blocked | 2 |
| Approval Completed | 3 |
| Approval Mode Updated | 1 |
| Approval Started | 3 |
| Artifact Written | 89 |
| Assessment Completed | 1 |
| Assessment Started | 1 |
| Build Completed | 1 |
| Command Started | 2 |
| Job Created | 1 |
| Migration Completed | 1 |
| Planning Completed | 1 |
| Planning Started | 1 |
| Process Started | 2 |
| Proof Updated | 1 |
| Resume Started | 1 |
| Sandbox Transform Completed | 2 |
| Sandbox Transform Started | 1 |
| Stage Completed | 1 |
| Stage Queued | 1 |
| Stage Report Completed | 2 |
| Stage Report Started | 2 |
| Stage Started | 1 |
| Stdout | 2 |
| Test Completed | 1 |

Console output events omitted from the narrative timeline: 2. Their aggregate count remains above.

## Report Provenance and Limitations

- Narrative generation: azure_openai (live_ok)
- Line metrics exclude binary files, generated build output, dependency caches, and files larger than 5 MiB.
- LLM narrative is advisory; deterministic metrics and persisted stage evidence are authoritative.
- The report describes sandbox migration execution and does not claim production deployment or production validation.

- Report generated at: 2026-07-10T14:50:39Z
- Migration job: 0497bf71e61f4d5dac20e9cede4c2322
