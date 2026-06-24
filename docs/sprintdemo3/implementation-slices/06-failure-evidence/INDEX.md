# Feature 06 — Failure Evidence

## Purpose

Persist strong immutable evidence for failed attempts.

## Problem solved

Existing evidence collection is useful but file-oriented and does not consistently bind complete DEMO3 lineage.

## PRD alignment

Grounds classification, retrieval, candidate generation, review, and audit.

## Current code reality

`repair_loop/evidence_collector.py` collects logs, reports, POM excerpts, and prior repairs, redacts them, classifies, and writes files. `v2_failure_diagnosis.py` can call it but accepts payload path data internally and stores diagnoses in memory.

## Expected architecture

An application service resolves backend-owned sources, normalizes evidence, persists an immutable record/artifact, and binds attempt/checkpoint/profile/checksums.

This feature also introduces the thin `FailureRecoveryEngine` coordinator shell that calls existing services and persists typed recovery transitions. It must not replace the stage orchestrator or repair flow.

## Likely reuse points

Existing collector, evidence pack builder, artifact resolver/storage, redaction, failure diagnosis, and events.

## Likely future modified files

`v2_failure_diagnosis.py`, `v2_evidence_pack_builder.py`, `repair_loop/evidence_collector.py`, `v2_repair_flow.py`.

## Likely future new files

`v2_failure_evidence_service.py`, `domain/v2_failure_evidence.py`, `v2_failure_recovery_engine.py`, and focused evidence/engine tests.

## Dependencies

Features 04 and 05.

## Blocks

Features 07–10.

## Out of scope

Authoritative model classification, arbitrary filesystem reads, and retrieval knowledge.

## Acceptance criteria

Evidence binds failed attempt, input checkpoint, normalized diagnostics, source hashes/snippets, profile, dependencies, transform/build/test results, and prior repairs.

## Focused test strategy

Completeness, immutability, redaction, prompt injection framing, bounded content, missing artifacts, and checksums.

## Risks

Leaking paths/secrets or storing mutable references instead of immutable content.
