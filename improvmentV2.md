# Improvement V2 — AI Migration Control Tower

Status: product and technical planning only  
Branch/source inspected: `DEMO2` at `d4e0398`  
Generated: 2026-06-13  
Allowed change for this task: this document only  

## 1. Executive summary

V2 turns the AI Migration Control Tower into the real local migration cockpit. The product starts with a form, not a chatbot prompt. The user opens `New Migration`, pastes or enters the same local inputs they used in the old PowerShell flow, runs preflight, sees readiness, and starts when the backend says the local runner, AI Hub, pipeline route, JDKs, Maven, output parent, and legacy app marker are ready. Azure model readiness is shown clearly, but it is not a hard blocker for deterministic local migration start.

The user supplies local migration inputs:

- legacy app path
- output parent path
- run name
- `JAVA11_HOME`, `JAVA17_HOME`, `JAVA21_HOME`
- `MAVEN_CMD`
- local AI Hub path when not using the bundled backend path
- optional migration behavior flags

The product is fully local for now. In local operator mode, the frontend may accept local absolute paths for the legacy app path, output parent path, AI Hub path, `JAVA11_HOME`, `JAVA17_HOME`, `JAVA21_HOME`, and `MAVEN_CMD`. This preserves the exact terminal-style migration inputs without losing or breaking paths between the frontend and backend. The backend still validates every path before running anything.

The user does not paste Azure Foundry secrets or deployment IDs into `New Migration`. Azure Foundry configuration belongs in backend `.env`, backend settings, or an admin-only settings surface. The form may show model readiness, redacted deployment role labels, and health status only. If Azure health is false or errored, the migration may still continue through the deterministic local orchestrator flow; AI plan, repair, or chat help may be unavailable or degraded until model health recovers.

V2 keeps the backend as the source of truth:

```text
Next.js New Migration form
-> FastAPI setup/preflight API
-> Control Tower application services
-> persisted setup, readiness, job, stage, approval, action, model, context, proof state
-> backend-owned worker command manifests
-> migration_factory.orchestrator.runner/resume
-> LangGraph approval interrupt/persistence
-> Stage 1 -> Stage 2 -> Stage 3 automatic progression
-> sandbox-only OpenRewrite/Maven/repair execution
-> deterministic proof/report
```

Azure Foundry supplies model calls and structured outputs only. It does not own execution. The LLM proposes, explains, classifies, and critiques. The backend validates state, paths, policies, schemas, checksums, and readiness. The human approves exact checksums. The worker executes typed backend-owned commands. Maven/tests/proof artifacts are the technical truth.

The chatbot remains central after setup. It should explain the current stage, summarize evidence, diagnose failures, help the user write plan or repair instructions, and request pending typed actions. It cannot execute, approve, write files, choose raw paths, choose Maven goals, choose model deployments, change the route, change stages, or override proof. Chat instructions never rewrite the migration route or stage sequence. They create plan amendments, repair instructions, or pending actions that are validated against the locked pipeline and current stage state.

The orchestrator owns stage progression. The user does not manually start Stage 1, Stage 2, and Stage 3. `Start Migration` starts the parent job, then the backend queues Stage 1, resumes after approval, records proof, advances Stage 2 from Stage 1 sandbox, advances Stage 3 from Stage 2 sandbox, and generates the final proof/report when gates pass.

## 2. Current V1 reality from repo

### Already implemented V1 capabilities

Current code is broader than the older README/system docs imply.

- FastAPI app exists in `migration_factory/control_tower/adapters/fastapi/app.py`.
- Local-only API guardrails exist: the frontend default is `http://127.0.0.1:8000`, and API base URL validation rejects mixed `localhost`.
- Domain records exist for runner profiles, pipeline definitions, migration jobs, run configurations, stage runs, artifacts, events, audit records, command executions, stage chain ledger records, approvals, model invocations, context packs, privileged actions, plan amendments/revisions/reviews, repair records, patch policy records, sandbox snapshots, patch applications, Maven validations, rollbacks, proof gates, and proof reports.
- SQLite migrations `0001` through `0027` cover the M1/M2 foundation and V1 additions: locked route, stage-chain ledger, runner readiness, event type registry, model profiles, approvals, stage continuation policy, proof gates, model invocations, context packs, privileged actions, plan amendments/reviews, repairs, patch apply/validate/rollback, and proof reports.
- V1 route invariants are documented in `docs/full-implementation/00_IMPLEMENTATION_RULES.md`:
  - pipeline `springboot-216-to-356-java21-three-stage`
  - Stage 1: Boot `2.7.18`, Java `11`, JDK `java11`
  - Stage 2: Boot `3.5.6`, Java `17`, JDK `java17`, input from Stage 1 sandbox
  - Stage 3: Boot `3.5.6`, Java `21`, JDK `java21`, input from Stage 2 sandbox
  - Boot 4 excluded
  - browser/model cannot choose raw executable paths, Maven goals, shell commands, working dirs, or model deployments
  - LLM cannot execute, approve, write files, or create proof
- Application services include runner JDK/Maven readiness, stage command launch contracts, stage continuation policy, model invocation audit, context packs, plan amendments, fake-provider proposal flow, plan review gate, repair classification/proposals, privileged actions, patch policy, assistant tools, and deterministic proof.
- Tests under `tests/control_tower/*` cover the M1/M2 foundation and V1 features through proof/report APIs.
- Web tests under `web/control-tower/tests/*` cover panels for stage timeline, runner evidence, model activity, approvals/actions, repairs, assistant, proof/report, API contracts, and accessibility.

### Diagnostic/job-form limitations

Current UI still feels diagnostic/form-lite:

- `/jobs/new` renders `CreateDiagnosticJobForm`, copy says `Create foundation diagnostic job`, and the submit button says `Create foundation diagnostic job`.
- `web/control-tower/lib/contracts.ts` still exposes `CreateDiagnosticJobFormValues` and `CreateDiagnosticJobRequest`.
- `createDiagnosticJobPayload()` hard-codes `target_proof_level: "ANALYZED"`.
- The current form uses registered root selectors plus relative paths. It does not support pasting the local terminal env block.
- Current job page copy still says `Foundation diagnostic`.
- `StartDiagnosticJobButton` queues a diagnostic command.
- `CurrentRunClient` centers on command state, stdout/stderr windows, artifacts, public events, proof/report, repair, and approvals. It is useful evidence UI, but not yet a polished migration cockpit.
- Several UI panels intentionally have no input controls. That is correct for V1 safety, but V2 needs safe, typed input surfaces for setup, plan instructions, repair instructions, approval decisions, and pending actions.

### Local terminal/orchestrator capabilities

The old terminal flow is real and should be surfaced safely:

- `migration_factory/orchestrator/runner.py` accepts `--run-id`, `--legacy`, `--modernized`, `--ai-hub`, `--profile`, and `--mode`.
- `runner.py` supports `read_only_assessment` and `full_sandbox_migration`.
- `runner.py` builds initial state, invokes LangGraph, and returns `human_approval_required` when interrupted.
- `migration_factory/orchestrator/resume.py` accepts `--run-id`, `--run-dir`, `--decision`, `--approved-by`, and `--comments`.
- `resume.py` records approval decision, resumes LangGraph via `Command(resume=...)`, and can recover from `orchestration/approval_interrupt_state.json`.
- `migration_factory/orchestrator/graph.py` wires analysis, planning, assessment, approval, approval record, transform, build/test/final report, and optional Copilot assist paths.
- `docs/system/09-how-to-run.md` preserves the operator PowerShell flow, including `PYTHONPATH`, `MAVEN_CMD`, Java homes, Copilot flags, proof flags, stage profiles, runner, resume, and final Maven verification.
- Repo docs still contain older two-stage V1 notes and `3.5.14` references. For V2 planning, treat these as historical docs unless current V1 full-implementation rules/code/tests say otherwise.

