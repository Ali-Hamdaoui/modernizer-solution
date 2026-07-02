from __future__ import annotations

from pathlib import Path

from migration_factory.control_tower.application.v2_repair_proposer import (
    SUPPORTED_FAMILY,
    propose_stage_repair,
)
from migration_factory.control_tower.adapters.fastapi.app import _safe_repair_proposal_draft


def _classification(
    *,
    failure_type: str = SUPPORTED_FAMILY,
    status: str = "known_family_candidate",
    family: str = SUPPORTED_FAMILY,
    gate: str = "future_deterministic_candidate",
) -> dict[str, object]:
    return {
        "stage_index": 2,
        "stage_name": "Stage 2",
        "source_boot_version": "2.7",
        "target_boot_version": "3.5.16",
        "source_java_version": "11",
        "target_java_version": "17",
        "classification_status": status,
        "failure_type": failure_type,
        "repair_family_candidate": family,
        "governance_gate_type": gate,
        "repair_blocked_reason": "human_review_gate_no_auto_repair" if gate == "human_review_gate" else "",
        "assistant_next_action": "review_powermock_legacy_test_strategy" if gate == "human_review_gate" else "prepare_evidence_bound_proposal_in_R7D",
        "matched_signals": ["candidate:initmocks_to_openmocks"],
        "missing_required_evidence": [],
        "usable_artifacts": ["test_source"],
        "repair_enabled": False,
        "evidence_pack_id": "stage-evidence-test",
        "evidence_pack_checksum": "sha256:evidence",
    }


def _memory() -> dict[str, object]:
    return {
        "retrieval_status": "available",
        "query_signature": "sha256:memory-query",
        "retrieved_case_ids": ["msa-utils-initmocks-to-openmocks"],
        "authority_level": "advisory_only",
        "repair_enabled": False,
        "memory_can_apply": False,
        "memory_can_approve": False,
        "memory_can_start_downstream": False,
    }


def _stage_evidence(tmp_path: Path, source_text: str = "MockitoAnnotations.initMocks(this);\n") -> dict[str, object]:
    sandbox = tmp_path / "sandbox"
    test_file = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(source_text, encoding="utf-8")
    return {
        "stage_index": 2,
        "source_boot_version": "2.7",
        "target_boot_version": "3.5.16",
        "source_java_version": "11",
        "target_java_version": "17",
        "evidence_pack_id": "stage-evidence-test",
        "evidence_pack_checksum": "sha256:evidence",
        "usable_artifacts": [
            {"kind": "sandbox", "ref": "[redacted-windows-path]", "internal_ref": str(sandbox), "checksum": ""},
            {
                "kind": "test_source",
                "ref": "[redacted-windows-path]",
                "internal_ref": str(test_file),
                "checksum": "sha256:test",
                "excerpt": source_text,
            },
        ],
        "missing_artifacts": [],
        "downstream_stage_state": {"next_stage_index": 3, "state": "pending_blocked_by_failed_stage", "auto_started": False},
    }


def test_powermock_classification_blocks_human_review_gate(tmp_path: Path) -> None:
    result = propose_stage_repair(
        _classification(
            failure_type="POWERMOCK_LEGACY_TEST_STRATEGY",
            status="unsupported_known_failure",
            family="",
            gate="human_review_gate",
        ),
        _stage_evidence(tmp_path),
        _memory(),
    )
    assert result["proposal_status"] == "blocked_human_review_gate"
    assert result["proposed_diff_preview"] == ""
    assert result["apply_enabled"] is False
    assert result["approval_enabled"] is False
    assert result["repair_enabled"] is False


def test_initmocks_complete_evidence_creates_non_actionable_draft(tmp_path: Path) -> None:
    result = propose_stage_repair(_classification(), _stage_evidence(tmp_path), _memory())
    assert result["proposal_status"] == "drafted_non_actionable"
    assert result["supported_family"] == SUPPORTED_FAMILY
    assert result["evidence_pack_checksum"] == "sha256:evidence"
    assert result["memory_query_signature"] == "sha256:memory-query"
    assert result["retrieved_memory_case_ids"] == ["msa-utils-initmocks-to-openmocks"]
    assert result["target_files"] == ["src/test/java/ExampleTest.java"]
    assert result["target_file_checksums"]["src/test/java/ExampleTest.java"].startswith("sha256:")
    assert "-MockitoAnnotations.initMocks(this);" in result["proposed_diff_preview"]
    assert "+MockitoAnnotations.openMocks(this);" in result["proposed_diff_preview"]
    assert result["proposed_diff_checksum"].startswith("sha256:")
    assert result["proposal_checksum"].startswith("sha256:")
    assert result["llm_invoked"] is False
    assert result["apply_enabled"] is False
    assert result["approval_enabled"] is False
    assert result["repair_enabled"] is False
    assert result["downstream_start_allowed"] is False


def test_initmocks_preserves_target_argument(tmp_path: Path) -> None:
    result = propose_stage_repair(
        _classification(),
        _stage_evidence(tmp_path, "MockitoAnnotations.initMocks(target);\n"),
        _memory(),
    )
    assert "+MockitoAnnotations.openMocks(target);" in result["proposed_diff_preview"]


def test_initmocks_blocks_when_test_source_missing(tmp_path: Path) -> None:
    evidence = _stage_evidence(tmp_path)
    evidence["usable_artifacts"] = [evidence["usable_artifacts"][0]]
    result = propose_stage_repair(_classification(), evidence, _memory())
    assert result["proposal_status"] == "blocked_pending_evidence"
    assert result["blocked_reason"] == "test_source_evidence_missing"


