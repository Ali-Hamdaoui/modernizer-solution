# V2 Implementation Subagent Plan

Status: execution planning for V2 only
Integration branch: `V2IMPROVMENT`
Stable V1 baseline: `DEMO2` at `1b84b60`
Product source of truth: `improvmentV2.md`
Do not replace or rewrite `improvmentV2.md`.

## 0. How to Use This Document

If you are A1-A14, read only these sections before editing:

- `1. Global Idea`
- `2. Final Product Vision`
- `3. Non-Negotiable Rules`
- `5. Full Dependency Map`
- `6. Subagent Roster`
- your own `A<N>` dossier under `7. Detailed Dossiers`
- `8. Integration Gates`
- `9. Testing Strategy`
- `10. Review Gates`

If you are A15 Security Review Agent, read all dossiers and all changed code.

If you are A16 Test Discipline Agent, read all dossiers, all test sections, `9. Testing Strategy`, and `11. Final V2 Acceptance`.

Do not read or implement adjacent agent dossiers unless your own dossier says it depends on them. Dependency names tell you merge order and contract shape; they do not grant scope to implement dependency work.

### Subagent Direct Map

| Agent ID | Agent name | Direct dossier heading | Must-read shared sections | Must-not-read/implement | Branch | PR base | Primary tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | Backend Settings & Redaction Agent | `### A1 Backend Settings & Redaction Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A2-A16 dossiers; Azure calls; UI | `v2/a1-backend-settings-redaction` | `V2IMPROVMENT` | API security and settings redaction tests |
| A2 | Local Env Parser Agent | `### A2 Local Env Parser Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A3-A16 dossiers; path validation; persistence | `v2/a2-local-env-parser` | `V2IMPROVMENT` | parser and API contract tests |
| A3 | Setup Persistence & Preflight Agent | `### A3 Setup Persistence & Preflight Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A4-A16 dossiers; Azure health; job start | `v2/a3-setup-preflight` | `V2IMPROVMENT` | setup/preflight and create job regressions |
| A4 | Azure Readiness Agent | `### A4 Azure Readiness Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A5-A16 dossiers; migration start gating | `v2/a4-azure-readiness` | `V2IMPROVMENT` | model profile, health, security tests |
| A5 | New Migration Frontend Agent | `### A5 New Migration Frontend Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A6-A16 dossiers; backend execution; cockpit | `v2/a5-new-migration-frontend` | `V2IMPROVMENT` | frontend parser/readiness/start gating tests |
| A6 | Migration Job Creation Agent | `### A6 Migration Job Creation Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A7-A16 dossiers; worker launch | `v2/a6-migration-job-creation` | `V2IMPROVMENT` | job creation and command/query tests |
| A7 | Worker Stage Execution Agent | `### A7 Worker Stage Execution Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A8-A16 dossiers; approval resume; Stage 2/3 auto-progression | `v2/a7-worker-stage-execution` | `V2IMPROVMENT` | worker launch and command manifest tests |
| A8 | Stage Auto-Progression Agent | `### A8 Stage Auto-Progression Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A10-A16 dossiers; manual stage controls | `v2/a8-stage-auto-progression` | `V2IMPROVMENT` | V1-08 continuation and proof gate tests |
| A9 | LangGraph Approval Mapping Agent | `### A9 LangGraph Approval Mapping Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A8, A10-A16 dossiers unless needed for dependency contract; direct graph execution | `v2/a9-langgraph-approval-mapping` | `V2IMPROVMENT` | approval/resume checksum and idempotency tests |
| A10 | Assistant Chat Instruction Agent | `### A10 Assistant Chat Instruction Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A12-A16 dossiers; direct execution/model provider work unless A11 exists | `v2/a10-assistant-chat-instruction` | `V2IMPROVMENT` | assistant and pending action tests |
| A11 | Azure Model Calls & Structured Outputs Agent | `### A11 Azure Model Calls & Structured Outputs Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A10, A12-A16 dossiers; frontend cockpit | `v2/a11-model-calls-structured-outputs` | `V2IMPROVMENT` | schema, audit, redaction, provider error tests |
| A12 | Repair/Proposal Flow Agent | `### A12 Repair/Proposal Flow Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A13-A16 dossiers; legacy source mutation; arbitrary shell | `v2/a12-repair-proposal-flow` | `V2IMPROVMENT` | V1-14/V1-15/V1-17 repair/action tests |
| A13 | Cockpit Frontend Agent | `### A13 Cockpit Frontend Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A14-A16 dossiers; backend implementation; stage-start buttons | `v2/a13-cockpit-frontend` | `V2IMPROVMENT` | cockpit, SSE, approval UI, accessibility tests |
| A14 | UAT/Operator Runbook Agent | `### A14 UAT/Operator Runbook Agent` | 1, 2, 3, 5, 6, 8, 9, 10 | A15-A16 dossiers; product code | `v2/a14-uat-operator-runbook` | `V2IMPROVMENT` | docs checks and `git diff --check` |
| A15 | Security Review Agent | `### A15 Security Review Agent` | all sections, all A1-A13 dossiers, all changed code | broad refactors; feature implementation beyond focused fixes | `v2/a15-security-review` | `V2IMPROVMENT` | targeted security, redaction, approval, worker, frontend env scans |
| A16 | Test Discipline Agent | `### A16 Test Discipline Agent` | all sections, all dossiers, all test sections, final acceptance | feature implementation; weakened skips | `v2/a16-test-discipline` | `V2IMPROVMENT` | backend suite, frontend suite, V2 acceptance gaps |

## 1. Global Idea

V2 turns the Control Tower from a diagnostic job UI into a local migration cockpit. Work is split into small subagent missions so backend settings, local setup parsing, preflight, Azure readiness, migration job creation, worker execution, approvals, assistant, repair, cockpit UI, UAT, security, and tests can advance independently and merge through one integration branch.

All V2 subagent PRs target `V2IMPROVMENT`. `DEMO2` remains the stable V1 baseline.

## 2. Final Product Vision

User flow:

