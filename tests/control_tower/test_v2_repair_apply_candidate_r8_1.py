from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

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


def _sort_sandbox(tmp_path: Path) -> tuple[Path, Path, Path, dict, dict]:
    sandbox = tmp_path / "sandbox"
    dto = sandbox / "src" / "main" / "java" / "com" / "total" / "corp" / "common" / "dto" / "DTOHelpers.java"
    search = sandbox / "src" / "main" / "java" / "com" / "total" / "corp" / "common" / "service" / "base" / "SearchService.java"
    dto.parent.mkdir(parents=True)
    search.parent.mkdir(parents=True)
    dto.write_text(
        "class DTOHelpers {\n"
        "  void p(){ final Sort sort = new Sort(sortDirection, sortCollumn); }\n"
        "}\n",
        encoding="utf-8",
    )
    search.write_text(
        "class SearchService {\n"
        "  void p(){ final Sort sort = new Sort(Direction.fromString(query.getSortDirection()), query.getSortColumn()); }\n"
        "}\n",
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
            {"kind": "source_ref", "internal_ref": str(dto), "excerpt": dto.read_text(encoding="utf-8")},
            {"kind": "build_error_contract", "compile_errors": [{"path": "src/main/java/com/total/corp/common/dto/DTOHelpers.java"}]},
            {"kind": "pom_xml", "internal_ref": str(sandbox / "pom.xml")},
        ],
    }
    return sandbox, dto, search, classification, stage_evidence


def _jackson_pom(version: str = "2.10.0", *, dependency_management: bool = False) -> str:
    dependency_management_block = (
        "  <dependencyManagement>\n"
        "    <dependencies>\n"
        "      <dependency>\n"
        "        <groupId>org.springframework.boot</groupId>\n"
        "        <artifactId>spring-boot-dependencies</artifactId>\n"
        "        <version>${spring-boot.version}</version>\n"
        "        <type>pom</type>\n"
        "        <scope>import</scope>\n"
        "      </dependency>\n"
        "    </dependencies>\n"
        "  </dependencyManagement>\n"
        if dependency_management
        else ""
    )
    return (
        "<project>\n"
        "  <properties>\n"
        "    <java.version>11</java.version>\n"
        "    <spring-boot.version>2.7.18</spring-boot.version>\n"
        f"    <fasterxml-jackson.version>{version}</fasterxml-jackson.version>\n"
        "  </properties>\n"
        f"{dependency_management_block}"
        "  <dependencies>\n"
        "    <dependency>\n"
        "      <groupId>com.fasterxml.jackson.dataformat</groupId>\n"
        "      <artifactId>jackson-dataformat-csv</artifactId>\n"
        "      <version>${fasterxml-jackson.version}</version>\n"
        "    </dependency>\n"
        "  </dependencies>\n"
        "</project>\n"
    )


def _dependency_management_block(text: str) -> str:
    start = text.index("<dependencyManagement>")
    end = text.index("</dependencyManagement>") + len("</dependencyManagement>")
    return text[start:end]


def _project_dependencies_block(text: str) -> str:
    start = text.index("</dependencyManagement>") + len("</dependencyManagement>")
    deps_start = text.index("<dependencies>", start)
    deps_end = text.index("</dependencies>", deps_start) + len("</dependencies>")
    return text[deps_start:deps_end]


def _assert_jackson_dependency_structure(text: str) -> None:
    dependency_management = _dependency_management_block(text)
    project_dependencies = _project_dependencies_block(text)
    assert "<artifactId>jackson-bom</artifactId>" in dependency_management
    assert "<artifactId>jackson-databind</artifactId>" not in dependency_management
    assert "<artifactId>jackson-core</artifactId>" not in dependency_management
    assert "<artifactId>jackson-annotations</artifactId>" not in dependency_management
    assert "<artifactId>jackson-databind</artifactId>" in project_dependencies
    assert "<artifactId>jackson-core</artifactId>" in project_dependencies
    assert "<artifactId>jackson-annotations</artifactId>" in project_dependencies
    assert text.index("<artifactId>jackson-bom</artifactId>") < text.index("<artifactId>jackson-databind</artifactId>")


