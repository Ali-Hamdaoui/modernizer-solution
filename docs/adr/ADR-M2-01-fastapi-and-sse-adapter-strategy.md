# ADR-M2-01 FastAPI and SSE adapter strategy

Status: Proposed for review

Date: 2026-06-10

## Context

The repository currently has no FastAPI adapter, no SSE adapter, and no declared FastAPI, Starlette, or Uvicorn dependency.

Runtime diagnostics:

- FastAPI: not installed.
- Starlette: not installed.
- Uvicorn: not installed.
- Python: 3.13.9 locally; repository declares `>=3.10`.
- Pydantic: 2.13.4 locally; repository declares `pydantic>=2,<3`.

The M2 plan lists FastAPI `0.136.3` as a candidate only. It also proposes:

```python
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

This import path is not verified in this repository because FastAPI is not installed.

## Decision

M2-00 does not add FastAPI, Starlette, Uvicorn, routes, or SSE code.

M2-10 must introduce the FastAPI adapter only after dependency compatibility is verified against the repository's supported Python and Pydantic versions.

M2-11 must use native FastAPI SSE only if the selected FastAPI version provides verified `EventSourceResponse` and `ServerSentEvent` support. If the native import is unavailable, M2-11 must record a reviewed alternative before implementation.

FastAPI lifespan is the required ownership boundary for singleton ownership, dispatcher, ingestor, notifier, and process monitor startup once those components exist.

## Rules

- Do not use FastAPI `BackgroundTasks` for durable command execution.
- Do not start subprocesses directly from routes.
- Do not run Uvicorn with `--workers > 1` for M2.
- Do not use Uvicorn reload for acceptance or production-like M2 runs.
- Routes adapt HTTP to application services only.
- SSE streams committed public database events only.

## Blocked or unverified

- Native FastAPI SSE availability is unverified.
- Exact FastAPI/Starlette/Uvicorn versions are unverified.
- Dependency lock strategy is absent.

## Consequences

M2-10 owns dependency introduction and local-security HTTP adapter tests.

M2-11 owns native SSE verification, replay behavior, keepalive behavior, and disconnect cleanup tests.
