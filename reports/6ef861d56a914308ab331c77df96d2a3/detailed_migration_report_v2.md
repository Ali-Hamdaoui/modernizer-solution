# Detailed Migration Report

## Executive Summary

This migration moved the application from **Spring Boot 2.1 / Java 11** to **Spring Boot 2.7 / Java 11**.

| Metric | Value |
|---|---|
| Outcome | completed |
| Duration | 13m 12s |
| Migration stages | 1 |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Tests executed | 0 |
| Tests passed | 0 |
| Repair attempts | 0 |

## Migration Story

The migration began with a Stage 1 job created at 2026-07-09T23:25:11.119886Z. Stage 1 was queued and started immediately; the orchestrator launched and entered an analysis phase at 2026-07-09T23:25:13Z. Analysis completed at 2026-07-09T23:34:00Z and planning and assessment phases ran back-to-back, completing within seconds. The stage run finished at 2026-07-09T23:38:23.153216Z after a total recorded duration of ~792 seconds (started 23:25:11.181809Z, completed 23:38:23.153216Z).

Technical work during Stage 1 focused on analysis, planning, and producing migration artifacts rather than on source edits. The process generated the analysis, assessment, dependency, and plan artifacts (examples: analysis_report, assessment_report, dependency_graph, target_dependency_plan, migration_plan.yaml, rewrite_preview and rewrite_patch). A sandbox transform step was executed and completed (sandbox_transform started 23:34:06.683936Z, completed 23:38:18.407528Z), indicating code-change previews and rewrite artifacts were produced, but the recorded change metrics show files_changed: 0 and zero lines added/changed/deleted.

Validation outcomes and approvals are recorded in the timeline. Auto Approval was enabled at 23:25:19.730321Z, and the approval gate was auto-approved shortly after artifact production; multiple human approval events were recorded (two approval_blocked entries and three approval_completed entries), with an approval decision recorded and the human approval phase completing before the sandbox transform started. Artifacts capturing these decisions were written (approval_request.json, approval_decision, approved_plan_lock).

Testing and build outcomes are not captured in the supplied evidence: test_totals report zero tests run and test_status is listed as "not captured"; build_status and proof_level are also "not captured". Repair attempts are recorded as 0. In short, the run produced planning and rewrite artifacts and passed the recorded approval gating, but there is no captured evidence of executed source changes, builds, or test validation in this dataset.

