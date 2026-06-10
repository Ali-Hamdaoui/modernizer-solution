# Graphify developer context

## Purpose

Graphify builds a local, code-only knowledge graph of this repository. Use it for developer exploration, targeted codebase queries, and token reduction during AI-assisted development.

It is not a migration step, runtime dependency, Control Tower feature, worker capability, or production dependency. Graphify is developer navigation tooling only.

## Local install

```bash
uv tool install "graphifyy==0.8.36"
graphify --version
```

Do not add Graphify to `pyproject.toml`, `package.json`, runtime images, FastAPI, LangGraph, worker packaging, or the migration pipeline.

## Shared skill

The repository ships a shared Graphify skill at `.agents/skills/graphify/`. It is discovered automatically by both Codex and OpenCode.

### Codex usage

Invoke via `$graphify` in your prompt. The skill provides `/graphify query`, `/graphify path`, and `/graphify explain` commands.

### OpenCode usage

OpenCode discovers skills from `.agents/skills/` by default. Use the `skill` tool to load the Graphify skill by name.

## Terminal examples

```bash
# Find which services are involved in a specific capability
graphify query "Which services update command execution state?"

# Trace a dependency path
graphify query "Which service prepares command workspaces?"

# Shortest path between two components
graphify path "CommandWorkspaceService" "SqliteControlTowerUnitOfWork"

# Explain a specific concept
graphify explain "CommandWorkspaceService"
```

## Important caveats

- Graphify results are **derived navigation context** — every finding must be confirmed against real source and tests.
- Graphify output is **not** approval or acceptance evidence.
- Graph refreshes happen only from merged `DEMO2` on this `tooling/repository-skills` branch.
- **Normal issue branches must not update shared graph artifacts.**
