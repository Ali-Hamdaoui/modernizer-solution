-- R9.1 durable immutable repair strategy packets.
CREATE TABLE v2_repair_strategy_packets (
    strategy_id TEXT PRIMARY KEY,
    strategy_base_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL,
    family TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    strategy_status TEXT NOT NULL,
    strategy_checksum TEXT NOT NULL,
    evidence_pack_checksum TEXT NOT NULL,
    classification_status TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    packet_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(strategy_base_id, version),
    UNIQUE(strategy_base_id, strategy_checksum)
);

CREATE INDEX ix_v2_repair_strategy_packets_job_stage
ON v2_repair_strategy_packets(job_id, stage_index, version DESC, created_at DESC);

CREATE INDEX ix_v2_repair_strategy_packets_job
ON v2_repair_strategy_packets(job_id, created_at DESC);