1. Open `/migrations/new`.
2. Paste the old PowerShell local migration config or enter typed fields.
3. Backend parses allowlisted fields only.
4. User runs preflight.
5. Start is enabled only when deterministic local readiness is `READY`.
6. Backend creates a parent migration job and queues Stage 1.
7. Backend automatically advances Stage 1 -> Stage 2 -> Stage 3.
8. LangGraph interrupts become checksum/version guarded decision cards.
9. Assistant explains status, cites evidence, and drafts plan/repair/action requests without executing.
10. Final proof/report is generated from deterministic stage, command, and artifact evidence.

## 3. Non-Negotiable Rules

- `DEMO2` is V1 stable baseline. Do not merge V2 work directly to `DEMO2`.
- `V2IMPROVMENT` is the only V2 integration branch.
- Every V2 subagent starts from latest `origin/V2IMPROVMENT`.
- Every V2 subagent uses `v2/<agent-id>-<short-title>`.
- One branch = one mission. Do not batch unrelated work.
- Read this plan and `improvmentV2.md` before editing.
- Do not implement outside the assigned dossier.
- Do not create Jira issues.
- Stage explicit files only; never `git add .`.
- Never stage `web/control-tower/next-env.d.ts` unless the dossier explicitly owns it.
- Never print secrets/tokens.
- Azure secrets, endpoints, and deployment IDs stay backend-only and redacted.
- Azure model health does not block deterministic migration start.
- Backend owns the locked route and Stage 1 -> Stage 2 -> Stage 3.
- Browser cannot choose commands, Maven goals, working dirs, model deployments, or Stage 2/3 inputs.
- Chatbot cannot execute, approve, write files, change route, change stages, or override proof.
- Worker executes backend-owned command manifests only.
- Model outputs are proposals/evidence only; Maven/tests/proof artifacts are technical truth.
- Use append-only migrations for persistence changes.
- Every subagent runs focused tests, affected regression tests, and hygiene checks.

## 4. Current Repo Baseline

Observed baseline:

- Local `DEMO2` at `1b84b60` includes `improvmentV2.md`.
- `origin/DEMO2` was observed at `d4e0398`; `V2IMPROVMENT` was created from local `DEMO2` at `1b84b60`.
- `web/control-tower/next-env.d.ts` is dirty and unrelated. Do not touch or stage it.
- `OPERATOR_RUNBOOK.md` is not present.
- V1 implementation rules live in `docs/full-implementation/00_IMPLEMENTATION_RULES.md`.
- Existing V1 backend areas: `migration_factory/control_tower/domain`, `application`, `infrastructure/sqlite`, `adapters/fastapi`.
- Existing V1 frontend areas: `web/control-tower/app/jobs`, `web/control-tower/lib`, `web/control-tower/tests`.
- Existing skills: `caveman`, `test-discipline`, `graphify`, `triage`, `requesting-code-review`, `subagent-driven-development`, `to-issues`.

## 5. Full Dependency Map

1. A1 Backend Settings & Redaction Agent
2. A2 Local Env Parser Agent
3. A3 Setup Persistence & Preflight Agent
4. A4 Azure Readiness Agent
5. A5 New Migration Frontend Agent
6. A6 Migration Job Creation Agent
7. A7 Worker Stage Execution Agent
8. A9 LangGraph Approval Mapping Agent
9. A8 Stage Auto-Progression Agent
10. A11 Azure Model Calls & Structured Outputs Agent
11. A10 Assistant Chat Instruction Agent
12. A12 Repair/Proposal Flow Agent
13. A13 Cockpit Frontend Agent
14. A14 UAT/Operator Runbook Agent
15. A15 Security Review Agent
16. A16 Test Discipline Agent

## 6. Subagent Roster

| Agent | Branch | Mission | Depends on |
| --- | --- | --- | --- |
| A1 | `v2/a1-backend-settings-redaction` | Backend settings, env refs, redaction baseline | none |
| A2 | `v2/a2-local-env-parser` | Safe PowerShell env block parser | A1 |
| A3 | `v2/a3-setup-preflight` | Setup persistence and readiness engine | A1, A2 |
| A4 | `v2/a4-azure-readiness` | Redacted Azure role health checks | A1 |
| A5 | `v2/a5-new-migration-frontend` | `/migrations/new` form and gating UI | A2, A3, A4 |
| A6 | `v2/a6-migration-job-creation` | Parent V2 job from ready setup | A3 |
| A7 | `v2/a7-worker-stage-execution` | Worker-owned Stage 1 runner command | A6 |
| A8 | `v2/a8-stage-auto-progression` | Stage 2/3 continuation from previous sandbox | A7, A9 |
| A9 | `v2/a9-langgraph-approval-mapping` | Interrupt to decision card to resume command | A7 |
| A10 | `v2/a10-assistant-chat-instruction` | Chat composer, instructions, pending action draft | A11 |
| A11 | `v2/a11-model-calls-structured-outputs` | Context packs, model audit, strict schemas | A1, A4 |
| A12 | `v2/a12-repair-proposal-flow` | Failure context, repair proposal, approval path | A10, A11 |
| A13 | `v2/a13-cockpit-frontend` | Migration cockpit layout and evidence panels | A6-A12 |
| A14 | `v2/a14-uat-operator-runbook` | Operator runbook and UAT script | A5-A13 |
| A15 | `v2/a15-security-review` | Cross-cutting security/redaction review | A1-A13 |
| A16 | `v2/a16-test-discipline` | Cross-cutting regression and coverage hardening | A1-A15 |

## 7. Detailed Dossiers

### A1 Backend Settings & Redaction Agent