### Azure/LLM gaps

- `v1_model_profiles` exists, but current FastAPI registration accepts `provider_kind` as `fake` or `azure_openai` and stores environment references. There is no verified live Azure Foundry health flow in the inspected code.
- Model proposal and repair endpoints still include fake-provider naming:
  - `/v1/plan-amendments/{amendment_id}/fake-provider-proposals`
  - `/v1/commands/{command_id}/fake-repair-proposals`
- Current model invocation audit exists, but V2 needs real Azure role health checks, structured output schema checks, model-call audit tied to roles, and clear AI capability status.
- Current assistant tool contracts are read-only. V2 needs assistant-driven pending action requests while preserving no direct execution.

### UI gaps

- New Migration must become a real setup page, not a diagnostic job selector.
- Start gating must combine local setup preflight, runner readiness, AI Hub readiness, pipeline route readiness, output parent readiness, and legacy app marker readiness. Azure model readiness is displayed as AI feature status, not a deterministic migration start blocker.
- The cockpit must show stage progress, decisions, model activity, pending actions, logs, evidence, repairs, proof, final report, and chat in one migration-native layout.
- The chatbot must accept user instructions and draft plan/repair/action requests. Current assistant panel streams read-only messages but does not provide a full chat composer or action request flow.

## 3. Target user experience

### Flow

```text
Open /migrations/new
-> Paste PowerShell env block or fill fields
-> Backend parses env block into typed fields
-> User reviews extracted local paths and flags
-> Run Preflight
-> Readiness panels update
-> Start Migration disabled until required local deterministic checks are READY
-> Start Migration creates parent job and queues Stage 1
-> Cockpit opens
-> Backend automatically advances Stage 1 -> Stage 2 -> Stage 3
-> Chatbot explains status, diagnoses failures, accepts repair instructions, and can request pending actions
-> Decision cards handle approvals/checksums/actions
-> Proof/report generated from deterministic evidence
```

### New Migration screen wireframe

```text
+-----------------------------------------------------------------------+
| New Migration                                                         |
| Run the same local migration flow from the Control Tower.              |
+-----------------------------+-----------------------------------------+
| Migration inputs            | Readiness                               |
| Run name [msa-v2-demo]      | Backend API              READY          |
| Legacy app path [...]       | Legacy app               READY          |
| Output parent path [...]    | Output parent            READY          |
| AI Hub path [...]           | AI Hub profiles/catalogs READY          |
|                             | JDK 11                   READY          |
| Paste PowerShell env block  | JDK 17                   READY          |
| [textarea]                  | JDK 21                   READY          |
| [Parse env block]           | Maven                    READY          |
|                             | Pipeline route           READY          |
| Extracted local tools       | Azure proposer           READY          |
| JAVA11_HOME [...]           | Azure reviewer           READY          |
| JAVA17_HOME [...]           | Assistant model          DEGRADED      |
| JAVA21_HOME [...]           | Fallback disabled        READY          |
| MAVEN_CMD [...]             | Structured outputs       READY          |
|                             |                                         |
| Optional flags              | [Run preflight] [Start Migration]       |
| [ ] Enable H2 smoke         | Azure errors warn, not block start.     |
| [ ] Skip endpoint smoke     |                                         |
+-----------------------------+-----------------------------------------+
```

### Cockpit screen wireframe

```text
+--------------------------------------------------------------------------------+
| Migration: msa-v2-demo                     READY | RUNNING | proof pending       |
+-------------------------------+------------------------------+-----------------+
| Stage timeline                 | Current work                 | Assistant       |
| 1 Boot 2.1.6 -> 2.7 Java 11   | LangGraph node: planning     | Chat messages   |
| 2 Boot 2.7 -> 3.5.6 Java 17   | Command: RUN_ORCHESTRATOR    | Tool evidence   |
| 3 Java 17 -> Java 21          | Model role: proposer         | Instruction box |
| Final proof/report             | Waiting on approval          | Request action  |
+-------------------------------+------------------------------+-----------------+
| Decision cards                                                                   |
| Plan approval: checksum sha256:...  [Approve exact checksum] [Reject] [Revise]    |
| Pending Maven validation: typed test, stage 2, checksum ... [Approve] [Reject]    |
+--------------------------------------------------------------------------------+
| Evidence tabs: Logs | Artifacts | Model calls | Context packs | Repairs | Proof |
+--------------------------------------------------------------------------------+
```

### UX rules

- The user never has to say “migrate this app” to the chatbot to begin. The user starts from the form, pastes terminal-style local config, and lets the backend parse and validate it.
- The chatbot is prominent after setup because migration work is conversational once evidence starts moving.
- The Start button has one clear rule: disabled until all required local deterministic readiness checks are `READY`.
- Azure `BLOCKED` or `ERROR` status warns that AI plan, repair, or chat help may be unavailable or degraded, but does not block deterministic migration start.
- All decisions show exact checksum, target, actor, expected version, and impact before approval.
- Stage transitions are automatic. The UI shows why a stage is blocked or queued but does not expose raw stage-start buttons for normal operation.
- Chatbot instructions cannot execute, approve, write files, change the route, or change the stage sequence.

## 4. New Migration form contract

### User inputs

This form is for local operator mode. It may accept local absolute paths for `legacy_app_path`, `output_parent_path`, `ai_hub_path`, `JAVA11_HOME`, `JAVA17_HOME`, `JAVA21_HOME`, and `MAVEN_CMD` so the Control Tower can preserve the operator's terminal-style inputs exactly. The browser still cannot choose commands, Maven goals, working directories, model deployments, or stage inputs. The backend validates path existence, type, containment policy, writability, checksums, and tool versions before any command is queued.

The form must accept these typed fields:

| Field | Required | Type | Notes |
| --- | --- | --- | --- |
| `run_name` | yes | string | Human-readable name and source for sanitized `run_id`. Reject shell metacharacters and path separators. |
| `legacy_app_path` | yes | local path string | User may paste absolute local path in local mode. Backend validates path exists and contains Maven/Gradle project. |
| `output_parent_path` | yes | local path string | Backend validates writable parent and creates stage output dirs. |
| `ai_hub_path` | yes | local absolute path string or backend default | Backend validates profiles/catalogs/policies. |
| `powershell_env_block` | optional | string | Multi-line paste parsed by backend. Never executed. |
| `JAVA11_HOME` | yes | local absolute path string | Can be parsed from env block or entered manually. Backend validates Java major 11. |
| `JAVA17_HOME` | yes | local absolute path string | Can be parsed from env block or entered manually. Backend validates Java major 17. |
| `JAVA21_HOME` | yes | local absolute path string | Can be parsed from env block or entered manually. Backend validates Java major 21. |
| `MAVEN_CMD` | yes | local absolute path string | Backend stores as command ref after validation. Browser cannot add goals. |
| `migration_flags` | optional | object | Typed booleans/enums only. No arbitrary env. |

Example paste block:

