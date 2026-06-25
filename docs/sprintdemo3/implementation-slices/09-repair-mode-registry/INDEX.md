# Feature 09 — Repair Mode Registry

## Purpose

Define allowed repair modes and safety envelopes rather than only fixed repairs.

## Problem solved

Current `rule_registry.py` is an allowlisted catalog of specific deterministic rules. That is useful reuse but cannot define DEMO3’s generative architecture.

## PRD alignment

Supports deterministic and LLM-authored modes through one generic state machine.

## Current code reality

Existing rules validate known dependency/config/source changes. Repair flow and gate services already coordinate proposals and approvals.

## Expected architecture

A versioned registry maps failure/profile compatibility to candidate type, path/size limits, review policy, executor adapter, and validation policy.

## Likely reuse points

Current rule registry, patch gate, repair flow/gate, and validation runner.

## Likely future modified files

`repair_loop/rule_registry.py`, `v2_repair_flow.py`, `v2_repair_gate_service.py`.

## Likely future new files

`v2_repair_mode_registry.py`, `domain/v2_repair_mode.py`, focused tests.

## Dependencies

Feature 08.

## Blocks

Features 10, 12, 14, and 15.

## Out of scope

Encoding every exact repair or allowing model-created modes/envelopes.

## Acceptance criteria

Required modes are registered: `OPENREWRITE_RECIPE`, `DEPENDENCY_ALIGNMENT`, `CONFIG_PROPERTY_UPDATE`, `LLM_AUTHORED_PATCH`, `LLM_AUTHORED_POM_CHANGE`, `LLM_AUTHORED_CONFIG_CHANGE`, `LLM_AUTHORED_TEST_FIX`, `MANUAL_REVIEW_ONLY`.

## Focused test strategy

Mode compatibility, disabled/unknown mode, deterministic/generative selection, safety-envelope version/checksum, and Jackson/non-Jackson cases.

## Risks

Static catalog regression or envelopes broad enough to bypass policy.
