# How To Run

Commands assume the repository root is:

```powershell
C:\Users\abdelilah.mortaki\Desktop\modernizer-solution
```

Do not run these against production paths. Use a modernized output directory dedicated to run artifacts.

The validated V1 path is build/test-only and two-stage. Do not use a direct `springboot-2.1.6-to-3.5-java17-v1-build-only` profile; it does not exist. Do not apply `springboot-2.7-to-3.5-java17` directly to the original Spring Boot `2.1.6.RELEASE` app.

## Run Tests

```powershell
py -m pytest -q
```

## Current V1 Terminal Environment

```powershell
cd C:\Users\abdelilah.mortaki\Desktop\modernizer-solution
git switch copilotfull-integration

$env:PYTHONPATH = "."
$env:JAVA_HOME = "C:\Program Files\Java\jdk-21.0.10"
$env:MAVEN_CMD = "C:\Tools\apache-maven-3.9.15\bin\mvn.cmd"
$env:Path = "$env:JAVA_HOME\bin;C:\Tools\apache-maven-3.9.15\bin;$env:Path"

$env:AI_MIGRATION_COPILOT_FAILURE_AGENT_ENABLED = "true"
$env:AI_MIGRATION_COPILOT_REQUIRED = "true"
$env:AI_MIGRATION_COPILOT_PROVIDER = "copilot_cli"
$env:AI_MIGRATION_COPILOT_MODEL = "gpt-5-mini"
$env:AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS = "false"

$env:AI_MIGRATION_H2_STARTUP_REQUIRED = "false"
$env:AI_MIGRATION_SKIP_ENDPOINT_SMOKE = "true"
$env:AI_MIGRATION_PROOF_LEVEL = "build_test_verified"

$legacy = "C:\Users\abdelilah.mortaki\Desktop\MSA-translation-service-msa-test-1.34\MSA-translation-service-msa-test-1.34"
$modernizedStage1 = "C:\Users\abdelilah.mortaki\Desktop\modernized-app-copilotfull-v1-stage1"
$modernizedStage2 = "C:\Users\abdelilah.mortaki\Desktop\modernized-app-copilotfull-v1-stage2"
$aihub = "C:\Users\abdelilah.mortaki\Desktop\modernizer-solution\modernizer-solution-ai-hub"

$profileStage1 = "springboot-2.1.6-to-2.7-java11"
$profileStage2 = "springboot-2.7-to-3.5-java17"
```

## Run Read-Only Assessment

```powershell
py -m migration_factory.orchestrator.runner `
  --run-id run-001 `
  --legacy C:\path\to\legacy-app `
  --modernized C:\path\to\modernized-output `
  --ai-hub C:\Users\abdelilah.mortaki\Desktop\modernizer-solution\modernizer-solution-ai-hub `
  --profile springboot-2.7-to-3.5-java17 `
  --mode read_only_assessment
```

Expected:

- Writes analysis/planning/assessment artifacts under `.migration/runs/run-001/`.
- Stops at human approval interrupt.
- Does not transform source.

## Run Full Sandbox Migration To Approval Interrupt

```powershell
py -m migration_factory.orchestrator.runner `
  --run-id run-001 `
  --legacy C:\path\to\legacy-app `
  --modernized C:\path\to\modernized-output `
  --ai-hub C:\Users\abdelilah.mortaki\Desktop\modernizer-solution\modernizer-solution-ai-hub `
  --profile springboot-2.7-to-3.5-java17 `
  --mode full_sandbox_migration
```

Expected:

- Same Phase 1 artifacts as read-only assessment.
- LangGraph interrupt returns `human_approval_required`.
- `orchestration/approval_interrupt_state.json` is written.

## Resume After Approval

The run directory is:

```text
<modernized-output>\.migration\runs\run-001
```

Resume approved:

```powershell
py -m migration_factory.orchestrator.resume `
  --run-id run-001 `
  --run-dir C:\path\to\modernized-output\.migration\runs\run-001 `
  --decision approved `
  --approved-by reviewer `
  --comments "approved for sandbox transform"
```

Resume rejected:

```powershell
py -m migration_factory.orchestrator.resume `
  --run-id run-001 `
  --run-dir C:\path\to\modernized-output\.migration\runs\run-001 `
  --decision rejected `
  --approved-by reviewer `
  --comments "not approved"
```

Resume with replan required:

```powershell
py -m migration_factory.orchestrator.resume `
  --run-id run-001 `
  --run-dir C:\path\to\modernized-output\.migration\runs\run-001 `
  --decision replan_required `
  --approved-by reviewer `
  --comments "revise plan"
