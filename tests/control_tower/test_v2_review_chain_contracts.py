"""Focused tests for F2 review-chain foundation contracts.

AMF-254 — Deterministic artifact contract
AMF-255 — Primary LLM role
AMF-256 — Reviewer LLM role
"""

from __future__ import annotations

import pytest

from migration_factory.control_tower.application.v2_review_chain_contracts import (
    ArtifactPhase,
    ChecksumBindingValidationError,
    DeterministicAnalysisFacts,
    DeterministicArtifactBinding,
    DeterministicPlanningFacts,
    PrimaryLLMInput,
    PrimaryLLMOutput,
    PrimaryLLMOutputValidationError,
    ReviewDimension,
    ReviewerDecision,
    ReviewerLLMInput,
    ReviewerLLMOutput,
    ReviewerValidationResult,
    compute_primary_output_checksum,
    compute_reviewer_output_checksum,
    validate_checksum_binding,
    validate_deterministic_artifact_binding,
    validate_primary_llm_input,
    validate_primary_llm_output,
    validate_reviewed_output_contract,
    validate_reviewer_llm_input,
    validate_reviewer_llm_output,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json


# ── Helpers ─────────────────────────────────────────────────────────────


def _valid_analysis_facts() -> DeterministicAnalysisFacts:
    return DeterministicAnalysisFacts(
        detected_framework="Spring Boot",
        detected_language="Java",
        build_tool="maven",
        source_java_version="8",
        source_spring_boot_version="2.1.6",
        javax_import_count=45,
        has_datasource_config=True,
    )


def _valid_planning_facts() -> DeterministicPlanningFacts:
    return DeterministicPlanningFacts(
        selected_migration_stages=("baseline", "java-17", "spring-boot-3-5-14"),
        included_stages=("baseline", "java-17", "spring-boot-3-5-14"),
        target_java_version="17",
        target_spring_boot_version="3.5.14",
        profile_id="boot2-to-boot3",
        strategy="upgrade",
        executable=True,
        unit_count=3,
    )


def _valid_analysis_binding() -> DeterministicArtifactBinding:
    return DeterministicArtifactBinding(
        artifact_role="deterministic",
        artifact_phase="analysis",
        job_id="job-001",
        stage_index=1,
        artifact_ref="analysis/analysis_report.json",
        content_checksum=sha256_canonical_json({"version": "1.0.0"}),
        input_checksum=sha256_canonical_json({"pom": "checksum1"}),
        deterministic_facts=_valid_analysis_facts(),
        created_at="2025-01-01T00:00:00.000000Z",
    )


def _valid_planning_binding() -> DeterministicArtifactBinding:
    return DeterministicArtifactBinding(
        artifact_role="deterministic",
        artifact_phase="planning",
        job_id="job-001",
        stage_index=2,
        artifact_ref="planning/migration_plan.yaml",
        content_checksum=sha256_canonical_json({"plan": "v1"}),
        input_checksum=sha256_canonical_json({"report": "checksum1"}),
        deterministic_facts=_valid_planning_facts(),
        created_at="2025-01-01T00:00:00.000000Z",
    )


def _valid_primary_input() -> PrimaryLLMInput:
    return PrimaryLLMInput(
        deterministic_artifact_ref="analysis/analysis_report.json",
        deterministic_artifact_checksum=sha256_canonical_json({"version": "1.0.0"}),
        phase="analysis",
        job_id="job-001",
        stage_index=1,
        source_profile={"java": "8", "spring_boot": "2.1.6"},
        target_profile={"java": "17", "spring_boot": "3.5.14"},
    )


def _valid_primary_output() -> PrimaryLLMOutput:
    return PrimaryLLMOutput(
        reasoning="The project uses javax.* imports which require Jakarta migration.",
        risks=("javax-to-jakarta migration complexity",),
        confidence=0.85,
        recommended_next_step="Proceed with Jakarta migration stage.",
        draft_markdown="# Analysis Summary\n\nThis project needs Jakarta migration.",
        machine_readable_metadata={"version": "1.0"},
    )


def _valid_reviewer_input() -> ReviewerLLMInput:
    return ReviewerLLMInput(
        deterministic_artifact_ref="analysis/analysis_report.json",
        deterministic_artifact_checksum=sha256_canonical_json({"version": "1.0.0"}),
        primary_output_ref="primary/analysis_primary_output",
        primary_output_checksum=sha256_canonical_json({"output": "v1"}),
        primary_reasoning="The project uses javax.* imports.",
        draft_markdown="# Analysis Summary",
        phase="analysis",
        job_id="job-001",
        stage_index=1,
    )


def _valid_reviewer_output(deterministic_checksum: str, primary_checksum: str) -> ReviewerLLMOutput:
    return ReviewerLLMOutput(
        decision="accept",
        notes=("Evidence fits the deterministic facts.",),
        confidence=0.9,
        risks=("javax-to-jakarta migration is non-trivial.",),
        policy_concerns=(),
        reviewed_artifact_checksum=deterministic_checksum,
        reviewed_primary_output_checksum=primary_checksum,
    )


# ── AMF-254: Deterministic Artifact Contract ───────────────────────────


class TestDeterministicArtifactContract:
    """Tests for deterministic Analysis and Planning artifact contracts."""

    def test_valid_analysis_binding_passes_validation(self) -> None:
        binding = _valid_analysis_binding()
        failures = validate_deterministic_artifact_binding(binding)
        assert failures == []

    def test_valid_planning_binding_passes_validation(self) -> None:
        binding = _valid_planning_binding()
        failures = validate_deterministic_artifact_binding(binding)
        assert failures == []

    def test_missing_artifact_ref_fails(self) -> None:
        binding = DeterministicArtifactBinding(
            artifact_role="deterministic",
            artifact_phase="analysis",
            job_id="job-001",
            stage_index=1,
            artifact_ref="",
            content_checksum="abc123",
            deterministic_facts=_valid_analysis_facts(),
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("missing artifact_ref" in f for f in failures)

    def test_missing_content_checksum_fails(self) -> None:
        binding = DeterministicArtifactBinding(
            artifact_role="deterministic",
            artifact_phase="analysis",
            job_id="job-001",
            stage_index=1,
            artifact_ref="analysis/report.json",
            content_checksum="",
            deterministic_facts=_valid_analysis_facts(),
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("missing content_checksum" in f for f in failures)

    def test_missing_job_id_fails(self) -> None:
        binding = DeterministicArtifactBinding(
            artifact_role="deterministic",
            artifact_phase="analysis",
            job_id="",
            stage_index=1,
            artifact_ref="analysis/report.json",
            content_checksum="abc123",
            deterministic_facts=_valid_analysis_facts(),
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("missing job_id" in f for f in failures)

    def test_unknown_phase_fails(self) -> None:
        binding = DeterministicArtifactBinding(
            artifact_role="deterministic",
            artifact_phase="unknown_phase",
            job_id="job-001",
            stage_index=1,
            artifact_ref="analysis/report.json",
            content_checksum="abc123",
            deterministic_facts=_valid_analysis_facts(),
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("unknown artifact_phase" in f for f in failures)

    def test_invalid_artifact_role_fails(self) -> None:
        binding = DeterministicArtifactBinding(
            artifact_role="primary",
            artifact_phase="analysis",
            job_id="job-001",
            stage_index=1,
            artifact_ref="analysis/report.json",
            content_checksum="abc123",
            deterministic_facts=_valid_analysis_facts(),
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("invalid artifact_role" in f for f in failures)

    def test_stage_index_out_of_range_fails(self) -> None:
        for bad_index in (0, 4, -1):
            binding = DeterministicArtifactBinding(
                artifact_role="deterministic",
                artifact_phase="analysis",
                job_id="job-001",
                stage_index=bad_index,
                artifact_ref="analysis/report.json",
                content_checksum="abc123",
                deterministic_facts=_valid_analysis_facts(),
            )
            failures = validate_deterministic_artifact_binding(binding)
            assert any("stage_index" in f for f in failures)

    def test_missing_deterministic_facts_fails(self) -> None:
        binding = DeterministicArtifactBinding(
            artifact_role="deterministic",
            artifact_phase="analysis",
            job_id="job-001",
            stage_index=1,
            artifact_ref="analysis/report.json",
            content_checksum="abc123",
            deterministic_facts=None,
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("missing deterministic_facts" in f for f in failures)

    def test_analysis_facts_require_framework_or_language_or_build_tool(self) -> None:
        facts = DeterministicAnalysisFacts()
        binding = DeterministicArtifactBinding(
            artifact_role="deterministic",
            artifact_phase="analysis",
            job_id="job-001",
            stage_index=1,
            artifact_ref="analysis/report.json",
            content_checksum="abc123",
            deterministic_facts=facts,
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("must include at least one" in f for f in failures)

    def test_planning_facts_require_selected_migration_stages(self) -> None:
        facts = DeterministicPlanningFacts()
        binding = DeterministicArtifactBinding(
            artifact_role="deterministic",
            artifact_phase="planning",
            job_id="job-001",
            stage_index=2,
            artifact_ref="planning/plan.yaml",
            content_checksum="abc123",
            deterministic_facts=facts,
        )
        failures = validate_deterministic_artifact_binding(binding)
        assert any("must include selected_migration_stages" in f for f in failures)

    def test_analysis_facts_fields_are_accessible(self) -> None:
        facts = _valid_analysis_facts()
        assert facts.detected_framework == "Spring Boot"
        assert facts.detected_language == "Java"
        assert facts.build_tool == "maven"
        assert facts.source_java_version == "8"
        assert facts.source_spring_boot_version == "2.1.6"
        assert facts.javax_import_count == 45
        assert facts.has_datasource_config is True

    def test_planning_facts_fields_are_accessible(self) -> None:
        facts = _valid_planning_facts()
        assert facts.target_java_version == "17"
        assert facts.target_spring_boot_version == "3.5.14"
        assert "baseline" in facts.selected_migration_stages
        assert facts.executable is True
        assert facts.unit_count == 3


# ── AMF-255: Primary LLM Role ──────────────────────────────────────────


class TestPrimaryLLMInput:
    """Tests for primary LLM input contract."""

    def test_valid_input_passes_validation(self) -> None:
        input_ = _valid_primary_input()
        failures = validate_primary_llm_input(input_)
        assert failures == []

    def test_missing_deterministic_artifact_ref_fails(self) -> None:
        input_ = PrimaryLLMInput(
            deterministic_artifact_ref="",
            deterministic_artifact_checksum="abc123",
            phase="analysis",
            job_id="job-001",
            stage_index=1,
        )
        failures = validate_primary_llm_input(input_)
        assert any("missing deterministic_artifact_ref" in f for f in failures)

    def test_missing_deterministic_artifact_checksum_fails(self) -> None:
        input_ = PrimaryLLMInput(
            deterministic_artifact_ref="analysis/report.json",
            deterministic_artifact_checksum="",
            phase="analysis",
            job_id="job-001",
            stage_index=1,
        )
        failures = validate_primary_llm_input(input_)
        assert any("missing deterministic_artifact_checksum" in f for f in failures)

    def test_unknown_phase_fails(self) -> None:
        input_ = PrimaryLLMInput(
            deterministic_artifact_ref="analysis/report.json",
            deterministic_artifact_checksum="abc123",
            phase="unknown_phase",
            job_id="job-001",
            stage_index=1,
        )
        failures = validate_primary_llm_input(input_)
        assert any("unknown phase" in f for f in failures)

    def test_input_includes_source_and_target_profiles(self) -> None:
        input_ = _valid_primary_input()
        assert input_.source_profile == {"java": "8", "spring_boot": "2.1.6"}
        assert input_.target_profile == {"java": "17", "spring_boot": "3.5.14"}


class TestPrimaryLLMOutput:
    """Tests for primary LLM output contract."""

    def test_valid_output_passes_validation(self) -> None:
        output = _valid_primary_output()
        failures = validate_primary_llm_output(output)
        assert failures == []

    def test_missing_reasoning_fails(self) -> None:
        output = PrimaryLLMOutput(
            reasoning="",
            risks=(),
            confidence=0.5,
            recommended_next_step="proceed",
            draft_markdown="# Summary",
        )
        failures = validate_primary_llm_output(output)
        assert any("missing reasoning" in f for f in failures)

    def test_missing_draft_markdown_fails(self) -> None:
        output = PrimaryLLMOutput(
            reasoning="valid reasoning",
            risks=(),
            confidence=0.5,
            recommended_next_step="proceed",
            draft_markdown="",
        )
        failures = validate_primary_llm_output(output)
        assert any("draft_markdown" in f for f in failures)

    def test_missing_confidence_fails(self) -> None:
        output = PrimaryLLMOutput(
            reasoning="valid reasoning",
            risks=(),
            confidence=-1.0,
            recommended_next_step="proceed",
            draft_markdown="# Summary",
        )
        failures = validate_primary_llm_output(output)
        assert any("confidence" in f for f in failures)

    def test_confidence_out_of_range_fails(self) -> None:
        for bad_conf in (-0.1, 1.1, 99.0):
            output = PrimaryLLMOutput(
                reasoning="valid reasoning",
                risks=("risk1",),
                confidence=bad_conf,
                recommended_next_step="proceed",
                draft_markdown="# Summary",
            )
            failures = validate_primary_llm_output(output)
            assert any("confidence" in f for f in failures)

    def test_execution_instruction_fails(self) -> None:
        output = PrimaryLLMOutput(
            reasoning="You should execute command to update files.",
            risks=(),
            confidence=0.7,
            recommended_next_step="proceed",
            draft_markdown="# Summary",
        )
        failures = validate_primary_llm_output(output)
        assert any("execution instruction" in f for f in failures)

    def test_apply_patch_instruction_fails(self) -> None:
        output = PrimaryLLMOutput(
            reasoning="Valid reasoning.",
            risks=(),
            confidence=0.7,
            recommended_next_step="apply patch to pom.xml",
            draft_markdown="# Summary",
        )
        failures = validate_primary_llm_output(output)
        assert any("execution instruction" in f for f in failures)

    def test_no_execution_instruction_in_normal_text_passes(self) -> None:
        output = PrimaryLLMOutput(
            reasoning="The analysis found javax imports that need migration.",
            risks=("javax-to-jakarta",),
            confidence=0.8,
            recommended_next_step="Proceed to Jakarta migration stage.",
            draft_markdown="# Analysis Summary\n\nThe project needs updates.",
        )
        failures = validate_primary_llm_output(output)
        assert failures == []

    def test_output_computes_checksum(self) -> None:
        output = _valid_primary_output()
        cs = compute_primary_output_checksum(output)
        assert cs
        assert len(cs) == 64  # SHA-256 hex

    def test_computed_checksum_is_deterministic(self) -> None:
        o1 = _valid_primary_output()
        o2 = _valid_primary_output()
        cs1 = compute_primary_output_checksum(o1)
        cs2 = compute_primary_output_checksum(o2)
        assert cs1 == cs2


# ── AMF-256: Reviewer LLM Role ─────────────────────────────────────────


class TestReviewerLLMInput:
    """Tests for reviewer LLM input contract."""

    def test_valid_input_passes_validation(self) -> None:
        input_ = _valid_reviewer_input()
        failures = validate_reviewer_llm_input(input_)
        assert failures == []

    def test_missing_deterministic_artifact_ref_fails(self) -> None:
        input_ = ReviewerLLMInput(
            deterministic_artifact_ref="",
            deterministic_artifact_checksum="abc123",
            primary_output_ref="ref",
            primary_output_checksum="abc",
            primary_reasoning="reasoning",
            draft_markdown="# Summary",
            phase="analysis",
            job_id="job-001",
            stage_index=1,
        )
        failures = validate_reviewer_llm_input(input_)
        assert any("missing deterministic_artifact_ref" in f for f in failures)

    def test_missing_primary_output_ref_fails(self) -> None:
        input_ = ReviewerLLMInput(
            deterministic_artifact_ref="analysis/report.json",
            deterministic_artifact_checksum="abc123",
            primary_output_ref="",
            primary_output_checksum="abc",
            primary_reasoning="reasoning",
            draft_markdown="# Summary",
            phase="analysis",
            job_id="job-001",
            stage_index=1,
        )
        failures = validate_reviewer_llm_input(input_)
        assert any("missing primary_output_ref" in f for f in failures)

    def test_missing_primary_reasoning_fails(self) -> None:
        input_ = ReviewerLLMInput(
            deterministic_artifact_ref="analysis/report.json",
            deterministic_artifact_checksum="abc123",
            primary_output_ref="ref",
            primary_output_checksum="abc",
            primary_reasoning="",
            draft_markdown="# Summary",
            phase="analysis",
            job_id="job-001",
            stage_index=1,
        )
        failures = validate_reviewer_llm_input(input_)
        assert any("missing primary_reasoning" in f for f in failures)

    def test_missing_draft_markdown_fails(self) -> None:
        input_ = ReviewerLLMInput(
            deterministic_artifact_ref="analysis/report.json",
            deterministic_artifact_checksum="abc123",
            primary_output_ref="ref",
            primary_output_checksum="abc",
            primary_reasoning="reasoning",
            draft_markdown="",
            phase="analysis",
            job_id="job-001",
            stage_index=1,
        )
        failures = validate_reviewer_llm_input(input_)
        assert any("missing draft_markdown" in f for f in failures)


class TestReviewerLLMOutput:
    """Tests for reviewer LLM output contract."""

    def test_accept_decision_passes_validation(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        pri_cs = sha256_canonical_json({"output": "v1"})
        output = ReviewerLLMOutput(
            decision="accept",
            notes=("looks good",),
            confidence=0.9,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        failures = validate_reviewer_llm_output(output)
        assert failures == []

    def test_invalid_decision_fails(self) -> None:
        output = ReviewerLLMOutput(
            decision="approved",
            notes=(),
            confidence=0.5,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum="abc",
            reviewed_primary_output_checksum="def",
        )
        failures = validate_reviewer_llm_output(output)
        assert any("invalid decision" in f for f in failures)

    def test_confidence_out_of_range_fails(self) -> None:
        for bad_conf in (-0.1, 1.1, 2.0):
            output = ReviewerLLMOutput(
                decision="accept",
                notes=(),
                confidence=bad_conf,
                risks=(),
                policy_concerns=(),
                reviewed_artifact_checksum="abc",
                reviewed_primary_output_checksum="def",
            )
            failures = validate_reviewer_llm_output(output)
            assert any("confidence" in f for f in failures)

    def test_missing_reviewed_artifact_checksum_fails(self) -> None:
        output = ReviewerLLMOutput(
            decision="accept",
            notes=(),
            confidence=0.5,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum="",
            reviewed_primary_output_checksum="def",
        )
        failures = validate_reviewer_llm_output(output)
        assert any("missing reviewed_artifact_checksum" in f for f in failures)

    def test_missing_reviewed_primary_output_checksum_fails(self) -> None:
        output = ReviewerLLMOutput(
            decision="accept",
            notes=(),
            confidence=0.5,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum="abc",
            reviewed_primary_output_checksum="",
        )
        failures = validate_reviewer_llm_output(output)
        assert any("missing reviewed_primary_output_checksum" in f for f in failures)

    def test_output_computes_checksum(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        pri_cs = sha256_canonical_json({"output": "v1"})
        output = ReviewerLLMOutput(
            decision="accept",
            notes=("good",),
            confidence=0.9,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        cs = compute_reviewer_output_checksum(output)
        assert cs
        assert len(cs) == 64

    def test_computed_checksum_is_deterministic(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        pri_cs = sha256_canonical_json({"output": "v1"})
        o1 = ReviewerLLMOutput(
            decision="accept", notes=("good",), confidence=0.9, risks=(),
            policy_concerns=(), reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        o2 = ReviewerLLMOutput(
            decision="accept", notes=("good",), confidence=0.9, risks=(),
            policy_concerns=(), reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        assert compute_reviewer_output_checksum(o1) == compute_reviewer_output_checksum(o2)


# ── Integrated Chain Tests ──────────────────────────────────────────────


class TestReviewerChecksumBinding:
    """Tests for reviewer checksum binding."""

    def test_accept_with_matching_checksums_passes(self) -> None:
        det_cs = "det-abc123"
        pri_cs = "pri-def456"
        output = ReviewerLLMOutput(
            decision="accept",
            notes=(),
            confidence=0.9,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        failures = validate_checksum_binding(det_cs, pri_cs, output)
        assert failures == []

    def test_checksum_mismatch_on_deterministic_artifact_fails(self) -> None:
        output = ReviewerLLMOutput(
            decision="accept",
            notes=(),
            confidence=0.9,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum="wrong-checksum",
            reviewed_primary_output_checksum="pri-def456",
        )
        failures = validate_checksum_binding("det-abc123", "pri-def456", output)
        assert any("checksum mismatch on deterministic artifact" in f for f in failures)

    def test_checksum_mismatch_on_primary_output_fails(self) -> None:
        output = ReviewerLLMOutput(
            decision="accept",
            notes=(),
            confidence=0.9,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum="det-abc123",
            reviewed_primary_output_checksum="wrong-checksum",
        )
        failures = validate_checksum_binding("det-abc123", "pri-def456", output)
        assert any("checksum mismatch on primary output" in f for f in failures)


class TestReviewedOutputContract:
    """Tests for the full reviewed output contract (integrates all three)."""

    def test_full_accept_chain_passes(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        pri_cs = sha256_canonical_json({"output": "v1"})
        reviewer_output = ReviewerLLMOutput(
            decision="accept",
            notes=("Evidence matches.",),
            confidence=0.95,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        result = validate_reviewed_output_contract(det_cs, pri_cs, reviewer_output)
        assert result.ok is True
        assert result.checksum_matched is True
        assert result.decision == "accept"

    def test_reviewer_reject_fails_closed(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        pri_cs = sha256_canonical_json({"output": "v1"})
        reviewer_output = ReviewerLLMOutput(
            decision="reject",
            notes=("Evidence does not match facts.",),
            confidence=0.3,
            risks=("mismatched evidence",),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        result = validate_reviewed_output_contract(det_cs, pri_cs, reviewer_output)
        assert result.ok is False
        assert any("reviewer rejected" in f for f in result.failures)

    def test_reviewer_request_revision_fails_closed(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        pri_cs = sha256_canonical_json({"output": "v1"})
        reviewer_output = ReviewerLLMOutput(
            decision="request_revision",
            notes=("Needs more detail on risks.",),
            confidence=0.6,
            risks=("incomplete risk assessment",),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        result = validate_reviewed_output_contract(det_cs, pri_cs, reviewer_output)
        assert result.ok is False
        assert any("reviewer requested revision" in f for f in result.failures)

    def test_checksum_mismatch_fails_closed_even_with_accept(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        wrong_pri_cs = "wrong-checksum"
        pri_cs = "correct-primary-checksum"
        reviewer_output = ReviewerLLMOutput(
            decision="accept",
            notes=(),
            confidence=0.9,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=wrong_pri_cs,
        )
        result = validate_reviewed_output_contract(det_cs, pri_cs, reviewer_output)
        assert result.ok is False
        assert result.checksum_matched is False

    def test_malformed_reviewer_output_fails_closed(self) -> None:
        det_cs = sha256_canonical_json({"version": "1.0.0"})
        pri_cs = sha256_canonical_json({"output": "v1"})
        reviewer_output = ReviewerLLMOutput(
            decision="invalid_decision",
            notes=(),
            confidence=0.5,
            risks=(),
            policy_concerns=(),
            reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        result = validate_reviewed_output_contract(det_cs, pri_cs, reviewer_output)
        assert result.ok is False
        assert any("invalid decision" in f for f in result.failures)


# ── Enums and Dimensions ────────────────────────────────────────────────


class TestReviewChainEnums:
    """Tests for enum values used across the review chain."""

    def test_artifact_phase_values(self) -> None:
        assert ArtifactPhase.ANALYSIS.value == "analysis"
        assert ArtifactPhase.PLANNING.value == "planning"

    def test_reviewer_decision_values(self) -> None:
        assert ReviewerDecision.ACCEPT.value == "accept"
        assert ReviewerDecision.REJECT.value == "reject"
        assert ReviewerDecision.REQUEST_REVISION.value == "request_revision"

    def test_review_dimension_values(self) -> None:
        assert ReviewDimension.EVIDENCE_FIT.value == "evidence_fit"
        assert ReviewDimension.CORRECTNESS.value == "correctness"
        assert ReviewDimension.COMPLETENESS.value == "completeness"
        assert ReviewDimension.CHECKSUM_MATCH.value == "checksum_match"
        assert ReviewDimension.STALE_INPUT_CHECK.value == "stale_input_check"


# ── Immutability Tests ──────────────────────────────────────────────────


class TestContractImmutability:
    """Verify that contract dataclasses are frozen (immutable)."""

    def test_deterministic_artifact_binding_is_frozen(self) -> None:
        binding = _valid_analysis_binding()
        with pytest.raises(Exception):
            binding.artifact_ref = "new-ref"  # type: ignore[misc]

    def test_primary_llm_input_is_frozen(self) -> None:
        input_ = _valid_primary_input()
        with pytest.raises(Exception):
            input_.phase = "planning"  # type: ignore[misc]

    def test_primary_llm_output_is_frozen(self) -> None:
        output = _valid_primary_output()
        with pytest.raises(Exception):
            output.confidence = 1.0  # type: ignore[misc]

    def test_reviewer_llm_input_is_frozen(self) -> None:
        input_ = _valid_reviewer_input()
        with pytest.raises(Exception):
            input_.phase = "planning"  # type: ignore[misc]

    def test_reviewer_llm_output_is_frozen(self) -> None:
        det_cs = sha256_canonical_json({"v": "1"})
        pri_cs = sha256_canonical_json({"o": "1"})
        output = ReviewerLLMOutput(
            decision="accept", notes=(), confidence=0.5, risks=(),
            policy_concerns=(), reviewed_artifact_checksum=det_cs,
            reviewed_primary_output_checksum=pri_cs,
        )
        with pytest.raises(Exception):
            output.decision = "reject"  # type: ignore[misc]