- Mission: Add backend settings primitives and V2 redaction rules for local mode and Azure env refs.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A1` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect only A1-listed files and direct call sites. Do not inspect or implement A2-A16 dossiers, Azure live calls, setup parsing, or UI.
- Implementation entrypoint: open `migration_factory/control_tower/application/redaction.py`, `migration_factory/control_tower/application/context_pack_redaction.py`, `migration_factory/control_tower/adapters/fastapi/app.py`, and `tests/control_tower/test_api_security.py` first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI settings `https://fastapi.tiangolo.com/advanced/settings/`, Microsoft Foundry Agent Service `https://learn.microsoft.com/en-us/azure/foundry/agents/overview`, Azure OpenAI structured outputs `https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A1 Backend Settings & Redaction Agent.
  Branch: v2/a1-backend-settings-redaction
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A1 dossier, 8, 9, 10.
  Do not implement: Azure live calls, setup parser, UI.
  ```
- Source context: `improvmentV2.md:275-368`, `342-353`, `1106-1143`.
- Repo files to inspect: `migration_factory/control_tower/application/redaction.py`, `context_pack_redaction.py`, `adapters/fastapi/app.py`, `adapters/fastapi/security.py`, `infrastructure/sqlite/migrations`, `tests/control_tower/test_api_security.py`.
- Likely files to change: new settings module, redaction helpers, FastAPI dependency wiring, focused tests.
- Existing code to reuse: V1 redaction/filtering, FastAPI app factory, audit/security tests.
- Responsibilities: settings class, env ref projection, no secret values in responses, local bind policy, redacted path display helpers.
- Non-goals: Azure live calls, setup parser, UI.
- APIs/data models/UI contracts: redacted settings projection for `/v1/settings/ai`.
- Security constraints: no `NEXT_PUBLIC_*` secrets; never return endpoint/key/deployment values.
- Tests to write: settings env loading, redacted projections, forbidden secret response checks.
- Commands: `py -m pytest tests/control_tower/test_api_security.py -q -rs --tb=short`, focused new tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`; `graphify` if navigation broadens.
- Branch: `v2/a1-backend-settings-redaction`; PR target `V2IMPROVMENT`.
- Handoff: branch, commit, settings files, tests, risks, next dependency A2/A4.
- Done checklist: env refs only; redaction tests pass; no frontend secret exposure.

### A2 Local Env Parser Agent

- Mission: Parse pasted PowerShell env blocks into typed local setup fields without execution.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A2` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect only parser/API contract paths named here plus A1 redaction interfaces as needed. Do not inspect or implement A3-A16 dossiers, path validation, persistence, or migration start.
- Implementation entrypoint: open `migration_factory/control_tower/adapters/fastapi/app.py`, `migration_factory/control_tower/application/dto.py`, and focused `tests/control_tower` parser/API tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI request bodies `https://fastapi.tiangolo.com/tutorial/body/`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A2 Local Env Parser Agent.
  Branch: v2/a2-local-env-parser
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A2 dossier, 8, 9, 10.
  Do not implement: path validation, persistence, migration start.
  ```
- Source context: `improvmentV2.md:190-274`, `1011-1051`.
- Repo files to inspect: FastAPI request schemas in `adapters/fastapi/app.py`, contracts in `application/dto.py`, tests in `tests/control_tower`.
- Likely files to change: parser service, API schemas/endpoints, parser tests.
- Existing code to reuse: checksum utilities, redaction helpers from A1, FastAPI Pydantic patterns.
- Responsibilities: allowlist keys, ignore `PYTHONPATH`, block Azure secrets/deployments, map flags to typed options, return `ignored_keys` and `blocked_keys`.
- Non-goals: path validation, persistence, migration start.
- APIs/data models/UI contracts: `POST /v1/migration-setups/parse-env`.
- Security constraints: never execute pasted text; do not persist raw env block; blocked keys never include values.
- Tests to write: valid block extraction, quoting variants, blocked Azure keys, ignored arbitrary keys, no command parsing.
- Commands: focused parser tests, API contract tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a2-local-env-parser`; PR target `V2IMPROVMENT`.
- Handoff: parser behavior matrix, commit, tests, risks, dependency A3.
- Done checklist: allowlist enforced; secrets blocked/redacted; no execution path.

### A3 Setup Persistence & Preflight Agent

- Mission: Persist local migration setup drafts and compute deterministic readiness.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A3` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect only setup/preflight persistence and readiness paths named here, plus A1/A2 public contracts as needed. Do not inspect or implement A4-A16 dossiers, Azure health, job start, or UI.
- Implementation entrypoint: open SQLite migrations/repositories, `migration_factory/control_tower/application/runner_readiness.py`, `migration_factory/control_tower/application/v1_route_lock.py`, `migration_factory/control_tower/application/services.py`, and `tests/control_tower/test_create_migration_job.py` first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI request bodies `https://fastapi.tiangolo.com/tutorial/body/`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A3 Setup Persistence & Preflight Agent.
  Branch: v2/a3-setup-preflight
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A3 dossier, 8, 9, 10.
  Do not implement: Azure health, job start, UI.
  ```
- Source context: `improvmentV2.md:369-478`, `705-792`, `1011-1051`.
- Repo files to inspect: SQLite repositories/migrations, `runner_readiness.py`, `v1_route_lock.py`, `services.py`, `tests/control_tower/test_create_migration_job.py`.
- Likely files to change: append-only migration, setup/preflight repositories, application service, FastAPI endpoints, tests.
- Existing code to reuse: runner readiness, route lock, checksum, artifact registry, migrations.
- Responsibilities: setup checksum, path refs/redacted displays, output parent gate, legacy marker gate, AI Hub profile/catalog/policy checks, JDK/Maven checks, route gate.
- Non-goals: Azure health, job start, UI.
- APIs/data models/UI contracts: setup CRUD, preflight, readiness projection.
- Security constraints: local paths accepted only in local operator mode; backend validates before command queue.
- Tests to write: setup checksum gating, stale preflight rejected, bad local config blocks, Azure status ignored for start.
- Commands: focused setup/preflight tests, affected `tests/control_tower/test_create_migration_job.py`, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a3-setup-preflight`; PR target `V2IMPROVMENT`.
- Handoff: schema IDs, endpoint list, tests, risks, dependency A5/A6.
- Done checklist: latest preflight for current checksum required; all deterministic gates modeled.

### A4 Azure Readiness Agent