```powershell
$env:PYTHONPATH = "."
$env:JAVA11_HOME = "C:\Tools\jdk-11"
$env:JAVA17_HOME = "C:\Tools\jdk-17"
$env:JAVA21_HOME = "C:\Tools\jdk-21"
$env:MAVEN_CMD = "C:\Tools\apache-maven-3.9.15\bin\mvn.cmd"
$AI_HUB = "C:\Users\me\modernizer-solution\modernizer-solution-ai-hub"
$legacy = "C:\work\apps\legacy-service"
$outputParent = "C:\work\modernized"
$runName = "legacy-service-v2"
$env:AI_MIGRATION_PROOF_LEVEL = "build_test_verified"
$env:AI_MIGRATION_SKIP_ENDPOINT_SMOKE = "true"
```

The parser accepts assignment syntax and extracts only allowlisted keys. It rejects or ignores:

- Azure endpoints, keys, bearer tokens, deployment IDs
- arbitrary `Path` edits except for detection hints
- arbitrary shell commands
- Maven goals
- unrecognized `AI_MIGRATION_*` flags unless mapped to a typed V2 option

Example parse response:

```json
{
  "parsed": {
    "run_name": "legacy-service-v2",
    "legacy_app_path": "C:\\work\\apps\\legacy-service",
    "output_parent_path": "C:\\work\\modernized",
    "ai_hub_path": "C:\\Users\\me\\modernizer-solution\\modernizer-solution-ai-hub",
    "java_homes": {
      "java11": "C:\\Tools\\jdk-11",
      "java17": "C:\\Tools\\jdk-17",
      "java21": "C:\\Tools\\jdk-21"
    },
    "maven_cmd": "C:\\Tools\\apache-maven-3.9.15\\bin\\mvn.cmd",
    "migration_flags": {
      "proof_level": "build_test_verified",
      "skip_endpoint_smoke": true
    }
  },
  "ignored_keys": ["PYTHONPATH"],
  "blocked_keys": []
}
```

### Explicit exclusions

The form must not accept:

- Azure API keys
- Entra secrets/client credentials
- Azure/OpenAI endpoints as raw user fields
- proposer/reviewer/assistant/fallback deployment IDs
- model names
- arbitrary environment variables
- arbitrary Maven goals
- shell commands
- stage profile overrides
- Stage 2/3 input paths

## 5. Backend platform configuration

Azure Foundry and model configuration belong to backend settings. FastAPI can use Pydantic Settings to load and validate environment-backed settings; the official FastAPI docs describe `pydantic-settings`, typed conversion, `.env` loading, and dependency-based settings access.[^fastapi-settings]

### Proposed env names

```text
CONTROL_TOWER_BIND_HOST=127.0.0.1
CONTROL_TOWER_BIND_PORT=8000

AZURE_FOUNDRY_PROVIDER=azure_openai
AZURE_FOUNDRY_ENDPOINT_ENV=AZURE_OPENAI_ENDPOINT
AZURE_FOUNDRY_AUTH_MODE=api_key_or_entra
AZURE_FOUNDRY_API_KEY_ENV=AZURE_OPENAI_API_KEY
AZURE_FOUNDRY_API_VERSION=2026-xx-xx

AZURE_FOUNDRY_PROPOSER_DEPLOYMENT_ENV=AZURE_OPENAI_PROPOSER_DEPLOYMENT
AZURE_FOUNDRY_REVIEWER_DEPLOYMENT_ENV=AZURE_OPENAI_REVIEWER_DEPLOYMENT
AZURE_FOUNDRY_ASSISTANT_DEPLOYMENT_ENV=AZURE_OPENAI_ASSISTANT_DEPLOYMENT
AZURE_FOUNDRY_FALLBACK_DEPLOYMENT_ENV=AZURE_OPENAI_FALLBACK_DEPLOYMENT
AZURE_FOUNDRY_FALLBACK_ENABLED=false

CONTROL_TOWER_LOCAL_MODE=true
CONTROL_TOWER_ALLOWED_SOURCE_ROOTS=C:\work\apps
CONTROL_TOWER_ALLOWED_OUTPUT_ROOTS=C:\work\modernized
CONTROL_TOWER_DEFAULT_AI_HUB_PATH=C:\Users\me\modernizer-solution\modernizer-solution-ai-hub
```

The env ref pattern stores names of env variables and reads values only inside the backend process. UI/API responses return:

```json
{
  "profile_id": "azure-foundry-v2",
  "provider": "azure_openai",
  "endpoint_env_ref": "AZURE_OPENAI_ENDPOINT",
  "auth_mode": "api_key_or_entra",
  "api_version_configured": true,
  "roles": {
    "proposer": { "configured": true, "deployment_label": "proposer" },
    "reviewer": { "configured": true, "deployment_label": "reviewer" },
    "assistant": { "configured": true, "deployment_label": "assistant" },
    "fallback": { "configured": true, "enabled": false }
  }
}
```

### Settings class concept

```python
from pydantic import Field
from pydantic_settings import BaseSettings

class ControlTowerSettings(BaseSettings):
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    azure_provider: str = "azure_openai"
    azure_endpoint_env: str = "AZURE_OPENAI_ENDPOINT"
    azure_auth_mode: str = "api_key_or_entra"
    azure_api_key_env: str = "AZURE_OPENAI_API_KEY"
    azure_api_version: str
    proposer_deployment_env: str
    reviewer_deployment_env: str
    assistant_deployment_env: str
    fallback_deployment_env: str | None = None
    fallback_enabled: bool = False
```

### Redaction rules

- Never return env values for endpoint, key, token, deployment, tenant, client secret, or connection string.
- Store config snapshots as env refs, booleans, role labels, and checksums.
- Redact absolute local paths in model context unless path display is explicitly needed for the local-only UI.
- Persist health artifacts with status, latency, role, schema name/checksum, and redacted error classification only.

### Next.js rules

No Azure secret or model deployment variable may use `NEXT_PUBLIC_`. Next.js documents that non-`NEXT_PUBLIC_` env vars are server-only, while `NEXT_PUBLIC_` values are inlined into browser JavaScript bundles.[^next-env] Server Components should fetch server-side data and can use secrets server-side; Client Components are for state, event handlers, browser APIs, and interactivity.[^next-components]

### Read-only settings screen

Add `/settings/ai`:

- shows configured profile ID
- shows endpoint env ref as configured/not configured
- shows credential as present/missing, never the credential value
- shows proposer as ready/error
- shows reviewer as ready/error
- shows assistant as ready/degraded/error
- shows fallback as disabled
- shows last health result
- shows redacted error classification
- has `Run health check` button only if backend policy allows admin/local operator action
- never shows endpoint value, API key, bearer token, deployment ID, or raw prompt

## 6. Readiness and Start gating

### Status model

| Status | Meaning | Start impact |
| --- | --- | --- |
| `READY` | Required check passed with current setup checksum. | Allows start for that gate. |
| `DEGRADED` | Non-required feature failed or timed out, required migration path still safe. | Allows deterministic start; warns for affected feature. |
| `BLOCKED` | Required local deterministic check failed, missing, stale, unsafe, or unverified. | Disables start for local deterministic gates. Azure `BLOCKED` disables/degrades AI features only. |
| `UNKNOWN` | Not checked for current setup checksum. | Disables start. |

For Azure/model checks, `UNKNOWN`, `BLOCKED`, or `ERROR` degrades AI features only and does not disable deterministic migration start.

### Required checks

Backend health:

- `GET /v1/health/live` returns live.
- `GET /v1/health/ready` returns ready.
- SQLite migrations applied through latest known migration.
- Local binding is `127.0.0.1`.

Local setup:

