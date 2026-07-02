from __future__ import annotations

from copy import deepcopy

from migration_factory.control_tower.adapters.fastapi.app import _safe_repair_draft_review
from migration_factory.control_tower.domain.checksums import sha256_canonical_json
from migration_factory.control_tower.application.v2_repair_reviewer import (
    FutureLlmRepairDraftReviewer,
    review_stage_repair_draft,
)


FAMILY = "INITMOCKS_TO_OPENMOCKS_CANDIDATE"


def _classification(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "stage_index": 2,
        "stage_name": "Stage 2",
        "source_boot_version": "2.7",
        "target_boot_version": "3.5.16",
        "source_java_version": "11",
        "target_java_version": "17",
        "classification_status": "known_family_candidate",
        "failure_type": FAMILY,
        "repair_family_candidate": FAMILY,
        "governance_gate_type": "future_deterministic_candidate",
        "repair_blocked_reason": "",
        "repair_enabled": False,
        "evidence_pack_id": "stage-evidence-test",
        "evidence_pack_checksum": "sha256:evidence",
    }
    value.update(overrides)
    return value


def _stage_evidence() -> dict[str, object]:
    return {
        "stage_index": 2,
        "source_boot_version": "2.7",
        "target_boot_version": "3.5.16",
        "source_java_version": "11",
        "target_java_version": "17",
        "evidence_pack_id": "stage-evidence-test",
        "evidence_pack_checksum": "sha256:evidence",
        "downstream_stage_state": {
            "next_stage_index": 3,
            "state": "pending_blocked_by_failed_stage",
            "auto_started": False,
        },
    }


def _memory(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "retrieval_status": "available",
        "query_signature": "sha256:memory-query",
        "retrieved_case_ids": ["msa-utils-initmocks-to-openmocks"],
        "authority_level": "advisory_only",
        "repair_enabled": False,
        "memory_can_apply": False,
        "memory_can_approve": False,
        "memory_can_start_downstream": False,
    }
    value.update(overrides)
    return value


def _draft(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "proposal_status": "drafted_non_actionable",
        "proposal_type": "evidence_bound_repair_draft",
        "supported_family": FAMILY,
        "failure_type": FAMILY,
        "classification_status": "known_family_candidate",
        "governance_gate_type": "future_deterministic_candidate",
        "stage_index": 2,
        "source_boot_version": "2.7",
        "target_boot_version": "3.5.16",
        "source_java_version": "11",
        "target_java_version": "17",
        "evidence_pack_id": "stage-evidence-test",
        "evidence_pack_checksum": "sha256:evidence",
        "memory_query_signature": "sha256:memory-query",
        "retrieved_memory_case_ids": ["msa-utils-initmocks-to-openmocks"],
        "target_files": ["src/test/java/ExampleTest.java"],
        "source_markers": ["MockitoAnnotations.initMocks"],
        "target_file_checksums": {"src/test/java/ExampleTest.java": "sha256:file-before"},
        "proposed_diff_preview": (
            "--- a/src/test/java/ExampleTest.java\n"
            "+++ b/src/test/java/ExampleTest.java\n"
            "@@ -1 +1 @@\n"
            "-MockitoAnnotations.initMocks(this);\n"
            "+MockitoAnnotations.openMocks(this);\n"
        ),
        "proposed_diff_checksum": "",
        "proposal_checksum": "",
        "proposer_kind": "deterministic_local",
        "proposer_origin": "backend_evidence_bound",
        "llm_invoked": False,
        "reviewer_required": True,
        "human_approval_required": True,
        "backend_apply_required": True,
        "apply_enabled": False,
        "approval_enabled": False,
        "repair_enabled": False,
        "sandbox_only": True,
        "legacy_mutation_allowed": False,
        "downstream_start_allowed": False,
        "blocked_reason": "",
        "assistant_next_action": "send_draft_to_future_reviewer_gate",
        "safety_warnings": ["Draft is non-actionable in R7D."],
    }
    value.update(overrides)
    if "proposed_diff_checksum" not in overrides:
        value["proposed_diff_checksum"] = _diff_checksum(str(value["proposed_diff_preview"]))
    if "proposal_checksum" not in overrides:
        value["proposal_checksum"] = _proposal_checksum(value)
    return value


def _diff_checksum(diff: str) -> str:
    return f"sha256:{sha256_canonical_json({'diff': diff})}"


