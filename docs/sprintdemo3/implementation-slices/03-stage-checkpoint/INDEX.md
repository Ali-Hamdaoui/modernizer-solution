# Feature 03 — StageCheckpoint

## Purpose

Make successful stage output an immutable reusable checkpoint.

## Problem solved

Current progression resolves mutable sandbox data from command results; LangGraph persistence is not a DEMO3 stage checkpoint.

## PRD alignment

Creates checksum-bound accepted output with explicit lineage and validation proof.

## Current code reality

Artifact revisions, gates, checksums, repositories, and UoW exist. No `StageCheckpoint` aggregate or repository was found.

## Expected architecture

Checkpoint records reference artifacts and proof; they never expose or equal a sandbox path.

## Likely reuse points

Artifact revision repository, gate artifact resolver, checksum utilities, stage progression, SQLite UoW/migration conventions.

## Likely future modified files

`domain/`, `infrastructure/sqlite/unit_of_work.py`, migrations, `v2_stage_progression.py`, `v2_gate_action_service.py`, `v2_gate_artifact_resolver.py`.

## Likely future new files

`domain/v2_stage_checkpoint.py`, `application/v2_checkpoint_service.py`, checkpoint repository/migration, and focused tests.

## Dependencies

Feature 01.

## Blocks

Features 04, 05, and 16.

## Out of scope

Cross-job reuse, retention policy, arbitrary filesystem import, and exposing storage locations.

## Acceptance criteria

Checkpoint captures ID, job, stage, status, profile, input checkpoint, creating attempt, artifact manifest checksum, validation checksum, and timestamps.

## Focused test strategy

Domain validation, repository round trip, immutable accepted state, lineage, uniqueness, and checksum compatibility.

## Risks

Treating a mutable working directory or command result as accepted output.
