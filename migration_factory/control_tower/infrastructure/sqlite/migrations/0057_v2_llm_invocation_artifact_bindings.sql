-- LLM-WF-01: additive artifact/checksum bindings for governed LLM invocations.
--
-- Migration 0056 is immutable once applied. Add the raw/normalized/validated/diff
-- checksum and artifact-reference ledger fields here without rebuilding
-- v2_llm_invocations, so existing rows and 0056 checksums remain valid.

ALTER TABLE v2_llm_invocations ADD COLUMN stage_index INTEGER;

ALTER TABLE v2_llm_invocations ADD COLUMN attempt_number INTEGER;

ALTER TABLE v2_llm_invocations ADD COLUMN raw_response_checksum TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN normalized_output_checksum TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN validated_output_checksum TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN diff_checksum TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN raw_response_artifact_ref TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN normalized_output_artifact_ref TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN validated_output_artifact_ref TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN diff_artifact_ref TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN accepted_provider_source TEXT;

ALTER TABLE v2_llm_invocations ADD COLUMN deterministic_fallback_used INTEGER DEFAULT 0
    CHECK (deterministic_fallback_used IN (0, 1));

CREATE INDEX ix_v2_llm_invocations_checksums
ON v2_llm_invocations(raw_response_checksum, validated_output_checksum, diff_checksum);