def _proposal_checksum(draft: dict[str, object]) -> str:
    return f"sha256:{sha256_canonical_json({k: v for k, v in draft.items() if k != 'proposal_checksum'})}"


def _review(
    *,
    classification: dict[str, object] | None = None,
    memory: dict[str, object] | None = None,
    draft: dict[str, object] | None = None,
) -> dict[str, object]:
    return review_stage_repair_draft(
        classification if classification is not None else _classification(),
        _stage_evidence(),
        memory if memory is not None else _memory(),
        draft if draft is not None else _draft(),
    )


def test_powermock_blocked_draft_returns_not_reviewable_human_gate() -> None:
    result = _review(
        classification=_classification(
            failure_type="POWERMOCK_LEGACY_TEST_STRATEGY",
            classification_status="unsupported_known_failure",
            repair_family_candidate="",
            governance_gate_type="human_review_gate",
            repair_blocked_reason="human_review_gate_no_auto_repair",
        ),
        draft=_draft(
            proposal_status="blocked_human_review_gate",
            supported_family="",
            failure_type="POWERMOCK_LEGACY_TEST_STRATEGY",
            classification_status="unsupported_known_failure",
            governance_gate_type="human_review_gate",
            proposed_diff_preview="",
            proposed_diff_checksum="",
            proposal_checksum="",
            target_files=[],
            target_file_checksums={},
        ),
    )
    assert result["review_status"] == "not_reviewable_blocked_human_gate"
    assert result["verdict"] == "blocked"
    assert result["checksum_verification_status"] == "not_applicable"
    assert result["apply_enabled"] is False
    assert result["approval_enabled"] is False
    assert result["repair_enabled"] is False
    assert result["downstream_start_allowed"] is False


def test_unsupported_family_never_accepted() -> None:
    result = _review(draft=_draft(
        supported_family="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        failure_type="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
    ))
    assert result["review_status"] == "reviewed_non_actionable"
    assert result["verdict"] == "rejected"
    assert "unsupported_family" in result["reasons"]


def test_browser_style_draft_without_backend_origin_rejects() -> None:
    result = _review(draft=_draft(proposer_origin=""))
    assert result["verdict"] == "rejected"
    assert "proposer_origin_not_backend_evidence_bound" in result["reasons"]


def test_complete_initmocks_draft_is_accepted_for_future_apply_gate() -> None:
    result = _review()
    assert result["review_status"] == "reviewed_non_actionable"
    assert result["verdict"] == "accepted_for_future_apply_gate"
    assert result["reviewer_kind"] == "deterministic_local"
    assert result["reviewer_origin"] == "backend_evidence_bound"
    assert result["llm_invoked"] is False
    assert result["future_llm_reviewer_compatible"] is True
    assert result["reviewed_family"] == FAMILY
    assert result["evidence_pack_checksum"] == "sha256:evidence"
    assert result["memory_query_signature"] == "sha256:memory-query"
    assert result["target_file_checksums"] == {"src/test/java/ExampleTest.java": "sha256:file-before"}
    assert result["checksum_verification_status"] == "verified"
    assert result["diff_checksum_match"] is True
    assert result["proposal_checksum_match"] is True
    assert result["declared_diff_checksum"] == result["recomputed_diff_checksum"]
    assert result["declared_proposal_checksum"] == result["recomputed_proposal_checksum"]
    assert result["proposed_diff_checksum"] == result["recomputed_diff_checksum"]
    assert result["proposal_checksum"] == result["recomputed_proposal_checksum"]
    assert str(result["review_checksum"]).startswith("sha256:")
    assert result["required_followup_gate"] == "future_human_approval_and_backend_apply_gate"
    assert result["reasons"] == []


def test_missing_evidence_checksum_rejects() -> None:
    result = _review(draft=_draft(evidence_pack_checksum=""))
    assert result["verdict"] == "rejected"
    assert "evidence_pack_checksum_missing" in result["reasons"]


def test_missing_memory_query_signature_rejects() -> None:
    result = _review(draft=_draft(memory_query_signature=""))
    assert result["verdict"] == "rejected"
    assert "memory_query_signature_missing" in result["reasons"]


def test_missing_target_checksum_rejects() -> None:
    result = _review(draft=_draft(target_file_checksums={}))
    assert result["verdict"] == "rejected"
    assert "target_file_checksum_missing" in result["reasons"]