- Mission: Add redacted Azure model profile and role health checks that do not block deterministic start.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A4` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect only model profile/readiness paths and A1 settings/redaction contracts. Do not inspect or implement A5-A16 dossiers, setup persistence, migration start gating, or assistant/model proposal flows.
- Implementation entrypoint: open `migration_factory/control_tower/domain/model_profiles.py`, `migration_factory/control_tower/infrastructure/sqlite/v1_model_profile_repository.py`, model invocation tests, and `migration_factory/control_tower/adapters/fastapi/app.py` first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI settings `https://fastapi.tiangolo.com/advanced/settings/`, Microsoft Foundry Agent Service `https://learn.microsoft.com/en-us/azure/foundry/agents/overview`, Azure OpenAI structured outputs `https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A4 Azure Readiness Agent.
  Branch: v2/a4-azure-readiness
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A4 dossier, 8, 9, 10.
  Do not implement: full proposal generation, assistant chat, migration start gating.
  ```
- Source context: `improvmentV2.md:275-368`, `479-607`, `793-846`.
- Repo files to inspect: `domain/model_profiles.py`, `v1_model_profile_repository.py`, model invocation tests, FastAPI app.
- Likely files to change: model profile service/repository, health check service, API endpoints, tests.
- Existing code to reuse: V1 model profile registry and invocation audit patterns.
- Responsibilities: role readiness, fallback disabled, structured schema health, redacted error classification.
- Non-goals: full proposal generation, assistant chat.
- APIs/data models/UI contracts: `GET /v1/settings/ai`, `GET /v1/model-profiles`, `POST /v1/model-profiles/{id}/health-check`.
- Security constraints: env refs only; deployment role labels only; no raw prompts/secrets.
- Tests to write: missing env produces redacted blocked/degraded, health errors not start-blocking, no deployment IDs in payload.
- Commands: focused model profile tests, security tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a4-azure-readiness`; PR target `V2IMPROVMENT`.
- Handoff: profile contract, test results, risks, dependency A5/A11.
- Done checklist: Azure status displayable; deterministic start unaffected.

### A5 New Migration Frontend Agent

- Mission: Replace diagnostic form experience with `/migrations/new` setup, parser, readiness, and start gating UI.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A5` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect only frontend routes/contracts/tests named here and backend API contracts from A2/A3/A4. Do not inspect or implement A6-A16 dossiers, backend execution, Azure secret inputs, or cockpit.
- Implementation entrypoint: open `web/control-tower/app/jobs/new`, `web/control-tower/lib/contracts.ts`, `web/control-tower/lib/controlTowerApi.ts`, and related frontend tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, Next.js environment variables `https://nextjs.org/docs/app/guides/environment-variables`, Next.js Server and Client Components `https://nextjs.org/docs/app/getting-started/server-and-client-components`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A5 New Migration Frontend Agent.
  Branch: v2/a5-new-migration-frontend
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A5 dossier, 8, 9, 10.
  Do not implement: cockpit, backend execution, Azure secret inputs.
  ```
- Source context: `improvmentV2.md:111-189`, `190-274`, `1052-1105`.
- Repo files to inspect: `web/control-tower/app/jobs/new`, `lib/contracts.ts`, `lib/controlTowerApi.ts`, frontend tests.
- Likely files to change: new route/components/tests/contracts; possibly preserve old route compatibility.
- Existing code to reuse: current API client, form/test patterns, accessibility tests.
- Responsibilities: env paste, typed fields, readiness panel, Azure warning, disabled start until deterministic gates ready.
- Non-goals: cockpit, backend execution, Azure secret inputs.
- APIs/data models/UI contracts: setup parse/create/preflight/readiness/settings.
- Security constraints: no raw Maven goals/model deployment fields; do not use `NEXT_PUBLIC_*` Azure secrets; do not touch `next-env.d.ts`.
- Tests to write: parser UI, blocked secret warnings, Azure non-blocking warning, start disabled/enabled rules, no forbidden inputs.
- Commands: `cd web/control-tower; npm test -- --run`, focused Vitest files, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a5-new-migration-frontend`; PR target `V2IMPROVMENT`.
- Handoff: UI routes, screenshots if run, tests, risks, dependency A6/A13.
- Done checklist: `/migrations/new` usable; Azure visible but non-blocking; dirty `next-env.d.ts` untouched.

### A6 Migration Job Creation Agent

- Mission: Create V2 parent migration job from a ready setup snapshot.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A6` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect job creation and stage ledger paths named here plus A3 setup/preflight contracts. Do not inspect or implement A7-A16 dossiers, worker launch, or auto-progression.
- Implementation entrypoint: open `migration_factory/control_tower/application/commands.py`, `migration_factory/control_tower/application/services.py`, `migration_factory/control_tower/domain/entities.py`, and stage chain ledger tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI request bodies `https://fastapi.tiangolo.com/tutorial/body/`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A6 Migration Job Creation Agent.
  Branch: v2/a6-migration-job-creation
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A6 dossier, 8, 9, 10.
  Do not implement: launch worker, auto-progression.
  ```
- Source context: `improvmentV2.md:608-704`, `932-970`, `1011-1051`.
- Repo files to inspect: `application/commands.py`, `services.py`, `domain/entities.py`, stage chain ledger repos/tests.
- Likely files to change: job creation command/service, setup binding, stage ledger rows, API endpoint tests.
- Existing code to reuse: V1 job creation, run configuration, stage ledger.
- Responsibilities: require current preflight READY, bind setup checksum, create three stage chain records, reject Azure-only failures as blocker.
- Non-goals: launch worker, auto-progression.
- APIs/data models/UI contracts: `POST /v1/migration-jobs`, job projection.
- Security constraints: no paths/goals/model IDs accepted in job create request.
- Tests to write: ready setup creates parent job, stale checksum rejected, bad preflight rejected, stage inputs fixed.
- Commands: focused job creation tests, affected command/query tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a6-migration-job-creation`; PR target `V2IMPROVMENT`.
- Handoff: job projection shape, tests, risks, dependency A7.
- Done checklist: setup-bound parent job exists; route locked.

### A7 Worker Stage Execution Agent