def _jackson_evidence(pom: Path, sandbox: Path, *, include_mismatch: bool = True) -> tuple[dict, dict]:
    conflict = (
        "java.lang.NoClassDefFoundError: com/fasterxml/jackson/databind/ser/std/ToStringSerializerBase\n"
        "MessageUtils.createObjectMapper(MessageUtils.java:50)\n"
        "MessageUtilsTest failures\n"
        "com.fasterxml.jackson.core:jackson-databind:jar:2.13.5 omitted for conflict with 2.9.6\n"
        "com.fasterxml.jackson.core:jackson-core:jar:2.13.5 omitted for conflict with 2.10.0\n"
        "selected jackson-databind is 2.9.6\n"
    )
    classification = {
        "failure_type": "JACKSON_VERSION_ALIGNMENT_DRIFT",
        "matched_signals": ["runtime:jackson_tostringserializerbase_missing"],
    }
    stage_evidence = {
        "job_id": "job-jackson",
        "stage_index": 1,
        "evidence_pack_checksum": "sha256:evidence",
        "usable_artifacts": [
            {"kind": "sandbox", "internal_ref": str(sandbox)},
            {"kind": "pom_xml", "internal_ref": str(pom), "excerpt": pom.read_text(encoding="utf-8")},
            {"kind": "test_report", "excerpt": conflict if include_mismatch else "MessageUtilsTest passed"},
            {"kind": "dependency_graph", "excerpt": conflict if include_mismatch else "jackson-databind 2.13.5"},
        ],
    }
    return classification, stage_evidence


class _FakePostRepairRunner:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, command: list[str], cwd: Path) -> dict[str, Any]:
        self.calls.append((list(command), str(cwd)))
        key = " ".join(command)
        response = dict(self.responses.get(key, {"exit_code": 1, "stdout": "", "stderr": f"missing response: {key}"}))
        response.setdefault("command", list(command))
        response.setdefault("working_directory", str(cwd))
        response.setdefault("started_at", "2026-07-05T00:00:00Z")
        response.setdefault("completed_at", "2026-07-05T00:00:01Z")
        response.setdefault("duration_ms", 1)
        return response


def test_sort_by_apply_candidate_is_governed_and_not_auto_applied(tmp_path: Path) -> None:
    _, dto, search, classification, stage_evidence = _sort_sandbox(tmp_path)

    candidate = create_repair_apply_candidate(classification, stage_evidence, {})

    assert candidate is not None
    public = public_repair_apply_candidate(candidate)
    assert public is not None
    assert public["family"] == "SPRING_DATA_SORT_API_DRIFT"
    assert public["recipe_id"] == "SPRING_DATA_SORT_BY"
    assert public["target_files"] == [
        "src/main/java/com/total/corp/common/dto/DTOHelpers.java",
        "src/main/java/com/total/corp/common/service/base/SearchService.java",
    ]
    assert len(public["change_preview"]) == 2
    assert {item["target_file"] for item in public["change_preview"]} == set(public["target_files"])
    assert all(item["replacement_count"] == 1 for item in public["change_preview"])
    assert all(item["before_marker"] == "new Sort(" for item in public["change_preview"])
    assert all(item["after_marker"] == "Sort.by(" for item in public["change_preview"])
    assert public["status"] == "pending_human_approval"
    assert public["sandbox_only"] is True
    assert public["approval_required"] is True
    assert public["human_gate_required"] is True
    assert public["apply_enabled"] is False
    assert public["approval_enabled"] is True
    assert public["downstream_start_allowed"] is False
    assert public["legacy_mutation_allowed"] is False
    assert public["browser_can_supply_patch"] is False
    assert public["llm_can_apply"] is False
    assert public["patch_checksum"].startswith("sha256:")
    assert public["target_file_checksum"].startswith("sha256:")
    assert public["review_checksum"].startswith("sha256:")
    assert public["candidate_checksum"].startswith("sha256:")
    assert public["rollback_metadata"]["rollback_required"] is True
    assert public["impact_summary"]
    assert public["risk_notes"]
    assert "new Sort(" in dto.read_text(encoding="utf-8")
    assert "new Sort(" in search.read_text(encoding="utf-8")
    assert public["target_files"] == [change["target_file"] for change in candidate["_file_changes"]]


