# Modernizer Solution Agent Instructions

## Mission

Build the V2 Governed LLM Migration Supervisor for AI Migration Control Tower.

Source of truth:

```text
docs/governed-llm-migration-supervisor/
```

Core rule:

```text
LLM creates migration intent. Human approves. Backend executes in sandbox. Repair loop validates proof.
```

## Branch Rule

Base branch is always:

```text
V2IMPROVMENT
```

One feature = one branch = one focused commit.

Branch format:

```text
v2/llm-f<feature-number>-<short-title>
```

Start every feature from latest base:

```powershell
git fetch --prune origin
git switch V2IMPROVMENT
git pull --ff-only origin V2IMPROVMENT
git switch -c v2/llm-f<feature-number>-<short-title>
```

PR target is always `V2IMPROVMENT`. Never target `DEMO2`.

## Required Read Order

Before editing, read:

1. `docs/governed-llm-migration-supervisor/index.md`
2. assigned feature file
3. dependency feature files
4. code files named by the feature doc
5. related tests
6. relevant `.agents/skills/`

Do not read or implement unrelated features unless required by dependency.

## Feature Files

```text
01-contextpack-extension.md
02-automatic-failure-diagnosis.md
03-event-based-prompt-router.md
04-pom-intelligence-summary.md
05-chatbot-proposal-steering.md
06-sandbox-action-resolver.md
07-reviewer-before-apply.md
08-v2-to-repair-loop-bridge.md
09-cockpit-supervision-panels.md
10-final-report-ai-trace.md
```

## Dependencies

```text
F01 starts now.
F03 starts now.
F06 starts now.
F02 depends on F01 + F03.
F04 depends on F01 + F06.
F05 depends on F02 + F06.
F07 depends on repair/POM proposal objects.
F08 depends on F06 + F07.
F09 depends on backend records/events from F02/F05/F07/F08.
F10 depends on records from F01-F08.
```

## Product Authority

LLM may create:

```text
diagnosis
repair proposal
POM patch intent
proposal revision
reviewer critique
approval preparation request
validation rerun request
```

LLM must never:

```text
execute commands
write files directly
approve decisions
choose sandbox/path
modify legacy source
change stages
choose Maven goals
override failed proof
```

Backend owns:

```text
state resolution
sandbox binding
checksum attachment
patch apply
validation rerun
rollback
proof persistence
unsafe-action blocking
```

Human owns:

```text
approve
reject
ask for revision
continue/stop
```

Truth comes from:

```text
OpenRewrite
Maven
build/test
repair_loop
patch_gate
rule_registry
patch_apply
validation_runner
repair ledger
proof artifacts
```

## Non-Negotiables

Do not create parallel systems for:

```text
context packs
artifact store
failure evidence
failure classifier
repair schemas
patch gate
patch apply
rollback
validation runner
repair ledger
POM parser
POM patch helpers
approval cards
event stream
reviewer schema
```

Feature 8 must route approved V2 proposals through existing `repair_loop`.

Never bypass:

```text
patch_gate
rule_registry
patch_apply
validation_runner
rollback
ledger
```

## Before Editing Report

Briefly report:

```text
feature number
branch name
feature doc read
dependency docs read
owned scope
non-goals
likely files
tests/checks
blockers
```

## Work Rules

Implement only the assigned feature.

No broad refactor.

No adjacent feature work.

No Jira unless asked.

No secrets, tokens, raw paths, logs, DBs, caches, or runtime files in output.

Never `git add .`.

Stage explicit owned files only.

Never stage `.env`, `.next/`, caches, DBs, logs, or another developer’s work.

Never stage `web/control-tower/next-env.d.ts` unless explicitly owned.

Do not edit applied migrations. Add append-only migrations only when required.

## Tests

Run targeted tests for the owned feature.

If web changed, run relevant web tests/typecheck/build.

Always run:

```powershell
git diff --check
git diff --cached --check
git status --short
```

## Commit

```powershell
git add <explicit-owned-files>
git diff --cached --check
git diff --cached --name-only
git commit -m "feat(v2-llm-f<feature-number>): <summary>"
git status --short
git log -1 --oneline
```

Push only when requested.

## Stop If

Stop and report if:

```text
source docs are missing
dependency feature is not merged
sources conflict
safe sandbox binding is unclear
unsafe apply path is required
LLM needs execute/approve/write/proof authority
legacy source mutation risk exists
unrelated dirty files would be included
acceptance fails after 3 focused attempts
```

## Final Report

Report only:

```text
base branch/commit
work branch
PR target
commit hash
changed files
tests run
acceptance result
git status --short
risks/deviations
next dependency
pushed or not pushed
```