- Mission: Queue and execute backend-owned Stage 1 orchestrator command manifest.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A7` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect worker launch/manifest paths named here plus A6 job contracts. Do not inspect or implement A8-A16 dossiers, approval resume, Stage 2/3 auto-progression, or UI.
- Implementation entrypoint: open `migration_factory/control_tower/domain/manifests.py`, `migration_factory/control_tower/infrastructure/worker_launcher.py`, `migration_factory/control_tower/application/commands.py`, and worker launch tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, LangGraph interrupts `https://docs.langchain.com/oss/python/langgraph/interrupts`, LangGraph persistence `https://docs.langchain.com/oss/python/langgraph/persistence`, GitHub PR checks `https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A7 Worker Stage Execution Agent.
  Branch: v2/a7-worker-stage-execution
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A7 dossier, 8, 9, 10.
  Do not implement: approval resume, Stage 2/3 auto-progression.
  ```
- Source context: `improvmentV2.md:608-704`, especially `610-672`, `694-704`.
- Repo files to inspect: `domain/manifests.py`, `infrastructure/worker_launcher.py`, `application/commands.py`, worker launch tests.
- Likely files to change: command manifest type, worker argv/env builder, stage launch service/tests.
- Existing code to reuse: V1 orchestrator stage command manifest, worker launcher, runner readiness.
- Responsibilities: runner module args, backend-owned env policy, JDK mapping, timeouts/output limits, result artifacts.
- Non-goals: approval resume, Stage 2/3 auto-progression.
- APIs/data models/UI contracts: `POST /v1/migration-jobs/{job_id}/start`.
- Security constraints: browser cannot supply argv/env; no shell; process launch fails closed.
- Tests to write: command persisted before launch, argv/env derived from setup, no raw browser command fields, failure artifact.
- Commands: worker launch focused tests, `py -m pytest tests/control_tower -q -rs --tb=short --maxfail=3` if practical, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a7-worker-stage-execution`; PR target `V2IMPROVMENT`.
- Handoff: manifest examples, tests, risks, dependency A9/A8.
- Done checklist: Stage 1 launch is worker-owned and typed.

### A8 Stage Auto-Progression Agent

- Mission: Automatically queue Stage 2 and Stage 3 from previous stage sandbox after gates pass.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A8` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect continuation/proof/ledger paths named here plus A7/A9 contracts. Do not inspect or implement A10-A16 dossiers, worker process implementation, proof report UI, or manual stage controls.
- Implementation entrypoint: open stage continuation policy, ledger repositories, proof services, and V1-08 tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, LangGraph interrupts `https://docs.langchain.com/oss/python/langgraph/interrupts`, LangGraph persistence `https://docs.langchain.com/oss/python/langgraph/persistence`, GitHub PR checks `https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A8 Stage Auto-Progression Agent.
  Branch: v2/a8-stage-auto-progression
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A8 dossier, 8, 9, 10.
  Do not implement: worker process implementation, proof report UI.
  ```
- Source context: `improvmentV2.md:674-704`, `932-970`, `1348-1377`.
- Repo files to inspect: stage continuation policy, ledger repos, proof services, V1-08 tests.
- Likely files to change: continuation service, ledger status updates, queueing logic/tests.
- Existing code to reuse: V1 stage continuation policy and proof gate services.
- Responsibilities: Stage 2 input = Stage 1 sandbox; Stage 3 input = Stage 2 sandbox; no manual stage buttons.
- Non-goals: worker process implementation, proof report UI.
- APIs/data models/UI contracts: stage timeline continuation status.
- Security constraints: no user-selected Stage 2/3 paths; unclear recovery fails closed.
- Tests to write: auto queue after pass, block on failed/missing sandbox, no Boot 4 path, idempotent continuation.
- Commands: V1-08 affected tests, proof gate tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a8-stage-auto-progression`; PR target `V2IMPROVMENT`.
- Handoff: continuation state machine, tests, risks, dependency A13.
- Done checklist: three-stage automatic chain proven.

### A9 LangGraph Approval Mapping Agent

- Mission: Map orchestrator approval interrupts to Control Tower approvals and resume commands.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A9` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect approval/resume paths named here plus A7 command contracts. Do not inspect or implement A8/A10-A16 dossiers unless needed only for dependency shape; do not run graph execution in HTTP handlers.
- Implementation entrypoint: open `orchestrator/resume.py`, approval repositories, action approval tests, and FastAPI approval endpoints first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, LangGraph interrupts `https://docs.langchain.com/oss/python/langgraph/interrupts`, LangGraph persistence `https://docs.langchain.com/oss/python/langgraph/persistence`, GitHub PR checks `https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A9 LangGraph Approval Mapping Agent.
  Branch: v2/a9-langgraph-approval-mapping
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A9 dossier, 8, 9, 10.
  Do not implement: direct graph execution in HTTP handler, UI implementation.
  ```
- Source context: `improvmentV2.md:608-704`, `971-991`, `1144-1189`.
- Repo files to inspect: `orchestrator/resume.py`, approval repositories, action approval tests, FastAPI approval endpoints.
- Likely files to change: interrupt artifact parser, approval service, resume command queue, tests.
- Existing code to reuse: V1 approvals, privileged action checksum/version patterns.
- Responsibilities: exact checksum card, approve/reject/revise, expected job/stage version, queue resume command only after approval.
- Non-goals: direct graph execution in HTTP handler, UI implementation.
- APIs/data models/UI contracts: approval projection and approve/reject endpoints.
- Security constraints: LLM cannot approve; stale version/checksum rejected; comments stored as artifact/ref.
- Tests to write: approve queues resume, reject pauses/stops, checksum mismatch rejected, duplicate idempotency.
- Commands: V1-07/V1-17 affected tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a9-langgraph-approval-mapping`; PR target `V2IMPROVMENT`.
- Handoff: approval/resume payloads, tests, risks, dependency A8/A13.
- Done checklist: interrupts become durable decision cards.

### A10 Assistant Chat Instruction Agent

