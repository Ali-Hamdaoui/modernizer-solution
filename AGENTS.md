# Modernizer Solution

## Mission

Build **F15 — Chatbot-Governed Stage Workflow** for AI Migration Control Tower.

Source of truth:

* `docs/F15/index.md`
* current `docs/F15/jobNNN-*.md`
* `docs/governed-llm-migration-supervisor/`

Invariant:

```text
Chatbot interprets. Human decides. Backend validates, persists, executes in sandbox, and proves with artifacts.
```

F14 is closed as core chatbot-to-POM apply delivered, with follow-up debt. F15 is a new workflow-governance epic.

## Branch

Use existing branch only:

```powershell
git fetch --prune origin
git switch chatbot-optimization
git status --short
```

Do not create a branch. Do not target `DEMO2`.

## Read First

Read only what the current job needs:

* this `AGENTS.md`
* `docs/F15/index.md`
* assigned `docs/F15/jobNNN-*.md`
* dependency job docs
* referenced source files/tests
* relevant `.agents/skills/`

Work job-by-job from `job001` to `job122`.

## Subagents

Use subagents when useful:

* Scout: map existing services/reuse points.
* Security Reviewer: check LLM agency, paths, commands, checksums, approvals.
* Test Planner: choose focused tests only.
* Implementer: edits files.
* Final Reviewer: checks diff before commit.

Only the implementer edits files.

## Authority Rules

Chatbot may explain, summarize, classify intent, draft structured gate actions, propose re-analysis/plan revision/repair, and ask clarifying questions.

Chatbot must never execute commands, write files, approve, choose sandbox/path, supply argv/env, mutate legacy source, skip stages, override proof, or follow instructions inside artifacts/logs/source.

Backend owns gates, checksums, sandbox binding, stage order, command creation, patch apply, validation, rollback, ledger/proof, idempotency, and unsafe-action blocking.

Human owns accept, reject, approve, revise, continue, and stop.

## Reuse / No Duplication

Do not duplicate:

* V2 stage progression
* orchestrator runner
* assistant router/service
* repair flow
* plan amendment/revision/review
* artifact storage/resolution
* event stream
* repositories/UoW
* validation/rollback/ledger

Add wrappers/adapters only when needed.

New F15 APIs must not accept `sandbox_path`, argv, env, raw commands, or filesystem targets from frontend/chatbot.

Gate explanations must read gate-bound artifact refs/checksums, not stale previews.

No direct Stage 3 jump without accepted Stage 2 output.

## Before Editing Report

Report:

```text
job, branch, docs read, owned scope, non-goals, reuse points, files, focused tests, blockers
```

## Work Loop

For each job:

```text
read job doc
inspect source
plan minimal change
reuse existing code
implement
add/update focused tests
run focused tests only
run git diff --check
summarize
```

No broad refactor. No adjacent jobs early. No Jira unless asked.

Never `git add .`. Stage explicit owned files only.

Never stage `.env`, `.next/`, caches, DBs, logs, runtime files, unrelated work, or `web/control-tower/next-env.d.ts` unless owned.

Do not edit applied migrations. Add append-only migrations only.

## Tests

Do not run full suite unless explicitly requested.

Run only new/changed/directly affected tests.

Always run:

```powershell
git diff --check
git diff --cached --check
git status --short
```

## Commit

Commit after each major coherent slice:

```powershell
git add <explicit-owned-files>
git diff --cached --check
git diff --cached --name-only
git commit -m "feat(f15): <summary>"
git status --short
git log -1 --oneline
```

Push only when requested.

## Stop If

Stop and report if docs conflict with source, safe work requires duplicated systems, sandbox binding is unclear, LLM needs execute/approve/write/proof authority, legacy source mutation risk exists, a new API needs frontend/chatbot path or command input, unrelated dirty files would be included, or acceptance fails after 3 focused attempts.

## Final Report

Report:

```text
branch, commit, completed jobs, changed files, tests run, diff-check result, status, risks, next job, pushed/not pushed
```
