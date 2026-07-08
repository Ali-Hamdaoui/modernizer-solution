# AGENTS.md - Repository Agent Guidelines

This file defines precise repository rules and best practices for AI coding agents working in this repository.

The protected main working branch is:

```text
demov3
```

`demov3` must always stay safe, clean, and synchronized with `origin/demov3`.

Agents must **never implement directly on `demov3`**.  
All new work must happen on a dedicated task branch created from the latest `demov3`.

---

## 1. Golden Rule

For every new task:

```text
fetch origin -> switch to demov3 -> pull latest demov3 -> verify clean state -> create a new task branch -> work only on that task branch
```

No code, documentation, configuration, migration, test, or generated file change should be made directly on `demov3`.

`demov3` is only used as the clean base branch.

---

## 2. Mandatory Preflight Before Any Work

Before reading deeply, planning implementation, creating files, changing files, running tests, or creating a task branch, run:

```bash
git fetch origin
git status --short
git branch --show-current
```

If the working tree is dirty:

- Stop before switching branches.
- Report the dirty files.
- Do not overwrite, delete, reset, stash, or modify the files.
- Continue only if the user explicitly authorizes what to do.

Do not assume dirty files are safe to ignore.

---

## 3. Synchronize `demov3`

After confirming it is safe to switch branches, update `demov3`:

```bash
git switch demov3
git pull --ff-only origin demov3
git status --short
git branch --show-current
```

Proceed only when all conditions are true:

- Current branch is `demov3`.
- `git pull --ff-only origin demov3` completed successfully.
- Working tree is clean.
- No unrelated local changes are present.

If `git pull --ff-only origin demov3` fails:

- Stop.
- Report the error.
- Do not merge.
- Do not rebase.
- Do not reset.
- Do not force-update.
- Wait for explicit user instruction.

---

## 4. Mandatory Task Branch Rule

Every new unit of work must start from a new branch created from updated `demov3`.

Use:

```bash
git switch demov3
git pull --ff-only origin demov3
git switch -c <task-branch-name>
```

Only after the new task branch is created may the agent modify files.

The task branch must contain the new work.  
`demov3` must remain unchanged locally except for the fast-forward pull from origin.

Recommended branch naming:

```text
feature/<short-task-name>
fix/<short-task-name>
docs/<short-task-name>
test/<short-task-name>
chore/<short-task-name>
```

Examples:

```bash
git switch -c feature/add-checkpoint-validation
git switch -c fix/repair-agent-error-handling
git switch -c docs/update-agent-guidelines
```

Branch names should be:

- Short.
- Descriptive.
- Lowercase.
- Hyphen-separated.
- Related to the task.

---

## 5. Forbidden Direct Work On `demov3`

Never do these on `demov3`:

- Edit source code.
- Edit documentation.
- Add tests.
- Modify configuration.
- Add or change database migrations.
- Generate artifacts.
- Apply patches.
- Run commands that modify repository files.
- Stage files.
- Commit files.
- Push changes.

Allowed on `demov3` only:

```bash
git fetch origin
git switch demov3
git pull --ff-only origin demov3
git status --short
git branch --show-current
git diff --name-only
git diff --check
```

If a command may modify files, do not run it on `demov3`.

---

## 6. Branch Safety Rules

Do not create task branches from:

- Stale local branches.
- Old feature branches.
- Experimental branches.
- Deprecated sprint branches.
- Any branch other than synchronized `demov3`.

Do not switch away from a dirty branch unless the user explicitly authorizes how to handle the local changes.

Do not reuse an old task branch for new unrelated work.

One task branch should represent one clear unit of work.

---

## 7. Git Commands Permission Model

Allowed without asking:

```bash
git fetch origin
git status --short
git branch --show-current
git diff --name-only
git diff --check
```

Allowed after confirming the working tree is clean:

```bash
git switch demov3
git pull --ff-only origin demov3
git switch -c <task-branch-name>
```

Ask before:

- Creating a branch if the task name or branch name is unclear.
- Switching away from a task branch with local changes.
- Stashing changes.
- Deleting files.
- Moving or renaming large sets of files.
- Running commands that rewrite history.

Never do these unless the user explicitly asks:

