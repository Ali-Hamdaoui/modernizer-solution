# Modernizer Solution

## Purpose

This repository builds and evolves an AI-assisted software modernization platform.

Always work from the current assigned issue and current repository state. Keep one issue per branch or worktree.

## Sources of truth

Use this priority order:

1. Current assigned issue and acceptance criteria
2. Current approved specification or implementation plan
3. Repository code and tests
4. Relevant documentation under `docs/`
5. This file

For M1, use:

```text
docs/M1_IMPLEMENTATION_PLAN.md
```

When sources conflict, report the conflict. Do not silently choose.

## Required workflow

Before editing or switching branches:

```powershell
git status --short
git branch --show-current
```

Preserve unrelated work. Never delete, reset, clean, overwrite, rebase, or modify unrelated files.

If completed issue-owned files are modified or untracked:

1. Run focused and regression tests.
2. Review the files.
3. Stage only issue-owned files.
4. Commit them locally.

Use explicit paths:

```powershell
git add <issue-files>
git diff --cached --check
git diff --cached
git commit -m "<type>(<scope>): <summary>"
```

Do not use `git add .` when unrelated files exist. Never commit secrets, logs, local databases, generated files, environment files, or another developer’s work.

After committing:

```powershell
git status --short
git log -1 --oneline
```

## Starting a new issue

New issue branches must start from the latest `DEMO2`, unless the issue specifies another approved base.

```powershell
git switch DEMO2
git pull --ff-only origin DEMO2
git rev-parse --short HEAD
git switch -c <issue-branch>
```

If `DEMO2` does not exist locally:

```powershell
git fetch origin
git switch --track origin/DEMO2
```

If the issue branch already exists, switch to it instead of recreating it.

Do not merge, rebase, reset, force-update, or resolve branch divergence without explicit approval.

## Scope and engineering

* Read the assigned issue and all applicable `AGENTS.md` files.
* Use targeted searches such as `rg`.
* Change only files required by the issue.
* Prefer small, typed, testable changes.
* Reuse existing abstractions.
* Keep domain logic independent from infrastructure and interfaces.
* Preserve existing behavior unless the issue approves a change.
* Do not add future milestone features.
* Do not add or upgrade dependencies without justification.
* Never store credentials or secrets.

## Testing

Before editing, identify and run the relevant baseline tests.

After editing:

1. Run focused tests.
2. Run broader affected tests.
3. Run the full repository suite when practical.
4. Run:

```powershell
git diff --check
git diff --cached --check
```

Do not weaken tests or claim success without real output. Report unrelated baseline failures separately.

## Commit and push policy

Completed issue work must end in a local commit unless:

* acceptance criteria are incomplete;
* implementation tests fail;
* a source conflict blocks completion;
* safe staging is impossible;
* the user explicitly says not to commit.

Do not push unless explicitly requested.

Never force-push without explicit approval.

## Completion criteria

Work is complete only when:

* acceptance criteria pass;
* focused and regression tests pass;
* no unrelated behavior changed;
* no unapproved scope was added;
* issue-owned files are committed locally;
* only issue-relevant files are included;
* risks and deviations are reported.

Do not mark an issue complete while its implementation remains untracked.

## Final report

Report:

* integration base and commit;
* issue branch;
* final commit hash and subject;
* files changed;
* implementation summary;
* tests and exact results;
* acceptance-criteria status;
* final `git status --short`;
* risks, conflicts, or deviations;
* whether anything was pushed.
