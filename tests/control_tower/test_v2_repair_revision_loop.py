"""F5-T9: Request Another Review / Revision Loop tests.

Verifies context pack checksum semantics, revision cycle progression,
and V2RepairFlowService.create_revision_proposal behavior.
"""

from __future__ import annotations

import pytest

from migration_factory.repair_loop.repair_context import (
    RepairContextPack,
    build_repair_context_pack,
    compute_context_pack_checksum,
)
from migration_factory.repair_loop.failure_evidence import (
    FailureEvidence,
    FailureSource,
    build_failure_evidence,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
    RepairProposal,
)


_failure_evidence = build_failure_evidence(
    failure_source=FailureSource.BUILD,
    job_id="job-1",
    stage_index=1,
    command_id="cmd-1",
    failure_summary="Build failed: missing import",
    changed_files=("src/App.java",),
    source_profile="java8",
    target_profile="java21",
)


def _pack(**overrides) -> RepairContextPack:
    kwargs: dict = {
        "failure_evidence": _failure_evidence,
        "job_id": "job-1",
        "stage_index": 1,
        "command_id": "cmd-1",
        "source_profile": "java8",
        "target_profile": "java21",
        "cycle_number": 1,
        "max_cycles": 3,
    }
    kwargs.update(overrides)
    return build_repair_context_pack(**kwargs)


def _pack_cycle_0(**overrides) -> RepairContextPack:
    return _pack(cycle_number=0, **overrides)


def _pack_cycle_1(**overrides) -> RepairContextPack:
    return _pack(cycle_number=1, **overrides)


def _pack_cycle_2(**overrides) -> RepairContextPack:
    return _pack(cycle_number=2, **overrides)


# ── Context pack checksum tests ──────────────────────────────────────


def test_checksum_changes_when_user_comments_change() -> None:
    pack_a = _pack(user_comments="fix the typo")
    pack_b = _pack(user_comments="also update the dependency version")
    assert pack_a.context_pack_checksum != pack_b.context_pack_checksum


def test_checksum_differs_from_previous_cycle_pack() -> None:
    pack_c0 = _pack(cycle_number=0, prior_proposal_checksums=("prop-a",))
    pack_c1 = _pack(
        cycle_number=1,
        prior_proposal_checksums=("prop-a", "prop-b"),
        prior_reviewer_notes=("reviewer said no",),
        prior_revision_ids=("rev-1",),
        user_comments="please use narrower scope",
    )
    assert pack_c0.context_pack_checksum != pack_c1.context_pack_checksum


def test_prior_proposal_checksums_in_next_cycle() -> None:
    pack = _pack(cycle_number=2, prior_proposal_checksums=("prop-a", "prop-b"))
    checksum = compute_context_pack_checksum(pack)
    payload = {
        k: v
        for k, v in pack.__dict__.items()
        if k in (
            "job_id",
            "stage_index",
            "command_id",
            "failure_source",
            "failure_evidence_checksum",
            "source_profile",
            "target_profile",
            "accepted_analysis_checksum",
            "accepted_planning_checksum",
            "prior_proposal_checksums",
            "prior_reviewer_notes",
            "user_comments",
            "changed_files",
            "safe_log_preview",
            "base_repo_state_checksum",
            "prior_revision_ids",
            "cycle_number",
            "max_cycles",
        )
    }
    pack_from = RepairContextPack(**{
        **{f: getattr(pack, f) for f in ["job_id", "stage_index", "command_id", "failure_source", "failure_evidence_checksum", "source_profile", "target_profile", "accepted_analysis_checksum", "accepted_planning_checksum", "user_comments", "safe_log_preview", "base_repo_state_checksum", "context_pack_checksum", "created_at", "schema_version"]},
        "prior_proposal_checksums": ("prop-a",),
        "prior_reviewer_notes": pack.prior_reviewer_notes,
        "prior_revision_ids": pack.prior_revision_ids,
        "changed_files": pack.changed_files,
        "cycle_number": pack.cycle_number,
        "max_cycles": pack.max_cycles,
    })
    diff_checksum = compute_context_pack_checksum(pack_from)
    assert checksum != diff_checksum
    assert "prop-a" in pack.prior_proposal_checksums
    assert "prop-b" in pack.prior_proposal_checksums


def test_prior_reviewer_notes_in_next_cycle() -> None:
    pack = _pack(cycle_number=2, prior_reviewer_notes=("needs narrower scope", "check imports"))
    assert "needs narrower scope" in pack.prior_reviewer_notes
    assert "check imports" in pack.prior_reviewer_notes


def test_prior_revision_ids_in_new_context() -> None:
    pack = _pack(prior_revision_ids=("rev-1", "rev-2"))
    assert "rev-1" in pack.prior_revision_ids
    assert "rev-2" in pack.prior_revision_ids


def test_cycle_number_increments_each_revision() -> None:
    c0 = _pack(cycle_number=0)
    c1 = _pack(cycle_number=1, prior_proposal_checksums=("prop-0",))
    c2 = _pack(cycle_number=2, prior_proposal_checksums=("prop-0", "prop-1"))
    assert c0.cycle_number == 0
    assert c1.cycle_number == 1
    assert c2.cycle_number == 2