- Commit changes.
- Push changes.
- Merge branches.
- Rebase branches.
- Force-push.
- Reset branches.
- Delete branches.
- Transition issue-tracker tickets.
- Comment on issue-tracker tickets.

---

## 8. Core Engineering Principles

Agents must:

- Work from the current user request and current repository state.
- Always start from updated `demov3`.
- Always create a new task branch before changing files.
- Prefer small, focused, reviewable changes.
- Read relevant code and configuration before modifying files.
- Preserve existing architecture, naming conventions, and style unless the task explicitly asks for a change.
- Avoid assumptions based on old sprint notes, stale branches, or previous project phases.
- Keep user-facing behavior, API contracts, and data migrations stable unless explicitly asked to change them.
- Provide evidence for completed work.

When instructions conflict, follow this priority:

1. Explicit user instruction in the current task.
2. Protected `demov3` and mandatory task branch rules in this file.
3. Directly relevant project documentation.
4. Existing code patterns.
5. General best practices.

Do not follow outdated sprint rules unless the user explicitly reactivates them.

---

## 9. Scope Control

Work only on files directly relevant to the task.

Before modifying files, identify:

- The goal of the task.
- The affected feature, module, package, or folder.
- Existing patterns used by nearby code.
- Tests or validation commands related to the change.

If the implementation requires touching files outside the expected scope:

- Stop briefly.
- Explain why the extra files are necessary.
- Continue only when the reason is clear or the user approves.

Avoid drive-by refactoring.  
Do not reformat unrelated files.

---

## 10. Reading And Context Strategy

Read enough context to make a safe change, but avoid unnecessary full-repository scanning.

Recommended order:

1. Current user request.
2. Relevant source files.
3. Nearby tests.
4. Build/config files.
5. Relevant documentation.
6. Existing issue or task description, if provided.

Do not treat old sprint folders, archived docs, or stale implementation plans as active requirements unless the current task explicitly references them.

When documentation and code disagree, prefer the code as the source of truth, then mention the documentation mismatch.

---

## 11. Command Discipline

Use commands that are supported by repository configuration.

Before running project-specific commands, inspect the relevant config files, for example:

- `package.json`
- `pyproject.toml`
- `requirements.txt`
- `pom.xml`
- `build.gradle`
- `Makefile`
- `docker-compose.yml`
- CI workflow files

Do not assume package managers, test runners, Docker usage, or CI workflows exist.

Prefer focused commands over broad commands.

Examples:

```bash
pytest path/to/test_file.py
npm test -- path/to/test-file
npm run typecheck
mvn -pl module-name test
git diff --check
git status --short
```

Ask before running:

- Dependency installation.
- Full test suites.
- Long-running builds.
- Database migrations.
- Docker commands.
- Network calls.
- Commands that modify global or user-level configuration.

---

## 12. Dependency And Environment Rules

Do not add, upgrade, or remove dependencies unless required by the task.

Before changing dependencies:

- Inspect the existing dependency file.
- Check whether the dependency is already available.
- Prefer built-in or existing project libraries.
- Explain why the dependency is needed.
- Update lock files only when appropriate for the repository.

Never expose secrets, tokens, API keys, environment values, private endpoints, deployment names, or local machine paths in logs, reports, commits, or public product fields.

Do not print raw environment variables unless the user explicitly asks and it is safe.

---

## 13. Implementation Standards

When changing code:

- Keep changes minimal and intentional.
- Match existing style and architecture.
- Prefer readable code over clever code.
- Preserve backward compatibility unless the task says otherwise.
- Handle errors explicitly.
- Avoid swallowing exceptions silently.
- Keep business logic out of UI/controller layers when the existing architecture separates them.
- Do not introduce hidden side effects.
- Do not hardcode local paths, credentials, provider names, deployment names, or machine-specific configuration.

When adding behavior:

- Add or update tests when practical.
- Cover negative/error cases for security-sensitive or data-sensitive behavior.
- Update documentation when behavior, setup, or commands change.

---

## 14. API And Product Boundaries

Do not change public API contracts without explicit instruction.

Public contracts may include:

- REST endpoints.
- Request/response schemas.
- Database schema.
- CLI arguments.
- Configuration keys.
- Frontend routes.
- User-visible labels or workflows.
- Exported functions/classes used by other modules.

If a contract change is necessary:

- Explain the reason.
- Update callers.
- Update tests.
- Update documentation or migration notes.

Do not expose backend runtime internals as product fields unless explicitly required. This includes:

- Raw command lines.
- `argv`
- Environment variable names or values.
- Provider endpoints.
- Deployment names.
- Sandbox paths.
- Local filesystem details.
- Internal orchestration traces that are not meant for users.

---

## 15. Database And Migration Rules

Before adding or changing a database migration:

- Inspect existing migrations on updated `demov3`.
- Create the task branch before adding or editing migration files.
- Use the next correct migration number or naming convention.
- Do not reuse migration numbers from stale branches or old examples.
- Keep migrations deterministic and reversible when the project expects reversibility.
- Add or update migration tests when possible.
- Verify schema assumptions against existing models and queries.

Never modify production data or run destructive database commands unless the user explicitly asks and the risk is clear.

---

## 16. Testing And Validation

Prefer focused validation related to changed files.

Minimum completion checks should usually include:

```bash
git diff --check
git status --short
```

For code changes, also run the most relevant focused tests available.

Examples:

```bash
pytest path/to/test_file.py
npm test -- path/to/test-file
npm run typecheck
mvn -pl module-name test
```

Do not claim tests passed unless they were actually run.

If tests cannot be run:

- Say they were not run.
- Explain why.
- Suggest the exact command the user can run.

For docs-only changes, `git diff --check` may be enough.

---

## 17. Security And Privacy

Agents must protect sensitive information.

Never expose:

- API keys.
- Access tokens.
- Passwords.
- Private certificates.
- Internal endpoints.
- Personal data.
- `.env` contents.
- Raw environment variable values.
- Local absolute paths, unless necessary for local debugging and already provided by the user.

Do not commit generated logs, caches, local database files, screenshots, runtime outputs, or temporary artifacts unless explicitly requested.

Security-sensitive code should include negative tests when possible.

---

## 18. Generated Artifacts

Do not commit generated artifacts unless the task explicitly asks for them.

Usually exclude:

- Build outputs.
- Runtime JSON outputs.
- Generated reports.
- Local audit files.
- Logs.
- Cache folders.
- Temporary files.
- Local SQLite/database files.
- Coverage output.
- PDFs or screenshots generated during local testing.

If generated artifacts are required, document why they are needed.

---

## 19. Documentation Rules

Update documentation when the task changes:

- Setup steps.
- Commands.
- Architecture.
- API behavior.
- Configuration.
- User workflows.
- Migration behavior.
- Testing strategy.

Documentation should describe the current state, not old sprint intent.

Avoid adding temporary sprint plans or personal notes to repository-level documentation.

---

## 20. Issue Tracker Rules

If the task references an issue tracker item, use it to understand scope.

Do not update issue status, transition tickets, assign people, or post comments unless the user explicitly asks.

At completion, prepare a human-readable status update instead of applying it automatically.

Recommended format:

```text
Issue:
Summary:
Branch:
Files changed:
Validation:
Risks:
Recommended status:
Suggested comment:
```

---

## 21. Completion Report

At the end of a task, report:

```text
Summary:
- What changed.

Branch:
- Base branch: demov3.
- Task branch: <branch-name>.
- Confirm work was done on the task branch, not directly on demov3.

Files changed:
- List key files.

Validation:
- Commands run and results.
- Or explain why validation was not run.

Risks / notes:
- Remaining concerns, follow-ups, or assumptions.
```

Be honest.  
Do not say work is complete if acceptance criteria, tests, or validation are missing.

---

## 22. What Not To Put In This File

Do not add:

- Temporary sprint names.
- Demo-specific feature mappings.
- One-time Jira issue mappings.
- Deprecated workflow descriptions.
- Old branch restrictions that are no longer relevant.
- Short-lived roadmap constraints.
- Temporary delivery checklists.
- Personal machine setup details.
- Secrets or environment-specific values.

This file should remain precise, stable, and reusable while keeping `demov3` protected and requiring all new work to happen on task branches.
