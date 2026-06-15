# Modernizer Solution — AGENTS.md

## Mission

Build the **V2 Governed LLM Migration Supervisor**.

Source of truth:

```text
docs/governed-llm-migration-supervisor/
```

Invariant:

```text
LLM creates migration intent. Human approves. Backend executes in sandbox. Repair loop validates proof.
```

This is not a chatbot-only feature and not a replacement for OpenRewrite, Maven, patch gates, validation, rollback, ledger, or proof artifacts.

## Branching

Base and PR target:

```text
V2IMPROVMENT
```

Never target `DEMO2`.

One feature = one branch.

Branch format:

```text
v2/llm-f<feature-number>-<short-title>
```

Start:

```powershell
git fetch --prune origin
git switch V2IMPROVMENT
git pull --ff-only origin V2IMPROVMENT
git switch -c v2/llm-f<feature-number>-<short-title>
```

## Read Before Editing

Read only what the assigned feature needs:

1. `docs/governed-llm-migration-supervisor/index.md`
2. assigned feature doc
3. dependency feature docs
4. source files named by docs
5. related tests
6. relevant `.agents/skills/`

Do not implement unrelated features.

## Dependencies

```text
F01 start now
F03 start now
F06 start now
F02 needs F01+F03
F04 needs F01+F06
F05 needs F02+F06
F07 needs proposal objects
F08 needs F06+F07
F09 needs backend records/events
F10 needs F01-F08 records
```

## Product Authority

These rules apply to the product LLM being built.

LLM may create:

```text
diagnosis
repair proposal
POM patch intent
proposal revision
reviewer critique
approval-card preparation request
validation-rerun request
```

LLM must never:

```text
execute commands
write files
approve decisions
choose sandbox/path
modify legacy source
change stages
choose Maven goals
override failed proof
```

Backend owns state resolution, sandbox binding, checksums, patch apply, validation rerun, rollback, ledger/proof persistence, and unsafe-action blocking.

Human owns approve, reject, request revision, continue, and stop.

Execution truth comes from OpenRewrite, Maven, build/test, `repair_loop`, `patch_gate`, `rule_registry`, `patch_apply`, `validation_runner`, repair ledger, and proof artifacts.

## Non-Negotiables

Do not create parallel systems for context packs, artifact store, failure evidence, failure classifier, repair schemas, patch gate, patch apply, rollback, validation runner, repair ledger, POM parser/helpers, approval cards, event stream, or reviewer schema.

F08 must route approved V2 proposals through existing `repair_loop`.

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

Report:

```text
feature
branch
docs read
owned scope
non-goals
likely files
new/changed tests to run
blockers
```

## Work Rules

Implement only the assigned feature. No broad refactor. No adjacent feature work. No Jira unless asked.

No secrets, tokens, raw paths, logs, DBs, caches, or runtime files in output.

Never `git add .`. Stage explicit owned files only.

Never stage `.env`, `.next/`, caches, DBs, logs, another developer’s work, or `web/control-tower/next-env.d.ts` unless explicitly owned.

Do not edit applied migrations. Add append-only migrations only when required.

## Tests

Run only tests that are new, changed, or directly affected by the owned feature. Do not run the full suite unless explicitly requested.

If no test exists, add a focused test and run only that test file.

If web changed, run relevant web test plus typecheck/build.

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

Stop and report if docs are missing, dependency is not merged, docs conflict with source, sandbox binding is unclear, safe work requires bypassing `repair_loop`, LLM needs execute/approve/write/proof authority, legacy source mutation risk exists, unrelated dirty files would be included, or acceptance fails after 3 focused attempts.

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
