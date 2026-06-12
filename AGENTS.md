# Modernizer Solution — Agent Instructions

## Purpose

This repository builds the AI Migration Control Tower and modernization platform.

Work is issue-driven:

* One issue = one branch = one local commit unless blocked.
* The local issue file under `docs/full-implementation/` is the implementation source of truth.
* Jira is tracking only. Do not require Jira access.
* Do not implement adjacent issues, future issues, or cleanup work not explicitly owned by the assigned issue.

## Output Limit

Keep normal agent responses under **1500 tokens**. Be direct. Do not print long analysis, full files, or broad search logs unless asked.

## Required Skills

Before implementation, read and use local skills from `.agents/skills/`:

* use `caveman` for simple, direct, low-token execution discipline
* use `test-discipline` before planning, running, or reporting tests
* use `graphify` only when broad code navigation is needed and `graphify-out/graph.json` exists
* use `triage` only when scope, dependency, or readiness is unclear
* use `requesting-code-review` for security, worker, approval, shell, model, patch, action, or redaction changes
* use `subagent-driven-development` only for complex implementation tasks
* use `to-issues` only for backlog splitting, not normal implementation

## Start Workflow

Always start from latest `DEMO2`.

```powershell
git status --short
git branch --show-current
git switch DEMO2
git pull --ff-only origin DEMO2
git rev-parse --short HEAD
```

If local `DEMO2` is missing:

```powershell
git fetch origin
git switch --track origin/DEMO2
git pull --ff-only origin DEMO2
```

Create or switch to the issue branch:

```powershell
git switch -c amf/<issue-id>-short-title
```

If the branch already exists, switch to it. Do not reset, rebase, force-update, clean, or resolve divergence without approval.

## Issue File Workflow

The assigned work must include a V1 ID, for example `V1-06B1`.

First locate the matching local issue file:

```powershell
Get-ChildItem docs/full-implementation -Filter "<V1-ID>*"
```

Examples:

```powershell
Get-ChildItem docs/full-implementation -Filter "V1-06B1*"
Get-ChildItem docs/full-implementation -Filter "V1-17D*"
Get-ChildItem docs/full-implementation -Filter "V1-18G*"
```

Open the matching file first. Do not search the whole docs tree first.

If no matching issue file exists, stop and report.

## Source of Truth

Use this order:

1. Assigned issue file under `docs/full-implementation/`
2. `docs/full-implementation/00_IMPLEMENTATION_RULES.md`
3. `docs/full-implementation/00_INDEX.md`
4. Direct dependency issue files only when needed
5. Current repository code and tests
6. Relevant `.agents/skills/` files
7. This file

If sources conflict, stop and report. Do not guess.

## Token Discipline

Before editing, read only:

* assigned issue file
* `00_IMPLEMENTATION_RULES.md` only if needed
* `00_INDEX.md` only if file/dependency lookup is unclear
* direct dependency issue files only if readiness is unclear
* targeted source/test files named by the issue
* Graphify output only when needed

Avoid:

* reading all issue files
* recursive docs scans
* broad source scans before reading the issue file
* speculative architecture exploration
* implementing from memory

Use targeted `rg` only after understanding the assigned issue.

## Required Plan Before Editing

Before any code change, produce a short plan:

1. Issue contract:

   * V1 ID
   * issue file path
   * goal
   * owned scope
   * acceptance criteria
   * constraints
   * dependencies

2. Code target:

   * exact files/classes/endpoints likely to change
   * tests likely to add or update

3. Test plan:

   * focused tests from the issue
   * affected regression tests
   * hygiene checks

## Scope Rules

* Change only files required by the assigned issue.
* Do not implement adjacent issues.
* Do not touch unrelated deleted docs.
* Never use `git add .`.
* Stage explicit issue-owned paths only.
* Never commit secrets, logs, local DBs, `.env`, `.next/`, caches, generated runtime files, or another developer's work.

## V1 Invariants

Preserve always:

* Pipeline: `springboot-216-to-356-java21-three-stage`
* Stage 1: Boot `2.7.18`, Java `11`, JDK `java11`
* Stage 2: Boot `3.5.6`, Java `17`, JDK `java17`, input from Stage 1 sandbox
* Stage 3: Boot `3.5.6`, Java `21`, JDK `java21`, input from Stage 2 sandbox
* Boot 4 is not selectable in V1
* `3.5.14` is not execution-relevant in V1
* Browser cannot choose raw paths, Maven goals, shell commands, working dirs, or model deployment IDs
* LLM cannot execute, approve, write files directly, or create proof
* Shell is disabled by default
* Maven/write actions are typed privileged actions only
* Control Tower validates; developer approves; worker executes; Maven/tests prove

## Engineering Rules

Prefer small, typed, testable changes.

Keep domain logic independent from infrastructure and UI.

No direct long-running work in API handlers.

Persist commands before launch. Worker argv/env must be backend-owned. Approval/resume must be checksum/version guarded.

Do not add dependencies unless the issue explicitly requires it.

Do not edit applied migrations. Add append-only migrations only when the issue requires persistence changes.

## Testing

Use `.agents/skills/test-discipline` before test planning and final evidence.

After editing, run:

* focused tests from the issue file
* affected regression tests
* broader suite when practical
* hygiene checks:

```powershell
git diff --check
git diff --cached --check
git status --short
```

Use real output. Do not weaken tests. Report unrelated baseline failures separately.

## Commit Policy

When acceptance passes:

```powershell
git add <explicit issue-owned files>
git diff --cached --check
git diff --cached
git commit -m "<type>(<scope>): <summary>"
git status --short
git log -1 --oneline
```

Do not push unless requested.

## Stop Rules

Stop and report if:

* assigned issue file is missing
* dependency work is incomplete or not merged into `DEMO2`
* acceptance cannot be met after 3 focused attempts
* V1 invariants must change
* arbitrary shell is needed
* LLM execution, approval, direct write authority, or proof creation is needed
* unrelated deleted docs must be restored
* safe explicit staging is impossible
* security risk is unclear
* source-of-truth documents conflict

## Final Report

Report only:

* base branch and commit
* issue branch
* local commit hash
* changed files
* summary
* tests with exact results
* acceptance status
* final `git status --short`
* risks/deviations
* pushed or not pushed