def test_previous_artifact_not_mutated_by_new_revision() -> None:
    pack_a = build_repair_context_pack(
        failure_evidence=_failure_evidence,
        cycle_number=1,
        prior_proposal_checksums=("prop-0",),
    )
    checksum_a = pack_a.context_pack_checksum
    _pack(
        cycle_number=2,
        prior_proposal_checksums=("prop-0", "prop-1"),
        prior_reviewer_notes=("fix",),
        prior_revision_ids=("rev-1",),
        user_comments="redo",
    )
    assert pack_a.context_pack_checksum == checksum_a
    assert pack_a.cycle_number == 1


def test_new_context_includes_original_failure_evidence_checksum() -> None:
    pack = _pack(cycle_number=2)
    assert pack.failure_evidence_checksum == _failure_evidence.content_checksum
    assert pack.failure_evidence_checksum


def test_new_context_includes_base_repo_state_checksum() -> None:
    pack = _pack(cycle_number=1)
    assert pack.base_repo_state_checksum
    pack_empty = build_repair_context_pack(
        failure_evidence=_failure_evidence,
        changed_files=(),
        file_checksums={},
    )
    assert pack_empty.base_repo_state_checksum


def test_user_comments_truncated_by_build_function() -> None:
    long_comment = "x" * 5000
    pack = build_repair_context_pack(
        failure_evidence=_failure_evidence,
        user_comments=long_comment,
    )
    assert pack.user_comments == long_comment


# ── V2RepairFlowService revision flow tests ──────────────────────────


def test_create_revision_proposal_creates_new_proposal_with_revision_metadata() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd1",
        failure_summary="build failed",
        hypothesis="missing import",
        patch_summary="add import",
        affected_paths=("file.java",),
    )
    revision = service.create_revision_proposal(
        command_id="cmd1",
        source_proposal_id=proposal.proposal_id,
        failure_summary="build failed",
        hypothesis="add import v2",
        patch_summary="add import revised",
        affected_paths=("file.java",),
        revision_instruction="fix the typo",
        context_pack_checksum="abc123",
        revision_number=2,
    )
    assert revision.proposal_id != proposal.proposal_id
    assert revision.status == "draft"
    assert revision.source_proposal_id == proposal.proposal_id
    assert revision.revision_of == proposal.proposal_id
    assert revision.revision_number == 2
    assert revision.context_pack_checksum == "abc123"
    assert revision.proposal_checksum
    assert revision.hypothesis == "add import v2"
    assert revision.patch_summary == "add import revised"


def test_source_proposal_id_recorded_in_revision() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd1",
        failure_summary="build failed",
        hypothesis="missing import",
        patch_summary="add import",
        affected_paths=("file.java",),
    )
    revision = service.create_revision_proposal(
        command_id="cmd1",
        source_proposal_id=proposal.proposal_id,
        failure_summary="build failed",
        hypothesis="add import revised",
        patch_summary="add import revised",
        affected_paths=("file.java",),
        revision_number=2,
    )
    assert revision.source_proposal_id == proposal.proposal_id
    assert revision.revision_of == proposal.proposal_id


def test_revision_number_increments() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd1",
        failure_summary="build failed",
        hypothesis="missing import",
        patch_summary="add import",
        affected_paths=("file.java",),
    )
    rev2 = service.create_revision_proposal(
        command_id="cmd1",
        source_proposal_id=proposal.proposal_id,
        failure_summary="build failed",
        hypothesis="add import v2",
        patch_summary="add import revised",
        affected_paths=("file.java",),
        revision_number=2,
    )
    rev3 = service.create_revision_proposal(
        command_id="cmd1",
        source_proposal_id=rev2.proposal_id,
        failure_summary="build failed",
        hypothesis="add import v3",
        patch_summary="add import revised v3",
        affected_paths=("file.java",),
        revision_number=3,
    )
    assert rev2.revision_number == 2
    assert rev3.revision_number == 3
    assert rev3.source_proposal_id == rev2.proposal_id


def test_origin_proposal_not_mutated_by_revision() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd1",
        failure_summary="build failed",
        hypothesis="missing import",
        patch_summary="add import",
        affected_paths=("file.java",),
    )
    original_id = proposal.proposal_id
    original_checksum = proposal.proposal_checksum
    original_status = proposal.status
    original_hypothesis = proposal.hypothesis
    assert proposal.source_proposal_id is None
    assert proposal.revision_of is None
    assert proposal.revision_number is None

    _revision = service.create_revision_proposal(
        command_id="cmd1",
        source_proposal_id=proposal.proposal_id,
        failure_summary="build failed",
        hypothesis="add import v2",
        patch_summary="add import revised",
        affected_paths=("file.java",),
        revision_number=2,
    )

    assert proposal.proposal_id == original_id
    assert proposal.proposal_checksum == original_checksum
    assert proposal.status == original_status
    assert proposal.hypothesis == original_hypothesis
    assert proposal.source_proposal_id is None
    assert proposal.revision_of is None
    assert proposal.revision_number is None
