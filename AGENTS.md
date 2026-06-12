# Modernizer Solution — Agent Instructions

## Purpose

This repository builds the AI Migration Control Tower and modernization platform. Work is issue-driven. One issue = one branch = one local commit unless blocked.

## Source of Truth

Use this priority order:

1. Assigned issue file under `docs/full-implementation/`
2. `docs/full-implementation/00_IMPLEMENTATION_RULES.md`
3. `docs/full-implementation/00_INDEX.md`
4. Current repository code and tests
5. Relevant local skill files under `.agents/skills/`
6. This file

Read only the assigned issue and directly related docs. Do not read the full docs tree unless the issue requires it. If sources conflict, stop and report.

## Branch Workflow

Before work:

```powershell
git status --short
git branch --show-current

# Always start from latest DEMO2:
git switch DEMO2
git pull --ff-only origin DEMO2
git rev-parse --short HEAD
git switch -c <issue-branch>

# If local DEMO2 is missing:
git fetch origin
git switch --track origin/DEMO2
git pull --ff-only origin DEMO2

# If the issue branch already exists, switch to it.
# Do not reset, rebase, force-update, clean, or resolve divergence without approval.
```

**Branch name:** `amf/<issue-id>-short-title`

## Before Implementation

Every agent must produce this plan before editing:

**Implementation plan:**

1. Confirm scope and dependencies:
   - Read the assigned issue file
   - Read only directly related rules/docs
   - Verify dependency issues are complete or not required

2. Locate affected code:
   - Use graphify first when graphify-out/graph.json exists
   - Use targeted rg/search after graphify
   - Identify exact files/classes/tests likely to change

3. Implement the smallest safe change:
   - Change only issue-owned files
   - Preserve V1 invariants
   - Avoid adjacent/future issue work
   - Keep domain, infrastructure, API, and UI boundaries clean

**Test plan:**

1. Baseline check:
   - Run focused baseline tests named in the issue when practical
   - Record unrelated pre-existing failures before editing

2. Focused validation:
   - Run tests required by issue acceptance criteria

3. Regression validation:
   - Run affected Control Tower regressions
   - Run broader suite when practical

4. Hygiene checks:
   - `git diff --check`
   - `git diff --cached --check`
   - `git status --short`

**Other skills:**
- `to-issues`: backlog splitting only
- `triage`: scope/dependency risk
- `requesting-code-review`: security, worker, approval, shell, model, patch, action, or redaction changes
- `subagent-driven-development`: complex implementation tasks only
- `test-discipline`: test planning
- `graphify`: broad exploration when graphify-out/graph.json exists

## Scope Rules

- Change only files required by the assigned issue. Do not implement adjacent issues.
- Do not touch unrelated deleted docs; some historical docs may be intentionally deleted.
- Never use `git add .`. Stage explicit paths only.
- Never commit secrets, logs, local DBs, .env, .next/, caches, or another developer's work.

## V1 Invariants

Preserve always:

- **Pipeline:** springboot-216-to-356-java21-three-stage
- **Stage 1:** Boot 2.7.18, Java 11, JDK java11
- **Stage 2:** Boot 3.5.6, Java 17, JDK java17, input from Stage 1 sandbox
- **Stage 3:** Boot 3.5.6, Java 21, JDK java21, input from Stage 2 sandbox
- Boot 4 is not selectable in V1
- 3.5.14 is not execution-relevant in V1
- Browser cannot choose raw paths, Maven goals, shell commands, working dirs, or model deployment IDs
- LLM cannot execute, approve, write files directly, or create proof
- Shell is disabled by default
- Maven/write actions are typed privileged actions only
- Control Tower validates; developer approves; worker executes; Maven/tests prove

## Engineering Rules

Prefer small, typed, testable changes. Reuse existing abstractions. Keep domain logic independent from infrastructure and UI. Do not add dependencies unless the issue requires it.

No direct long-running work in API handlers. Persist commands before launch. Worker argv/env must be backend-owned. Approval/resume must be checksum/version guarded.

## Testing

After editing, run:

- Focused tests from the issue
- Affected regression tests
- Broader suite when practical
- Hygiene checks:
  - `git diff --check`
  - `git diff --cached --check`
  - `git status --short`

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

Stop if acceptance cannot be met after 3 attempts; V1 invariants must change; arbitrary shell is needed; LLM execution/approval/write authority is needed; unrelated deleted docs must be restored; safe staging is impossible; dependency issue is incomplete; or security risk is unclear.

## Final Report

Report base branch, issue branch, commit hash, files changed, summary, tests with exact results, acceptance status, final `git status --short`, risks/deviations, and whether anything was pushed.