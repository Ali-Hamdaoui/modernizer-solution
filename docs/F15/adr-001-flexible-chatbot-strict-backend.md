# ADR-001: Flexible Chatbot + Strict Backend Gate Engine

**Status:** Accepted  
**Date:** 2026-06-17  
**Epic:** F15 — Chatbot-Governed Stage Workflow

## Context

F14 delivered core chatbot-to-POM apply. The Control Tower needs governed
stage workflows where the pipeline pauses at analysis, planning, approval,
repair, and stage-completion review points.

The chatbot must remain flexible in natural language understanding and
explanation. But execution must remain strict, auditable, and sandbox-bound.

## Decision

**F15 implements a "flexible chatbot, strict backend gate engine" pattern.**

The chatbot can:
- Understand many phrasings of the same gate intent
- Explain gate-bound evidence to the user
- Ask clarifying questions
- Draft structured gate actions for backend validation

The backend owns:
- Gate creation, status transitions, and resolution
- Checksum binding to artifact content
- Idempotency and duplicate detection
- Stage ordering and skip prevention
- Command creation, sandbox binding, execution
- Audit trail and proof generation

**Phase-split commands are preferred over LangGraph interrupts** for the
initial F15 implementation. The existing V2 orchestrator uses phase-split
commands and run configurations. LangGraph interrupts would require
adopting a new state machine runtime, duplicating the orchestrator runner,
and risking regression on proven three-stage migration pipelines.

Phase-split commands keep the existing runner, stage progression service,
and command repository intact. F15 gates are inserted as governed pause
points before each phase transition.

## Constraints

1. **No direct Stage 3 jump.** Stage 3 requires accepted Stage 2 output,
   enforced by gate dependency model (`get_upstream_kind`).

2. **No chatbot-supplied execution parameters.** New F15 APIs reject
   `sandbox_path`, `argv`, `env`, raw commands, or raw filesystem targets
   from the frontend or chatbot.

3. **No duplication.** F15 must not duplicate the orchestrator runner,
   repair engine, plan revision system, prompt router, stage progression
   service, artifact resolver, or ledger.

4. **Gate explanations read persisted checksums**, never stale in-memory
   previews.

## Reuse Targets

| System | Module | Reuse Strategy |
|--------|--------|---------------|
| Stage progression | `v2_stage_progression.py` | Wrap; add policy check before auto-queue |
| Orchestrator runner | `orchestrator/runner.py` | Unchanged; gates pause between phase commands |
| Assistant service | `v2_assistant_service.py` | Extend with gate-aware context loader |
| Prompt router | `v2_prompt_router.py` | Add gate intent classification paths |
| Repair flow | `v2_repair_flow.py` | Bind to repair_review gates |
| Plan amendments | `plan_amendments.py` | Consume via revision model |
| Plan revisions | `plan_proposals.py` / `plan_reviews.py` | Adapt through ArtifactRevision |
| Repositories/UoW | `repositories.py` / `unit_of_work.py` | Add gate/revision/decision repos |
| SQLite migrations | `migrations/` | Append-only, new numbered migrations |
| API layer | `adapters/fastapi/app.py` | Add gate endpoints; keep old endpoints compatible |
| Frontend | `MigrationCockpit.tsx` | Add gate panel; no filesystem path input |

## Consequences

- **Positive:** Safe demo after ~25 jobs: Stage 1 analysis completes,
  pipeline stops at analysis_review gate, chatbot explains evidence,
  user says continue, backend queues planning.
- **Negative:** Phase-split commands are coarser than LangGraph interrupts.
  Granular pause/resume within a phase requires additional state in the
  command execution model.
- **Risk:** Adoption of F15 manual policy at scale requires the frontend
  gate panel to present enough context for informed decisions. This is
  addressed in jobs 115–117.

## Alternatives Considered

### LangGraph Interrupts
- **Pros:** Native durable pause/resume, graph-level state persistence.
- **Cons:** Requires adopting LangGraph as the orchestrator runtime,
  replacing the existing runner, risk of regression on three-stage
  pipelines, and significant migration cost.
- **Decision:** Rejected for initial F15; may be reconsidered in a
  future epic if phase-split commands prove insufficient.

### Direct Chatbot Command Execution
- **Pros:** Simplest implementation path.
- **Cons:** Violates F15 invariants; chatbot would have excessive agency
  (OWASP LLM Top 10 risk LLM02 — Insecure Output Handling, LLM06 —
  Excessive Agency).
- **Decision:** Rejected permanently.
