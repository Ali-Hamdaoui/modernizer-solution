# Feature 07 — Failure Classifier Registry

## Purpose

Classify failures deterministically through versioned broad signatures.

## Problem solved

Current classifier uses an in-code tuple list and falls back to `UNKNOWN_MIGRATION_FAILURE`; the Jackson Stage 4 case is not registered.

## PRD alignment

Makes classification backend-authoritative, extensible, evidence-backed, and model-independent.

## Current code reality

`agents/failure_classifier/agent.py` performs deterministic token matching. `repair_loop/rule_registry.py` contains fixed repair-specific rules and must not become the classifier architecture.

## Expected architecture

A signature registry evaluates versioned predicates against normalized evidence/profile and persists match evidence, confidence, and registry version.

## Likely reuse points

Existing classifier payload shape, failure diagnosis, evidence artifacts, and current rule fixtures.

## Likely future modified files

Classifier agent, repair rule registry, and `v2_failure_diagnosis.py`.

## Likely future new files

`v2_failure_signature_registry.py`, `domain/v2_failure_classification.py`, registry/classifier tests.

## Dependencies

Feature 06.

## Blocks

Features 08 and 09.

## Out of scope

LLM-authoritative classification and hardcoded orchestration branches.

## Acceptance criteria

Versioned Jackson and non-Jackson signatures match deterministically; ambiguous/unknown failures remain non-actionable; Jackson annotation exception is preserved.

## Focused test strategy

Positive/negative tokens, profile constraints, ambiguity, unknown, version binding, and registration without engine changes.

## Risks

Overbroad signatures, hidden priority rules, or coupling signatures to fixed repairs.
