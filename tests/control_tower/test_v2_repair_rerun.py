"""Tests for F5-T11 (Rerun Proof) and F5-T12 (Repeated Failure) — failure evidence repair context."""

from __future__ import annotations

from pathlib import Path

import pytest

from migration_factory.repair_loop.failure_evidence import (
    FailureSource,
    FailureEvidence,
    NormalizedCompilerError,
    NormalizedTestFailure,
    build_failure_evidence,
    compute_failure_content_checksum,
    compute_failure_artifact_checksum,
)
from migration_factory.repair_loop.repair_context import (
    RepairContextPack,
    build_repair_context_pack,
    compute_base_repo_state_checksum,
    compute_context_pack_checksum,
    is_context_pack_stale,
)


# ── F5-T11-1: FailureSource enum values are correct ────────────────────

def test_failure_source_enum_values() -> None:
    assert FailureSource.BUILD.value == "build"
    assert FailureSource.TEST.value == "test"
    assert FailureSource.VALIDATION.value == "validation"
    assert FailureSource.TRANSFORM.value == "transform"
    assert FailureSource.UNKNOWN.value == "unknown"


# ── F5-T11-2: build_failure_evidence with BUILD source ─────────────────

def test_build_failure_evidence_with_build_source() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        stage_index=1,
        job_id="job-1",
        command_id="cmd-1",
        failure_summary="Compilation error",
        compiler_errors=(
            NormalizedCompilerError(
                message="Cannot find symbol",
                file_path="src/App.java",
                line=42,
                column=10,
                severity="error",
            ),
        ),
    )

    assert evidence.failure_source == FailureSource.BUILD
    assert evidence.stage_index == 1
    assert evidence.job_id == "job-1"
    assert evidence.command_id == "cmd-1"
    assert evidence.failure_summary == "Compilation error"
    assert len(evidence.compiler_errors) == 1
    assert evidence.compiler_errors[0].message == "Cannot find symbol"
    assert evidence.content_checksum != ""
    assert evidence.artifact_checksum != ""


# ── F5-T11-3: build_failure_evidence with TEST source ──────────────────

def test_build_failure_evidence_with_test_source() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.TEST,
        stage_index=2,
        job_id="job-2",
        command_id="cmd-2",
        failure_summary="3 tests failed",
        test_failures=(
            NormalizedTestFailure(
                test_name="testFoo",
                test_class="FooTest",
                message="expected true but was false",
                file_path="src/test/FooTest.java",
            ),
        ),
    )

    assert evidence.failure_source == FailureSource.TEST
    assert evidence.stage_index == 2
    assert len(evidence.test_failures) == 1
    assert evidence.test_failures[0].test_name == "testFoo"
    assert evidence.content_checksum != ""


# ── F5-T11-4: Failure evidence content_checksum changes when source changes ──

def test_failure_evidence_content_checksum_changes_on_source_change() -> None:
    e1 = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-1",
        failure_summary="error",
    )
    e2 = build_failure_evidence(
        failure_source=FailureSource.TEST,
        command_id="cmd-1",
        failure_summary="error",
    )

    assert e1.content_checksum != e2.content_checksum


# ── F5-T12-5: Repair context pack includes cycle_number ─────────────────

def test_repair_context_pack_includes_cycle_number() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-1",
        failure_summary="build error",
    )
    pack = build_repair_context_pack(
        failure_evidence=evidence,
        cycle_number=2,
        max_cycles=5,
    )

    assert pack.cycle_number == 2
    assert pack.max_cycles == 5
    assert pack.failure_evidence_checksum == evidence.content_checksum


# ── F5-T12-6: Context pack checksum changes with cycle_number ──────────

def test_context_pack_checksum_changes_with_cycle_number() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-1",
        failure_summary="error",
    )
    pack1 = build_repair_context_pack(
        failure_evidence=evidence,
        cycle_number=0,
    )
    pack2 = build_repair_context_pack(
        failure_evidence=evidence,
        cycle_number=1,
    )

    assert pack1.context_pack_checksum != pack2.context_pack_checksum


# ── F5-T12-7: Attempt tracking: verify max_cycles is propagated ────────

def test_attempt_tracking_max_cycles_propagated() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-1",
        failure_summary="error",
    )
    pack = build_repair_context_pack(
        failure_evidence=evidence,
        max_cycles=3,
        cycle_number=0,
    )

    assert pack.max_cycles == 3
    assert pack.cycle_number == 0


# ── F5-T12-8: Stale context detection when file checksums change ───────

def test_stale_context_detection_when_file_checksums_change() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-1",
        failure_summary="error",
    )
    pack = build_repair_context_pack(
        failure_evidence=evidence,
        file_checksums={"pom.xml": "abc123"},
    )

    stale = is_context_pack_stale(
        pack,
        current_file_checksums={"pom.xml": "def456"},
    )
    assert stale is True

    not_stale = is_context_pack_stale(
        pack,
        current_file_checksums={"pom.xml": "abc123"},
    )
    assert not_stale is False


# ── F5-T12-9: Context pack stability with same inputs ──────────────────

def test_context_pack_stability_with_same_inputs() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-1",
        failure_summary="error",
    )
    pack1 = build_repair_context_pack(
        failure_evidence=evidence,
        job_id="job-1",
        stage_index=2,
        cycle_number=1,
        max_cycles=3,
    )
    pack2 = build_repair_context_pack(
        failure_evidence=evidence,
        job_id="job-1",
        stage_index=2,
        cycle_number=1,
        max_cycles=3,
    )

    assert pack1.context_pack_checksum == pack2.context_pack_checksum


# ── F5-T12-10: Repeated context: verify prior_proposal_checksums grows ─

def test_repeated_context_prior_proposal_checksums_grows() -> None:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-1",
        failure_summary="error",
    )
    pack1 = build_repair_context_pack(
        failure_evidence=evidence,
        prior_proposal_checksums=("prop-a-checksum",),
        cycle_number=1,
    )
    pack2 = build_repair_context_pack(
        failure_evidence=evidence,
        prior_proposal_checksums=("prop-a-checksum", "prop-b-checksum"),
        cycle_number=2,
    )

    assert len(pack1.prior_proposal_checksums) == 1
    assert len(pack2.prior_proposal_checksums) == 2
    assert pack1.context_pack_checksum != pack2.context_pack_checksum
    assert pack2.cycle_number == 2