def test_initmocks_blocks_when_marker_absent(tmp_path: Path) -> None:
    result = propose_stage_repair(_classification(), _stage_evidence(tmp_path, "assertTrue(true);\n"), _memory())
    assert result["proposal_status"] == "blocked_pending_evidence"
    assert result["blocked_reason"] == "initmocks_marker_missing"


def test_initmocks_blocks_when_checksum_unavailable(tmp_path: Path) -> None:
    evidence = _stage_evidence(tmp_path)
    test_file = Path(evidence["usable_artifacts"][1]["internal_ref"])
    test_file.unlink()
    result = propose_stage_repair(_classification(), evidence, _memory())
    assert result["proposal_status"] == "blocked_pending_evidence"
    assert result["blocked_reason"] == "target_file_unreadable"


def test_initmocks_blocks_untrusted_absolute_path_without_sandbox(tmp_path: Path) -> None:
    evidence = _stage_evidence(tmp_path)
    evidence["usable_artifacts"] = [evidence["usable_artifacts"][1]]
    result = propose_stage_repair(_classification(), evidence, _memory())
    assert result["proposal_status"] == "blocked_pending_evidence"
    assert result["blocked_reason"] == "sandbox_binding_unavailable_for_target_file"


def test_initmocks_blocks_relative_target_without_sandbox_binding(tmp_path: Path, monkeypatch) -> None:
    relative_file = tmp_path / "src" / "test" / "java" / "ExampleTest.java"
    relative_file.parent.mkdir(parents=True)
    relative_file.write_text("MockitoAnnotations.initMocks(this);\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    evidence = {
        "stage_index": 2,
        "evidence_pack_id": "stage-evidence-test",
        "evidence_pack_checksum": "sha256:evidence",
        "usable_artifacts": [{
            "kind": "test_source",
            "ref": "src/test/java/ExampleTest.java",
            "internal_ref": "src/test/java/ExampleTest.java",
            "checksum": "sha256:test",
            "excerpt": "MockitoAnnotations.initMocks(this);",
        }],
        "missing_artifacts": [],
    }
    result = propose_stage_repair(_classification(), evidence, _memory())
    assert result["proposal_status"] == "blocked_pending_evidence"
    assert result["blocked_reason"] == "target_file_ref_untrusted"


def test_mockbean_remains_unsupported_even_with_memory(tmp_path: Path) -> None:
    result = propose_stage_repair(
        _classification(
            failure_type="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
            family="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        ),
        _stage_evidence(tmp_path),
        {"query_signature": "sha256:memory", "retrieved_case_ids": ["msa-utils-mockbean-to-mockitobean"]},
    )
    assert result["proposal_status"] == "blocked_unsupported_family"
    assert result["proposed_diff_preview"] == ""


def test_review_gate_families_remain_blocked(tmp_path: Path) -> None:
    for failure_type in (
        "AZURE_SDK_API_MIGRATION_REVIEW",
        "PUBLIC_API_SIGNATURE_CHANGE_REVIEW",
        "SPRING_SECURITY_BEHAVIOR_REVIEW",
        "HTTP_STATUS_CONTRACT_DRIFT",
    ):
        result = propose_stage_repair(
            _classification(failure_type=failure_type, status="unsupported_known_failure", family="", gate="human_review_gate"),
            _stage_evidence(tmp_path),
            _memory(),
        )
        assert result["proposal_status"] == "blocked_human_review_gate"
        assert result["apply_enabled"] is False


def test_browser_cannot_inject_proposal_authority() -> None:
    sanitized = _safe_repair_proposal_draft({
        "proposal_status": "drafted_non_actionable",
        "supported_family": "POWERMOCK_LEGACY_TEST_STRATEGY",
        "target_files": ["C:/legacy/App.java"],
        "proposed_diff_preview": "patch",
        "apply_enabled": True,
        "approval_enabled": True,
        "repair_enabled": True,
        "llm_invoked": True,
        "legacy_mutation_allowed": True,
        "downstream_start_allowed": True,
        "sandbox_only": False,
    })
    assert sanitized is not None
    assert sanitized["supported_family"] == ""
    assert sanitized["target_files"] == []
    assert sanitized["proposed_diff_preview"] == ""
    assert sanitized["apply_enabled"] is False
    assert sanitized["approval_enabled"] is False
    assert sanitized["repair_enabled"] is False
    assert sanitized["llm_invoked"] is False
    assert sanitized["legacy_mutation_allowed"] is False
    assert sanitized["downstream_start_allowed"] is False
    assert sanitized["sandbox_only"] is True


def test_browser_cannot_inject_allowed_family_patch_fields() -> None:
    sanitized = _safe_repair_proposal_draft({
        "proposal_status": "drafted_non_actionable",
        "supported_family": "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        "target_files": ["src/test/java/ExampleTest.java"],
        "target_file_checksums": {"src/test/java/ExampleTest.java": "sha256:file"},
        "source_markers": ["MockitoAnnotations.initMocks"],
        "proposed_diff_preview": "-initMocks\n+openMocks",
        "proposed_diff_checksum": "sha256:diff",
        "proposal_checksum": "sha256:proposal",
        "apply_enabled": True,
    })
    assert sanitized is not None
    assert sanitized["target_files"] == []
    assert sanitized["target_file_checksums"] == {}
    assert sanitized["source_markers"] == []
    assert sanitized["proposed_diff_preview"] == ""
    assert sanitized["proposed_diff_checksum"] == ""
    assert sanitized["apply_enabled"] is False


def test_proposer_uses_no_live_llm_or_api_calls(monkeypatch, tmp_path: Path) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("network call attempted")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    result = propose_stage_repair(_classification(), _stage_evidence(tmp_path), _memory())
    assert result["proposal_status"] == "drafted_non_actionable"
    assert result["llm_invoked"] is False
