# ADR-M2-01 FastAPI and SSE adapter strategy

Status: Ready for reviewer approval

Date: 2026-06-10

## Context

The repository now has a minimal FastAPI adapter and persisted SSE replay path for the AMF-149/AMF-150 tracer bullets.

Runtime diagnostics:

- FastAPI: `0.136.3`.
- Starlette: `1.2.1`.
- Uvicorn: `0.38.0`.
- `sse-starlette`: `3.4.4`.
- Python: `3.14.5` locally through `py`; repository declares `>=3.10`.
- Pydantic: 2.13.4 locally; repository declares `pydantic>=2,<3`.

The M2 plan lists FastAPI `0.136.3` as a candidate only. It also proposes:

```python
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

This import path is verified in the current environment:

```powershell
py -c "from fastapi.sse import EventSourceResponse, ServerSentEvent; print(EventSourceResponse.__module__, ServerSentEvent.__module__)"
```

Output:

```text
fastapi.sse fastapi.sse
```

## Decision

Use FastAPI `0.136.3`, Uvicorn `0.38.0`, and native `fastapi.sse.EventSourceResponse` / `ServerSentEvent`.

Keep `sse-starlette==3.4.4` declared because FastAPI's native SSE module depends on that package.

The reproducible backend installation command is:

```powershell
py -m pip install -e .[test]
```

FastAPI lifespan is the required ownership boundary for singleton ownership, dispatcher, ingestor, notifier, and process monitor startup once those components exist.

AMF-150 SSE cursor precedence:

- Initial connection: when `Last-Event-ID` is absent, use validated `after_sequence` when provided; otherwise use `0`.
- Browser automatic reconnect: when valid `Last-Event-ID` is present, it is authoritative. `after_sequence` is treated as the original bootstrap cursor and may be stale if it is less than or equal to `Last-Event-ID`.
- Invalid requests: reject malformed cursors, negative cursors, cursors greater than the committed event head, and `after_sequence > Last-Event-ID` because that is not ordinary EventSource reconnect behavior.

## Rules

- Do not use FastAPI `BackgroundTasks` for durable command execution.
- Do not start subprocesses directly from routes.
- Do not run Uvicorn with `--workers > 1` for M2.
- Do not use Uvicorn reload for acceptance or production-like M2 runs.
- Routes adapt HTTP to application services only.
- SSE streams committed public database events only.

## Approval

| Reviewer | Decision | Date | Comments |
|---|---|---|---|
| HAMDAOUI Ali | Pending | Pending | Pending |
| ilyas abarbach | Pending | Pending | Pending |

## Consequences

AMF-149 owns create/start HTTP contracts for the diagnostic queue slice.

AMF-150 owns persisted public event replay, bounded event queries, FastAPI SSE, browser EventSource replay, and reconnect behavior.

Later worker/private-event behavior remains deferred and must extend these public contracts instead of duplicating them.
