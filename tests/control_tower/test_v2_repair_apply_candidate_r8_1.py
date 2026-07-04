from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    apply_approved_repair_candidate,
    approve_repair_apply_candidate,
    create_repair_apply_candidate,
    public_repair_apply_candidate,
    repair_state_narration,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork


def _headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "r8_1.sqlite3"), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return conn


def _seed_v2_job(conn: sqlite3.Connection, job_id: str = "job-r8") -> None:
    conn.execute(
        """INSERT INTO v2_migration_jobs (
            job_id, setup_id, setup_checksum, pipeline_id, stage_chain_json,
            status, created_at, updated_at, correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            "setup-r8",
            "sha256:setup",
            "pipeline-r8",
            json.dumps([{"stage_index": 1, "pipeline_stage": "stage-1", "chain_status": "failed"}]),
            "failed",
            "2026-07-03T00:00:00Z",
            "2026-07-03T00:00:00Z",
            None,
        ),
    )


def _sandbox(tmp_path: Path) -> tuple[Path, Path, Path]:
    legacy = tmp_path / "legacy" / "src" / "test" / "java"
    sandbox = tmp_path / "sandbox"
    target = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    legacy.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    text = "class ExampleTest { void setUp(){ MockitoAnnotations.initMocks(this); } }"
    (legacy / "ExampleTest.java").write_text(text, encoding="utf-8")
    target.write_text(text, encoding="utf-8")
    return legacy.parent.parent.parent, sandbox, target


def _candidate(tmp_path: Path, job_id: str = "job-r8") -> dict:
    _, sandbox, target = _sandbox(tmp_path)
    candidate = create_repair_apply_candidate(
        job_id=job_id,
        stage_index=1,
        target_file="src/test/java/ExampleTest.java",
        sandbox_root=str(sandbox),
        target_path=str(target),
        review_checksum="sha256:review",
        proposal_checksum="sha256:proposal",
    )
    assert candidate is not None
    return candidate


def test_candidate_persisted_with_private_fields_not_exposed_publicly(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_v2_job(conn)
    candidate = _candidate(tmp_path)
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repair_candidates.save_candidate(candidate)
        uow.v2_repair_candidates.save_candidate(candidate)

    with SqliteUnitOfWork(conn) as uow:
        internal = uow.v2_repair_candidates.get_internal("job-r8", 1, candidate["repair_candidate_id"])
        public = uow.v2_repair_candidates.get_public("job-r8", 1, candidate["repair_candidate_id"])

    assert internal is not None
    assert internal["_sandbox_root"]
    assert internal["_target_path"]
    assert internal["_after_text"]
    assert internal["_patch_payload"]
    assert public is not None
    assert all(not key.startswith("_") for key in public)
    count = conn.execute("SELECT COUNT(*) AS n FROM v2_repair_apply_candidates WHERE job_id = ?", ("job-r8",)).fetchone()["n"]
    assert count == 1


def test_public_only_candidate_is_not_persisted(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_v2_job(conn)
    candidate = _candidate(tmp_path)
    public = public_repair_apply_candidate(candidate)
    assert public is not None
    try:
        with SqliteUnitOfWork(conn) as uow:
            uow.v2_repair_candidates.save_candidate(public)
    except ValueError as exc:
        assert str(exc) == "internal_repair_candidate_required"
    else:
        raise AssertionError("public-only candidate should not be persisted")

    count = conn.execute("SELECT COUNT(*) AS n FROM v2_repair_apply_candidates WHERE job_id = ?", ("job-r8",)).fetchone()["n"]
    assert count == 0


def test_approve_endpoint_checksum_mismatch_rejected_and_valid_request_accepted(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_v2_job(conn)
    candidate = _candidate(tmp_path)
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repair_candidates.save_candidate(candidate)
    client = TestClient(create_app(lambda: SqliteUnitOfWork(conn)), base_url="http://127.0.0.1:8000")
    url = f"/v1/v2/jobs/job-r8/stages/1/repair-candidates/{candidate['repair_candidate_id']}/approve"

    bad = client.post(url, headers=_headers(), json={
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": "sha256:wrong",
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    assert bad.status_code == 409

    good = client.post(url, headers=_headers(), json={
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    assert good.status_code == 200, good.text
    assert good.json()["candidate"]["status"] == "approved"


def test_apply_endpoint_loads_internal_candidate_changes_sandbox_writes_proof_leaves_legacy(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_v2_job(conn)
    legacy_root, sandbox, target = _sandbox(tmp_path)
    candidate = create_repair_apply_candidate(
        job_id="job-r8",
        stage_index=1,
        target_file="src/test/java/ExampleTest.java",
        sandbox_root=str(sandbox),
        target_path=str(target),
        review_checksum="sha256:review",
    )
    assert candidate is not None
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repair_candidates.save_candidate(candidate)
        uow.v2_repair_candidates.save_approval("job-r8", 1, candidate["repair_candidate_id"], approval)

    client = TestClient(create_app(lambda: SqliteUnitOfWork(conn)), base_url="http://127.0.0.1:8000")
    response = client.post(
        f"/v1/v2/jobs/job-r8/stages/1/repair-candidates/{candidate['repair_candidate_id']}/apply",
        headers=_headers(),
        json={"repair_candidate_id": candidate["repair_candidate_id"], "patch": "browser ignored"},
    )
    assert response.status_code == 422
    response = client.post(
        f"/v1/v2/jobs/job-r8/stages/1/repair-candidates/{candidate['repair_candidate_id']}/apply",
        headers=_headers(),
        json={"repair_candidate_id": candidate["repair_candidate_id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution"]["execution_status"] == "verified"
    assert "openMocks" in target.read_text(encoding="utf-8")
    assert "initMocks" in (legacy_root / "src" / "test" / "java" / "ExampleTest.java").read_text(encoding="utf-8")
    assert body["execution"]["proof_artifact"]
    assert body["execution"]["downstream_start_allowed"] is False


def test_pre_apply_checksum_mismatch_rejects(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    Path(candidate["_target_path"]).write_text("changed", encoding="utf-8")
    try:
        apply_approved_repair_candidate(candidate, approval)
    except ValueError as exc:
        assert str(exc) == "pre_apply_checksum_mismatch"
    else:
        raise AssertionError("checksum mismatch should reject")


def test_rollback_works_when_verification_fails(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    before = Path(candidate["_target_path"]).read_text(encoding="utf-8")
    result = apply_approved_repair_candidate(candidate, approval, verification_runner=lambda _p: (False, "nope"))
    assert result["execution_status"] == "rolled_back"
    assert result["rollback_status"] == "succeeded"
    assert Path(candidate["_target_path"]).read_text(encoding="utf-8") == before
    assert result["proof_artifact"]


def test_chatbot_can_summarize_repair_state_but_cannot_execute(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    summary = repair_state_narration(public_repair_apply_candidate(candidate))
    assert "Required checksums" in summary
    assert "Status: pending_human_approval" in summary
    assert "Downstream remains blocked" in summary
    assert "execute" not in summary.lower()


def test_chatbot_summarizes_no_candidate_and_terminal_candidate_states(tmp_path: Path) -> None:
    no_candidate = repair_state_narration(None)
    assert "Repair candidate: none" in no_candidate
    assert "PowerMock or unsupported failures require human review" in no_candidate
    assert "Approval: unavailable" in no_candidate
    assert "Apply: unavailable" in no_candidate

    candidate = public_repair_apply_candidate(_candidate(tmp_path))
    assert candidate is not None
    candidate["status"] = "approved"
    approved = repair_state_narration(candidate)
    assert "Status: approved" in approved
    assert "Verification: not_started" in approved

    candidate["status"] = "verified"
    candidate["verification_status"] = "passed"
    candidate["rollback_status"] = "not_needed"
    candidate["proof_artifact"] = "artifact:repair-proof"
    verified = repair_state_narration(candidate)
    assert "Status: verified" in verified
    assert "Verification: passed" in verified
    assert "Rollback: not_needed" in verified
    assert "Proof: artifact:repair-proof" in verified


def test_powermock_remains_no_candidate_human_gate(tmp_path: Path) -> None:
    _, sandbox, target = _sandbox(tmp_path)
    target.write_text("PowerMockito.mockStatic(Foo.class);", encoding="utf-8")
    candidate = create_repair_apply_candidate(
        job_id="job-r8",
        stage_index=1,
        target_file="src/test/java/ExampleTest.java",
        sandbox_root=str(sandbox),
        target_path=str(target),
        review_checksum="sha256:review",
    )
    assert candidate is None


def test_sort_by_apply_candidate_is_governed_and_not_auto_applied(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    target = sandbox / "src" / "main" / "java" / "com" / "total" / "corp" / "common" / "dto" / "DTOHelpers.java"
    target.parent.mkdir(parents=True)
    target.write_text(
        "class DTOHelpers { void p(){ final Sort sort = new Sort(sortDirection, sortCollumn); } }",
        encoding="utf-8",
    )
    classification = {
        "failure_type": "SPRING_DATA_SORT_API_DRIFT",
        "sort_api_drift_targets": [{"path": "src/main/java/com/total/corp/common/dto/DTOHelpers.java"}],
    }
    stage_evidence = {
        "job_id": "job-sort",
        "stage_index": 1,
        "evidence_pack_checksum": "sha256:evidence",
        "usable_artifacts": [
            {"kind": "sandbox", "internal_ref": str(sandbox)},
            {"kind": "source_ref", "internal_ref": str(target), "excerpt": target.read_text(encoding="utf-8")},
            {"kind": "build_error_contract", "compile_errors": [{"path": "src/main/java/com/total/corp/common/dto/DTOHelpers.java"}]},
            {"kind": "pom_xml", "internal_ref": str(sandbox / "pom.xml")},
        ],
    }

    candidate = create_repair_apply_candidate(classification, stage_evidence, {})

    assert candidate is not None
    public = public_repair_apply_candidate(candidate)
    assert public is not None
    assert public["family"] == "SPRING_DATA_SORT_API_DRIFT"
    assert public["recipe_id"] == "SPRING_DATA_SORT_BY"
    assert public["status"] == "pending_human_approval"
    assert public["sandbox_only"] is True
    assert public["approval_required"] is True
    assert public["human_gate_required"] is True
    assert public["apply_enabled"] is False
    assert public["downstream_start_allowed"] is False
    assert public["legacy_mutation_allowed"] is False
    assert public["patch_checksum"].startswith("sha256:")
    assert public["candidate_checksum"].startswith("sha256:")
    assert public["rollback_metadata"]["rollback_required"] is True
    assert public["impact_summary"]
    assert public["risk_notes"]
    assert "new Sort(" in target.read_text(encoding="utf-8")
    assert "Sort.by(" in candidate["_after_text"]


def test_sort_by_candidate_rejects_outside_sandbox_or_ambiguous_pattern(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    outside = tmp_path / "outside" / "src" / "main" / "java" / "DTOHelpers.java"
    ambiguous = sandbox / "src" / "main" / "java" / "DTOHelpers.java"
    outside.parent.mkdir(parents=True)
    ambiguous.parent.mkdir(parents=True)
    outside.write_text("class DTOHelpers { void p(){ final Sort sort = new Sort(sortDirection, sortCollumn); } }", encoding="utf-8")
    ambiguous.write_text("class DTOHelpers { void p(){ final Sort sort = new Sort(factory.create(), other); } }", encoding="utf-8")
    classification = {
        "failure_type": "SPRING_DATA_SORT_API_DRIFT",
        "sort_api_drift_targets": [{"path": "src/main/java/DTOHelpers.java"}],
    }

    outside_candidate = create_repair_apply_candidate(classification, {
        "job_id": "job-sort",
        "stage_index": 1,
        "usable_artifacts": [
            {"kind": "sandbox", "internal_ref": str(sandbox)},
            {"kind": "source_ref", "internal_ref": str(outside), "excerpt": outside.read_text(encoding="utf-8")},
        ],
    }, {})
    ambiguous_candidate = create_repair_apply_candidate(classification, {
        "job_id": "job-sort",
        "stage_index": 1,
        "usable_artifacts": [
            {"kind": "sandbox", "internal_ref": str(sandbox)},
            {"kind": "source_ref", "internal_ref": str(ambiguous), "excerpt": ambiguous.read_text(encoding="utf-8")},
        ],
    }, {})

    assert outside_candidate is None
    assert ambiguous_candidate is None