- Mission: Add durable assistant messages, user instructions, and typed pending action drafts without execution.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A10` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect assistant/action paths named here plus A11 public contracts if merged. Do not inspect or implement A12-A16 dossiers, direct execution, approval, or real model provider work unless A11 exists.
- Implementation entrypoint: open `assistant_message_service.py`, `assistant_tools.py`, assistant tests, and privileged action services/tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI request bodies `https://fastapi.tiangolo.com/tutorial/body/`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A10 Assistant Chat Instruction Agent.
  Branch: v2/a10-assistant-chat-instruction
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A10 dossier, 8, 9, 10.
  Do not implement: direct execution, approval authority, real model provider work unless A11 exists.
  ```
- Source context: `improvmentV2.md:479-607`, `910-931`, `1011-1051`, `1052-1105`.
- Repo files to inspect: `assistant_message_service.py`, `assistant_tools.py`, assistant tests, privileged actions.
- Likely files to change: assistant message/action services, API endpoints, frontend chat component/tests if scoped.
- Existing code to reuse: V1 read-only assistant tools and redaction.
- Responsibilities: composer API, intent routing, plan/repair instruction artifacts, action request drafts, SSE messages.
- Non-goals: direct execution, real model provider work unless A11 exists.
- APIs/data models/UI contracts: assistant messages, stream, plan/repair instruction endpoints.
- Security constraints: read tools cannot mutate; action tools create pending actions only; content redacted.
- Tests to write: instruction stored, action draft created not executed, forbidden capabilities absent, redaction.
- Commands: assistant focused tests, action tests as affected, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a10-assistant-chat-instruction`; PR target `V2IMPROVMENT`.
- Handoff: assistant contracts, tests, risks, dependency A12/A13.
- Done checklist: chatbot can guide/request, not act.

### A11 Azure Model Calls & Structured Outputs Agent

- Mission: Build context packs, model-call audit, and strict structured output schema flow.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A11` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect model/context/audit paths named here plus A1/A4 settings and health contracts. Do not inspect or implement A10/A12-A16 dossiers, frontend cockpit, or repair application.
- Implementation entrypoint: open `context_packs.py`, `context_pack_redaction.py`, `plan_proposals.py`, `plan_reviews.py`, `repairs.py`, and model invocation audit tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI settings `https://fastapi.tiangolo.com/advanced/settings/`, Microsoft Foundry Agent Service `https://learn.microsoft.com/en-us/azure/foundry/agents/overview`, Azure OpenAI structured outputs `https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A11 Azure Model Calls & Structured Outputs Agent.
  Branch: v2/a11-model-calls-structured-outputs
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A11 dossier, 8, 9, 10.
  Do not implement: frontend cockpit, repair application.
  ```
- Source context: `improvmentV2.md:479-607`, `847-909`, `1011-1051`.
- Repo files to inspect: `context_packs.py`, `context_pack_redaction.py`, `plan_proposals.py`, `plan_reviews.py`, `repairs.py`, model invocation audit.
- Likely files to change: schema definitions, model provider adapter, audit repositories, tests.
- Existing code to reuse: V1 model invocations, context packs, fake proposal flow as temporary seam.
- Responsibilities: PlanProposal, RepairProposal, ReviewerCritique, ActionRequest, AssistantAnswer schemas; token budgets; redaction report; response artifacts.
- Non-goals: frontend cockpit, repair application.
- APIs/data models/UI contracts: model calls list, context pack list, proposal endpoints.
- Security constraints: no raw prompts with secrets; deployment role label only; strict `additionalProperties: false` where supported.
- Tests to write: schema validation, audit fields, context redaction, provider errors redacted.
- Commands: context/model tests, security tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a11-model-calls-structured-outputs`; PR target `V2IMPROVMENT`.
- Handoff: schema IDs/checksums, tests, risks, dependency A10/A12.
- Done checklist: model output is structured, audited, redacted.

### A12 Repair/Proposal Flow Agent

- Mission: Convert failed stage evidence into bounded repair proposals and approved sandbox actions.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A12` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect repair/proposal/action paths named here plus A10/A11 contracts. Do not inspect or implement A13-A16 dossiers, legacy source mutation, arbitrary shell, or unapproved writes.
- Implementation entrypoint: open `repairs.py`, `patch_policy.py`, patch apply/validate/rollback services, and repair panel/action approval tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, Azure OpenAI structured outputs `https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A12 Repair/Proposal Flow Agent.
  Branch: v2/a12-repair-proposal-flow
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A12 dossier, 8, 9, 10.
  Do not implement: legacy source mutation, arbitrary shell.
  ```
- Source context: `improvmentV2.md:1144-1189`, `971-991`, `992-1010`.
- Repo files to inspect: `repairs.py`, `patch_policy.py`, patch apply/validate/rollback services, repair panel tests.
- Likely files to change: repair workflow services, proposal storage, action approval integration, tests.
- Existing code to reuse: V1 repair classification, generated repair proposals, patch policy, snapshot/apply/Maven/rollback.
- Responsibilities: failed command context pack, repair proposal, reviewer critique, policy validation, exact approval, rollback limit.
- Non-goals: legacy source mutation, arbitrary shell.
- APIs/data models/UI contracts: proposals/actions/repairs/proof impact projections.
- Security constraints: sandbox-only writes; approval checksum required; model cannot apply patch.
- Tests to write: failed command creates proposal path, policy gates unsafe patch, approved action mutates sandbox only, rollback on failure.
- Commands: V1-14/V1-15/V1-17 affected tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a12-repair-proposal-flow`; PR target `V2IMPROVMENT`.
- Handoff: repair state machine, tests, risks, dependency A13.
- Done checklist: repair loop is typed, approved, sandboxed.

### A13 Cockpit Frontend Agent

