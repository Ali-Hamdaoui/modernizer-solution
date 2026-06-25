# AGENTS.md - DEMO3 Implementation Work

This file is the entrypoint for Codex and dev-agent work on DEMO3 / AMF Sprint DEMO 3.

## Hard Preflight

At the start of any new DEMO3 task or subtask, before creating the task branch and before changing files:

```powershell
git fetch origin
git status --short
```

If the working tree is dirty, stop and report the dirty files. Do not switch branches or modify files until the user resolves or explicitly authorizes handling them.

Then:

```powershell
git switch demov3
git pull --ff-only origin demov3
git status --short
git branch --show-current
```

Proceed only when the current branch is `demov3` and the working tree is clean.

## Current Sprint Source Of Truth

Current sprint: DEMO3 / AMF Sprint DEMO 3

Base and merge target: `demov3`

The DEMO3 product spine is:

- F0 - Pre-feature codebase cleanup
- F1 - Agent checkpoints and user decisions
- F2 - Deterministic artifact + primary LLM + reviewer LLM
- F3 - Target profile control
- F4 - Start from current app state
- F5 - Build/Test Repair Agent review loop

The `docs/sprintdemo3/` feature folders are the implementation contract for DEMO3 work.

## Branch Rules

Every task or subtask starts from latest `demov3`:

```powershell
git switch demov3
git pull --ff-only origin demov3
git switch -c <feature-or-task-branch>
```

Work only on the assigned Jira task scope. Completed task branches merge back into `demov3` only after review.

Before recommending merge into `demov3`, run `requesting-code-review` when applicable and include review evidence.

Forbidden bases:

- `CSV-update`
- `chatbot-optimization`
- stale feature branches
- old DEMO2 branches
- any branch other than `demov3` for DEMO3 implementation kickoff

## Task-Driven Reading Order

Read enough of these files to orient:

- `docs/DEMO3/PRD.md`
- `docs/sprintdemo3/INDEX.md`
- `docs/sprintdemo3/BACKLOG.md`
- `docs/sprintdemo3/TASKS.md`
- `docs/sprintdemo3/ROADMAP.md`
- `docs/sprintdemo3/ARCHITECTURE.md`
- `docs/sprintdemo3/RISKS.md`
- `docs/sprintdemo3/F0-F5-MAPPING.md`

Then locate the Jira issue in `BACKLOG.md` or `TASKS.md`.

Fully read the assigned feature folder:

- `README.md`
- `STORY.md`
- `TASKS.md`

Do not reread the full sprint documentation set unless needed. Use global docs to orient, then fully read the assigned feature folder and directly relevant docs.

Read stable integration docs only when relevant:

- `docs/foundry-only-prd-codebase-findings.md`
- `docs/STABLE_INTEGRATION_AUDIT_REPORT.md`
- `docs/STABLE_INTEGRATION_IMPLEMENTATION_PLAYBOOK.md`
- `docs/STABLE_INTEGRATION_RERUN_AUDIT_REPORT.md`

## Jira And Feature Mapping

- AMF-232 / F0 -> `docs/sprintdemo3/00-pre-feature-cleanup/`
- AMF-233 / F1 -> `docs/sprintdemo3/01-agent-checkpoints/`
- AMF-234 / F2 -> `docs/sprintdemo3/02-llm-review-chain/`
- AMF-235 / F3 -> `docs/sprintdemo3/03-profile-targeting/`
- AMF-236 / F4 -> `docs/sprintdemo3/04-source-profile-start/`
- AMF-237 / F5 -> `docs/sprintdemo3/05-build-test-repair-agent-review-loop/`

Every implementation task starts from a Jira issue key. Before changing files, identify:

- Jira issue key
- Parent story
- Feature lane
- Matching feature folder
- `README.md`
- `STORY.md`
- `TASKS.md`
- Task or subtask block inside `TASKS.md`

Codex must not update Jira status, transition Jira issues, or post Jira comments unless the user explicitly asks. When a task is finished, prepare a recommended Jira update for a human to apply manually.

Jira Done requires evidence, not just "code finished."

## Verified Tech Stack And Commands

Only use commands proven by repository files. If a command is not listed here, inspect repo config before using it.

Install commands are documented for setup, but agents must ask before running install commands unless the user explicitly requested setup.

Backend setup, verified from `pyproject.toml` and `requirements.txt`:

```powershell
python -m pip install -r requirements.txt
```

Backend focused tests, verified from `pyproject.toml` optional test dependencies:

```powershell
python -m pytest <focused-test-file-or-node>
```

Frontend setup, verified from `web/control-tower/package.json`:

```powershell
npm --prefix web/control-tower install
```

Frontend focused tests, verified from `web/control-tower/package.json`:

```powershell
npm --prefix web/control-tower test -- <focused-test-file>
npm --prefix web/control-tower run typecheck
npm --prefix web/control-tower run build
```

Docs-only checks:

```powershell
git diff --check
git status --short
```

Git checks:

```powershell
git status --short
git diff --name-only
git diff --check
```

