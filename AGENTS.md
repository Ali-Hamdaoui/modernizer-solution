# Modernizer Solution

## Purpose

This repository builds and evolves an AI-assisted software modernization platform.

Always work from the **current assigned issue and current repository state**. Do not assume that an older milestone, architecture phase, status, state model, or implementation plan is still active.

## Sources of truth

Use this priority order:

1. Assigned Jira issue or explicit user request
2. Current approved specification or implementation plan
3. Repository code and tests
4. Existing documentation
5. This file

When sources conflict, stop and report the conflict instead of silently choosing.

## Context discipline

* Read the assigned issue first.
* Read all applicable `AGENTS.md` files.
* Use targeted searches such as `rg`; avoid scanning the whole repository without need.
* Open only relevant parts of large documents.
* Do not repeat specifications in code or reports.
* Do not expand scope beyond the assigned issue.
* Verify assumptions against the current code.

## Engineering approach

* Understand existing behavior before changing it.
* Prefer small, typed, testable changes.
* Reuse existing abstractions and conventions.
* Avoid broad refactors unless explicitly required.
* Keep domain logic independent from interfaces and infrastructure.
* Preserve backward compatibility unless the issue approves a breaking change.
* Never store credentials, secrets, or private keys in source code or configuration examples.
* Validate external input at system boundaries.
* Make state-changing operations atomic where practical.
* Keep generated artifacts, logs, and persistent state traceable and reproducible.

## Parallel work

* Use one issue per branch or worktree.
* Change only files required by the issue.
* Run `git status --short` before editing.
* Preserve unrelated and uncommitted work.
* Do not reset, rebase, delete, commit, push, or modify unrelated files unless explicitly requested.
* Minimize shared-file edits to reduce merge conflicts.
* Report dependencies or conflicts early.

## Testing

Before editing, identify the relevant existing tests and baseline.

After editing:

1. Run focused tests for the changed behavior.
2. Run the broader affected test group.
3. Run the full repository suite when practical.
4. Do not weaken tests or change them only to force success.
5. Do not claim success without actual test output.

If an unrelated failure already exists, report it separately.

## Dependencies and tools

* Prefer existing dependencies and standard-library solutions.
* Do not add or upgrade dependencies without explaining the need.
* Follow the repository’s supported language and tool versions.
* Use the project’s existing formatting, linting, and test commands.

## Documentation

Update documentation when behavior, configuration, architecture, setup, or public contracts change.

Keep comments focused on intent and non-obvious decisions.

## Completion criteria

Work is complete only when:

* The assigned acceptance criteria are satisfied.
* Focused tests pass.
* Relevant regression tests pass.
* No unrelated behavior changed.
* No unapproved scope was added.
* Risks, assumptions, and deviations are reported.

## Final report

Report:

* Files changed
* What was implemented
* Tests run and results
* Acceptance-criteria status
* Assumptions, risks, blockers, or deviations

Keep the report concise and evidence-based.
