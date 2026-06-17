# F15 Compatibility Matrix

**Status:** Active  
**Date:** 2026-06-17  
**Epic:** F15 — Chatbot-Governed Stage Workflow

## Purpose

Define old job vs new F15 job behavior before any runtime changes.
F15 mode is opt-in via `RunPolicy.f15_manual()`. Old jobs with
`StageContinuationPolicy.AUTO_ON_GREEN` continue unchanged.

## Policy Matrix

| Policy | Stage Progression | Gates Created | Chatbot Interaction |
|--------|-------------------|---------------|---------------------|
| `auto_on_green` (default) | Auto-queues next stage | None | Read-only (explain only) |
| `manual` (F15 opt-in) | Pauses at every gate | Full gate lifecycle | Flexible explain + decide |

## Endpoint Matrix

| Endpoint | Old Jobs (auto_on_green) | New F15 Jobs (manual) |
|----------|--------------------------|----------------------|
| `POST /jobs` (existing) | Creates job, auto-progresses | Creates job, stops at first gate |
| `GET /jobs/{id}/status` | Returns stage status | Returns stage status + open gates |
| `GET /jobs/{id}/gates` (new) | Returns empty list | Returns gate list with status |
| `POST /jobs/{id}/gates/{gate_id}/decide` (new) | 404 (no gates) | Validates checksum, persists decision |
| `GET /jobs/{id}/events` (existing) | V1 events only | V1 + F15 events |

## Stage 1 / 2 / 3 Matrix

| Stage | auto_on_green | manual (F15) |
|-------|---------------|--------------|
| 1 (Analysis) | Auto-runs, auto-queues Stage 2 | Runs, creates analysis_review gate, pauses |
| 2 (Planning) | Auto-runs, auto-queues Stage 3 | Runs from Stage 1 sandbox, creates planning_review gate, pauses |
| 3 (Implementation) | Auto-runs to completion | Runs from Stage 2 sandbox, creates approval_review gate before transformation, repair_review on failure |

## Migration Strategy

1. **Phase 1 (jobs 001–025):** Domain models + persistence. No runtime changes.
2. **Phase 2 (jobs 036–050):** Orchestration hooks. `auto_on_green` unchanged.
3. **Phase 3 (jobs 076–100):** Gate review logic. Only `manual` jobs affected.
4. **Phase 4 (jobs 113–117):** API + frontend. Old endpoints remain compatible.

## Backward Compatibility Guarantees

- Existing `auto_on_green` jobs never see gates.
- Existing API endpoints return the same shape for old jobs.
- Existing SSE event stream adds F15 events without removing V1 events.
- Existing SQLite migrations are append-only (never edit applied migrations).
- Existing orchestrator runner is not forked or replaced.
