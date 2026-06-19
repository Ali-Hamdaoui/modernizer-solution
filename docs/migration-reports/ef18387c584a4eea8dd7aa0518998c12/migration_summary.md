# Migration Summary

- Run ID: v2-ef18387c-s3
- Migration Duration: 248.429s
- Target Java: 21
- Target Spring Boot: 3.5
- Target Spring Framework: 6.2.18
- Risk Level: medium
- Strategy: java21_runtime_validation_only
- Fallback Profile: None
- Production Allowed: false
- Approval: approved
- Transform: TRANSFORM_APPLIED_IN_SANDBOX
- Build: BUILD_PASSED_IN_SANDBOX
- Test: PASS_WITH_WARNINGS
- Proof Level: compiled
- Repair Loop: NOT_IMPLEMENTED
- Dependency Policy: PASS
- Test Totals: tests=0 passed=0 failures=0 errors=0 skipped=0
- Executed Recipes: org.openrewrite.java.migrate.UpgradeToJava21
- Scope Limits: no production promotion, no PR creation, no deployment, no automatic merge

## Full Migration Summary

Migration completed with approval decision approved, transform status TRANSFORM_APPLIED_IN_SANDBOX, build status BUILD_PASSED_IN_SANDBOX, and test status PASS_WITH_WARNINGS. Elapsed duration: 248.429s. Primary change summary: Java changed from 17 to 21.

## What Changed

- Java changed from 17 to 21.
- Spring Boot remained at 3.5.
- Spring Framework changed from not_captured to 6.2.18.
- Executed OpenRewrite recipes: org.openrewrite.java.migrate.UpgradeToJava21.

## Validated

- sandbox transform applied
- Maven build passed

## Not Validated

- SQL Server production behavior
- production DB scripts
- endpoint/business behavior
- production secrets/JWT/keystore validity
- deployment
- PR creation/merge

POC-ready sandbox migration artifacts are captured under this run directory.

## Repair Loop

- Enabled: false
- Max Attempts: 3
- Attempts: 0
- Final Status: NOT_IMPLEMENTED
- Ledger: 
- Copilot Used: false
- Safe Patch Applied: false
- Human Review Required: false

## Dependency Policy

- Status: PASS
- Risks: 0
- Blockers: 0
- Copilot Advisory: SKIPPED
- Policy Patch Applied: false
- Report: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\assessment\dependency_policy_report.json

## Timing

- Total duration: 248.429s
- Timing report: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\performance\timing_report.json
- Timing summary: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\performance\timing_summary.md

## Related Artifacts

- approval_decision: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\approval\approval_decision.json
- approved_plan_lock: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\approval\approved_plan_lock.json
- transformation_execution_plan: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\transformation\transformation_execution_plan.yaml
- migration_ledger: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\workspaces\sandbox\.migration\ledger.json
- post_transform_test_report: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\test\post_transform\test_report.json
- orchestration_summary: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\orchestration\orchestration_summary.json
- timing_report: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\performance\timing_report.json
- timing_summary: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\performance\timing_summary.md
- final_migration_report: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\final\migration_report.json
- final_migration_summary: C:\Users\hamdaoui.ali\Downloads\MSA-COMMON-STG1\.migration\runs\v2-ef18387c-s3\final\migration_summary.md