- legacy path exists.
- legacy path is under allowed local roots or local-mode policy permits explicit path with audit.
- legacy path contains `pom.xml` or `build.gradle`.
- legacy app marker is `READY` only when the project marker and route-eligible build files are present.
- legacy path does not point inside output parent.
- output parent exists or can be created.
- output parent is writable.
- output parent readiness is tracked as its own gate.
- generated run/stage output dirs do not collide unless user explicitly chooses a safe retry policy.
- run name sanitizes to a unique run ID.

AI Hub:

- AI Hub root exists.
- required profiles exist:
  - `springboot-2.1.6-to-2.7-java11`
  - `springboot-2.7-to-3.5-java17`
  - `springboot-3.5-java17-to-java21`
- required catalogs exist:
  - `springboot-2.1.6-to-2.7-java11.yaml`
  - `springboot-2.7-to-3.5-java17.yaml`
  - `springboot-3.5-java17-to-java21.yaml`
- required policies exist: `planning`, `safety`, `transformation`.
- profile/catalog checksums match the pipeline snapshot.
- Boot 4 profiles/catalogs exist in repo but are excluded from this V2 route.

JDK/Maven:

- `JAVA11_HOME` exists and `bin/java -version` reports major 11.
- `JAVA17_HOME` exists and reports major 17.
- `JAVA21_HOME` exists and reports major 21.
- `MAVEN_CMD` exists and `mvn --version` runs under timeout.
- Maven runs with backend-owned env.
- Stage env mapping is:
  - Stage 1: `JAVA_HOME=%JAVA11_HOME%`, prepend `%JAVA11_HOME%\bin`
  - Stage 2: `JAVA_HOME=%JAVA17_HOME%`, prepend `%JAVA17_HOME%\bin`
  - Stage 3: `JAVA_HOME=%JAVA21_HOME%`, prepend `%JAVA21_HOME%\bin`
- Maven Toolchains may be added later; official Maven docs state toolchains let a project specify JDKs for builds independently of the JDK running Maven.[^maven-toolchains]

Pipeline route:

- pipeline ID is `springboot-216-to-356-java21-three-stage`.
- Stage 1 input is legacy source.
- Stage 2 input is Stage 1 sandbox only.
- Stage 3 input is Stage 2 sandbox only.
- no user-selected Stage 2/3 input path.
- no Boot 4 selectable path.

Azure model health, shown but not start-blocking:

- endpoint env ref configured and value present in backend process.
- credential mode configured and credential available.
- API version configured.
- proposer deployment health is ready or reports a redacted error.
- reviewer deployment health is ready or reports a redacted error.
- assistant deployment health is ready, degraded, or reports a redacted error.
- structured output schema health is ready or reports a redacted error.
- fallback is disabled.
- no silent fallback.
- Azure `BLOCKED` means AI features are unavailable/degraded, not that the local deterministic migration cannot start. AI-required actions later block or degrade only when the user needs model help.

Structured output schemas:

- `PlanProposal`
- `RepairProposal`
- `ReviewerCritique`
- `ActionRequest`
- `AssistantAnswer`

Azure OpenAI structured outputs can force model responses to follow a supplied JSON Schema, unlike plain JSON mode.[^azure-structured] V2 should use strict schemas with `additionalProperties: false` where supported.

### Gating formula

```text
Start Migration enabled =
- backend READY
- local setup READY
- AI Hub READY
- runner JDK/Maven READY
- pipeline route READY
- output parent READY
- legacy app marker READY
```

Azure status is shown but not blocking deterministic migration start.

## 7. Azure Foundry and LLM architecture

### Authority split

Azure Foundry can provide agent/model infrastructure, including agents that use models, tools, and knowledge sources.[^azure-agents] In this product, Foundry must not become the migration authority. The Control Tower backend remains the orchestrator because it owns:

- local filesystem trust boundaries
- registered roots
- worker manifests
- stage chain
- approvals
- checksums
- sandbox write policy
- Maven/test/proof evidence
- cancellation/recovery
- audit records

Chat instructions never rewrite the migration route or stage sequence. They create plan amendments, repair instructions, or pending actions that are validated against the locked pipeline and current stage state.

Foundry roles:

These roles are required for AI-assisted features, not required for deterministic local migration start.

| Role | AI-assisted requirement | Purpose |
| --- | --- | --- |
| proposer | required for AI plan/repair proposals | plan proposals, repair proposals, action requests |
| reviewer | required for AI critique flow | critique plans/repairs/actions before human approval |
| assistant | optional/degraded for chat UX | status explanation, evidence navigation, instruction drafting |
| classifier | optional | failure classification if deterministic classifier is insufficient |
| fallback | configured disabled | never invoked automatically in V2 |

### Structured outputs

Schemas:

```json
{
  "PlanProposal": {
    "type": "object",
    "additionalProperties": false,
    "required": ["summary", "stage_impacts", "risks", "approval_checksum"],
    "properties": {
      "summary": { "type": "string" },
      "stage_impacts": { "type": "array", "items": { "type": "object" } },
      "risks": { "type": "array", "items": { "type": "string" } },
      "approval_checksum": { "type": "string" }
    }
  }
}
```

V2 schema set:

- `PlanProposal`: exact plan candidate, stage impacts, risk notes, validation expectations.
- `RepairProposal`: failure hypothesis, patch summary, affected paths, validation plan, rollback note.
- `ReviewerCritique`: accept/revise/reject, missing evidence, unsafe assumptions, policy issues.
- `ActionRequest`: typed pending action request, reason, stage, payload checksum.
- `AssistantAnswer`: answer plus cited evidence refs and optional follow-up action draft.

### Model-call audit

Every model call persists:

- role
- provider
- model profile checksum
- deployment role label, not raw deployment ID in UI
- request schema ID/checksum
- response schema ID/checksum
- context pack ID/checksum
- prompt manifest refs
- token estimate and actual token counts when available
- latency
- finish status
- redacted error classification
- structured output artifact ref/checksum

Do not persist:

- API keys
- bearer tokens
- raw full prompts with secrets
- unrestricted logs
- full repo dumps
- deployment IDs in browser-facing payloads

### Context packs

Context Builder creates bounded evidence packs:

- relevant file/log windows with byte/line offsets
- POM/build snippets
- stage status
- command result
- approval target
- previous proposal when revising
- user instruction when relevant
- redaction report
- token estimate
- checksum

Default budgets:

| Task | Input tokens | Output tokens |
| --- | ---: | ---: |
| plan proposal | 24000 | 6000 |
| plan revision | 18000 | 5000 |
| repair proposal | 20000 | 6000 |
| reviewer critique | 16000 | 4000 |
| assistant answer | 8000 | 2000 |
| action request | 6000 | 1500 |

### LLM hard limits

The LLM cannot:

- execute commands
- approve decisions
- write files directly
- mutate legacy source
- rewrite the migration route
- change the stage sequence
- choose model deployments
- choose Maven goals
- choose raw executable paths
- choose Stage 2/3 input paths
- access secrets
- override deterministic proof

## 8. Orchestrator integration

### Terminal-to-backend mapping

Old terminal:

```powershell
py -m migration_factory.orchestrator.runner `
  --run-id $runId `
  --legacy $legacy `
  --modernized $modernized `
  --ai-hub $aiHub `
  --profile $profile `
  --mode full_sandbox_migration
```

V2 backend:

