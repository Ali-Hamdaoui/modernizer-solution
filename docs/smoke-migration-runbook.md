# Smoke Migration Runbook

## Purpose

Use this runbook for a small local demo of the governed sandbox migration flow. Recommended first trial: a small Spring Boot 2.7 / Java 11 Maven app.

## Local Prerequisites

You need:

* Python environment with this repo dependencies installed
* Maven on `PATH`
* JDKs needed by the selected profile
* For the multi-hop Boot 2.1 profile, set:
  * `JAVA_HOME_11`
  * `JAVA_HOME_17`

Recommended first profile:

* `springboot-2.7-to-3.5-java17`

Use the multi-hop Boot 2.1 profile only after the first smoke pass is stable:

* `springboot-2.1-to-3.5-java17`

## First Smoke Run

From the repo root:

```powershell
.\scripts\run_smoke_migration.ps1 `
  -LegacyApp C:\path\to\legacy-app `
  -ModernizedApp C:\path\to\modernized-app
```

With an explicit profile and run id:

```powershell
.\scripts\run_smoke_migration.ps1 `
  -LegacyApp C:\path\to\legacy-app `
  -ModernizedApp C:\path\to\modernized-app `
  -Profile springboot-2.7-to-3.5-java17 `
  -RunId demo-run-001
```

The script:

* sets `PYTHONPATH=.`
* prints the resolved run directory
* runs `python -m migration_factory.orchestrator.runner --mode full_sandbox_migration`
* stops after the approval interrupt by default
* does not auto-approve unless you explicitly pass `-ApproveAndResume`

## Raw CLI Commands

Initial orchestration:

```powershell
$env:PYTHONPATH="."
python -m migration_factory.orchestrator.runner `
  --run-id demo-run-001 `
  --legacy C:\path\to\legacy-app `
  --modernized C:\path\to\modernized-app `
  --ai-hub C:\path\to\modernizer-solution-ai-hub `
  --profile springboot-2.7-to-3.5-java17 `
  --mode full_sandbox_migration
```

Approval resume after review:

```powershell
$env:PYTHONPATH="."
python -m migration_factory.orchestrator.resume `
  --run-id demo-run-001 `
  --run-dir C:\path\to\modernized-app\.migration\runs\demo-run-001 `
  --decision approved `
  --approved-by your-name
```

One-shot helper with explicit approval resume:

```powershell
.\scripts\run_smoke_migration.ps1 `
  -LegacyApp C:\path\to\legacy-app `
  -ModernizedApp C:\path\to\modernized-app `
  -RunId demo-run-001 `
  -ApprovedBy your-name `
  -ApproveAndResume
```

## Artifact Review

Before approval, review at least:

* `analysis/analysis_report.json`
* `planning/migration_plan.yaml`
* `planning/migration_units.yaml`
* `planning/approval_request.json`
* `assessment/assessment_report.json`

After approval and sandbox execution, also review:

* `transformation/transformation_execution_plan.yaml`
* `workspaces/sandbox/.migration/ledger.json`
* `final/migration_report.json`

## Expected Outputs

For a normal smoke run, expect artifacts under:

```text
<modernized-app>\.migration\runs\<run-id>\
```

Key outputs:

* analysis report
  * `analysis/analysis_report.json`
* migration plan
  * `planning/migration_plan.yaml`
* migration units
  * `planning/migration_units.yaml`
* approval request
  * `planning/approval_request.json`
* assessment report
  * `assessment/assessment_report.json`
* transformation execution plan
  * `transformation/transformation_execution_plan.yaml`
* ledger
  * `workspaces/sandbox/.migration/ledger.json`
* final report
  * `final/migration_report.json`

## Troubleshooting

### Maven dependency resolution failure

Check:

* network access to your artifact repositories
* Maven settings and mirrors
* whether the legacy app builds locally before migration

### Missing JDK env vars

If using the Boot 2.1 multi-hop profile, verify:

```powershell
$env:JAVA_HOME_11
$env:JAVA_HOME_17
```

If either is empty, export it before rerunning.

### OpenRewrite blocked by policy

This is expected outside approved sandbox execution. Check:

* approval decision exists and is `approved`
* approved plan lock exists
* execution is using the sandbox workspace under `workspaces/sandbox`
* the selected flow is the approved sandbox resume flow, not a direct source apply

### Build/test failures after transformation

Review:

* `workspaces/sandbox/.migration/ledger.json`
* build logs under the run directory
* post-transform test artifacts
* the blocked migration unit and its recorded transformations

If needed, rerun with a fresh `RunId` after adjusting project prerequisites or dependency issues.
