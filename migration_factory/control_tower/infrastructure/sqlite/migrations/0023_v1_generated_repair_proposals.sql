-- V1-14C: Generate fake-provider repair proposals
--
-- Extend append-only fake repair proposal storage with deterministic
-- generated-proposal metadata. No prompt, provider output, patch
-- content, deployment ID, or executable instructions are stored.

ALTER TABLE v1_fake_repair_proposals
ADD COLUMN proposal_kind TEXT NOT NULL DEFAULT 'manual'
CHECK (proposal_kind IN ('manual', 'repair_attempt', 'generated'));

ALTER TABLE v1_fake_repair_proposals
ADD COLUMN recommendation_type TEXT;

ALTER TABLE v1_fake_repair_proposals
ADD COLUMN confidence_label TEXT;

ALTER TABLE v1_fake_repair_proposals
ADD COLUMN confidence_score REAL;

ALTER TABLE v1_fake_repair_proposals
ADD COLUMN warning_codes_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE v1_fake_repair_proposals
ADD COLUMN applicable INTEGER NOT NULL DEFAULT 1
CHECK (applicable IN (0, 1));

ALTER TABLE v1_fake_repair_proposals
ADD COLUMN context_checksum TEXT;

CREATE UNIQUE INDEX ux_v1_fake_repair_proposals_generated_context
ON v1_fake_repair_proposals(classification_id, proposal_kind, context_checksum)
WHERE proposal_kind = 'generated' AND context_checksum IS NOT NULL;