```json
{
  "command_type": "RUN_ORCHESTRATOR_STAGE",
  "stage_index": 1,
  "module": "migration_factory.orchestrator.runner",
  "args": {
    "--run-id": "job-123-s1",
    "--legacy": "<backend-resolved legacy path>",
    "--modernized": "<backend-resolved stage 1 output>",
    "--ai-hub": "<backend-resolved ai hub path>",
    "--profile": "springboot-2.1.6-to-2.7-java11",
    "--mode": "full_sandbox_migration"
  },
  "env_policy": {
    "JAVA_HOME": "java11",
    "PATH_PREPEND": "java11/bin",
    "PYTHONPATH": "."
  }
}
```

Old resume:

```powershell
py -m migration_factory.orchestrator.resume `
  --run-id $runId `
  --run-dir $runDir `
  --decision approved `
  --approved-by reviewer `
  --comments "approved"
```

V2 backend queues:

```json
{
  "command_type": "RESUME_ORCHESTRATOR_STAGE",
  "module": "migration_factory.orchestrator.resume",
  "args": {
    "--run-id": "job-123-s1",
    "--run-dir": "<backend-resolved stage run dir>",
    "--decision": "approved",
    "--approved-by": "local-operator",
    "--comments": "<approval artifact ref>"
  }
}
```

### Stage progression

```text
Start parent job
-> create setup snapshot
-> create stage chain ledger rows
-> queue Stage 1 runner
-> LangGraph interrupt becomes Control Tower approval card
-> approval queues Stage 1 resume
-> Stage 1 finalizes sandbox/proof gate
-> backend continuation policy verifies Stage 1 output
-> queue Stage 2 runner with Stage 1 sandbox as legacy input
-> approval/resume/finalize
-> queue Stage 3 runner with Stage 2 sandbox as legacy input
-> approval/resume/finalize
-> compute final proof/report
```

LangGraph interrupts pause graph execution and wait for external input; the docs state graph state is saved through persistence until resume.[^langgraph-interrupts] LangGraph persistence/checkpointers support resume after interruption and recovery/fault tolerance.[^langgraph-persistence] Control Tower should map this to durable approvals and backend-owned resume commands.

### Worker-owned process execution

- HTTP routes persist commands; they do not run migrations directly.
- Worker reads queued command manifests.
- Worker constructs argv/env from backend-owned setup snapshot and stage ledger.
- Worker enforces timeout/output limits.
- Worker records stdout/stderr/result artifacts.
- Worker emits public and audit events.
- Worker supports cancellation/recovery.
- Unclear restart state fails closed.

## 9. Data model and persistence

Use append-only migrations. Do not edit existing applied migrations.

### `v2_local_migration_setups`

Purpose: persisted setup from New Migration before job creation.

Key columns:

- `setup_id`
- `setup_version`
- `run_name`
- `sanitized_run_id`
- `legacy_app_path_redacted`
- `legacy_path_ref`
- `output_parent_path_redacted`
- `output_parent_ref`
- `ai_hub_path_redacted`
- `ai_hub_ref`
- `java11_home_ref`, `java17_home_ref`, `java21_home_ref`
- `maven_cmd_ref`
- `flags_json`
- `setup_checksum`
- `status`
- `created_by`, `created_at`, `updated_at`

Invariants:

- stores refs/redacted display values, not secrets
- no raw Maven goals
- no Azure config
- setup checksum gates preflight/job creation

Indexes:

- unique `setup_id`
- `(status, created_at)`
- unique `(sanitized_run_id)` while non-terminal

### `v2_env_parse_artifacts`

Purpose: safe parse result for pasted PowerShell block.

Key columns:

- `parse_id`
- `setup_id`
- `source_checksum`
- `extracted_json`
- `ignored_keys_json`
- `blocked_keys_json`
- `redaction_report_json`
- `created_at`

Invariants:

- raw env block is not persisted unless redacted artifact policy explicitly allows it
- blocked secret-like keys never appear with values

Indexes:

- `(setup_id, created_at)`

### `v2_preflight_runs`

Purpose: immutable readiness result for setup checksum.

Key columns:

- `preflight_id`
- `setup_id`
- `setup_checksum`
- `overall_status`
- `checks_json`
- `artifact_id`
- `created_at`

Invariants:

- start requires latest preflight for current setup checksum
- status is computed from checks

Indexes:

- `(setup_id, created_at)`
- `(overall_status, created_at)`

### `v2_model_profiles`

Purpose: Azure/backend model profile.

Key columns:

- `profile_id`
- `provider`
- `endpoint_env_ref`
- `auth_mode`
- `api_key_env_ref`
- `api_version`
- `role_deployments_json`
- `fallback_enabled`
- `profile_checksum`
- `created_at`

Invariants:

- env refs only
- fallback disabled for V2 unless future policy changes

Indexes:

- unique `profile_id`
- `(provider)`

### `v2_model_health_checks`

Purpose: readiness evidence for Azure roles.

Key columns:

- `health_id`
- `profile_id`
- `profile_checksum`
- `overall_status`
- `role_checks_json`
- `structured_output_checks_json`
- `latency_ms_json`
- `error_classification`
- `artifact_id`
- `created_at`

Invariants:

- no secrets/prompts/raw responses
- health checks bound to profile checksum

Indexes:

- `(profile_id, created_at)`
- `(overall_status, created_at)`

### `v2_model_calls`

Purpose: model-call audit.

Key columns:

- `model_call_id`
- `job_id`
- `stage_index`
- `role`
- `profile_id`
- `profile_checksum`
- `deployment_role`
- `context_pack_id`
- `request_schema_checksum`
- `response_schema_checksum`
- `status`
- `input_tokens_estimated`
- `input_tokens_actual`
- `output_tokens_actual`
- `latency_ms`
- `response_artifact_id`
- `response_checksum`
- `error_classification`
- `created_at`

Invariants:

- append-only
- browser never receives secrets or raw deployments

Indexes:

- `(job_id, stage_index, created_at)`
- `(role, created_at)`

### `v2_context_packs`

Purpose: bounded model evidence.

Key columns:

- `context_pack_id`
- `job_id`
- `stage_index`
- `purpose`
- `manifest_json`
- `budget_tokens`
- `estimated_tokens`
- `redaction_report_json`
- `checksum`
- `created_at`

Invariants:

- no forbidden files
- bounded windows only

Indexes:

- `(job_id, stage_index, purpose)`
- `(checksum)`

### `v2_assistant_threads`, `v2_assistant_messages`, `v2_tool_calls`

Purpose: durable chat and tool audit.

Key columns:

- thread: `thread_id`, `job_id`, `status`, `created_by`, `created_at`
- message: `message_id`, `thread_id`, `role`, `content_redacted`, `model_call_id`, `created_at`
- tool call: `tool_call_id`, `thread_id`, `job_id`, `stage_index`, `tool_name`, `tool_class`, `input_manifest_json`, `result_artifact_id`, `status`, `created_at`

Invariants:

- read tools cannot mutate
- action tools create pending action only
- content redacted before browser display

Indexes:

- `(job_id)`
- `(thread_id, created_at)`
- `(tool_name, created_at)`

### `v2_stage_chain_ledger`

Purpose: V2 parent job stage chain. Existing V1 stage-chain ledger can be extended if adequate; otherwise add V2 table for setup binding.

Key columns:

- `ledger_id`
- `job_id`
- `setup_id`
- `stage_index`
- `stage_run_id`
- `profile_id`
- `profile_checksum`
- `pipeline_id`
- `pipeline_checksum`
- `input_kind`
- `input_ref`
- `output_ref`
- `run_id`
- `run_dir_ref`
- `sandbox_ref`
- `jdk_id`
- `maven_cmd_ref`
- `status`
- `proof_gate_id`
- `created_at`

Invariants:

- Stage 2 input equals Stage 1 sandbox
- Stage 3 input equals Stage 2 sandbox
- append-only core fields

Indexes:

- unique `(job_id, stage_index)`
- unique `stage_run_id`
- `(job_id, status)`

### `v2_proposals`, `v2_approvals`, `v2_pending_actions`

Purpose: exact human decision gates.

Key columns:

- proposal: `proposal_id`, `job_id`, `stage_index`, `proposal_type`, `context_pack_id`, `model_call_id`, `artifact_id`, `checksum`, `status`
- approval: `approval_id`, `job_id`, `target_type`, `target_id`, `target_checksum`, `decision`, `actor`, `expected_job_version`, `comments_artifact_id`, `created_at`, `decided_at`
- action: `action_id`, `job_id`, `stage_index`, `action_type`, `payload_json`, `payload_checksum`, `policy_result_json`, `status`, `approval_id`, `command_id`

Invariants:

- no mutation before approval
- approval target checksum equals execution checksum
- stale job/stage version rejected

Indexes:

- `(job_id, stage_index, status)`
- unique `(target_type, target_id, target_checksum, actor)` for idempotent approvals if needed

### `v2_proof_gates`, `v2_final_reports`

Purpose: deterministic proof.

Key columns:

- proof gate: `proof_gate_id`, `job_id`, `stage_index`, `gate_type`, `source_command_id`, `artifact_id`, `status`, `checksum`, `created_at`
- report: `report_id`, `job_id`, `proof_complete`, `target_proof_level`, `report_md_artifact_id`, `report_json_artifact_id`, `checksum`, `created_at`

Invariants:

- model cannot create or override proof
- final report generated from proof gates/stage ledger/artifacts only

Indexes:

- `(job_id, stage_index, gate_type)`
- `(job_id, created_at)`

## 10. API design

All state-changing endpoints require local auth/session policy, actor attribution, idempotency key where applicable, audit record, strict request body validation, and `If-Match` for versioned resources. FastAPI request bodies using Pydantic models provide typed validation and generated schemas.[^fastapi-body]

| Method/path | Purpose | Request | Response | Security notes |
| --- | --- | --- | --- | --- |
| `POST /v1/migration-setups/parse-env` | Parse pasted PowerShell env block. | `{ "env_block": "...", "mode": "powershell" }` | extracted fields, ignored/blocked keys, checksum | Never execute; do not persist raw secrets; block Azure secret keys. |
| `POST /v1/migration-setups` | Create/update local setup draft. | typed local fields and flags | setup ID, checksum, redacted display values | Local paths accepted only for local mode; backend validates/stores refs. |
| `GET /v1/migration-setups/{setup_id}` | Read setup draft. | none | redacted setup | No secret/env values. |
| `POST /v1/migration-setups/{setup_id}/preflight` | Run preflight. | `{ "setup_checksum": "..." }` | readiness report | Uses backend-owned checks; no migration execution. |
| `GET /v1/migration-setups/{setup_id}/readiness` | Get latest readiness. | none | READY/DEGRADED/BLOCKED checks | Bound to setup checksum. |
| `GET /v1/settings/ai` | Read backend AI settings. | none | redacted model profile/settings | No Azure endpoint values, keys, or deployment IDs. |
| `POST /v1/model-profiles/{profile_id}/health-check` | Run Azure model readiness. | optional role list | role health/check artifact | Backend-only env refs; redacted errors. |
| `GET /v1/model-profiles` | List model profiles. | none | redacted profiles | No secret/deployment values. |
| `GET /v1/model-profiles/{profile_id}` | Read model profile. | none | redacted profile | Env refs only. |
| `POST /v1/migration-jobs` | Create V2 migration job from ready setup. | `{ "setup_id": "...", "setup_checksum": "...", "preflight_id": "..." }` | job projection, stage chain | Requires local deterministic preflight READY. Azure status is included but does not block creation. |
| `POST /v1/migration-jobs/{job_id}/start` | Start parent migration. | `{}` plus `If-Match` | queued Stage 1 command/job projection | Does not accept paths/goals/model IDs. |
| `POST /v1/migration-jobs/{job_id}/cancel` | Cancel parent job/active worker. | `{ "reason": "..." }` plus `If-Match` | cancellation projection | Worker-owned cancellation; audit. |
| `GET /v1/migration-jobs/{job_id}` | Job projection. | none | job, setup, active command, readiness summary | Redacted paths. |
| `GET /v1/migration-jobs/{job_id}/stages` | Stage timeline. | none | stage chain and continuation status | Read-only. |
| `GET /v1/migration-jobs/{job_id}/events` | Replay events. | cursor query | events | Public event redaction. |
| `GET /v1/migration-jobs/{job_id}/events/stream` | SSE event stream. | cursor query | event stream | Redacted; bounded clients. |
| `GET /v1/migration-jobs/{job_id}/commands` | List commands. | none | command manifests/status | No raw secret env. |
| `GET /v1/migration-jobs/{job_id}/logs` | Log index. | none | available streams | Redacted refs only. |
| `GET /v1/migration-jobs/{job_id}/commands/{command_id}/logs/{stream}` | Read bounded log window. | offset/max bytes query | bounded log window | Secret/path redaction; byte limits. |
| `GET /v1/migration-jobs/{job_id}/artifacts` | List artifacts. | none | artifact metadata | Registered roots only. |
| `GET /v1/migration-jobs/{job_id}/assistant/messages` | Read chat. | none | messages | Redacted content only. |
| `POST /v1/migration-jobs/{job_id}/assistant/messages` | Submit user instruction/question. | `{ "thread_id": "...", "content": "...", "intent": "question|plan_instruction|repair_instruction|action_request" }` | message/model call/action draft refs | Does not execute; may create pending action. |
| `GET /v1/migration-jobs/{job_id}/assistant/stream` | Assistant stream. | cursor query | SSE stream | Read/action-request events only. |
| `POST /v1/migration-jobs/{job_id}/plan-instructions` | Store plan instruction. | instruction text/stage target | immutable instruction artifact | No mutation. |
| `POST /v1/migration-jobs/{job_id}/repair-instructions` | Store repair instruction. | instruction text/failure ref | immutable instruction artifact | No mutation. |
| `GET /v1/migration-jobs/{job_id}/proposals` | List plan/repair proposals. | none | proposal list | Checksums visible. |
| `GET /v1/migration-jobs/{job_id}/actions` | List pending actions. | none | action cards | No raw shell. |
| `POST /v1/migration-jobs/{job_id}/actions/{action_id}/approve` | Approve exact pending action. | checksum, actor, expected version | queued/approved action | Reject checksum mismatch/stale version. |
| `POST /v1/migration-jobs/{job_id}/actions/{action_id}/reject` | Reject action. | reason | rejected action | Audit. |
| `POST /v1/migration-jobs/{job_id}/approvals/{approval_id}/approve` | Approve exact plan/interrupt/checksum. | checksum, comments | resume command queued | Worker resumes; route does not execute directly. |
| `POST /v1/migration-jobs/{job_id}/approvals/{approval_id}/reject` | Reject approval. | comments | job/stage paused or stopped | Audit. |
| `GET /v1/migration-jobs/{job_id}/proof` | Proof gates. | none | deterministic gates | Model cannot write. |
| `GET /v1/migration-jobs/{job_id}/report.json` | Final JSON report. | none | report JSON | Redacted deterministic refs. |
| `GET /v1/migration-jobs/{job_id}/report.md` | Final Markdown report. | none | markdown | Redacted. |

## 11. Frontend design

### App structure

Use Server Components for initial reads and static shells:

- `/migrations/new/page.tsx`: fetch backend health/settings/readiness skeleton.
- `/migrations/[jobId]/page.tsx`: fetch initial job projection, stage chain, event cursor.
- `/settings/ai/page.tsx`: fetch redacted AI readiness.

Use Client Components for interactivity:

- `NewMigrationForm.tsx`: local field entry, env paste, parse button, dirty-state handling.
- `ReadinessPanel.tsx`: run preflight and poll/read latest readiness.
- `StartMigrationButton.tsx`: disabled until required local deterministic readiness READY.
- `MigrationCockpitClient.tsx`: SSE, tabs, refreshes.
- `AssistantChatPanel.tsx`: composer, stream, tool-result cards, action drafts.
- `DecisionCard.tsx`: exact checksum approval/reject/revise.
- `PendingActionCard.tsx`: typed action approval/rejection.
- `LogViewer.tsx`: bounded log windows.

### Browser rules

- Browser can submit local absolute path strings only to setup/preflight APIs in local operator mode.
- Browser cannot launch local processes.
- Browser cannot pass Maven goals.
- Browser cannot pass executable argv.
- Browser cannot pass Azure secrets/model deployments.
- Browser cannot approve without showing target checksum.
- Browser cannot directly mutate files.

### Cockpit layout

Primary areas:

- top status bar: job, readiness, current stage, proof target
- left rail: stage timeline and gate status
- center: current work, decision cards, evidence tabs
- right rail: assistant chat
- bottom or tabbed section: logs, artifacts, model calls, context packs, repairs, proof/report

### Tests needed

- env block parser UI renders extracted fields and blocked secret warnings.
- Start button disabled until required local deterministic readiness READY.
- Azure readiness is shown without secrets/deployment IDs.
- Azure errors warn that AI plan/repair/chat help may be unavailable, but do not block deterministic start.
- no `NEXT_PUBLIC_*` Azure secret usage.
- cockpit shows three stages and automatic progression copy.
- assistant can submit instruction but not execute, approve, write, change route, or change stages.
- action cards require checksum.
- no raw shell/Maven goal/model deployment inputs.
- SSE reconnection preserves event cursor.

## 12. Security/trust model

Hard rules:

- Browser is untrusted for execution.
- Browser can paste local absolute paths only in local operator mode; backend validates and stores refs before running anything.
- Browser cannot choose raw executable commands.
- Browser cannot choose raw Maven goals.
- Browser cannot choose raw working dirs.
- Browser cannot choose model deployments.
- Browser cannot rewrite the migration route or stage sequence.
- Model cannot access secrets.
- Model cannot execute.
- Model cannot approve.
- Model cannot write files directly.
- Model cannot rewrite the migration route or stage sequence.
- Model cannot create proof.
- Chat instructions never rewrite the migration route or stage sequence. They create plan amendments, repair instructions, or pending actions that are validated against the locked pipeline and current stage state.
- Legacy source is never mutated.
- Writes happen only inside the current stage sandbox.
- Every source-changing/write/Maven action needs exact checksum approval.
- Logs/events/artifacts/context/model inputs are redacted.
- API and frontend are local-only by default: `127.0.0.1`, explicit port.
- No production paths, deployment automation, PR creation, or promotion.
- Backend owns Stage 1/2/3 profile selection and stage inputs.
- Worker owns process execution and cancellation.
- Unclear worker/recovery state fails closed.

Forbidden files for context/read tools:

- `.env*`
- private keys
- keystores
- SSH keys
- tokens
- local DB files unless explicitly registered non-secret evidence
- credential/config files matched by policy

## 13. Failure handling

### Failed preflight

- Show failing check, reason, remediation hint, and redacted command evidence.
- Keep `Start Migration` disabled.
- Allow user to edit setup or paste corrected env block.
- Re-run preflight creates new preflight artifact for new setup checksum.

### Failed Azure model health

- Proposer/reviewer failure = Azure AI feature `BLOCKED`, not deterministic migration start `BLOCKED`.
- Assistant failure = Azure AI feature `DEGRADED` or `ERROR`, not deterministic migration start `BLOCKED`.
- Structured output schema failure = Azure AI feature `BLOCKED`, not deterministic migration start `BLOCKED`.
- Quota/rate/auth errors are classified and redacted.
- No fallback unless explicitly enabled by future policy; V2 verifies fallback disabled.
- Show a clear warning that AI plan, repair, and chat help may be unavailable or degraded.
- Allow deterministic migration/orchestrator flow to start when local runner, JDK/Maven, AI Hub, pipeline route, output parent, and legacy app preflight are `READY`.
- Block or degrade later AI-required actions only when the user needs model help.

### Failed stage

```text
Stage command failed
-> persist command result/log artifacts
-> deterministic classifier determines repairability
-> context builder creates bounded failure pack
-> proposer generates RepairProposal
-> reviewer critiques
-> backend policy validates
-> UI shows proposal/diff/validation/checksum
-> user approves exact checksum or gives repair instruction via chatbot
-> approved patch/action executes in sandbox
-> validation runs typed Maven operation
-> pass continues stage or pipeline
-> fail rolls back or creates next repair attempt
```

### Rollback/escalation

- Snapshot sandbox before patch.
- Rollback restores snapshot through approved typed action.
- Repair attempts have limits.
- If attempt limit exceeded, stage pauses for manual escalation.
- Manual escalation can export evidence but cannot mutate legacy source from Control Tower.

## 14. Manual/UAT flow

### Configure backend `.env`

```powershell
cd C:\Users\me\modernizer-solution

