from __future__ import annotations

from pathlib import Path

from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    apply_approved_repair_candidate,
    approve_repair_apply_candidate,
)
from tests.control_tower.test_v2_repair_apply_candidate import _candidate


def test_r8_execution_captures_verification_and_keeps_downstream_blocked(tmp_path: Path) -> None:
    candidate, _legacy, target = _candidate(tmp_path)
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    result = apply_approved_repair_candidate(candidate, approval)
    assert result["verification_status"] == "passed"
    assert result["proof_artifact"]
    assert result["downstream_start_allowed"] is False
    assert "openMocks" in target.read_text(encoding="utf-8")


def test_r8_execution_rolls_back_when_verification_fails(tmp_path: Path) -> None:
    candidate, _legacy, target = _candidate(tmp_path)
    before = target.read_text(encoding="utf-8")
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    result = apply_approved_repair_candidate(candidate, approval, verification_runner=lambda _path: (False, "forced fail"))
    assert result["execution_status"] == "rolled_back"
    assert result["rollback_status"] == "succeeded"
    assert target.read_text(encoding="utf-8") == before
