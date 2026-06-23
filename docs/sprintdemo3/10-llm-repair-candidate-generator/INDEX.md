# Feature 10 — LLM Repair Candidate Generator

## Purpose

Let the Azure AI Foundry-backed proposer role author diagnosis and an exact bounded repair candidate through the backend.

## Problem solved

Current diagnosis creates draft proposal content and existing repair proposals are shaped around current repair flow; DEMO3 needs exact generative candidate revisions.

## PRD alignment

Makes the LLM the repair author while keeping execution authority in backend/human controls.

## Current code reality

Strict model schemas, role routing, repair proposals, revision metadata, context checksums, and fake-provider tests exist. Existing `copilot_*` and `azure_openai` names are legacy implementation details, not supported alternative DEMO3 providers. No explicit DEMO3 candidate aggregate or `repair_candidate.diff` contract was found.

## Expected architecture

Backend builds a controlled context pack and selected mode, then invokes one Azure AI Foundry adapter. The Foundry-backed proposer first returns a strict immutable diagnosis artifact, then a strict candidate revision. Exact diff bytes become an artifact revision. The frontend never calls Foundry directly.

## Likely reuse points

`v2_model_schemas.py`, role router, repair flow/gate, proposal revision persistence, artifact revisions, existing Azure-hosted model wiring where compatible, and fake model clients.

## Likely future modified files

`v2_repair_flow.py`, `v2_model_schemas.py`, `v2_model_role_router.py`, `v2_repair_gate_service.py`.

## Likely future new files

Diagnosis artifact domain/tests, candidate generator/domain, Azure AI Foundry adapter/configuration contract, and focused fake-adapter tests.

## Dependencies

Features 06, 08, and 09.

## Blocks

Features 11–13.

## Out of scope

Execution, approval, authoritative classification, model-authored commands, direct OpenAI access, multi-provider routing, provider fallback, and Copilot runtime integration.

## Acceptance criteria

Azure AI Foundry is the only provider path and is invoked only by the backend. Diagnosis and candidate have separate IDs, schema versions, checksums, provenance, and audit events. Candidate binds attempt/checkpoint/evidence/classification/retrieval/diagnosis/mode/envelope/author identity and exact content checksum; raw commands are rejected; revisions are immutable; provider secrets never enter responses or events.

## Focused test strategy

Valid candidate types, malformed/refusal/timeout/rate-limit/content-filter responses, exact diff, stale bindings, raw commands, revision feedback, context redaction, and fake Azure AI Foundry adapter only.

## Risks

Explanatory plan being treated as executable or model output carrying hidden authority.