def test_sort_by_multi_file_candidate_applies_both_files_after_checksum_approval(tmp_path: Path) -> None:
    sandbox, dto, search, classification, stage_evidence = _sort_sandbox(tmp_path)
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })

    result = apply_approved_repair_candidate(candidate, approval)

    dto_text = dto.read_text(encoding="utf-8")
    search_text = search.read_text(encoding="utf-8")
    assert "Sort.by(sortDirection, sortCollumn)" in dto_text
    assert "Sort.by(Direction.fromString(query.getSortDirection()), query.getSortColumn())" in search_text
    assert "new Sort(" not in dto_text
    assert "new Sort(" not in search_text
    assert result["execution_status"] == "verified"
    assert result["verification_status"] == "passed"
    assert result["rollback_status"] == "not_needed"
    assert result["downstream_start_allowed"] is False
    assert (sandbox / ".migration" / "repair-proofs" / f"{candidate['repair_candidate_id']}.json").is_file()


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


def test_jackson_alignment_candidate_is_pom_only_governed_and_previewed(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    pom = sandbox / "pom.xml"
    sandbox.mkdir(parents=True)
    pom.write_text(_jackson_pom(), encoding="utf-8")
    classification, stage_evidence = _jackson_evidence(pom, sandbox)

    candidate = create_repair_apply_candidate(classification, stage_evidence, {})

    assert candidate is not None
    public = public_repair_apply_candidate(candidate)
    assert public is not None
    assert public["family"] == "JACKSON_VERSION_ALIGNMENT_DRIFT"
    assert public["recipe_id"] == "JACKSON_PROPERTY_BOM_ALIGNMENT"
    assert public["target_file"] == "pom.xml"
    assert public["target_files"] == ["pom.xml"]
    assert public["status"] == "pending_human_approval"
    assert public["approval_required"] is True
    assert public["human_gate_required"] is True
    assert public["apply_enabled"] is False
    assert public["approval_enabled"] is True
    assert public["sandbox_only"] is True
    assert public["legacy_mutation_allowed"] is False
    assert public["downstream_start_allowed"] is False
    assert public["browser_can_supply_patch"] is False
    assert public["llm_can_apply"] is False
    assert public["patch_checksum"].startswith("sha256:")
    assert public["target_file_checksum"].startswith("sha256:")
    assert public["review_checksum"].startswith("sha256:")
    assert public["candidate_checksum"].startswith("sha256:")
    assert public["rollback_metadata"]["rollback_required"] is True
    assert public["operation_count"] >= 2
    assert any("2.10.0" in item["before"] and "2.13.5" in item["after"] for item in public["change_preview"])
    assert any(item["operation"] == "insert_dependency_management" for item in public["change_preview"])
    assert any(item["operation"] == "insert_direct_dependencies" for item in public["change_preview"])


def test_jackson_alignment_candidate_applies_after_checksum_approval(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    pom = sandbox / "pom.xml"
    sandbox.mkdir(parents=True)
    pom.write_text(_jackson_pom(), encoding="utf-8")
    classification, stage_evidence = _jackson_evidence(pom, sandbox)
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    runner = _FakePostRepairRunner(
        {
            "mvn -DskipTests clean compile": {"exit_code": 0, "stdout": "[INFO] BUILD SUCCESS", "stderr": ""},
            "mvn test": {"exit_code": 0, "stdout": "Tests run: 124, Failures: 0, Errors: 0, Skipped: 4", "stderr": ""},
        }
    )

    result = apply_approved_repair_candidate(candidate, approval, post_repair_verification_runner=runner)

    text = pom.read_text(encoding="utf-8")
    assert "<fasterxml-jackson.version>2.13.5</fasterxml-jackson.version>" in text
    assert "<artifactId>jackson-bom</artifactId>" in text
    assert "<artifactId>jackson-databind</artifactId>" in text
    assert "<artifactId>jackson-core</artifactId>" in text
    assert "<artifactId>jackson-annotations</artifactId>" in text
    _assert_jackson_dependency_structure(text)
    assert "2.20.0" not in text
    assert result["execution_status"] == "verified"
    assert result["verification_status"] == "passed"
    assert result["rollback_status"] == "not_needed"
    assert result["downstream_start_allowed"] is False
    assert (sandbox / ".migration" / "repair-proofs" / f"{candidate['repair_candidate_id']}.json").is_file()


def test_post_repair_verification_failure_after_sort_creates_jackson_candidate(tmp_path: Path) -> None:
    _, dto, search, classification, stage_evidence = _sort_sandbox(tmp_path)
    sandbox = tmp_path / "sandbox"
    (sandbox / "pom.xml").write_text(_jackson_pom(), encoding="utf-8")
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    runner = _FakePostRepairRunner(
        {
            "mvn -DskipTests clean compile": {"exit_code": 0, "stdout": "[INFO] BUILD SUCCESS", "stderr": ""},
            "mvn test": {
                "exit_code": 1,
                "stdout": "",
                "stderr": "\n".join([
                    "java.lang.NoClassDefFoundError: com/fasterxml/jackson/databind/ser/std/ToStringSerializerBase",
                    "at com.total.corp.common.util.MessageUtils.createObjectMapper(MessageUtils.java:50)",
                    "MessageUtilsTest failed",
                    "com.fasterxml.jackson.core:jackson-databind:jar:2.13.5 omitted for conflict with 2.9.6",
                    "com.fasterxml.jackson.core:jackson-core:jar:2.13.5 omitted for conflict with 2.10.0",
                    "selected jackson-databind is 2.9.6",
                    "selected jackson-core is 2.10.0",
                ]),
            },
            "mvn dependency:tree -DoutputType=text": {
                "exit_code": 0,
                "stdout": "\n".join([
                    "[INFO] com.fasterxml.jackson.core:jackson-databind:jar:2.13.5 omitted for conflict with 2.9.6",
                    "[INFO] com.fasterxml.jackson.core:jackson-core:jar:2.13.5 omitted for conflict with 2.10.0",
                    "[INFO] selected jackson-databind is 2.9.6",
                    "[INFO] selected jackson-core is 2.10.0",
                ]),
                "stderr": "",
            },
        }
    )

    result = apply_approved_repair_candidate(candidate, approval, post_repair_verification_runner=runner)

    assert result["verification_status"] == "passed"
    assert result["post_repair_verification_status"] == "failed"
    assert result["stage_recovery_status"] == "still_failed"
    assert result["downstream_start_allowed"] is False
    assert result["classification"]["failure_type"] == "JACKSON_VERSION_ALIGNMENT_DRIFT"
    next_candidate = result["next_repair_candidate"]
    assert next_candidate is not None
    assert next_candidate["family"] == "JACKSON_VERSION_ALIGNMENT_DRIFT"
    assert next_candidate["recipe_id"] == "JACKSON_PROPERTY_BOM_ALIGNMENT"
    assert next_candidate["approval_required"] is True
    assert next_candidate["apply_enabled"] is False
    assert next_candidate["sandbox_only"] is True
    assert next_candidate["downstream_start_allowed"] is False
    artifacts = {item["kind"]: item for item in result["post_repair_verification"]["evidence_pack"]["usable_artifacts"]}
    assert "ToStringSerializerBase" in artifacts["test_report"]["excerpt"]
    assert "jackson-databind" in artifacts["dependency_graph"]["excerpt"]


def test_post_repair_verification_success_marks_stage_recovered(tmp_path: Path) -> None:
    _, dto, search, classification, stage_evidence = _sort_sandbox(tmp_path)
    sandbox = tmp_path / "sandbox"
    (sandbox / "pom.xml").write_text(_jackson_pom(), encoding="utf-8")
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    runner = _FakePostRepairRunner(
        {
            "mvn -DskipTests clean compile": {"exit_code": 0, "stdout": "[INFO] BUILD SUCCESS", "stderr": ""},
            "mvn test": {"exit_code": 0, "stdout": "Tests run: 124, Failures: 0, Errors: 0, Skipped: 4", "stderr": ""},
        }
    )

    result = apply_approved_repair_candidate(candidate, approval, post_repair_verification_runner=runner)

    assert result["verification_status"] == "passed"
    assert result["post_repair_verification_status"] == "passed"
    assert result["stage_recovery_status"] == "recovered"
    assert result["downstream_start_allowed"] is False
    assert result["post_repair_proof_artifact"]
    assert result["post_repair_verification"]["post_repair_verification_status"] == "passed"
    assert result["post_repair_verification"]["stage_recovery_status"] == "recovered"
    assert result["next_repair_candidate"] is None


def test_post_repair_verification_ignores_browser_command_and_sandbox_override(tmp_path: Path) -> None:
    _, dto, search, classification, stage_evidence = _sort_sandbox(tmp_path)
    sandbox = tmp_path / "sandbox"
    (sandbox / "pom.xml").write_text(_jackson_pom(), encoding="utf-8")
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    candidate["command"] = "echo hacked"
    candidate["sandbox_path"] = r"C:\wrong"
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    runner = _FakePostRepairRunner(
        {
            "mvn -DskipTests clean compile": {"exit_code": 0, "stdout": "[INFO] BUILD SUCCESS", "stderr": ""},
            "mvn test": {"exit_code": 0, "stdout": "Tests run: 124, Failures: 0, Errors: 0, Skipped: 4", "stderr": ""},
        }
    )

    result = apply_approved_repair_candidate(candidate, approval, post_repair_verification_runner=runner)

    assert runner.calls[0][0] == ["mvn", "-DskipTests", "clean", "compile"]
    assert runner.calls[1][0] == ["mvn", "test"]
    assert runner.calls[0][1] == str(sandbox.resolve())
    assert result["downstream_start_allowed"] is False


def test_jackson_alignment_checksum_changes_with_after_text(tmp_path: Path) -> None:
    sandbox_a = tmp_path / "sandbox-a"
    sandbox_b = tmp_path / "sandbox-b"
    pom_a = sandbox_a / "pom.xml"
    pom_b = sandbox_b / "pom.xml"
    sandbox_a.mkdir(parents=True)
    sandbox_b.mkdir(parents=True)
    pom_a.write_text(_jackson_pom(), encoding="utf-8")
    pom_b.write_text(_jackson_pom(dependency_management=True), encoding="utf-8")
    class_a, evidence_a = _jackson_evidence(pom_a, sandbox_a)
    class_b, evidence_b = _jackson_evidence(pom_b, sandbox_b)
    candidate_a = create_repair_apply_candidate(class_a, evidence_a, {})
    candidate_b = create_repair_apply_candidate(class_b, evidence_b, {})
    assert candidate_a is not None
    assert candidate_b is not None
    assert candidate_a["patch_checksum"] != candidate_b["patch_checksum"]
    assert candidate_a["candidate_checksum"] != candidate_b["candidate_checksum"]


def test_jackson_alignment_approval_rejects_stale_checksum(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    pom = sandbox / "pom.xml"
    sandbox.mkdir(parents=True)
    pom.write_text(_jackson_pom(), encoding="utf-8")
    classification, stage_evidence = _jackson_evidence(pom, sandbox)
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    with pytest.raises(ValueError, match="patch_checksum_mismatch"):
        approve_repair_apply_candidate(candidate, {
            "repair_candidate_id": candidate["repair_candidate_id"],
            "patch_checksum": "sha256:stale",
            "target_file_checksum": candidate["target_file_checksum"],
            "review_checksum": candidate["review_checksum"],
        })


def test_jackson_alignment_preserves_existing_dependency_management_structure(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    pom = sandbox / "pom.xml"
    sandbox.mkdir(parents=True)
    pom.write_text(_jackson_pom(dependency_management=True), encoding="utf-8")
    classification, stage_evidence = _jackson_evidence(pom, sandbox)
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    approval = approve_repair_apply_candidate(candidate, {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
    })
    runner = _FakePostRepairRunner(
        {
            "mvn -DskipTests clean compile": {"exit_code": 0, "stdout": "[INFO] BUILD SUCCESS", "stderr": ""},
            "mvn test": {"exit_code": 0, "stdout": "Tests run: 124, Failures: 0, Errors: 0, Skipped: 4", "stderr": ""},
        }
    )

    result = apply_approved_repair_candidate(candidate, approval, post_repair_verification_runner=runner)

    text = pom.read_text(encoding="utf-8")
    assert result["execution_status"] == "verified"
    assert "<artifactId>spring-boot-dependencies</artifactId>" in _dependency_management_block(text)
    _assert_jackson_dependency_structure(text)
    assert text.count("<dependencyManagement>") == 1


def test_jackson_alignment_candidate_negative_gates(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    pom = sandbox / "pom.xml"
    outside = tmp_path / "outside" / "pom.xml"
    sandbox.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    pom.write_text(_jackson_pom(), encoding="utf-8")
    outside.write_text(_jackson_pom(), encoding="utf-8")
    classification, stage_evidence = _jackson_evidence(pom, sandbox)

    no_pom = dict(stage_evidence)
    no_pom["usable_artifacts"] = [item for item in stage_evidence["usable_artifacts"] if item["kind"] != "pom_xml"]
    no_mismatch_classification, no_mismatch = _jackson_evidence(pom, sandbox, include_mismatch=False)
    outside_evidence = dict(stage_evidence)
    outside_evidence["usable_artifacts"] = [
        {"kind": "sandbox", "internal_ref": str(sandbox)},
        {"kind": "pom_xml", "internal_ref": str(outside), "excerpt": outside.read_text(encoding="utf-8")},
        {"kind": "test_report", "excerpt": stage_evidence["usable_artifacts"][2]["excerpt"]},
        {"kind": "dependency_graph", "excerpt": stage_evidence["usable_artifacts"][3]["excerpt"]},
    ]
    aligned = sandbox / "aligned-pom.xml"
    aligned.write_text(_jackson_pom("2.13.5"), encoding="utf-8")
    aligned_evidence = dict(stage_evidence)
    aligned_evidence["usable_artifacts"] = [
        {"kind": "sandbox", "internal_ref": str(sandbox)},
        {"kind": "pom_xml", "internal_ref": str(aligned), "excerpt": aligned.read_text(encoding="utf-8")},
        {"kind": "test_report", "excerpt": stage_evidence["usable_artifacts"][2]["excerpt"]},
        {"kind": "dependency_graph", "excerpt": stage_evidence["usable_artifacts"][3]["excerpt"]},
    ]

    assert create_repair_apply_candidate(classification, no_pom, {}) is None
    assert create_repair_apply_candidate(no_mismatch_classification, no_mismatch, {}) is None
    assert create_repair_apply_candidate(classification, outside_evidence, {}) is None
    assert create_repair_apply_candidate(classification, aligned_evidence, {}) is None
