# Feature 08 — Retrieval Pack Builder

## Purpose

Build targeted controlled context packs from failure signature, migration profile, and backend policy.

## Problem solved

Current context/evidence packs do not provide a separate versioned migration-knowledge artifact with retrieval provenance.

## PRD alignment

Separates what happened in the application from approved knowledge about how to migrate it.

## Current code reality

Bounded retrievers, context packs, evidence packs, redaction, and model schemas exist. No DEMO3 `RetrievalPack` aggregate/repository was found.

## Expected architecture

Backend selects a policy by signature/profile, retrieves approved versioned entries, adds only allowed evidence/artifact excerpts, redacts sensitive content, checksums the result, and persists a bounded controlled context pack. Models never receive unrestricted repository access.

## Likely reuse points

Existing retrievers, context pack manifests, artifact storage, redaction, and failure diagnosis.

## Likely future modified files

`v2_failure_diagnosis.py`, `v2_model_schemas.py`.

## Likely future new files

Retrieval pack builder/domain/repository and focused tests.

## Dependencies

Features 06 and 07.

## Blocks

Features 10 and 11.

## Out of scope

General vector platform, live web search, and application evidence duplication.

## Acceptance criteria

Pack binds evidence, classification, signature/profile, policy/version, source artifact references, entry provenance/checksums, redaction decisions, and bounded content; secrets and raw environment variables are forbidden; required missing knowledge fails closed.

## Focused test strategy

Policy selection, profile mismatch, missing entry, provenance/checksum, deterministic fake retrieval, and redaction.

## Risks

Irrelevant retrieval, unapproved sources, and prompt injection in retrieved text.