No root `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `Dockerfile`, `docker-compose.yml`, `docker-compose.yaml`, `pytest.ini`, or `.github/workflows/` was present when this file was written. Verify before using package managers, Docker commands, workflow assumptions, or pytest config assumptions not listed above.

## Repository Map

- `migration_factory/control_tower/adapters/fastapi/` - FastAPI control surface.
- `migration_factory/control_tower/application/` - Control Tower application services and orchestration policy.
- `migration_factory/control_tower/schemas/` - API and domain schemas.
- `migration_factory/control_tower/infrastructure/sqlite/` - SQLite persistence and migrations.
- `migration_factory/agents/` - deterministic migration agents.
- `web/control-tower/` - frontend application.
- `docs/DEMO3/` - DEMO3 product requirements.
- `docs/sprintdemo3/` - sprint backlog, architecture, risks, roadmap, and feature folders.

## Core Architecture

```text
FastAPI backend
-> deterministic agents
-> primary LLM
-> reviewer LLM
-> final Markdown artifact
-> stored artifact/checkpoint
-> user decision
-> next pipeline step
```

## Core Rule

A model reviews another model.

The Reviewer LLM is mandatory for supported model-required outputs. Deterministic artifacts ground model work, but deterministic fallback alone does not satisfy reviewed-output requirements.

## Three-Tier Permission Model

Allowed without asking:

- read, list, and search files
- inspect docs and config
- run focused tests for changed files
- run `git status`, `git diff`, and `git diff --check`
- create docs/proposal files when the task asks

Ask first:

- install dependencies
- add dependencies
- run full test suites
- delete or move files
- create or modify DB migrations
- change public API contracts
- touch files outside assigned scope
- make network calls outside normal repo, Jira, or web research tasks

Never without explicit user instruction:

- push
- commit
- merge branches
- transition or comment Jira issues
- use `CSV-update` as a base
- cherry-pick `CSV-update` runtime code
- expose `sandbox_path`, argv, env, raw commands, provider, endpoint, deployment, or env refs

## Task Scope Lock

If implementation requires touching files not listed in the task docs, stop and explain why before changing them.

Do not touch files outside the assigned task without explaining why.

## Completion Gate

Recommend Jira status `Done` only if:

- assigned task and subtasks are complete
- acceptance criteria are checked
- focused tests pass, or N/A is explained
- `git diff --check` passes
- diff is confined to assigned scope, or the exception is explained
- final report includes evidence

If these are not true, recommend `Keep In Progress`, `Needs Review`, or `Blocked`.

## Completion Report

At the end of every task or subtask, Codex must output:

```text
Jira issue:
Parent story:
Feature folder:
Branch:
Commit:
Files changed:
Tests run:
Acceptance criteria covered:
Subtasks completed:
Remaining risks:
Recommended Jira status: Done / Needs Review / Keep In Progress / Blocked
Manual Jira comment:
```

Manual Jira comment template:

```text
Completed <issue key> - <task title>.

Evidence:
- Branch:
- Commit:
- Files changed:
- Tests run:
- Acceptance criteria covered:
- Subtasks completed:

Result:
- Recommended status:
- Remaining risks:
- Follow-up issues:
```

## Generated Artifact Rule

Do not commit generated migration reports, PDFs, runtime JSON outputs, sandbox outputs, DB files, local audit artifacts, caches, logs, or build outputs unless the task explicitly asks for documentation artifacts.

## SQLite Migration Rule

Before adding a DB migration:

- inspect existing migration numbers on `demov3`
- use the next available number
- never copy migration numbers from stale branches
- add or adjust migration tests if migration behavior changes

## Runtime And Product Boundaries

DEMO3 product workflow is backend/API-governed:

- chatbot interprets
- human decides
- backend validates, persists, executes, and proves with artifacts

The frontend and chatbot must not execute commands, choose paths, provide argv/env, apply patches, mutate source, skip proof, or expose backend runtime internals as product fields.

## Feature Dependency Rules

- F0 runtime can start first.
- F1/F2 runtime waits for F0 cleanup and model boundary safety.
- F3 can proceed if isolated.
- F4 depends on F3.
- F5 runtime is blocked until F0, F1, F2, and F3/F4 foundations are merged.
- F5 work before those foundations is design, schema, and test-plan only.

## Forbidden Actions

- Do not use `CSV-update` as a base.
- Do not merge `CSV-update`.
- Do not cherry-pick `CSV-update` runtime code.
- Do not use `chatbot-optimization` as sprint base.
- Do not reintroduce old DEMO2 / Stage 4-first / Copilot / TUI product workflow language.
- Do not expose `sandbox_path`, argv, env, raw commands, provider, endpoint, deployment, or env refs as public product fields.
- Do not implement F5 runtime before F0/F1/F2/F3/F4 foundations are ready.
- Do not update Jira status unless the user explicitly asks.
- Do not transition Jira issues unless the user explicitly asks.
- Do not push unless the user explicitly asks.
- Do not commit unless the user explicitly asks.

## Testing Rule

- Run focused tests only.
- Prefer tests related to changed files.
- Run `git diff --check`.
- Do not run broad or full suites unless the task requires it.

For docs-only tasks, focused verification may be limited to `git diff --check` and `git status --short`.

## Local Agent Skills

No `.agent/` folder is present in this repository checkout.

Discovered `.agents/skills/` skills:

- `graphify` - Use for codebase, architecture, file relationship, or project-content questions.
- `requesting-code-review` - Use when completing implementation work, major features, or before merging.
- `setup-matt-pocock-skills` - Use only when setting up or repairing the repository agent-skill context.
- `subagent-driven-development` - Use when executing implementation plans with independent tasks in the current session.
- `test-discipline` - Use when adding, changing, reviewing, or verifying tests and final evidence.
- `to-issues` - Use when converting plans/specs/PRDs into issue-tracker tasks.
- `triage` - Use when triaging issues or preparing issue workflow.

Agents must read the skill instruction file before using a skill. Use skills only when the trigger matches. Do not invoke skills just because they exist. Do not invent skill names.