def test_missing_proposed_diff_checksum_rejects() -> None:
    result = _review(draft=_draft(proposed_diff_checksum=""))
    assert result["verdict"] == "rejected"
    assert "proposed_diff_checksum_missing" in result["reasons"]
    assert result["checksum_verification_status"] == "failed"


def test_missing_proposal_checksum_rejects() -> None:
    result = _review(draft=_draft(proposal_checksum=""))
    assert result["verdict"] == "rejected"
    assert "proposal_checksum_missing" in result["reasons"]
    assert result["checksum_verification_status"] == "failed"


def test_tampered_diff_with_old_declared_checksum_rejects() -> None:
    original = _draft()
    result = _review(draft={**original, "proposed_diff_preview": "-MockitoAnnotations.initMocks(that);\n+MockitoAnnotations.openMocks(that);\n"})
    assert result["verdict"] == "rejected"
    assert result["checksum_verification_status"] == "failed"
    assert result["diff_checksum_match"] is False
    assert "proposed_diff_checksum_mismatch" in result["reasons"]


def test_tampered_proposal_field_with_old_proposal_checksum_rejects() -> None:
    original = _draft()
    result = _review(draft={**original, "memory_query_signature": "sha256:memory-query-tampered"})
    assert result["verdict"] == "rejected"
    assert result["checksum_verification_status"] == "failed"
    assert result["proposal_checksum_match"] is False
    assert "proposal_checksum_mismatch" in result["reasons"]


def test_diff_that_changes_powermock_rejects() -> None:
    result = _review(draft=_draft(
        proposed_diff_preview="-MockitoAnnotations.initMocks(this);\n+MockitoAnnotations.openMocks(this);\n+PowerMockito.mockStatic(Foo.class);\n",
    ))
    assert result["verdict"] == "rejected"
    assert "powermock_change_detected" in result["reasons"]


def test_diff_that_changes_dependencies_rejects() -> None:
    result = _review(draft=_draft(
        proposed_diff_preview="-MockitoAnnotations.initMocks(this);\n+MockitoAnnotations.openMocks(this);\n+<dependency>org.mockito</dependency>\n",
    ))
    assert result["verdict"] == "rejected"
    assert "dependency_change_detected" in result["reasons"]


def test_diff_without_initmocks_removal_rejects() -> None:
    result = _review(draft=_draft(proposed_diff_preview="+MockitoAnnotations.openMocks(this);\n"))
    assert result["verdict"] == "rejected"
    assert "initmocks_removal_missing" in result["reasons"]


def test_diff_without_openmocks_addition_rejects() -> None:
    result = _review(draft=_draft(proposed_diff_preview="-MockitoAnnotations.initMocks(this);\n"))
    assert result["verdict"] == "rejected"
    assert "openmocks_addition_missing" in result["reasons"]


def test_memory_attempting_authority_is_rejected_and_clamped_to_advisory() -> None:
    result = _review(memory=_memory(
        authority_level="apply_authority",
        repair_enabled=True,
        memory_can_apply=True,
        memory_can_approve=True,
        memory_can_start_downstream=True,
    ))
    assert result["verdict"] == "rejected"
    assert "memory_authority_not_advisory" in result["reasons"]
    assert result["memory_authority"] == "advisory_only"
    assert result["memory_can_apply"] is False
    assert result["memory_can_approve"] is False
    assert result["memory_can_start_downstream"] is False


def test_reviewer_output_always_has_no_authority_flags() -> None:
    result = _review(draft=_draft(
        apply_enabled=True,
        approval_enabled=True,
        repair_enabled=True,
        downstream_start_allowed=True,
        legacy_mutation_allowed=True,
    ))
    assert result["verdict"] == "rejected"
    assert result["apply_enabled"] is False
    assert result["approval_enabled"] is False
    assert result["repair_enabled"] is False
    assert result["downstream_start_allowed"] is False
    assert result["legacy_mutation_allowed"] is False


def test_review_checksum_changes_when_reviewed_inputs_change() -> None:
    first = _review()
    changed_draft = deepcopy(_draft())
    changed_draft["proposal_checksum"] = "sha256:proposal-changed"
    second = _review(draft=changed_draft)
    assert first["review_checksum"] != second["review_checksum"]


