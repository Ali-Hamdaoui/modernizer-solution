from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.application.v2_migration_memory import retrieve_migration_memory
from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    apply_approved_repair_candidate,
    approve_repair_apply_candidate,
    create_repair_apply_candidate,
    public_repair_apply_candidate,
)
from migration_factory.control_tower.application.v2_repair_proposer import propose_stage_repair
from migration_factory.control_tower.application.v2_repair_reviewer import review_stage_repair_draft


FAMILY = "INITMOCKS_TO_OPENMOCKS_CANDIDATE"


def _sandbox(tmp_path: Path) -> tuple[Path, Path, Path]:
    legacy = tmp_path / "legacy" / "src" / "test" / "java" / "ExampleTest.java"
    sandbox = tmp_path / "sandbox"
    target = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    legacy.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    text = "class ExampleTest {\n  void setup() { MockitoAnnotations.initMocks(this); }\n}\n"
    legacy.write_text(text, encoding="utf-8")
    target.write_text(text, encoding="utf-8")
    return legacy, sandbox, target


def _classification() -> dict[str, Any]:
    return {
        "stage_index": 2,
        "failure_type": FAMILY,
        "repair_family_candidate": FAMILY,
        "classification_status": "known_family_candidate",
        "governance_gate_type": "future_deterministic_candidate",
        "source_boot_version": "2.7",
        "target_boot_version": "3.5.16",
        "source_java_version": "11",
        "target_java_version": "17",
        "repair_enabled": False,
        "matched_signals": ["candidate:initmocks_to_openmocks"],
    }


def _stage_evidence(sandbox: Path, target: Path) -> dict[str, Any]:
    return {
        "job_id": "job-r8",
        "stage_index": 2,
        "source_boot_version": "2.7",
        "target_boot_version": "3.5.16",
        "source_java_version": "11",
        "target_java_version": "17",
        "evidence_pack_id": "stage-evidence-r8",
        "evidence_pack_checksum": "sha256:evidence",
        "usable_artifacts": [
            {
                "kind": "test_source",
                "ref": str(target),
                "internal_ref": str(target),
                "excerpt": target.read_text(encoding="utf-8"),
            },
            {
                "kind": "test_report",
                "ref": str(target.parent.parent.parent / "surefire-reports" / "TEST-ExampleTest.xml"),
                "internal_ref": str(target.parent.parent.parent / "surefire-reports" / "TEST-ExampleTest.xml"),
                "excerpt": "<testsuite failures='1'><failure>MockitoAnnotations.initMocks(this);</failure></testsuite>",
            },
            {"kind": "sandbox", "ref": str(sandbox), "internal_ref": str(sandbox)},
        ],
    }


def _llm_trace(*, reviewer_verdict: str = "advisory_accept", proposer_valid: bool = True) -> dict[str, Any]:
    proposer_output: dict[str, Any] = {
        "status": "available",
        "role": "repair_proposer",
        "root_cause": "Mockito initMocks is legacy.",
        "repair_strategy": "Use backend recipe to replace initMocks with openMocks.",
        "expected_change": "One test-local method call replacement.",
        "affected_files": ["src/test/java/ExampleTest.java"],
        "risk_notes": ["future backend gate required"],
        "required_backend_recipe": "INITMOCKS_TO_OPENMOCKS",
        "confidence": "medium",
        "apply_allowed": False,
        "approval_allowed": False,
        "downstream_start_allowed": False,
    }
    if not proposer_valid:
        proposer_output.pop("required_backend_recipe")
    return {
        "proposer_trace": {
            "schema_validation_status": "validated" if proposer_valid else "fallback_validated",
            "output": proposer_output,
            "fallback_used": not proposer_valid,
        },
        "reviewer_trace": {
            "schema_validation_status": "validated",
            "output": {
                "status": "available",
                "role": "repair_reviewer",
                "verdict": reviewer_verdict,
                "critique": "Backend recipe is bounded.",
                "risks": [],
                "missing_evidence": [],
                "unsafe_assumptions": [],
                "recommended_next_action": "use_backend_patch_gate",
                "confidence": "medium",
                "apply_allowed": False,
                "approval_allowed": False,
                "downstream_start_allowed": False,
            },
            "fallback_used": False,
        },
        "llm_fallback_trace": {
            "schema_validation_status": "not_applicable",
            "output": {"apply_allowed": True, "approval_allowed": True, "downstream_start_allowed": True},
        },
    }


def _candidate(tmp_path: Path) -> tuple[dict[str, Any], Path, Path]:
    legacy, sandbox, target = _sandbox(tmp_path)
    classification = _classification()
    evidence = _stage_evidence(sandbox, target)
    memory = retrieve_migration_memory({**classification, "matched_signals": classification["matched_signals"]})
    draft = propose_stage_repair(classification, evidence, memory)
    review = review_stage_repair_draft(classification, evidence, memory, draft)
    classification["migration_memory"] = memory
    classification["repair_proposal_draft"] = draft
    classification["repair_draft_review"] = review
    candidate = create_repair_apply_candidate(classification, evidence, _llm_trace())
    assert candidate is not None
    return candidate, legacy, target


