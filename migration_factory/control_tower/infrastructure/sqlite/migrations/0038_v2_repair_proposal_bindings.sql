-- V2-P0-008: Bind governed repair proposals to persisted diagnosis checksums

ALTER TABLE v2_repair_proposals
ADD COLUMN diagnosis_id TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN diagnosis_checksum TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN evidence_pack_checksum TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN context_pack_checksum TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN proposal_checksum TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN validation_plan_text TEXT NOT NULL DEFAULT '';

CREATE INDEX ix_v2_repair_proposals_diagnosis
ON v2_repair_proposals(diagnosis_id);

CREATE INDEX ix_v2_repair_proposals_proposal_checksum
ON v2_repair_proposals(proposal_checksum);
