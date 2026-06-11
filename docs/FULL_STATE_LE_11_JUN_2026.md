# Full State - 11 Jun 2026

Snapshot of the repository as inspected on 2026-06-11.

## How this snapshot was built

- Graphify was refreshed on the current head with `graphify update .`.
- Graph fresh commit: `3cb93923`.
- Corpus size: 337 files, about 166,226 words.
- Graph size: 5,497 nodes, 21,685 edges, 206 communities.
- HTML graph export was skipped because the graph is above the 5,000-node visual limit.
- Backend validation: `py -3 -m pytest -q`
  - Result: 934 passed, 5 skipped, 4 subtests passed.
  - Warning only: FastAPI/Starlette testclient deprecation warning from `httpx`.
- Web validation: `npm test` in `web/control-tower`
  - Result: 1 file passed, 5 tests passed.

Working tree note: there is one unrelated local change in `web/control-tower/next-env.d.ts`; it was not modified for this snapshot.

## Repo Shape

The repository has four major live surfaces:

1. `migration_factory/`
   - The Python migration engine and Control Tower backend.
   - Includes orchestrator, agents, approval, assessment, repair loop, final report, copilot assist, and the Control Tower package.
2. `modernizer-solution-ai-hub/`
   - Profiles, policies, catalogs, schemas, and hub metadata.
3. `web/control-tower/`
   - A thin Next.js client for Control Tower diagnostics.
4. `docs/`
   - Implementation plans, ADRs, issue guides, and architecture notes.

## What Is Actually Built

### Control Tower backend

The strongest built subsystem is `migration_factory/control_tower/`.

It already contains:

- domain state enums and transition rules
- typed domain errors
- command and DTO contracts
- read/write application services
- a transactional SQLite unit of work
- repository implementations
- SQLite migrations
- artifact path normalization and workspace path safety
- a FastAPI adapter with job, event, stream, launch, cancel, timeout, and output endpoints
- a Windows worker launcher and POSIX fallback terminator

The core domain revolves around:

- `JobState`
- `TargetProofLevel`
- `CommandExecutionDto`
- `MigrationJobDto`
- `RunPolicy`
- `ArtifactDto`
- `RunnerProfileDto`
- `CreateMigrationJobService`
- `ControlTowerRegistrationService`

### Orchestrator and agent stack

The older migration engine is still present and substantial:

- `migration_factory/orchestrator/`
- `migration_factory/agents/analysis_agent/`
- `migration_factory/agents/planning_agent/`
- `migration_factory/agents/transformation_agent/`
- `migration_factory/agents/build_agent/`
- `migration_factory/agents/test_agent/`
- `migration_factory/final_report/`
- `migration_factory/assessment/`
- `migration_factory/approval/`
- `migration_factory/repair_loop/`

That means the repo can already support:

- read-only analysis
- planning and approval artifact generation
- sandbox transformation work
- build/test validation
- final report generation
- advisory Copilot-style documentation

### Web control tower

The Next.js app is intentionally thin.

It does three things:

- fetches catalog data for runner profiles, pipelines, and filesystem roots
- creates a foundation diagnostic job
- opens a current-run view that replays committed public events over SSE

The frontend boundary lives mostly in:

- `web/control-tower/lib/controlTowerApi.ts`
- `web/control-tower/lib/contracts.ts`
- `web/control-tower/lib/eventReplay.ts`
- `web/control-tower/app/jobs/new/CreateDiagnosticJobForm.tsx`
- `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx`

## What the Graph Says Is Central

Most connected abstractions in the refreshed graph:

1. `JobState`
2. `TargetProofLevel`
3. `NotFoundError`
4. `CommandExecutionDto`
5. `RunPolicy`
6. `ArtifactDto`
7. `RunnerProfileDto`
8. `MigrationJobDto`
9. `CreateMigrationJobService`
10. `ControlTowerRegistrationService`

The clearest graph communities are:

- job lifecycle and command flow
- immutable DTOs
- application commands and services
- workspace preparation and worker launch
- safe workspace and artifact hashing
- transform execution
- migration ledger and build validation
- frontend boundary

## What Can Be Built Next

The most buildable near-term slices are the ones already backed by schemas, repositories, and tests:

1. Control Tower command lifecycle work
   - bounded stdout/stderr
   - terminal artifact finalization
   - cancel and timeout handling
   - fail-closed restart recovery
2. Web diagnostics improvements
   - current-run state polish
   - event replay behavior
   - create-job flow hardening
3. Migration engine evolution
   - analysis and planning refinement
   - transformation rules
   - build/test evidence
   - final reporting

The repo is not a blank slate. It is already a working platform with layered boundaries.
The safe pattern is to extend one issue slice at a time and keep the backend contracts and tests ahead of the UI.

## How To Build It

Recommended validation order:

```powershell
py -3 -m pytest tests/control_tower -q
py -3 -m pytest -q
cd web/control-tower
npm test
npm run type-check
npm run build
```

Recommended graph refresh after code changes:

```powershell
graphify update .
```

## Short Verdict

This repository is already strong in three places:

- the Control Tower backend model
- the migration engine and agent pipeline
- the basic diagnostics web client

The biggest remaining work is not inventing new structure. It is finishing the operational slices cleanly and keeping each issue isolated.