- Mission: Build migration cockpit UI for stage progress, decisions, assistant, evidence, repairs, proof, and report.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A13` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect cockpit frontend routes/contracts/tests named here plus public API contracts from A6-A12. Do not inspect or implement A14-A16 dossiers, backend implementation, direct execution buttons, or stage-start controls.
- Implementation entrypoint: open `web/control-tower/app/jobs/[jobId]`, existing panels/tests, `web/control-tower/lib/contracts.ts`, and `web/control-tower/lib/controlTowerApi.ts` first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, Next.js environment variables `https://nextjs.org/docs/app/guides/environment-variables`, Next.js Server and Client Components `https://nextjs.org/docs/app/getting-started/server-and-client-components`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A13 Cockpit Frontend Agent.
  Branch: v2/a13-cockpit-frontend
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A13 dossier, 8, 9, 10.
  Do not implement: backend implementation, direct execution buttons, stage-start controls.
  ```
- Source context: `improvmentV2.md:160-189`, `1052-1105`, `1218-1264`.
- Repo files to inspect: `web/control-tower/app/jobs/[jobId]`, panels/tests, `lib/contracts.ts`, `lib/controlTowerApi.ts`.
- Likely files to change: `/migrations/[jobId]` route, cockpit components, API client/contracts, tests.
- Existing code to reuse: existing stage timeline, runner evidence, model activity, approvals/actions, repairs, assistant, proof/report panels.
- Responsibilities: migration-native layout, SSE cursor recovery, decision cards, assistant composer, evidence tabs.
- Non-goals: backend implementation, direct execution buttons.
- APIs/data models/UI contracts: job projection, stages, events, commands/logs, assistant, actions, proof/report.
- Security constraints: no raw secrets/deployments; no stage-start buttons; approval cards show exact checksum.
- Tests to write: three stages visible, auto-progression copy, checksum required, no forbidden controls, SSE cursor preservation.
- Commands: frontend focused tests, `npm test -- --run`, accessibility tests, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`.
- Branch: `v2/a13-cockpit-frontend`; PR target `V2IMPROVMENT`.
- Handoff: UI routes, tests, risks, dependency A14/A15.
- Done checklist: cockpit reflects backend state without taking authority.

### A14 UAT/Operator Runbook Agent

- Mission: Create operator runbook and UAT checklist for local V2 flow.
- Read first: `1. Global Idea`, `2. Final Product Vision`, `3. Non-Negotiable Rules`, `5. Full Dependency Map`, `6. Subagent Roster`, this `A14` dossier, `8. Integration Gates`, `9. Testing Strategy`, `10. Review Gates`.
- Context boundary: inspect only operator/runbook docs and current endpoint/UI paths needed for accurate instructions. Do not inspect or implement A15-A16 dossiers or product code.
- Implementation entrypoint: open `docs/system/09-how-to-run.md`, README docs, and existing operator docs first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, Next.js environment variables `https://nextjs.org/docs/app/guides/environment-variables`, FastAPI settings `https://fastapi.tiangolo.com/advanced/settings/`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A14 UAT/Operator Runbook Agent.
  Branch: v2/a14-uat-operator-runbook
  Base: V2IMPROVMENT
  Read: sections 1, 2, 3, 5, 6, A14 dossier, 8, 9, 10.
  Do not implement: product code, tests beyond docs checks.
  ```
- Source context: `improvmentV2.md:1190-1264`, `1265-1290`, `1348-1377`.
- Repo files to inspect: `docs/system/09-how-to-run.md`, README docs, any operator docs.
- Likely files to change: new `OPERATOR_RUNBOOK.md` or docs path agreed by branch, UAT docs.
- Existing code to reuse: terminal runner/resume instructions from system docs.
- Responsibilities: backend/frontend startup, `.env` guidance, local path examples, UAT steps, troubleshooting.
- Non-goals: product code or tests except docs link checks if available.
- APIs/data models/UI contracts: document current endpoints and UI paths only.
- Security constraints: placeholders only; no real secrets; Azure values backend-only.
- Tests to write: docs lint if present; otherwise `git diff --check`.
- Commands: `git diff --check`, optional docs checks.
- Skills: `caveman`, `test-discipline`.
- Branch: `v2/a14-uat-operator-runbook`; PR target `V2IMPROVMENT`.
- Handoff: runbook path, test/check output, risks, next dependency A15.
- Done checklist: operator can follow local setup without exposing secrets.

### A15 Security Review Agent

- Mission: Review V2 integration for trust boundaries, redaction, approval, worker, model, and frontend secret exposure.
- Read first: all sections in this document, all A1-A13 dossiers, `11. Final V2 Acceptance`, and all changed code in merged V2 branches under review.
- Context boundary: inspect broadly for security only. Do not do broad refactors or feature implementation beyond focused blocker fixes and missing security regression tests.
- Implementation entrypoint: open V2-touched files from git history, security tests, redaction helpers, approval/action services, worker launch code, model/context code, and frontend env usage first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, FastAPI settings `https://fastapi.tiangolo.com/advanced/settings/`, Next.js environment variables `https://nextjs.org/docs/app/guides/environment-variables`, Microsoft Foundry Agent Service `https://learn.microsoft.com/en-us/azure/foundry/agents/overview`, Azure OpenAI structured outputs `https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs`, LangGraph interrupts `https://docs.langchain.com/oss/python/langgraph/interrupts`, LangGraph persistence `https://docs.langchain.com/oss/python/langgraph/persistence`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A15 Security Review Agent.
  Branch: v2/a15-security-review
  Base: V2IMPROVMENT
  Read: all sections, A1-A13 dossiers, final acceptance, and all V2 changed code.
  Do not implement: broad refactors or new features beyond focused security fixes.
  ```
- Source context: `improvmentV2.md:1106-1143`, plus all implementation sections.
- Repo files to inspect: all V2-touched files, security tests, redaction helpers, frontend env usage.
- Likely files to change: only focused fixes; otherwise review report docs/comments if requested.
- Existing code to reuse: API security tests, redaction tests, approval/action tests.
- Responsibilities: find blockers, verify no secret/deployment leaks, verify route/stage authority, verify checksum/version guards.
- Non-goals: broad refactors, feature implementation.
- APIs/data models/UI contracts: all V2 browser-facing payloads.
- Security constraints: apply all non-negotiable rules.
- Tests to write: missing security regression tests found during review.
- Commands: targeted security tests, `rg -n "NEXT_PUBLIC_.*(AZURE|OPENAI|DEPLOY|KEY|TOKEN|SECRET)" web/control-tower`, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `requesting-code-review`, `graphify` if broad.
- Branch: `v2/a15-security-review`; PR target `V2IMPROVMENT`.
- Handoff: findings with file/line, fixes/tests, residual risks, dependency A16.
- Done checklist: no high/critical security findings remain.

### A16 Test Discipline Agent

- Mission: Harden cross-cutting tests and verify V2 integration readiness.
- Read first: all sections in this document, all dossiers, all `Tests to write` and `Commands` fields, `9. Testing Strategy`, and `11. Final V2 Acceptance`.
- Context boundary: inspect broadly for test coverage and baseline classification only. Do not implement product features, weaken tests, or hide skips.
- Implementation entrypoint: open `tests/control_tower`, `web/control-tower/tests`, V2 changed files, and existing V1 focused tests first.
- Web/official docs to check: OpenAI Codex AGENTS.md `https://developers.openai.com/codex/guides/agents-md`, OpenAI Codex Subagents `https://developers.openai.com/codex/subagents`, OpenAI Codex Skills `https://developers.openai.com/codex/skills`, GitHub PR checks `https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests`, Next.js Server and Client Components `https://nextjs.org/docs/app/getting-started/server-and-client-components`, FastAPI request bodies `https://fastapi.tiangolo.com/tutorial/body/`.
- Prompt starter for this subagent:
  ```text
  /goal Implement A16 Test Discipline Agent.
  Branch: v2/a16-test-discipline
  Base: V2IMPROVMENT
  Read: all sections, all dossiers, all test sections, testing strategy, final acceptance.
  Do not implement: product features or weakened skips.
  ```