def test_initmocks_failure_creates_llm_assisted_repair_apply_candidate(tmp_path: Path) -> None:
    candidate, _legacy, _target = _candidate(tmp_path)
    public = public_repair_apply_candidate(candidate)
    assert public is not None
    assert public["status"] == "pending_human_approval"
    assert public["family"] == FAMILY
    assert public["patch_source"] == "backend_deterministic_recipe"
    assert public["llm_source"] == "advisory_only"
    assert public["approval_required"] is True
    assert public["apply_enabled"] is False
    assert "_target_path" not in public


def test_reviewer_reject_or_invalid_proposer_prevents_candidate(tmp_path: Path) -> None:
    _legacy, sandbox, target = _sandbox(tmp_path)
    classification = _classification()
    evidence = _stage_evidence(sandbox, target)
    memory = retrieve_migration_memory(classification)
    draft = propose_stage_repair(classification, evidence, memory)
    review = review_stage_repair_draft(classification, evidence, memory, draft)
    classification["repair_proposal_draft"] = draft
    classification["repair_draft_review"] = review
    assert create_repair_apply_candidate(classification, evidence, _llm_trace(reviewer_verdict="advisory_reject")) is None
    assert create_repair_apply_candidate(classification, evidence, _llm_trace(proposer_valid=False)) is None


def test_fallback_model_output_never_enables_apply(tmp_path: Path) -> None:
    candidate, _legacy, _target = _candidate(tmp_path)
    assert candidate["llm_can_apply"] is False
    assert candidate["apply_enabled"] is False


def test_browser_cannot_supply_patch_or_target_and_checksum_mismatch_rejects(tmp_path: Path) -> None:
    candidate, _legacy, _target = _candidate(tmp_path)
    with pytest.raises(ValueError, match="patch_checksum_mismatch"):
        approve_repair_apply_candidate(candidate, {
            "repair_candidate_id": candidate["repair_candidate_id"],
            "patch_checksum": "sha256:browser-patch",
            "target_file_checksum": candidate["target_file_checksum"],
            "review_checksum": candidate["review_checksum"],
            "patch": "browser supplied patch",
            "target_path": "src/test/java/Hacked.java",
        })


def test_valid_approval_applies_to_sandbox_only_and_writes_proof(tmp_path: Path) -> None:
    candidate, legacy, target = _candidate(tmp_path)
    legacy_before = legacy.read_text(encoding="utf-8")
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    result = apply_approved_repair_candidate(candidate, approval)
    assert result["execution_status"] == "verified"
    assert result["verification_status"] == "passed"
    assert "MockitoAnnotations.openMocks" in target.read_text(encoding="utf-8")
    assert "MockitoAnnotations.initMocks" not in target.read_text(encoding="utf-8")
    assert legacy.read_text(encoding="utf-8") == legacy_before
    assert result["downstream_start_allowed"] is False
    proof_path = next((Path(candidate["_sandbox_root"]) / ".migration" / "repair-proofs").glob("*.json"))
    assert proof_path.is_file()
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["status"] == "verified"


def test_pre_apply_checksum_mismatch_rejects_apply(tmp_path: Path) -> None:
    candidate, _legacy, target = _candidate(tmp_path)
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    target.write_text("changed before apply\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pre_apply_checksum_mismatch"):
        apply_approved_repair_candidate(candidate, approval)


def test_rollback_restores_original_file_on_verification_failure(tmp_path: Path) -> None:
    candidate, _legacy, target = _candidate(tmp_path)
    before = target.read_text(encoding="utf-8")
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    result = apply_approved_repair_candidate(candidate, approval, verification_runner=lambda _path: (False, "forced failure"))
    assert result["execution_status"] == "rolled_back"
    assert result["rollback_status"] == "succeeded"
    assert target.read_text(encoding="utf-8") == before
    assert next((Path(candidate["_sandbox_root"]) / ".migration" / "repair-proofs").glob("*.json")).is_file()


def test_powermock_remains_human_gate_no_apply_candidate(tmp_path: Path) -> None:
    _legacy, sandbox, target = _sandbox(tmp_path)
    classification = {
        "stage_index": 1,
        "failure_type": "POWERMOCK_LEGACY_TEST_STRATEGY",
        "classification_status": "unsupported_known_failure",
        "governance_gate_type": "human_review_gate",
        "repair_enabled": False,
    }
    evidence = _stage_evidence(sandbox, target)
    assert create_repair_apply_candidate(classification, evidence, _llm_trace()) is None
