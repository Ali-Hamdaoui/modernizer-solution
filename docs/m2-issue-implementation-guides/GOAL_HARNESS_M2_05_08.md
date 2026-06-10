# GOAL Harness — M2-05 to M2-08

## Purpose

Implement the remaining M2 Control Tower issues one by one through Pi/Hermes using a centralized `GOAL` branch.

## Issue order

1. AMF-153 — M2-05 — Stream bounded command output
2. AMF-154 — M2-06 — Finalize terminal command artifacts
3. AMF-155 — M2-07 — Cancel or time out the complete command
4. AMF-156 — M2-08 — Fail closed after restart or unclear worker state

## Source documents

Read before each issue:

* `AGENTS.md`
* `.agents/skills/test-discipline/SKILL.md`
* issue dossier under `docs/m2-issue-implementation-guides/`
* Jira issue and acceptance criteria
* relevant M2 docs/ADRs
* source and tests found through Graphify

## Branch model

* Start from latest `DEMO2`.
* Create centralized branch `GOAL` from `DEMO2`.
* For each issue, create a separate branch from clean `GOAL`.
* Merge an issue branch into `GOAL` only if tests pass or only proven baseline failures remain.
* Never merge a failed issue branch into `GOAL`.
* Never implement two issues in one branch.

Issue branches:

* `goal/amf-153-stream-bounded-command-output`
* `goal/amf-154-finalize-terminal-artifacts`
* `goal/amf-155-cancel-timeout-command`
* `goal/amf-156-restart-fail-closed`

## Required subagents

Use subagents as roles:

* Architecture Scout: `$graphify`, `$triage`
* Issue Planner: `$to-issues`
* Test Planner: `$test-discipline`
* Security Reviewer: `$requesting-code-review`
* Lead Implementer: `$subagent-driven-development`
* Verification Auditor: `$test-discipline`, `$caveman`

Only the Lead Implementer may edit files.

## Per-issue workflow

1. Switch to `GOAL`.
2. Confirm clean status.
3. Create/switch issue branch.
4. Read Jira and dossier.
5. Use Graphify first.
6. Map acceptance criteria before editing.
7. Implement only that issue.
8. Run focused tests.
9. Run `tests/control_tower`.
10. Run full suite when practical.
11. Commit explicit issue-owned files.
12. Merge into `GOAL` only if verified.
13. Push `GOAL` only when explicitly allowed.

## Graphify-first commands

Run before broad source reads:

```bash
graphify --version || true
graphify query "Which services handle command execution lifecycle?"
graphify query "Which services update command execution state?"
graphify query "Which tests cover this issue behavior?"
graphify query "Which repositories persist command executions and artifacts?"
graphify query "Which FastAPI routes expose Control Tower command execution?"
graphify explain "WorkerLaunchService"
graphify explain "CommandWorkspaceService"
```

## Test-fix attempt budget

Maximum 5 test-fix cycles per issue.

A cycle is:

1. run focused tests;
2. observe failure;
3. make one focused fix;
4. rerun focused tests.

After 5 failed cycles:

* stop that issue;
* write blocker note;
* do not merge into `GOAL`;
* return to clean `GOAL`;
* continue the next issue.

## Linux rules

* Linux may run portable tests.
* Skip real Windows-only integration tests with explicit reason.
* Do not fake Windows process-control behavior.
* Test fail-closed behavior where relevant.
* Do not claim Windows verification from Linux.

## Windows rules

* Windows-specific tests must run on Windows.
* Do not accept skipped Windows Job Object tests unless a real capability issue exists.
* Symlink privilege skips are allowed only with explicit reason.
* Verify process-control, cleanup, timeout, cancel, and artifact behavior where relevant.

## Baseline failure rule

Never call a failure unrelated without proof.
If full suite fails, compare against clean `origin/DEMO2` or clean `GOAL`.
If branch-caused, fix it.
If baseline, document it.

## Commands

Linux:

```bash
python -m pytest tests/control_tower -q -rs --tb=short
python -m pytest -q -p no:cacheprovider -rs --tb=short --maxfail=3
git diff --check
git diff --cached --check
```

Windows:

```powershell
py -m pytest tests/control_tower -q -rs --tb=short
py -m pytest -q -p no:cacheprovider -rs --tb=short
git diff --check
git diff --cached --check
```

## Git rules

* Never use `git add .`.
* Stage explicit issue-owned files only.
* Do not commit logs, local config, env files, DB files, caches, generated junk, unrelated work, or `graphify-out/*`.
* Do not push unless explicitly allowed.
* Do not merge/rebase/reset/clean/delete without approval.

## Issue boundaries

AMF-153:
Only bounded command output streaming. No terminal artifact finalization unless required.

AMF-154:
Only terminal command artifact finalization. No new cancel/timeout behavior unless needed for finalization tests.

AMF-155:
Only cancel/timeout behavior. No restart reconciliation except minimal state support.

AMF-156:
Only fail-closed restart/unclear worker state behavior. No PID attach/relaunch.

## Security rules

For every issue:

* no shell injection;
* no browser-controlled command args;
* no unbounded output in memory/API;
* no secret/env leakage;
* no unsafe absolute path leakage;
* no raw Windows HANDLE exposure;
* no duplicate finalization;
* no orphaned process;
* no state transition without durable event/audit.

## Merge into GOAL

Merge only after:

* acceptance criteria mapped and satisfied;
* focused tests pass;
* `tests/control_tower` passes;
* full suite passes or only proven baseline failures remain;
* git status is clean;
* no unrelated files included.

Merge command:

```bash
git switch GOAL
git status --short
git merge --no-ff <issue-branch> -m "merge(AMF-XXX): <issue title>"
python -m pytest tests/control_tower -q -rs --tb=short
git diff --check
git diff --cached --check
git status --short
```

## Final GOAL report

At the end report:

* GOAL branch base commit;
* issues completed;
* issues blocked;
* branches merged;
* branches not merged;
* final commits;
* files changed by issue;
* test results by issue;
* Linux behavior;
* Windows behavior;
* skipped tests and reasons;
* baseline failures and proof;
* final git status;
* pushed or not;
* ready for PR/merge to DEMO2: yes/no.