def test_reviewer_uses_no_live_llm_or_api_calls(monkeypatch) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("network call attempted")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    result = _review()
    assert result["verdict"] == "accepted_for_future_apply_gate"
    assert result["llm_invoked"] is False


def test_future_llm_reviewer_contract_exists_but_is_not_enabled() -> None:
    result = FutureLlmRepairDraftReviewer().review(_classification(), _stage_evidence(), _memory(), _draft())
    assert result["reviewer_kind"] == "deterministic_local"
    assert result["future_llm_reviewer_compatible"] is True
    assert result["llm_invoked"] is False
    assert result["verdict"] == "rejected"
    assert "future_llm_reviewer_not_enabled_in_R7E" in result["reasons"]


def test_browser_cannot_inject_reviewer_acceptance_or_authority() -> None:
    sanitized = _safe_repair_draft_review({
        "review_status": "reviewed_non_actionable",
        "verdict": "accepted_for_future_apply_gate",
        "reviewer_kind": "llm_live",
        "reviewer_origin": "browser",
        "reviewed_family": "POWERMOCK_LEGACY_TEST_STRATEGY",
        "target_files": ["C:/legacy/App.java"],
        "target_file_checksums": {"C:/legacy/App.java": "sha256:file"},
        "proposed_diff_checksum": "sha256:diff",
        "proposal_checksum": "sha256:proposal",
        "review_checksum": "sha256:review",
        "declared_diff_checksum": "sha256:declared-diff",
        "recomputed_diff_checksum": "sha256:fake-recomputed-diff",
        "diff_checksum_match": True,
        "declared_proposal_checksum": "sha256:declared-proposal",
        "recomputed_proposal_checksum": "sha256:fake-recomputed-proposal",
        "proposal_checksum_match": True,
        "checksum_verification_status": "verified",
        "apply_enabled": True,
        "approval_enabled": True,
        "repair_enabled": True,
        "downstream_start_allowed": True,
        "legacy_mutation_allowed": True,
        "memory_authority": "apply",
        "memory_can_apply": True,
        "memory_can_approve": True,
        "memory_can_start_downstream": True,
    })
    assert sanitized is not None
    assert sanitized["verdict"] == "rejected"
    assert sanitized["reviewed_family"] == ""
    assert sanitized["reviewer_kind"] == "deterministic_local"
    assert sanitized["reviewer_origin"] == ""
    assert sanitized["target_files"] == []
    assert sanitized["target_file_checksums"] == {}
    assert sanitized["proposed_diff_checksum"] == ""
    assert sanitized["proposal_checksum"] == ""
    assert sanitized["review_checksum"] == ""
    assert sanitized["declared_diff_checksum"] == ""
    assert sanitized["recomputed_diff_checksum"] == ""
    assert sanitized["diff_checksum_match"] is False
    assert sanitized["declared_proposal_checksum"] == ""
    assert sanitized["recomputed_proposal_checksum"] == ""
    assert sanitized["proposal_checksum_match"] is False
    assert sanitized["checksum_verification_status"] == "failed"
    assert sanitized["apply_enabled"] is False
    assert sanitized["approval_enabled"] is False
    assert sanitized["repair_enabled"] is False
    assert sanitized["downstream_start_allowed"] is False
    assert sanitized["legacy_mutation_allowed"] is False
    assert sanitized["memory_authority"] == "advisory_only"


def test_browser_injected_supported_family_verified_review_still_rejected() -> None:
    sanitized = _safe_repair_draft_review({
        "review_status": "reviewed_non_actionable",
        "verdict": "accepted_for_future_apply_gate",
        "reviewer_origin": "browser",
        "reviewed_family": FAMILY,
        "target_files": ["src/test/java/ExampleTest.java"],
        "target_file_checksums": {"src/test/java/ExampleTest.java": "sha256:file"},
        "declared_diff_checksum": "sha256:diff",
        "recomputed_diff_checksum": "sha256:diff",
        "diff_checksum_match": True,
        "declared_proposal_checksum": "sha256:proposal",
        "recomputed_proposal_checksum": "sha256:proposal",
        "proposal_checksum_match": True,
        "checksum_verification_status": "verified",
    })
    assert sanitized is not None
    assert sanitized["verdict"] == "rejected"
    assert sanitized["reviewer_origin"] == ""
    assert sanitized["target_files"] == []
    assert sanitized["declared_diff_checksum"] == ""
    assert sanitized["checksum_verification_status"] == "failed"
