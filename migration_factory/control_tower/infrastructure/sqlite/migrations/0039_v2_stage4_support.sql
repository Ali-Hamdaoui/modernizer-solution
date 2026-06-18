-- V2-P0-006: Allow Stage 4 records in V2 durable tables
--
-- This migration widens V2 stage-related CHECK constraints from 1..3 to 1..4.
-- It preserves append-only semantics by recreating the affected tables,
-- copying existing rows, and restoring indexes/triggers.

ALTER TABLE v2_stage_commands RENAME TO v2_stage_commands_old;
DROP INDEX ix_v2_stage_commands_job;
DROP TRIGGER v2_stage_commands_no_update;
DROP TRIGGER v2_stage_commands_no_delete;

CREATE TABLE v2_stage_commands (
    command_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index IN (1, 2, 3, 4)),
    manifest_checksum TEXT NOT NULL,
    argv_json TEXT NOT NULL DEFAULT '[]',
    env_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'manifest_ready',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT
);

INSERT INTO v2_stage_commands (
    command_id, job_id, stage_index, manifest_checksum,
    argv_json, env_json, status, created_at, updated_at, result_json
)
SELECT
    command_id, job_id, stage_index, manifest_checksum,
    argv_json, env_json, status, created_at, updated_at, result_json
FROM v2_stage_commands_old;

CREATE INDEX ix_v2_stage_commands_job
ON v2_stage_commands(job_id, stage_index);

CREATE TRIGGER v2_stage_commands_no_update
BEFORE UPDATE ON v2_stage_commands
BEGIN
    SELECT RAISE(ABORT, 'v2_stage_commands is append-only');
END;

CREATE TRIGGER v2_stage_commands_no_delete
BEFORE DELETE ON v2_stage_commands
BEGIN
    SELECT RAISE(ABORT, 'v2_stage_commands is append-only');
END;

DROP TABLE v2_stage_commands_old;

ALTER TABLE v2_approval_decisions RENAME TO v2_approval_decisions_old;
DROP INDEX ix_v2_approval_decisions_status;
DROP INDEX ix_v2_approval_decisions_job;
DROP TRIGGER v2_approval_decisions_no_delete;

CREATE TABLE v2_approval_decisions (
    card_id TEXT PRIMARY KEY,
    interrupt_id TEXT NOT NULL,
    request_checksum TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index IN (1, 2, 3, 4)),
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    job_id TEXT NOT NULL DEFAULT ''
);

INSERT INTO v2_approval_decisions (
    card_id, interrupt_id, request_checksum, stage_index,
    summary, status, created_at, job_id
)
SELECT
    card_id, interrupt_id, request_checksum, stage_index,
    summary, status, created_at, job_id
FROM v2_approval_decisions_old;

CREATE INDEX ix_v2_approval_decisions_status
ON v2_approval_decisions(status);

CREATE INDEX ix_v2_approval_decisions_job
ON v2_approval_decisions(job_id);

CREATE TRIGGER v2_approval_decisions_no_delete
BEFORE DELETE ON v2_approval_decisions
BEGIN
    SELECT RAISE(ABORT, 'v2_approval_decisions is append-only');
END;

DROP TABLE v2_approval_decisions_old;

ALTER TABLE v2_resume_commands RENAME TO v2_resume_commands_old;
DROP INDEX ix_v2_resume_commands_card;
DROP INDEX ix_v2_resume_commands_job;
DROP TRIGGER v2_resume_commands_no_update;
DROP TRIGGER v2_resume_commands_no_delete;

CREATE TABLE v2_resume_commands (
    resume_id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index IN (1, 2, 3, 4)),
    command_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

INSERT INTO v2_resume_commands (
    resume_id, card_id, decision, job_id, stage_index, command_json, created_at
)
SELECT
    resume_id, card_id, decision, job_id, stage_index, command_json, created_at
FROM v2_resume_commands_old;

CREATE INDEX ix_v2_resume_commands_card
ON v2_resume_commands(card_id);

CREATE INDEX ix_v2_resume_commands_job
ON v2_resume_commands(job_id);

CREATE TRIGGER v2_resume_commands_no_update
BEFORE UPDATE ON v2_resume_commands
BEGIN
    SELECT RAISE(ABORT, 'v2_resume_commands is append-only');
END;

CREATE TRIGGER v2_resume_commands_no_delete
BEFORE DELETE ON v2_resume_commands
BEGIN
    SELECT RAISE(ABORT, 'v2_resume_commands is append-only');
END;

DROP TABLE v2_resume_commands_old;

ALTER TABLE v2_pending_action_drafts RENAME TO v2_pending_action_drafts_old;
DROP INDEX ix_v2_pending_action_drafts_job;
DROP TRIGGER v2_pending_action_drafts_no_delete;

CREATE TABLE v2_pending_action_drafts (
    action_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    stage_index INTEGER NOT NULL CHECK (stage_index IN (1, 2, 3, 4)),
    payload_checksum TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);

INSERT INTO v2_pending_action_drafts (
    action_id, job_id, action_type, reason, stage_index,
    payload_checksum, status, created_at
)
SELECT
    action_id, job_id, action_type, reason, stage_index,
    payload_checksum, status, created_at
FROM v2_pending_action_drafts_old;

CREATE INDEX ix_v2_pending_action_drafts_job
ON v2_pending_action_drafts(job_id, status);

CREATE TRIGGER v2_pending_action_drafts_no_delete
BEFORE DELETE ON v2_pending_action_drafts
BEGIN
    SELECT RAISE(ABORT, 'v2_pending_action_drafts is append-only');
END;

DROP TABLE v2_pending_action_drafts_old;

ALTER TABLE v2_job_events RENAME TO v2_job_events_old;
DROP INDEX ix_v2_job_events_job_sequence;
DROP INDEX ix_v2_job_events_job_type;
DROP TRIGGER v2_job_events_no_update;
DROP TRIGGER v2_job_events_no_delete;

CREATE TABLE v2_job_events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage INTEGER CHECK (stage IS NULL OR stage IN (1, 2, 3, 4)),
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    sequence INTEGER NOT NULL UNIQUE
);

INSERT INTO v2_job_events (
    event_id, job_id, stage, type, status, message,
    payload_json, created_at, sequence
)
SELECT
    event_id, job_id, stage, type, status, message,
    payload_json, created_at, sequence
FROM v2_job_events_old;

CREATE INDEX ix_v2_job_events_job_sequence
ON v2_job_events(job_id, sequence);

CREATE INDEX ix_v2_job_events_job_type
ON v2_job_events(job_id, type);

CREATE TRIGGER v2_job_events_no_update
BEFORE UPDATE ON v2_job_events
BEGIN
    SELECT RAISE(ABORT, 'v2_job_events is append-only');
END;

CREATE TRIGGER v2_job_events_no_delete
BEFORE DELETE ON v2_job_events
BEGIN
    SELECT RAISE(ABORT, 'v2_job_events is append-only');
END;

DROP TABLE v2_job_events_old;