$env:CONTROL_TOWER_BIND_HOST = "127.0.0.1"
$env:CONTROL_TOWER_BIND_PORT = "8000"
$env:CONTROL_TOWER_DEFAULT_AI_HUB_PATH = "C:\Users\me\modernizer-solution\modernizer-solution-ai-hub"

$env:AZURE_OPENAI_ENDPOINT = "<configured outside UI>"
$env:AZURE_OPENAI_API_KEY = "<configured outside UI or use Entra>"
$env:AZURE_OPENAI_API_VERSION = "<api-version>"
$env:AZURE_OPENAI_PROPOSER_DEPLOYMENT = "<backend-only>"
$env:AZURE_OPENAI_REVIEWER_DEPLOYMENT = "<backend-only>"
$env:AZURE_OPENAI_ASSISTANT_DEPLOYMENT = "<backend-only>"
$env:AZURE_FOUNDRY_FALLBACK_ENABLED = "false"
```

### Start backend/frontend

```powershell
py -m uvicorn migration_factory.control_tower.adapters.fastapi.app:create_app --factory --host 127.0.0.1 --port 8000
cd web\control-tower
npm run dev
```

### UAT script

1. Open `http://127.0.0.1:<next-port>/migrations/new`.
2. Paste the old PowerShell env block into `Paste terminal config`.
3. Click `Parse env block`.
4. Verify fields populate:
   - run name
   - legacy path
   - output parent
   - AI Hub path
   - JDK homes
   - Maven command
   - flags
