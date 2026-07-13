# Detailed Migration Report

## Executive Summary

This migration moved the application from **Spring Boot 2.1 / Java 11** to **Spring Boot 2.7 / Java 11**.

### Key Metrics

| Metric | Value |
|---|---|
| Outcome | completed |
| Duration | 9m 5s |
| Migration stages | 1 |
| Files changed | 0 |
| Lines added | 0 |
| Lines deleted | 0 |
| Total lines changed | 0 |
| Tests executed | 0 |
| Tests passed | 0 |
| Repair attempts | 0 |

## Migration Story

The migration focused on a single included unit: an automated Stage 1 transition from the project's detected source profile "Spring Boot 2.1 / Java 11" toward the target profile "Spring Boot 2.7 / Java 11". The run explicitly excluded Stages 2–4, so the delivered work and artifacts are scoped to the initial planning, analysis, assessment, and sandbox transform for that first stage. The job was created and queued on 2026-07-10T15:13:54.934334Z and Stage 1 started immediately thereafter.

Stage 1 began with an analysis phase that completed within the first several minutes; planning and assessment phases then completed in rapid succession. The system produced a broad set of artifacts during these phases — analysis_report, assessment_report, dependency_graph, target_dependency_plan, migration_plan.yaml, rewrite_preview, rewrite_patch, rewrite_impact_summary, and multiple summaries and inventories — which collectively capture the detected state, recommended changes, and an automated rewrite dry-run. The analysis and planning outputs were written before the approval gate was reached.

Operationally the approval flow recorded both an auto-approval enablement and subsequent human approval activity. Auto Approval was enabled early in the run, and the approval gate was auto-approved; the timeline also records multiple human approval decisions being recorded and completed. After approvals were recorded, the orchestrator resumed and a sandbox transform was started and completed; sandbox transform completed at 2026-07-10T15:22:55.957768Z. Final report generation and a stage report were produced immediately after the transform.

Despite the sandbox transform, measured line- and file-level impact for this migration is zero: files_changed 0, lines_added 0, lines_changed 0, lines_deleted 0. The rewrite artifacts (rewrite_dry_run.patch, rewrite_patch, rewrite_preview) were generated and saved as evidence of proposed edits, but no on-repo changes are recorded by this run. Repair attempts are zero and no repair actions were required or executed during Stage 1.

Validation outcomes are partially recorded: planning, assessment, and artifact generation completed successfully and a final stage report was written. Test execution and build status are not captured in the evidence (test_totals show zero tests and build_status is "not captured"), and proof_level and transform_status fields are also "not captured." These gaps mean there is no recorded test pass/fail signal or verified build result from this run.

