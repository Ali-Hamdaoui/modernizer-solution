-- R8.1 durable internal repair candidates.
CREATE TABLE v2_repair_apply_candidates (
    repair_candidate_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index BETWEEN 1 AND 3),
    status TEXT NOT NULL,
    public_json TEXT NOT NULL,
    internal_json TEXT NOT NULL,
    approval_json TEXT,
    execution_json TEXT,
    patch_checksum TEXT NOT NULL,
    target_file_checksum TEXT NOT NULL,
    review_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_v2_repair_apply_candidates_job_stage
ON v2_repair_apply_candidates(job_id, stage_index, created_at DESC);