5. Confirm no Azure values appear in form fields.
6. Click `Run preflight`.
7. Verify readiness:
   - backend `READY`
   - legacy app `READY`
   - legacy app marker `READY`
   - output parent `READY`
   - AI Hub `READY`
   - JDK 11/17/21 `READY`
   - Maven `READY`
   - pipeline route `READY`
   - Azure proposer/reviewer status is visible as ready/error without secrets
   - Assistant status is visible as ready/degraded/error without secrets
   - fallback disabled status is visible
8. Verify `Start Migration` remains disabled if any required local deterministic check is `BLOCKED`.
9. Verify Azure `BLOCKED` or `ERROR` status warns that AI help may be unavailable/degraded but does not block deterministic start.
10. Click `Start Migration`.
11. Cockpit opens.
12. Verify Stage 1 is queued/running without user choosing the stage.
13. At approval interrupt, review decision card and checksum.
14. Approve exact checksum.
15. Verify backend queues resume command.
16. Verify Stage 2 starts automatically from Stage 1 sandbox after Stage 1 passes.
17. Verify Stage 3 starts automatically from Stage 2 sandbox after Stage 2 passes.
18. Simulate or use a sample failure.
19. Ask chatbot: `Why did this fail and what repair do you recommend?`
20. Verify chatbot cites bounded evidence and creates a repair instruction/proposal path, not direct execution.
21. Verify chatbot instructions do not rewrite the locked route or Stage 1 -> Stage 2 -> Stage 3 sequence.
22. Approve exact repair/action checksum.
23. Verify worker applies only approved sandbox mutation and runs typed validation.
24. Verify proof/report generated.
25. Verify final report says `production_ready_not_claimed`.
26. Verify no logs/artifacts/model calls show secrets or raw Azure deployments.