- Source context: `improvmentV2.md:1093-1105`, `1190-1264`, `1348-1377`.
- Repo files to inspect: `tests/control_tower`, `web/control-tower/tests`, V2 changed files.
- Likely files to change: missing or flaky tests only.
- Existing code to reuse: V1 focused tests and frontend Vitest patterns.
- Responsibilities: focused + affected suite matrix, baseline failure classification, hygiene checks, final evidence format.
- Non-goals: feature implementation.
- APIs/data models/UI contracts: cover final V2 acceptance.
- Security constraints: do not weaken tests or hide skips.
- Tests to write: gaps in parser/preflight/Azure/cockpit/assistant/approval/security acceptance.
- Commands: focused backend tests, `py -m pytest tests/control_tower -q -rs --tb=short --maxfail=3`, frontend `npm test -- --run`, `git diff --check`.
- Skills: `caveman`, `test-discipline`, `graphify` if broad.
- Branch: `v2/a16-test-discipline`; PR target `V2IMPROVMENT`.
- Handoff: exact commands/results, baseline failures, files changed, residual risks.
- Done checklist: V2 acceptance covered by tests or documented UAT.

## 8. Integration Gates

- Gate 1: A1-A4 merged; backend settings, parser, preflight, and Azure readiness contracts stable.
- Gate 2: A5-A7 merged; New Migration can parse, preflight, create job, and queue Stage 1.
- Gate 3: A8-A9 merged; approvals/resume and Stage 2/3 auto-progression work.
- Gate 4: A10-A12 merged; assistant/model/repair flows are structured, audited, redacted, and non-executing until approved.
- Gate 5: A13-A16 merged; cockpit, runbook, security review, and tests pass.

## 9. Testing Strategy

Each subagent must run:

- Focused tests for its changed service/component.
- Affected regression tests from V1 areas it touched.
- `git diff --check`.
- `git diff --cached --check` before commit.
- `git status --short` before and after staging.

Backend default:

```powershell
py -m pytest tests/control_tower/<focused_test>.py -q -rs --tb=short
py -m pytest tests/control_tower -q -rs --tb=short --maxfail=3
```

Frontend default:

```powershell
cd web\control-tower
npm test -- --run
```

Never call a failure unrelated without baseline evidence.

## 10. Review Gates

- PR title names agent and mission.
- PR base is `V2IMPROVMENT`.
- PR body includes summary, tests, risks, changed files, next dependency.
- No unrelated dirty files staged.
- No `web/control-tower/next-env.d.ts` unless explicitly owned.
- No Azure secrets, endpoints, or raw deployments in browser payloads.
- Security-sensitive agents request review before merge.
- Integration owner verifies merge order against dependency map.

## 11. Final V2 Acceptance

V2 is accepted only when:

- User can paste terminal-style local config into UI.
- Backend parses allowlisted local setup fields only.
- Backend validates paths/tools before command queue.
- Azure secrets/deployments are not accepted by New Migration.
- Start requires deterministic gates `READY`.
- Azure health is visible but does not block deterministic start.
- Parent migration job starts Stage 1 through worker-owned manifest.
- User does not manually start Stage 2 or Stage 3.
- Backend auto-progresses Stage 1 -> Stage 2 -> Stage 3.
- LangGraph approvals are checksum/version guarded.
- Assistant can explain, cite evidence, and create typed pending action requests.
- Assistant cannot execute, approve, write, choose raw paths/goals/deployments, change route/stages, or override proof.
- Failures produce bounded context packs and structured repair flow.
- Reviewer/backend policy gates precede human approval.
- Legacy source checksum remains unchanged.
- Final proof/report comes from deterministic evidence.
- Logs/events/artifacts/model calls/context/assistant/report outputs are redacted.
- Final report states achieved proof level and `production_ready_not_claimed`.

## Official References Checked

- OpenAI Codex Subagents: https://developers.openai.com/codex/subagents
- OpenAI Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- OpenAI Codex Skills: https://developers.openai.com/codex/skills
- OpenAI Codex Rules: https://developers.openai.com/codex/rules
- OpenAI Codex Worktrees: https://developers.openai.com/codex/app/worktrees
- Git branches: https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell
- GitHub pull requests: https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests
- GitHub branches: https://docs.github.com/articles/about-branches
- FastAPI settings: https://fastapi.tiangolo.com/advanced/settings/
- FastAPI request bodies: https://fastapi.tiangolo.com/tutorial/body/
- Next.js environment variables: https://nextjs.org/docs/app/guides/environment-variables
- Next.js Server and Client Components: https://nextjs.org/docs/app/getting-started/server-and-client-components
- Microsoft Foundry Agent Service: https://learn.microsoft.com/en-us/azure/foundry/agents/overview
- Azure OpenAI structured outputs: https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
