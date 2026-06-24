# Feature 18 — E2E Fixtures

## Purpose

Prove both the first deterministic fixture and flexible non-recipe repair.

## Problem solved

A Jackson-only test could pass while the architecture remains a static repair catalog.

## PRD alignment

Requires Jackson Stage 4 and non-Jackson LLM-authored patch fixtures through the same governed engine.

## Current code reality

Backend has extensive focused V2/F15/repair tests and fake model patterns. No `tests/fixtures/demo3/` or DEMO3 E2E tests were found.

## Expected architecture

Fixtures use fake Azure AI Foundry adapter responses for proposer/reviewer roles and fake retrieval; real domain/persistence/policy/executor adapters where safe; no live model/web and no Copilot dependency.

## Likely reuse points

Existing test helpers, temporary SQLite/UoW, fake model clients adapted behind the Foundry contract, patch fixtures, orchestrator callbacks, and frontend Vitest setup.

## Likely future modified files

Focused files under `tests/control_tower/` and `web/control-tower/tests/` only as shared helpers require.

## Likely future new files

`test_demo3_e2e_jackson_fixture.py`, `test_demo3_e2e_llm_authored_patch_fixture.py`, `tests/fixtures/demo3/`.

## Dependencies

Features 01–17.

## Blocks

Release acceptance.

## Out of scope

Live model/web calls, GitHub Copilot, direct OpenAI, multi-provider behavior, full-suite requirement, production deployment, and a Jackson-specific engine.

## Acceptance criteria

Jackson/OpenRewrite and non-Jackson/non-recipe candidates traverse the same backend Azure AI Foundry contract and governance; exact approved bytes reach sandbox; validation alone controls promotion.

## Focused test strategy

Two deterministic E2E families plus safe cockpit projection tests.

## Risks

Fixture-specific shortcuts, hidden backend repair knowledge, or flaky external dependencies.