```

## Guarded Sandbox Transform Env

Profiles with `production_allowed: false` require guarded sandbox override when source-changing transform is allowed by profile.

```powershell
$env:AI_MIGRATION_ALLOW_GUARDED_SANDBOX_TRANSFORM = "true"
```

Use this only for approved sandbox runs.

## Copilot Configuration

Disable phase assist:

```powershell
$env:AI_MIGRATION_COPILOT_ASSIST = "off"
```

Route to Copilot assist on failures:

```powershell
$env:AI_MIGRATION_COPILOT_ASSIST = "failures"
```

Generate optional final Copilot report:

```powershell
$env:AI_MIGRATION_ENABLE_COPILOT_REPORT = "true"
```

Use deterministic provider:

```powershell
$env:AI_MIGRATION_COPILOT_PROVIDER = "deterministic"
```

Use Copilot CLI provider:

```powershell
$env:AI_MIGRATION_COPILOT_PROVIDER = "copilot_cli"
$env:AI_MIGRATION_COPILOT_MODEL = "gpt-5-mini"
```

Enable Copilot documentation CLI adapter:

```powershell
$env:AI_MIGRATION_COPILOT_CLI_ENABLED = "true"
```

Do not write token values into docs or reports.

## JDK And Maven Environment

Useful env vars:

```powershell
$env:MAVEN_CMD = "C:\Tools\apache-maven-3.9.15\bin\mvn.cmd"
$env:JAVA_HOME = "C:\path\to\jdk"
```

Boot 4 profile includes:

```text
source_jdk_home_env: JAVA8_HOME
target_jdk_home_env: JAVA21_HOME
```

If using that profile:

```powershell
$env:JAVA8_HOME = "C:\path\to\jdk8"
$env:JAVA21_HOME = "C:\path\to\jdk21"
```

TODO/VERIFY: Stage A and Stage B profiles do not currently declare JDK env fields, so capture the actual JDK/Maven used in operator notes.

## Manual Agent Runs

Planning after analysis:

```powershell
py -m migration_factory.agents.planning_agent.runner `
  --run-id run-001 `
  --modernized C:\path\to\modernized-output `
  --legacy C:\path\to\legacy-app `
  --ai-hub C:\Users\abdelilah.mortaki\Desktop\modernizer-solution\modernizer-solution-ai-hub `
  --profile springboot-2.7-to-3.5-java17
```

Assessment after planning:

```powershell
py -m migration_factory.assessment.runner `
  --run-id run-001 `
  --modernized C:\path\to\modernized-output
```

Build Agent manual validation:

```powershell
py -m migration_factory.agents.build_agent C:\path\to\sandbox --timeout 120
```

Build Agent with ledger:

```powershell
py -m migration_factory.agents.build_agent C:\path\to\sandbox `
  --ledger-file C:\path\to\sandbox\.migration\ledger.json
```

## Staged Spring Migration Run Order

Recommended staged order:

1. Stage A profile: `springboot-2.1.6-to-2.7-java11`
2. Stage B profile: `springboot-2.7-to-3.5-java17`
3. Optional Stage C profile: `springboot-3.5-java17-to-java21`

Each stage should use a separate run id and preserve prior stage evidence.

Validated V1 Stage 1 run:

```powershell
$runId1 = "v1-stage1-216-to-27-watchonly-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$runDir1 = Join-Path $modernizedStage1 ".migration\runs\$runId1"

py -m migration_factory.orchestrator.runner `
  --run-id $runId1 `
  --legacy $legacy `
  --modernized $modernizedStage1 `
  --ai-hub $aihub `
  --profile $profileStage1 `
  --mode full_sandbox_migration

py -m migration_factory.orchestrator.resume `
  --run-id $runId1 `
  --run-dir $runDir1 `
  --decision approved `
  --approved-by manual-v1-build-only `
  --comments "Approved Stage 1 Boot 2.1.6 to 2.7 Java 11 sandbox migration; runtime/H2 non-blocking."
```

Validated V1 Stage 2 run:

```powershell
$stage2Legacy = "$runDir1\workspaces\sandbox"
$runId2 = "v1-stage2-27-to-35-watchonly-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$runDir2 = Join-Path $modernizedStage2 ".migration\runs\$runId2"

py -m migration_factory.orchestrator.runner `
  --run-id $runId2 `
  --legacy $stage2Legacy `
  --modernized $modernizedStage2 `
  --ai-hub $aihub `
  --profile $profileStage2 `
  --mode full_sandbox_migration

py -m migration_factory.orchestrator.resume `
  --run-id $runId2 `
  --run-dir $runDir2 `
  --decision approved `
  --approved-by manual-v1-build-only `
  --comments "Approved Stage 2 Boot 2.7 to 3.5 Java 17 sandbox migration; runtime/H2 non-blocking."
```

Final V1 verification:

```powershell
cd "$runDir2\workspaces\sandbox"
& $env:MAVEN_CMD clean test -DskipITs
```

Validated run ids:

- Stage 1: `v1-stage1-216-to-27-watchonly-20260602-233409`
- Stage 2: `v1-stage2-27-to-35-watchonly-20260602-233720`

## Runtime Smoke Notes

Current factory does not have a runtime smoke agent, and runtime/H2 was intentionally not tested for the V1 verdict. If runtime evidence is collected manually in V2, record:

- JDK used.
- Maven command or IDE run config.
- Active Spring profiles.
- Overrides such as H2 datasource and `spring.sql.init.mode=never`.
- Startup logs.
- Endpoint results.
- Security env warnings such as keystore/JWT missing secrets.

Current V2 runtime/H2 finding:

- H2 smoke config injection with `spring.config.additional-location` worked after a path fix.
- H2 startup still fails due to `common-utils` runtime config.
- Missing key: `caching.time-out`.
- Running profile `test` fails earlier because `config/application-test.yml` contains invalid `spring.profiles.active` in a profile-specific resource.
