# Modernizer Solution Agent Instructions

## Purpose

This repository builds the AI Migration Control Tower and modernization platform.

Work is branch-scoped and source-of-truth driven:

* One assigned issue or V2 subagent mission = one branch = one local commit unless blocked or a review fix is required.
* Jira is tracking only. Do not require Jira access or create Jira issues.
* Do not implement adjacent issues, future issues, or cleanup work not explicitly owned by the assigned task.

## Output Limit

Keep normal agent responses under **1500 tokens**. Be direct. Do not print long analysis, full files, broad search logs, secrets, or tokens unless explicitly asked and safe.

## Required Skills

Before implementation, read and use local skills from `.agents/skills/` when present:

* use `caveman` for simple, direct, low-token execution discipline
* use `test-discipline` before planning, running, or reporting tests
* use `graphify` only when broad code navigation is needed and `graphify-out/graph.json` exists
* use `triage` only when scope, dependency, or readiness is unclear
* use `requesting-code-review` for security, worker, approval, shell, model, patch, action, or redaction changes
* use `subagent-driven-development` only for complex implementation tasks
* use `to-issues` only for backlog splitting, not normal implementation

## Choose Work Mode First

Use **Standard V1/AMF mode** when the task names a V1 issue ID such as `V1-06B1`, references `docs/full-implementation/`, or does not explicitly say it is V2 subagent work.

Use **V2 subagent mode** when the task names a V2 agent such as `A5`, a `v2/<agent-id>-...` branch, `V2IMPROVMENT`, or `V2_IMPLEMENTATION_SUBAGENT_PLAN.md`.

If the mode is unclear, stop and ask one concise question. Do not mix V1 and V2 workflows.

## Standard V1/AMF Mode

### V1 Start Workflow

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

### V1 Issue File Workflow

The assigned work must include a V1 ID, for example `V1-06B1`.

First locate the matching local issue file:

```powershell
Get-ChildItem docs/full-implementation -Filter "<V1-ID>*"
```

Open the matching file first. Do not search the whole docs tree first. If no matching issue file exists, stop and report.

### V1 Source Of Truth

Use this order:

1. Assigned issue file under `docs/full-implementation/`
2. `docs/full-implementation/00_IMPLEMENTATION_RULES.md`
3. `docs/full-implementation/00_INDEX.md`
4. Direct dependency issue files only when needed
5. Current repository code and tests
6. Relevant `.agents/skills/` files
7. This file

If sources conflict, stop and report. Do not guess.

### V1 Branch Pattern

Use:

```text
amf/<issue-id>-short-title
```

## V2 Subagent Mode

`DEMO2` is the stable V1 baseline. Do not merge V2 subagent work directly to `DEMO2`.

`V2IMPROVMENT` is the V2 integration branch and the only PR target for V2 subagent work. Every V2 subagent starts from latest `origin/V2IMPROVMENT`, creates one dedicated branch for one mission, and targets its PR back to `V2IMPROVMENT`.

### V2 Quick Start

```powershell
git fetch --prune origin
git switch V2IMPROVMENT
git pull --ff-only origin V2IMPROVMENT
git switch -c v2/<agent-id>-<short-title>
```

If the branch already exists, switch to it. Do not reset, rebase, force-update, clean, or resolve divergence without approval.

### V2 Branch And PR Rules

* Branch pattern: `v2/<agent-id>-<short-title>`.
* PR base: `V2IMPROVMENT`, never `DEMO2`.
* One subagent mission per branch.
* One local commit per branch unless a review fix is required.
* Do not batch unrelated subagent missions.
* Do not create Jira issues.

### V2 Source Documents

Read in this order:

1. `V2_IMPLEMENTATION_SUBAGENT_PLAN.md`
2. the assigned agent dossier only
3. `improvmentV2.md` only for product vision/context
4. targeted repo files named by the dossier
5. relevant `.agents/skills/` files

Do not read all dossiers unless acting as A15 Security Review Agent, A16 Test Discipline Agent, or explicit V2 integration owner. Do not implement adjacent agent dossiers unless the assigned dossier says it depends on them.

### V2 Non-Negotiables

* Stage explicit files only; never `git add .`.
* Never stage `web/control-tower/next-env.d.ts` unless explicitly owned.
* Never print secrets/tokens.
* Do not expose Azure secrets, endpoints, or deployment IDs to frontend.
* Azure model health does not block deterministic migration start.
* Backend owns the locked route and Stage 1 -> Stage 2 -> Stage 3.
* Browser cannot choose commands, Maven goals, working dirs, model deployments, or Stage 2/3 inputs.
* Chatbot cannot execute, approve, write files, change route, change stages, or override proof.
* Worker executes backend-owned command manifests only.
* Model outputs are proposals/evidence only; Maven/tests/proof artifacts are technical truth.

### V2 Final Report

Every V2 subagent final report must include:

* branch
* commit hash
* PR target
* files changed
* tests with exact results
* risks/deviations
* next dependency
* pushed or not pushed

## Token Discipline

Before editing, read only the assigned source-of-truth documents, direct dependencies, targeted source/test files, and Graphify output only when needed.

Avoid broad docs scans, recursive source scans before reading the assigned source, speculative architecture exploration, and implementation from memory.

Use targeted `rg` only after understanding the assigned task.

## Required Plan Before Editing

Before any code or doc change, produce a short plan:

1. Contract: ID/agent, source file, goal, owned scope, acceptance criteria, constraints, dependencies.
2. Target: exact files/classes/endpoints/docs likely to change.
3. Test plan: focused tests/checks, affected regression tests when relevant, hygiene checks.

## Scope Rules

* Change only files required by the assigned task.
* Do not implement adjacent work.
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

Do not add dependencies unless the assigned task explicitly requires it.

Do not edit applied migrations. Add append-only migrations only when the assigned task requires persistence changes.

## Testing

Use `.agents/skills/test-discipline` before test planning and final evidence.

After editing, run the focused checks from the assigned task plus hygiene checks:

```powershell
git diff --check
git diff --cached --check
git status --short
```

Use real output. Do not weaken tests. Report unrelated baseline failures separately, with evidence.

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

Do not push unless requested. For V2 work, push only to the V2 branch or `V2IMPROVMENT` when the user explicitly requested direct integration-branch docs work.

## Stop Rules

Stop and report if:

* assigned issue file or V2 dossier is missing
* dependency work is incomplete or not merged into the required base branch
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
* work branch
* PR target when applicable
* local commit hash
* changed files
* summary
* tests with exact results
* acceptance status
* final `git status --short`
* risks/deviations
* next dependency when applicable
* pushed or not pushed
