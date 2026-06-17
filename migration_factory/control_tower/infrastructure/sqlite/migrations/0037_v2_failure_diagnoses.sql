-- V2-P0-009: Persist deterministic failure diagnoses (Phase 2.5)

CREATE TABLE v2_failure_diagnoses (
    diagnosis_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index >= 1),
    command_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    failure_type TEXT NOT NULL,
    likely_root_cause TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'low',
    recommended_fix_type TEXT NOT NULL DEFAULT '',
    affected_paths_json TEXT NOT NULL DEFAULT '[]',
    validation_plan_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    missing_artifacts_json TEXT NOT NULL DEFAULT '[]',
    context_pack_checksum TEXT NOT NULL DEFAULT '',
    evidence_pack_checksum TEXT NOT NULL DEFAULT '',
    diagnosis_checksum TEXT NOT NULL,
    redaction_status TEXT NOT NULL DEFAULT 'redacted',
    created_at TEXT NOT NULL,
    UNIQUE (command_id, event_type)
);

CREATE INDEX ix_v2_failure_diagnoses_job_stage
ON v2_failure_diagnoses(job_id, stage_index, created_at);

CREATE INDEX ix_v2_failure_diagnoses_command
ON v2_failure_diagnoses(command_id, event_type);

CREATE INDEX ix_v2_failure_diagnoses_checksum
ON v2_failure_diagnoses(diagnosis_checksum, evidence_pack_checksum);

CREATE TRIGGER v2_failure_diagnoses_no_update
BEFORE UPDATE ON v2_failure_diagnoses
BEGIN
    SELECT RAISE(ABORT, 'v2_failure_diagnoses is append-only');
END;

CREATE TRIGGER v2_failure_diagnoses_no_delete
BEFORE DELETE ON v2_failure_diagnoses
BEGIN
    SELECT RAISE(ABORT, 'v2_failure_diagnoses is append-only');
END;