Line-change impact and risk: the summary and stage change metrics both report zero files and zero lines changed, so no direct code modifications were applied in this Stage 1 run. The rewrite_preview and rewrite_patch artifacts exist (indicating proposed edits were generated), but the evidence shows they were produced as artifacts rather than applied. Required downstream actions (not captured here) would be human review and gated application of the proposed rewrite

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
| Duration | 13m 12s |
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
| 2026-07-09T23:25:11.119886Z |  | Job Created | created | V2 migration job created. |
| 2026-07-09T23:25:11.181809Z | 1 | Stage Queued | queued | Stage 1 command manifest queued for real orchestrator execution. |
| 2026-07-09T23:25:11.265503Z | 1 | Stage Started | running | Stage 1 real orchestrator started. |
| 2026-07-09T23:25:11.331596Z | 1 | Command Started | running | Backend-owned orchestrator manifest launched. |
| 2026-07-09T23:25:11.451236Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-09T23:25:13.427560Z | 1 | Analysis Started | running | analysis phase started. |
| 2026-07-09T23:25:19.730321Z |  | Approval Mode Updated | updated | Auto Approval enabled. |
| 2026-07-09T23:34:00.329268Z | 1 | Analysis Completed | completed | analysis phase completed. |
| 2026-07-09T23:34:00.386683Z | 1 | Planning Started | running | planning phase started. |
| 2026-07-09T23:34:00.624375Z | 1 | Planning Completed | completed | planning phase completed. |
| 2026-07-09T23:34:00.741752Z | 1 | Assessment Started | running | assessment phase started. |
| 2026-07-09T23:34:00.833873Z | 1 | Assessment Completed | completed | assessment phase completed. |
| 2026-07-09T23:34:00.927944Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-09T23:34:01.467138Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-09T23:34:01.500826Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-09T23:34:01.536050Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-09T23:34:01.587971Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-09T23:34:01.670673Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-09T23:34:01.731822Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-09T23:34:01.789609Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-09T23:34:01.849466Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-09T23:34:01.907325Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-09T23:34:01.951745Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-09T23:34:02.007601Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-09T23:34:02.061356Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-09T23:34:02.114607Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-09T23:34:02.183008Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-09T23:34:02.228930Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-09T23:34:02.301381Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-09T23:34:02.359313Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-09T23:34:02.425969Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-09T23:34:02.487449Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-09T23:34:02.523216Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-09T23:34:02.576377Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-09T23:34:02.640488Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-09T23:34:02.698065Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-09T23:34:02.757646Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-09T23:34:02.827235Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-09T23:34:02.879374Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-09T23:34:02.930793Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-09T23:34:02.988519Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-09T23:34:03.036269Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-09T23:34:03.102496Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-09T23:34:03.161192Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-09T23:34:03.218509Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-09T23:34:03.280254Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-09T23:34:03.340387Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-09T23:34:03.464837Z | 1 | Approval Auto Approved | completed | Approval gate auto-approved because Auto Approval is enabled. |
| 2026-07-09T23:34:03.548514Z | 1 | Approval Started | running | Approval accepted; orchestrator resume process starting. |
| 2026-07-09T23:34:03.641315Z | 1 | Resume Started | running | Stage 1 real orchestrator resume started. |
| 2026-07-09T23:34:03.754263Z | 1 | Command Started | running | Backend-owned approval resume command launched. |
| 2026-07-09T23:34:03.976596Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-09T23:34:06.048737Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-09T23:34:06.108101Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-09T23:34:06.162160Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-09T23:34:06.230518Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-09T23:34:06.285894Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-09T23:34:06.633990Z | 1 | Approval Completed | completed | Human approval phase complete; sandbox transform has started. |
| 2026-07-09T23:34:06.683936Z | 1 | Sandbox Transform Started | running | Sandbox transform started. |
| 2026-07-09T23:38:18.407528Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-09T23:38:18.460994Z | 1 | Stage Report Started | running | Final report generation started. |
| 2026-07-09T23:38:18.505504Z | 1 | Stage Report Completed | completed | Final report written. |
| 2026-07-09T23:38:18.995174Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-09T23:38:19.054185Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-09T23:38:19.118934Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-09T23:38:19.182892Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-09T23:38:19.242469Z | 1 | Artifact Written | completed | Artifact written: approval_decision |
| 2026-07-09T23:38:19.305829Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-09T23:38:19.349186Z | 1 | Artifact Written | completed | Artifact written: approved_plan_lock |
| 2026-07-09T23:38:19.408951Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-09T23:38:19.468935Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-09T23:38:19.525326Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-09T23:38:19.563793Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-09T23:38:19.626027Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-09T23:38:19.693126Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-09T23:38:19.750446Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-09T23:38:19.802362Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-09T23:38:19.856683Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_request |
| 2026-07-09T23:38:19.950719Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_response |
| 2026-07-09T23:38:20.014986Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-09T23:38:20.068636Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-09T23:38:20.139041Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_report |
| 2026-07-09T23:38:20.198996Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_summary |
| 2026-07-09T23:38:20.256358Z | 1 | Artifact Written | completed | Artifact written: dependency_repair_plan |
| 2026-07-09T23:38:20.316290Z | 1 | Artifact Written | completed | Artifact written: migration_ledger |
| 2026-07-09T23:38:20.372914Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-09T23:38:20.440014Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-09T23:38:20.496996Z | 1 | Artifact Written | completed | Artifact written: openrewrite_plugin_xml |
| 2026-07-09T23:38:20.571961Z | 1 | Artifact Written | completed | Artifact written: orchestration_summary |
| 2026-07-09T23:38:20.631743Z | 1 | Artifact Written | completed | Artifact written: phase2_log |
| 2026-07-09T23:38:20.680489Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-09T23:38:20.744250Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-09T23:38:20.802084Z | 1 | Artifact Written | completed | Artifact written: policy_patch_plan |
| 2026-07-09T23:38:20.879154Z | 1 | Artifact Written | completed | Artifact written: policy_patch_result |
| 2026-07-09T23:38:20.938356Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_log |
| 2026-07-09T23:38:21.005652Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_report |
| 2026-07-09T23:38:21.061977Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_summary |
| 2026-07-09T23:38:21.125531Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-09T23:38:21.194988Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-09T23:38:21.253149Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-09T23:38:21.323141Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-09T23:38:21.376906Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-09T23:38:21.436628Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-09T23:38:21.503044Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-09T23:38:21.560025Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-09T23:38:21.613733Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-09T23:38:21.675804Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-09T23:38:21.735753Z | 1 | Artifact Written | completed | Artifact written: sandbox |
| 2026-07-09T23:38:21.790903Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-09T23:38:21.848534Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-09T23:38:21.899884Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-09T23:38:21.950627Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-09T23:38:22.005923Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-09T23:38:22.066750Z | 1 | Artifact Written | completed | Artifact written: timing_report |
| 2026-07-09T23:38:22.125494Z | 1 | Artifact Written | completed | Artifact written: timing_summary |
| 2026-07-09T23:38:22.181404Z | 1 | Artifact Written | completed | Artifact written: transformation_execution_plan |
| 2026-07-09T23:38:22.248846Z | 1 | Artifact Written | completed | Stage sandbox output registered. |
| 2026-07-09T23:38:22.306958Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-09T23:38:22.363917Z | 1 | Build Completed | completed | Sandbox build completed. |
| 2026-07-09T23:38:22.416906Z | 1 | Test Completed | completed | Sandbox tests accepted with status: PASS_WITH_WARNINGS. |
| 2026-07-09T23:38:22.741909Z | 1 | Proof Updated | completed | Orchestrator result parsed into deterministic evidence. |
| 2026-07-09T23:38:22.812572Z | 1 | Stage Completed | completed | Stage 1 real orchestrator completed. |
| 2026-07-09T23:38:23.049281Z | 1 | Stage Report Started | running | Stage 1 report started. |
| 2026-07-09T23:38:23.103952Z | 1 | Stage Report Completed | completed | Stage 1 report completed. |
| 2026-07-09T23:38:23.153216Z | 1 | Migration Completed | completed | Selected target profile 'springboot-2.7-java11' reached. Migration completed. |

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

- Report generated at: 2026-07-10T00:26:05Z
- Migration job: 6ef861d56a914308ab331c77df96d2a3
