# Modernizer Solution Agent Instructions

## Purpose

Build the AI Migration Control Tower.

Active work is **V2**: branch-scoped, source-of-truth driven, and subagent-managed.

One mission = one branch = one focused commit unless blocked or a review fix is required.

## V2 Workflow

Base branch:

```text
V2IMPROVMENT
```

Subagent branch:

```text
v2/<agent-id>-<short-title>
```

Start:

```powershell
git fetch --prune origin
git switch V2IMPROVMENT
git pull --ff-only origin V2IMPROVMENT
git switch -c v2/<agent-id>-<short-title>
```

PR target is always `V2IMPROVMENT`. Do not merge V2 work to `DEMO2`.

## Source Of Truth

Read in this order:

1. `V2_IMPLEMENTATION_SUBAGENT_PLAN.md`
2. your assigned A1-A16 dossier only
3. `improvmentV2.md` only for product vision
4. targeted repo files named by the dossier
5. relevant `.agents/skills/`

Do not read all dossiers unless you are A15, A16, or integration owner.
Do not implement adjacent dossiers.

Use `graphify` only when broad navigation is needed and `graphify-out/graph.json` exists.

## Skills

Use local skills when present:

* `caveman`
* `test-discipline`
* `triage`
* `requesting-code-review`
* `subagent-driven-development`
* `graphify`

## Product Rules

V2 is local operator mode.

Frontend may accept local absolute paths only as setup inputs. Backend validates before queuing commands.

Azure secrets, endpoints, and deployment IDs stay backend-only.

Azure health does not block deterministic migration start.

Backend owns:

```text
Stage 1 -> Stage 2 -> Stage 3
```

Browser cannot choose commands, Maven goals, working dirs, model deployments, or Stage 2/3 inputs.

Chatbot cannot execute, approve, write files, change route, change stages, or override proof.

Worker executes backend-owned manifests only.

Model output is proposal/evidence only. Maven/tests/proof are truth.

## Work Rules

* No Jira creation unless explicitly asked.
* No adjacent work.
* No broad scans before source of truth.
* No secrets/tokens in output.
* Never `git add .`.
* Stage explicit owned files only.
* Never stage `web/control-tower/next-env.d.ts` unless explicitly owned.
* Never commit `.env`, logs, DBs, `.next/`, caches, runtime files, or another developer’s work.
* No direct long-running work in API handlers.
* Persist commands before launch.
* Worker argv/env must be backend-owned.
* Approval/resume must be checksum/version guarded.
* Do not edit applied migrations.
* Add append-only migrations only when required.

## Before Editing

Report briefly:

* agent ID
* source dossier
* owned scope
* non-goals
* likely files
* tests/checks
* blockers

## Build Flow

Implement only the dossier.

Run focused tests, then affected regressions.

If web changed, run web tests/typecheck/build.

Always run:

```powershell
git diff --check
git diff --cached --check
git status --short
```

Then review honestly:

* Does it build the V2 global idea?
* Is it inside the dossier?
* Are secrets, paths, model data, and authority safe?
* Are tests enough?

Fix issues before handoff.

## Commit

```powershell
git add <explicit-owned-files>
git diff --cached --check
git diff --cached --name-only
git commit -m "<type>(v2-<agent-id>): <summary>"
git status --short
git log -1 --oneline
```

Push only when requested or PR flow is required.

## Legacy V1

Use only if explicitly assigned V1/AMF work.

Start from `DEMO2`, read `docs/full-implementation/<V1-ID>*`, use branch:

```text
amf/<issue-id>-short-title
```

Preserve V1 route and invariants.

## Stop

Stop if:

* dossier/source is missing
* dependency not merged to base
* sources conflict
* arbitrary shell is needed
* LLM needs execute/approve/write/proof authority
* security risk is unclear
* safe staging is impossible
* unrelated dirty file would be included
* acceptance fails after 3 focused attempts

## Final Report

Report only:

* base branch/commit
* work branch
* PR target
* commit hash
* changed files
* tests
* acceptance
* `git status --short`
* risks/deviations
* next dependency
* pushed or not pushed