## 15. Risks and open decisions

Risks:

- Existing docs are partially stale and still mention older two-stage `3.5.14` V1 evidence.
- Azure health checks may be flaky or quota-limited.
- Local path paste is useful but risky; path containment/audit must be strict.
- Model context can leak secrets if redaction misses forbidden files.
- Current fake-provider endpoints must be replaced or wrapped without breaking tests.
- Full stage auto-progression needs robust recovery/cancellation semantics.
- Long-running Maven/OpenRewrite commands need Windows process-tree handling.
- Token/cost budgets may be too high for real workloads.
- Assistant action requests can blur UX authority if approval cards are not explicit.

Open decisions:

- Azure auth mode: API key, Entra ID, or both.
- Exact Azure API version.
- Whether shell diagnostics are allowed at all in V2.
- Where local setup refs are stored and whether raw absolute paths are encrypted or only redacted in projections.
- Windows worker implementation detail for process tree kill and restart recovery.
- Full run cancellation semantics across parent job and active stage.
- Token/cost budgets and per-role max latency.
- Whether runtime/H2 proof is part of this V2 cockpit or a follow-on V2.x proof enhancement.
- Whether typed Maven validations require approval every time or can be pre-approved inside an approved validation plan.

## 16. Implementation dependency map

Complete dependency map, foundation to finished V2:

```text
1. Backend settings + redaction baseline
   -> needed before model health and UI settings

2. Local setup parser + setup persistence
   -> needed before preflight

3. Preflight/readiness engine
   -> needed before job creation/start gating

4. Azure model profile health checks
   -> needed before reliable AI plan/repair/chat, but not before deterministic migration start

5. V2 frontend New Migration form
   -> depends on setup parser, preflight, and Azure status display

6. V2 migration job creation from setup
   -> depends on setup/preflight/pipeline/local runner readiness

7. Parent job start + stage-chain binding
   -> depends on job creation and V1 stage ledger/route

8. Worker-owned Stage 1 runner command
   -> depends on setup refs, JDK/Maven readiness, command manifests

9. Approval interrupt -> Control Tower approval -> resume command
   -> depends on orchestrator command execution

10. Automatic Stage 2/3 progression
    -> depends on Stage 1/2 proof outputs and continuation policy

11. Context packs + model-call audit
    -> depends on job/stage/evidence records and Azure health when AI help is available

12. Real proposer/reviewer calls
    -> depends on context packs/model audit/structured schemas and healthy Azure roles

13. Assistant chat with read tools and action requests
    -> depends on context/model/tool audit and pending action storage

14. Repair workflow
    -> depends on failed command evidence, context packs, proposer/reviewer, action approvals

15. Cockpit UI
    -> depends on job/stage/events/approvals/actions/assistant/proof APIs

16. Deterministic proof/report
    -> depends on all stages and typed validation artifacts

17. UAT hardening
    -> depends on end-to-end local flow, cancellation, redaction, restart recovery
```

## 17. Acceptance definition for V2

V2 is ready only when all of these are true:

- User can paste the old local terminal config into the UI.
- Frontend accepts local absolute paths for the legacy app, output parent, AI Hub, JDK homes, and Maven command only in local operator mode.
- Backend parses only allowlisted local setup fields.
- Backend validates local paths and tool readiness before queuing any command.
- Azure secrets/model deployments are not accepted by New Migration.
- Preflight blocks bad local config.
- Start is disabled until backend, local setup, AI Hub, runner JDK/Maven, pipeline route, output parent, and legacy app marker are `READY`.
- Azure status is shown clearly but does not block deterministic migration start; Azure `BLOCKED` means AI plan, repair, or chat help is unavailable/degraded until health recovers.
- Backend creates a parent migration job from the setup snapshot.
- Backend starts Stage 1 through worker-owned command manifest.
- User does not manually start Stage 2 or Stage 3.
- Backend auto-progresses Stage 1 -> Stage 2 -> Stage 3 with previous-stage sandbox binding.
- LangGraph approval interrupts become Control Tower decision cards.
- Approval/resume is checksum/version guarded.
- Chatbot can explain status, cite evidence, and accept plan/repair instructions.
- Chatbot can create typed pending action requests.
- Chatbot cannot execute, approve, write files, choose raw paths, choose Maven goals, choose model deployments, change route, change stages, or override proof.
- Chat instructions never rewrite the migration route or stage sequence. They create plan amendments, repair instructions, or pending actions that are validated against the locked pipeline and current stage state.
- Failures produce bounded context packs and structured repair flow.
- Reviewer critique and backend policy gate run before final human approval.
- Exact approval/checksum is required before sandbox mutation or typed Maven/write action.
- Legacy source checksum remains unchanged.
- Final proof/report is generated from deterministic stage/command/artifact evidence.
- Logs, events, artifacts, model calls, context packs, assistant messages, and reports are redacted.
- Final report states the achieved proof level and `production_ready_not_claimed`.

## Official references

[^fastapi-settings]: FastAPI, "Settings and Environment Variables": https://fastapi.tiangolo.com/advanced/settings/
[^fastapi-body]: FastAPI, "Request Body": https://fastapi.tiangolo.com/tutorial/body/
[^next-env]: Next.js, "Environment Variables": https://nextjs.org/docs/app/guides/environment-variables
[^next-components]: Next.js, "Server and Client Components": https://nextjs.org/docs/app/getting-started/server-and-client-components
[^azure-agents]: Microsoft Learn, "What is Microsoft Foundry Agent Service?": https://learn.microsoft.com/en-us/azure/foundry/agents/overview
[^azure-structured]: Microsoft Learn, "Structured outputs": https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs
[^langgraph-interrupts]: LangGraph docs, "Interrupts": https://docs.langchain.com/oss/python/langgraph/interrupts
[^langgraph-persistence]: LangGraph docs, "Persistence": https://docs.langchain.com/oss/python/langgraph/persistence
[^maven-toolchains]: Apache Maven, "Guide to Using Toolchains": https://maven.apache.org/guides/mini/guide-using-toolchains.html