Remaining limitations and next considerations are therefore explicit in the evidence: Stage 1 has produced a complete set of analysis and plan artifacts and a successful sandbox transform, but there is no captured result for builds or tests, no recorded

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
| Duration | 9m 5s |
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
| 2026-07-10T15:13:54.934334Z |  | Job Created | created | V2 migration job created. |
| 2026-07-10T15:13:54.969762Z | 1 | Stage Queued | queued | Stage 1 command manifest queued for real orchestrator execution. |
| 2026-07-10T15:13:55.022473Z | 1 | Stage Started | running | Stage 1 real orchestrator started. |
| 2026-07-10T15:13:55.066022Z | 1 | Command Started | running | Backend-owned orchestrator manifest launched. |
| 2026-07-10T15:13:55.142894Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T15:13:56.595002Z | 1 | Analysis Started | running | analysis phase started. |
| 2026-07-10T15:14:00.257969Z |  | Approval Mode Updated | updated | Auto Approval enabled. |
| 2026-07-10T15:20:02.204962Z | 1 | Analysis Completed | completed | analysis phase completed. |
| 2026-07-10T15:20:02.237564Z | 1 | Planning Started | running | planning phase started. |
| 2026-07-10T15:20:02.337803Z | 1 | Planning Completed | completed | planning phase completed. |
| 2026-07-10T15:20:02.394712Z | 1 | Assessment Started | running | assessment phase started. |
| 2026-07-10T15:20:02.454717Z | 1 | Assessment Completed | completed | assessment phase completed. |
| 2026-07-10T15:20:02.491847Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T15:20:02.929559Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T15:20:02.980657Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T15:20:03.012944Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T15:20:03.050225Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T15:20:03.092352Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T15:20:03.128712Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T15:20:03.166892Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T15:20:03.205055Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T15:20:03.231742Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T15:20:03.277300Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T15:20:03.315658Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-10T15:20:03.360071Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-10T15:20:03.398320Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-10T15:20:03.440724Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-10T15:20:03.480265Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-10T15:20:03.516879Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-10T15:20:03.559220Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-10T15:20:03.602304Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-10T15:20:03.641165Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-10T15:20:03.692426Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-10T15:20:03.728924Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-10T15:20:03.765415Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-10T15:20:03.798287Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-10T15:20:03.848249Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-10T15:20:03.882371Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-10T15:20:03.921981Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-10T15:20:03.966660Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-10T15:20:04.007779Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-10T15:20:04.046331Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-10T15:20:04.094086Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-10T15:20:04.129886Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-10T15:20:04.167167Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-10T15:20:04.226922Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-10T15:20:04.265257Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-10T15:20:04.373484Z | 1 | Approval Auto Approved | completed | Approval gate auto-approved because Auto Approval is enabled. |
| 2026-07-10T15:20:04.436193Z | 1 | Approval Started | running | Approval accepted; orchestrator resume process starting. |
| 2026-07-10T15:20:04.540690Z | 1 | Resume Started | running | Stage 1 real orchestrator resume started. |
| 2026-07-10T15:20:04.586774Z | 1 | Command Started | running | Backend-owned approval resume command launched. |
| 2026-07-10T15:20:04.707661Z | 1 | Process Started | running | Orchestrator subprocess is running. |
| 2026-07-10T15:20:06.292030Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-10T15:20:06.328546Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T15:20:06.366952Z | 1 | Approval Blocked | blocked | Human approval required. |
| 2026-07-10T15:20:06.401473Z | 1 | Approval Started | running | Recording approval decision. |
| 2026-07-10T15:20:06.434652Z | 1 | Approval Completed | completed | Approval decision recorded. |
| 2026-07-10T15:20:06.794212Z | 1 | Approval Completed | completed | Human approval phase complete; sandbox transform has started. |
| 2026-07-10T15:20:06.836103Z | 1 | Sandbox Transform Started | running | Sandbox transform started. |
| 2026-07-10T15:22:55.957768Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-10T15:22:55.999914Z | 1 | Stage Report Started | running | Final report generation started. |
| 2026-07-10T15:22:56.038897Z | 1 | Stage Report Completed | completed | Final report written. |
| 2026-07-10T15:22:56.454783Z | 1 | Artifact Written | completed | Artifact written: analysis_report |
| 2026-07-10T15:22:56.502340Z | 1 | Artifact Written | completed | Artifact written: analysis_report.json |
| 2026-07-10T15:22:56.573239Z | 1 | Artifact Written | completed | Artifact written: analysis_summary |
| 2026-07-10T15:22:56.625214Z | 1 | Artifact Written | completed | Artifact written: analysis_summary.md |
| 2026-07-10T15:22:56.666868Z | 1 | Artifact Written | completed | Artifact written: approval_decision |
| 2026-07-10T15:22:56.720748Z | 1 | Artifact Written | completed | Artifact written: approval_request.json |
| 2026-07-10T15:22:56.759323Z | 1 | Artifact Written | completed | Artifact written: approved_plan_lock |
| 2026-07-10T15:22:56.793588Z | 1 | Artifact Written | completed | Artifact written: assessment_report |
| 2026-07-10T15:22:56.840812Z | 1 | Artifact Written | completed | Artifact written: assessment_report.json |
| 2026-07-10T15:22:56.875913Z | 1 | Artifact Written | completed | Artifact written: assessment_summary |
| 2026-07-10T15:22:56.917650Z | 1 | Artifact Written | completed | Artifact written: assessment_summary.md |
| 2026-07-10T15:22:56.981326Z | 1 | Artifact Written | completed | Artifact written: config_inventory |
| 2026-07-10T15:22:57.027067Z | 1 | Artifact Written | completed | Artifact written: config_inventory.json |
| 2026-07-10T15:22:57.082692Z | 1 | Artifact Written | completed | Artifact written: copilot_assist |
| 2026-07-10T15:22:57.159454Z | 1 | Artifact Written | completed | Artifact written: copilot_assist.json |
| 2026-07-10T15:22:57.206053Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_request |
| 2026-07-10T15:22:57.249597Z | 1 | Artifact Written | completed | Artifact written: dependency_copilot_response |
| 2026-07-10T15:22:57.329232Z | 1 | Artifact Written | completed | Artifact written: dependency_graph |
| 2026-07-10T15:22:57.377700Z | 1 | Artifact Written | completed | Artifact written: dependency_graph.json |
| 2026-07-10T15:22:57.428476Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_report |
| 2026-07-10T15:22:57.471860Z | 1 | Artifact Written | completed | Artifact written: dependency_policy_summary |
| 2026-07-10T15:22:57.512438Z | 1 | Artifact Written | completed | Artifact written: dependency_repair_plan |
| 2026-07-10T15:22:57.556717Z | 1 | Artifact Written | completed | Artifact written: migration_ledger |
| 2026-07-10T15:22:57.610735Z | 1 | Artifact Written | completed | Artifact written: migration_plan.yaml |
| 2026-07-10T15:22:57.653739Z | 1 | Artifact Written | completed | Artifact written: migration_units.yaml |
| 2026-07-10T15:22:57.710982Z | 1 | Artifact Written | completed | Artifact written: openrewrite_plugin_xml |
| 2026-07-10T15:22:57.766202Z | 1 | Artifact Written | completed | Artifact written: orchestration_summary |
| 2026-07-10T15:22:57.811472Z | 1 | Artifact Written | completed | Artifact written: phase2_log |
| 2026-07-10T15:22:57.862451Z | 1 | Artifact Written | completed | Artifact written: plan_summary.md |
| 2026-07-10T15:22:57.936165Z | 1 | Artifact Written | completed | Artifact written: plan_validation_report.json |
| 2026-07-10T15:22:57.991234Z | 1 | Artifact Written | completed | Artifact written: policy_patch_plan |
| 2026-07-10T15:22:58.054207Z | 1 | Artifact Written | completed | Artifact written: policy_patch_result |
| 2026-07-10T15:22:58.111886Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_log |
| 2026-07-10T15:22:58.157994Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_report |
| 2026-07-10T15:22:58.204850Z | 1 | Artifact Written | completed | Artifact written: post_transform_test_summary |
| 2026-07-10T15:22:58.282730Z | 1 | Artifact Written | completed | Artifact written: read_only_verification |
| 2026-07-10T15:22:58.335300Z | 1 | Artifact Written | completed | Artifact written: read_only_verification.json |
| 2026-07-10T15:22:58.384575Z | 1 | Artifact Written | completed | Artifact written: rewrite_dry_run.patch |
| 2026-07-10T15:22:58.453828Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary |
| 2026-07-10T15:22:58.506682Z | 1 | Artifact Written | completed | Artifact written: rewrite_impact_summary.json |
| 2026-07-10T15:22:58.574751Z | 1 | Artifact Written | completed | Artifact written: rewrite_patch |
| 2026-07-10T15:22:58.623484Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan |
| 2026-07-10T15:22:58.689636Z | 1 | Artifact Written | completed | Artifact written: rewrite_plugin_plan.json |
| 2026-07-10T15:22:58.741272Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview |
| 2026-07-10T15:22:58.785890Z | 1 | Artifact Written | completed | Artifact written: rewrite_preview.json |
| 2026-07-10T15:22:58.848297Z | 1 | Artifact Written | completed | Artifact written: sandbox |
| 2026-07-10T15:22:58.919819Z | 1 | Artifact Written | completed | Artifact written: source_profile_detection |
| 2026-07-10T15:22:58.986021Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan |
| 2026-07-10T15:22:59.025434Z | 1 | Artifact Written | completed | Artifact written: target_dependency_plan.json |
| 2026-07-10T15:22:59.064859Z | 1 | Artifact Written | completed | Artifact written: test_inventory |
| 2026-07-10T15:22:59.113785Z | 1 | Artifact Written | completed | Artifact written: test_inventory.json |
| 2026-07-10T15:22:59.144230Z | 1 | Artifact Written | completed | Artifact written: timing_report |
| 2026-07-10T15:22:59.193884Z | 1 | Artifact Written | completed | Artifact written: timing_summary |
| 2026-07-10T15:22:59.243337Z | 1 | Artifact Written | completed | Artifact written: transformation_execution_plan |
| 2026-07-10T15:22:59.283062Z | 1 | Artifact Written | completed | Stage sandbox output registered. |
| 2026-07-10T15:22:59.311412Z | 1 | Sandbox Transform Completed | completed | Sandbox transform completed. |
| 2026-07-10T15:22:59.351242Z | 1 | Build Completed | completed | Sandbox build completed. |
| 2026-07-10T15:22:59.512793Z | 1 | Test Completed | completed | Sandbox tests accepted with status: PASS_WITH_WARNINGS. |
| 2026-07-10T15:22:59.605651Z | 1 | Proof Updated | completed | Orchestrator result parsed into deterministic evidence. |
| 2026-07-10T15:22:59.637407Z | 1 | Stage Completed | completed | Stage 1 real orchestrator completed. |
| 2026-07-10T15:22:59.679468Z | 1 | Stage Report Started | running | Stage 1 report started. |
| 2026-07-10T15:22:59.801209Z | 1 | Stage Report Completed | completed | Stage 1 report completed. |
| 2026-07-10T15:22:59.836372Z | 1 | Migration Completed | completed | Selected target profile 'springboot-2.7-java11' reached. Migration completed. |

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

- Report generated at: 2026-07-10T15:26:53Z
- Migration job: 7e0f11dd83a647fb88a3b72cbcd031ec
