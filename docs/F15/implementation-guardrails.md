# F15 Implementation Guardrails

**Status:** Active  
**Date:** 2026-06-17  
**Epic:** F15 — Chatbot-Governed Stage Workflow

## Purpose

These guardrails prevent subagents and implementers from duplicating
existing logic or introducing anti-patterns during F15 implementation.

## Reuse — Do Not Duplicate

The following services exist and must NOT be duplicated:

| Service | File | Use |
|---------|------|-----|
| Stage progression | `v2_stage_progression.py` | Wrap with policy check |
| Orchestrator runner | `orchestrator/runner.py` | Unchanged; gates pause between phases |
| Assistant service | `v2_assistant_service.py` | Extend with gate-aware context |
| Prompt router | `v2_prompt_router.py` | Add gate intent classification |
| Repair flow | `v2_repair_flow.py` | Bind to repair_review gates |
| Failure diagnosis | `v2_failure_diagnosis.py` | Consume via gate evidence packs |
| Plan amendments | `plan_amendments.py` | Consume via ArtifactRevision |
| Plan proposals | `plan_proposals.py` | Adapt through revision model |
| Plan reviews | `plan_reviews.py` | Bind to planning_review gates |
| Artifact resolver | (existing artifact resolution) | Use for gate evidence packs |
| Event stream | (existing SSE/event system) | Emit F15EventType events |
| Repositories | `repositories.py` | Add gate/revision repos |
| Unit of Work | `unit_of_work.py` | Wire new repositories |
| Validation | (existing validation layers) | Use for gate action validation |
| Rollback | (existing rollback layers) | Use for gate action rollback |
| Ledger | (existing ledger/proof) | Extend with gate entries |

## Files Not to Fork

- `migration_factory/orchestrator/graph.py`
- `migration_factory/orchestrator/runner.py`
- `migration_factory/orchestrator/phase_services.py`
- `migration_factory/control_tower/application/v2_assistant_service.py`
- `migration_factory/control_tower/application/v2_prompt_router.py`
- `migration_factory/control_tower/application/v2_repair_flow.py`
- `migration_factory/control_tower/application/plan_amendments.py`
- `migration_factory/control_tower/application/plan_proposals.py`
- `migration_factory/control_tower/application/plan_reviews.py`

These files may be extended with new methods/classes but must not be
forked into separate modules.

## Forbidden Frontend/Chatbot Fields

New F15 APIs must NEVER accept these fields from the frontend or chatbot:

- `sandbox_path` — paths are backend-owned
- `argv` — commands are backend-owned
- `env` — environment is backend-owned
- `command` / `raw_command` — commands are backend-owned
- `working_directory` — directories are backend-owned
- `filesystem_target` — targets are backend-owned
- `model_deployment_id` — deployments are backend-owned
- `maven_goal` (raw) — only typed goals allowed

## Artifact Truth Rule

Gate explanations MUST read gate-bound artifact refs and checksums.
They MUST NOT use stale in-memory previews, cached summaries, or
LLM-generated summaries that bypass the persisted checksum chain.

## Authority Rules

| Actor | Allowed | Forbidden |
|-------|---------|-----------|
| Chatbot | Explain, classify intent, draft structured actions, ask clarifying questions | Execute commands, write files, approve, choose sandbox, supply paths, mutate legacy source, override proof |
| Backend | Create/resolve/supersede gates, validate actions, bind checksums, persist decisions, queue commands, enforce stage order | Execute chatbot-supplied commands, skip gate validation, bypass checksum checks |
| Human | Accept, reject, approve, revise, continue, stop | Supply raw commands, sandbox paths, env vars through UI |

## Stage Skip Prevention

No direct Stage 3 jump without accepted Stage 2 output. The gate
dependency model (`get_upstream_kind`) and stage continuation policy
enforce sequential progression through gates.
