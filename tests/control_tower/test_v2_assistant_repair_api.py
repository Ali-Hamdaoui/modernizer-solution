"""Integration tests for V2 assistant and repair API endpoints."""

from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import migration_factory.control_tower.application.v2_repair_flow as v2_repair_flow

from migration_factory.control_tower.application.v2_repair_flow import V2RepairFlowService
from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2PreflightResultRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_assistant_repository import (
    SqliteV2AssistantRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    SqliteV2JobRepository,
    V2MigrationJobRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    V2MigrationSetupRecord,
)
from tests.control_tower.test_v2_gate_assistant_ask import (
    _RecordingGovernedRepairClient,
    _create_gate_with_refs,
    _ready_setup_with_output_root,
    _seed_migration_intelligence_artifacts,
)


def _mutation_headers():
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID
    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _api_client(tmp_path: Path, *, fake_model_client: object | None = None):
    from migration_factory.control_tower.adapters.fastapi import create_app
    conn = sqlite3.connect(
        tmp_path / "assistant_repair_test.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn))
    if fake_model_client is not None:
        app.state.v2_assistant_model_client = fake_model_client
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    return client, conn


def _seed_v2_command_for_model_audit(
    conn: sqlite3.Connection,
    tmp_path: Path,
    command_id: str,
    *,
    target_rel_path: str | None = None,
    include_sandbox_path: bool = True,
) -> None:
    setup_repo = SqliteV2SetupRepository(conn)
    job_repo = SqliteV2JobRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    output_root = tmp_path / f"out-{command_id}"
    sandbox = output_root / ".migration" / "runs" / "run-audit" / "workspaces" / "sandbox"
    legacy = tmp_path / f"legacy-{command_id}"
    sandbox.mkdir(parents=True, exist_ok=True)
    legacy.mkdir(parents=True, exist_ok=True)
    if target_rel_path:
        target = sandbox / target_rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "class App {\n"
            "  private static final int CONTROLLED_REPAIR_FAILURE = doesNotCompile;\n"
            "}\n",
            encoding="utf-8",
        )
    setup_repo.save(
        V2MigrationSetupRecord(
            setup_id=f"setup-{command_id}",
            run_name="audit",
            legacy_app_path=str(legacy),
            output_parent_path=str(output_root),
            ai_hub_path=str(tmp_path / "ai"),
            java11_home="C:/java11",
            java17_home="C:/java17",
            java21_home="C:/java21",
            maven_cmd="mvn",
            proof_level="build_test_verified",
            skip_endpoint_smoke=False,
            migration_flags_json="{}",
            setup_checksum="setup-chk",
            checksum_algorithm="sha256",
            created_at="2026-06-18T00:00:00Z",
            created_by="test",
            correlation_id=None,
        )
    )
    job_repo.save(
        V2MigrationJobRecord(
            job_id=f"job-{command_id}",
            setup_id=f"setup-{command_id}",
            setup_checksum="setup-chk",
            pipeline_id="pipeline-1",
            stage_chain_json="[]",
            status="created",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            correlation_id=None,
        )
    )
    result: dict[str, str] = {
        "run_id": "run-audit",
        "modernized_app_path": "[redacted-windows-path]",
    }
    if include_sandbox_path:
        result["sandbox_path"] = str(sandbox)
    command_repo.save(
        V2StageCommandRecord(
            command_id=command_id,
            job_id=f"job-{command_id}",
            stage_index=1,
            manifest_checksum="manifest-chk",
            argv_json="[]",
            env_json="{}",
            status="failed",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            result_json=json.dumps(
                result
            ),
            gate_id=None,
            decision_id=None,
        )
    )


def _seed_repair_apply_context(
    conn: sqlite3.Connection,
    tmp_path: Path,
    *,
    proposal_id: str,
    proposal_checksum: str,
    command_id: str,
    job_id: str = "job-2",
    create_job_row: bool = True,
    create_command_row: bool = True,
    run_id: str = "run-apply-1",
) -> Path:
    setup_repo = SqliteV2SetupRepository(conn)
    job_repo = SqliteV2JobRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    legacy_root = Path(tmp_path / "legacy")
    sandbox_root = Path(tmp_path / "out" / ".migration" / "runs" / run_id / "sandbox")
    legacy_root.mkdir(parents=True, exist_ok=True)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    (sandbox_root / "pom.xml").write_text("<project/>", encoding="utf-8")

    setup = V2MigrationSetupRecord(
        setup_id="setup-apply-1",
        run_name="repair-apply",
        legacy_app_path=str(tmp_path / "legacy"),
        output_parent_path=str(tmp_path / "out"),
        ai_hub_path=str(tmp_path / "ai-hub"),
        java11_home="C:/java11",
        java17_home="C:/java17",
        java21_home="C:/java21",
        maven_cmd="mvn",
        proof_level="build_test_verified",
        skip_endpoint_smoke=False,
        migration_flags_json="{}",
        setup_checksum="setup-chk",
        checksum_algorithm="sha256",
        created_at="2026-06-18T00:00:00Z",
        created_by="test",
        correlation_id=None,
    )
    setup_repo.save(setup)
    job_record = V2MigrationJobRecord(
        job_id=job_id,
        setup_id=setup.setup_id,
        setup_checksum="setup-chk",
        pipeline_id="pipeline-1",
        stage_chain_json="[]",
        status="created",
        created_at="2026-06-18T00:00:00Z",
        updated_at="2026-06-18T00:00:00Z",
        correlation_id=None,
    )
    if create_job_row:
        try:
            job_repo.save(job_record)
        except sqlite3.IntegrityError:
            conn.execute(
                """UPDATE v2_migration_jobs
                SET setup_id = ?,
                    setup_checksum = ?,
                    pipeline_id = ?,
                    stage_chain_json = ?,
                    status = ?,
                    created_at = ?,
                    updated_at = ?,
                    correlation_id = ?
                WHERE job_id = ?""",
                (
                    job_record.setup_id,
                    job_record.setup_checksum,
                    job_record.pipeline_id,
                    job_record.stage_chain_json,
                    job_record.status,
                    job_record.created_at,
                    job_record.updated_at,
                    job_record.correlation_id,
                    job_record.job_id,
                ),
            )

    run_dir = Path(tmp_path / "out" / ".migration" / "runs" / run_id)
    draft_path = run_dir / "repairs" / "patch_draft_1.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "proposal_id": proposal_id,
                "repair_proposal_checksum": proposal_checksum,
                "target_path": "pom.xml",
                "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                "risk": "LOW",
                "requires_human_review": False,
                "binding_checksum": "binding-1",
                "h2_required": True,
                "unified_diff": _h2_patch(),
                "expected_validation": ["mvn test"],
                "limitations": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    command_record = V2StageCommandRecord(
        command_id=command_id,
        job_id=job_id,
        stage_index=3,
        manifest_checksum="manifest-chk",
        argv_json="[]",
        env_json="{}",
        status="failed",
        created_at="2026-06-18T00:00:00Z",
        updated_at="2026-06-18T00:00:00Z",
        result_json=json.dumps(
            {
                "run_id": run_id,
                "sandbox_path": str(run_dir / "sandbox"),
                "modernized_app_path": str(tmp_path / "out"),
            }
        ),
        gate_id=None,
        decision_id=None,
    )
    if create_command_row:
        try:
            command_repo.save(command_record)
        except sqlite3.IntegrityError:
            conn.execute(
                """UPDATE v2_stage_commands
                SET job_id = ?,
                    stage_index = ?,
                    manifest_checksum = ?,
                    argv_json = ?,
                    env_json = ?,
                    status = ?,
                    created_at = ?,
                    updated_at = ?,
                    result_json = ?,
                    gate_id = ?,
                    decision_id = ?
                WHERE command_id = ?""",
                (
                    command_record.job_id,
                    command_record.stage_index,
                    command_record.manifest_checksum,
                    command_record.argv_json,
                    command_record.env_json,
                    command_record.status,
                    command_record.created_at,
                    command_record.updated_at,
                    command_record.result_json,
                    command_record.gate_id,
                    command_record.decision_id,
                    command_record.command_id,
                ),
            )
    return run_dir


def _seed_real_local_project_repair_apply_context(
    conn: sqlite3.Connection,
    tmp_path: Path,
    *,
    command_id: str,
    job_id: str = "job-2",
    create_job_row: bool = True,
    create_command_row: bool = True,
    run_id: str = "run-apply-1",
    proposal_id: str | None = None,
    proposal_checksum: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    source_fixture = Path(".migration/golden-references/repos/msa-utils-legacy/common-utils").resolve()
    legacy_root = tmp_path / "legacy-project"
    shutil.copytree(source_fixture, legacy_root)
    output_root = tmp_path / "out"
    run_dir = output_root / ".migration" / "runs" / run_id
    sandbox_root = run_dir / "sandbox"
    sandbox_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(legacy_root, sandbox_root)

    setup_id = _ready_setup_with_paths(
        conn,
        legacy_app_path=str(legacy_root),
        output_parent_path=str(output_root),
    )
    job_repo = SqliteV2JobRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    job_record = V2MigrationJobRecord(
        job_id=job_id,
        setup_id=setup_id,
        setup_checksum="setup-chk",
        pipeline_id="pipeline-1",
        stage_chain_json="[]",
        status="created",
        created_at="2026-06-18T00:00:00Z",
        updated_at="2026-06-18T00:00:00Z",
        correlation_id=None,
    )
    if create_job_row:
        try:
            job_repo.save(job_record)
        except sqlite3.IntegrityError:
            conn.execute(
                """UPDATE v2_migration_jobs
                SET setup_id = ?,
                    setup_checksum = ?,
                    pipeline_id = ?,
                    stage_chain_json = ?,
                    status = ?,
                    created_at = ?,
                    updated_at = ?,
                    correlation_id = ?
                WHERE job_id = ?""",
                (
                    job_record.setup_id,
                    job_record.setup_checksum,
                    job_record.pipeline_id,
                    job_record.stage_chain_json,
                    job_record.status,
                    job_record.created_at,
                    job_record.updated_at,
                    job_record.correlation_id,
                    job_record.job_id,
                ),
            )

    if proposal_id is not None and proposal_checksum is not None:
        draft_path = run_dir / "repairs" / "patch_draft_1.json"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "proposal_id": proposal_id,
                    "repair_proposal_checksum": proposal_checksum,
                    "target_path": "pom.xml",
                    "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                    "risk": "LOW",
                    "requires_human_review": False,
                    "binding_checksum": "binding-1",
                    "h2_required": True,
                    "unified_diff": _real_h2_patch((legacy_root / "pom.xml").read_text(encoding="utf-8")),
                    "expected_validation": ["mvn test"],
                    "limitations": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    command_record = V2StageCommandRecord(
        command_id=command_id,
        job_id=job_id,
        stage_index=3,
        manifest_checksum="manifest-chk",
        argv_json="[]",
        env_json="{}",
        status="failed",
        created_at="2026-06-18T00:00:00Z",
        updated_at="2026-06-18T00:00:00Z",
        result_json=json.dumps(
            {
                "run_id": run_id,
                "sandbox_path": str(sandbox_root),
                "modernized_app_path": str(output_root),
            }
        ),
        gate_id=None,
        decision_id=None,
    )
    if create_command_row:
        try:
            command_repo.save(command_record)
        except sqlite3.IntegrityError:
            conn.execute(
                """UPDATE v2_stage_commands
                SET job_id = ?,
                    stage_index = ?,
                    manifest_checksum = ?,
                    argv_json = ?,
                    env_json = ?,
                    status = ?,
                    created_at = ?,
                    updated_at = ?,
                    result_json = ?,
                    gate_id = ?,
                    decision_id = ?
                WHERE command_id = ?""",
                (
                    command_record.job_id,
                    command_record.stage_index,
                    command_record.manifest_checksum,
                    command_record.argv_json,
                    command_record.env_json,
                    command_record.status,
                    command_record.created_at,
                    command_record.updated_at,
                    command_record.result_json,
                    command_record.gate_id,
                    command_record.decision_id,
                    command_record.command_id,
                ),
            )
    return run_dir, legacy_root, sandbox_root, source_fixture


def _seed_repair_proposal(
    conn: sqlite3.Connection,
    *,
    command_id: str,
    failure_summary: str = "Build failed",
    hypothesis: str = "Missing dependency",
    patch_summary: str = "Add dependency",
    affected_paths: tuple[str, ...] = ("pom.xml",),
):
    service = V2RepairFlowService(repair_repo=SqliteV2RepairRepository(conn))
    return service.create_proposal(
        command_id=command_id,
        failure_summary=failure_summary,
        hypothesis=hypothesis,
        patch_summary=patch_summary,
        affected_paths=affected_paths,
    )


def _fake_apply_result(run_dir: Path):
    from migration_factory.repair_loop.patch_apply import PatchApplyResult

    patch_path = run_dir / "repairs" / "patch_attempt_1.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(_h2_patch(), encoding="utf-8")
    return PatchApplyResult(
        status="APPLIED",
        reason="ok",
        patch_path=patch_path,
        touched_paths=["pom.xml"],
        before_hashes={"pom.xml": "before"},
        after_hashes={"pom.xml": "after"},
        snapshot_dir=run_dir / "repairs" / "snapshots" / "attempt_1",
        created_paths=[],
        errors=[],
    )


def _fake_validation(passed: bool, *, artifact_refs: dict[str, str] | None = None):
    from migration_factory.repair_loop.validation_runner import ValidationResult

    return ValidationResult(
        passed=passed,
        build_status="BUILD_PASSED_IN_SANDBOX" if passed else "BUILD_FAILED_IN_SANDBOX",
        test_status="TEST_PASSED" if passed else "TEST_FAILED",
        h2_status="H2_STARTUP_PASSED" if passed else "H2_STARTUP_FAILED",
        validation_commands=[["mvn", "test"]],
        artifact_refs=artifact_refs or {},
        warnings=[],
        errors=[] if passed else ["validation failed"],
    )


def _fake_validation_with_artifacts(
    passed: bool,
    *,
    run_dir: Path,
    artifact_refs: dict[str, str] | None = None,
):
    refs = artifact_refs or {
        "verification_report": str(run_dir / "repairs" / "verification.json"),
        "test_log": str(run_dir / "repairs" / "test.log"),
        "h2_log": str(run_dir / "repairs" / "h2.log"),
    }
    for artifact_ref in refs.values():
        artifact_path = Path(artifact_ref)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(
                {
                    "status": "passed" if passed else "failed",
                    "artifact": artifact_path.name,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return _fake_validation(passed, artifact_refs=refs)


def _snapshot_directory(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _apply_real_fixture_patch(kwargs: dict[str, object], *, expected_file_before: str):
    from migration_factory.repair_loop.patch_apply import PatchApplyResult

    run_dir = Path(kwargs["run_dir"])  # type: ignore[arg-type]
    sandbox_path = Path(kwargs["sandbox_path"])  # type: ignore[arg-type]
    unified_diff = str(kwargs["unified_diff"])
    touched_paths = [str(path) for path in kwargs.get("touched_paths", ["pom.xml"])]
    target_rel_path = touched_paths[0]
    repairs_dir = run_dir / "repairs"
    repairs_dir.mkdir(parents=True, exist_ok=True)
    patch_path = repairs_dir / "patch_attempt_1.diff"
    patch_path.write_text(unified_diff.rstrip() + "\n", encoding="utf-8")

    snapshot_dir = repairs_dir / "snapshots" / "attempt_1"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    target_path = sandbox_path / target_rel_path
    before_text = target_path.read_text(encoding="utf-8")
    assert before_text == expected_file_before
    (snapshot_dir / target_rel_path).parent.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / target_rel_path).write_text(before_text, encoding="utf-8")
    before_hashes = {target_rel_path: hashlib.sha256(before_text.encode("utf-8")).hexdigest()}
    if target_rel_path.endswith(".java"):
        after_text = before_text.replace("import javax.", "import jakarta.")
        after_text = after_text.replace("package javax.", "package jakarta.")
    else:
        after_text = before_text.replace(
            "    </dependencies>\n",
            (
                "        <dependency>\n"
                "            <groupId>com.h2database</groupId>\n"
                "            <artifactId>h2</artifactId>\n"
                "            <scope>runtime</scope>\n"
                "        </dependency>\n"
                "    </dependencies>\n"
            ),
            1,
        )
    target_path.write_text(after_text, encoding="utf-8")
    after_hashes = {target_rel_path: hashlib.sha256(after_text.encode("utf-8")).hexdigest()}
    return PatchApplyResult(
        status="APPLIED",
        reason="patch applied inside sandbox",
        patch_path=patch_path,
        touched_paths=touched_paths,
        before_hashes=before_hashes,
        after_hashes=after_hashes,
        snapshot_dir=snapshot_dir,
        created_paths=[],
        errors=[],
    )


def _real_h2_patch(before_pom: str) -> str:
    after_pom = before_pom.replace(
        "    </dependencies>\n",
        (
            "        <dependency>\n"
            "            <groupId>com.h2database</groupId>\n"
            "            <artifactId>h2</artifactId>\n"
            "            <scope>runtime</scope>\n"
            "        </dependency>\n"
            "    </dependencies>\n"
        ),
        1,
    )
    diff = difflib.unified_diff(
        before_pom.splitlines(keepends=True),
        after_pom.splitlines(keepends=True),
        fromfile="a/pom.xml",
        tofile="b/pom.xml",
        lineterm="",
    )
    return "\n".join(["diff --git a/pom.xml b/pom.xml", *diff]) + "\n"


def _real_java_import_patch(before_text: str, *, rel_path: str) -> str:
    after_text = before_text.replace("import javax.", "import jakarta.")
    after_text = after_text.replace("package javax.", "package jakarta.")
    diff = difflib.unified_diff(
        before_text.splitlines(keepends=True),
        after_text.splitlines(keepends=True),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="",
    )
    return "\n".join([f"diff --git a/{rel_path} b/{rel_path}", *diff]) + "\n"


def _ready_setup_with_paths(conn: sqlite3.Connection, *, legacy_app_path: str, output_parent_path: str) -> str:
    repo = SqliteV2SetupRepository(conn)
    service = V2SetupService(repo)
    setup = service.create_setup(
        CreateSetupRequest(
            run_name="repair-apply",
            legacy_app_path=legacy_app_path,
            output_parent_path=output_parent_path,
            ai_hub_path="C:/work/ai-hub",
            java11_home="C:/java/11",
            java17_home="C:/java/17",
            java21_home="C:/java/21",
            maven_cmd="C:/maven/bin/mvn.cmd",
        )
    )
    ready_json = json.dumps({
        "legacy_app_exists": True,
        "legacy_app_has_project_file": True,
        "legacy_app_not_in_output_parent": True,
        "output_parent_writable": True,
        "ai_hub_root_exists": True,
        "ai_hub_profiles_ready": True,
        "ai_hub_catalogs_ready": True,
        "ai_hub_policies_ready": True,
        "jdk11_ready": True,
        "jdk17_ready": True,
        "jdk21_ready": True,
        "maven_ready": True,
        "pipeline_route_ready": True,
        "legacy_marker_ready": True,
        "output_parent_gate_ready": True,
        "azure_model_ready": True,
    })
    repo.save_preflight(
        V2PreflightResultRecord(
            preflight_id="pf-ready",
            setup_id=setup.setup_id,
            setup_checksum=setup.setup_checksum,
            all_ready=True,
            legacy_app_exists=True,
            legacy_app_has_project_file=True,
            legacy_app_not_in_output_parent=True,
            output_parent_writable=True,
            ai_hub_root_exists=True,
            ai_hub_profiles_ready=True,
            ai_hub_catalogs_ready=True,
            ai_hub_policies_ready=True,
            jdk11_ready=True,
            jdk17_ready=True,
            jdk21_ready=True,
            maven_ready=True,
            pipeline_route_ready=True,
            legacy_marker_ready=True,
            output_parent_gate_ready=True,
            readiness_json=ready_json,
            warnings_json="[]",
            errors_json="[]",
            checked_at=utc_now_text(),
            checked_by="test",
            correlation_id=None,
        )
    )
    return setup.setup_id


def _h2_patch() -> str:
    return (
        "diff --git a/pom.xml b/pom.xml\n"
        "--- a/pom.xml\n"
        "+++ b/pom.xml\n"
        "@@\n"
        " <dependencies>\n"
        "+<dependency><groupId>com.h2database</groupId><artifactId>h2</artifactId><scope>runtime</scope></dependency>\n"
    )


def _safe_patch_package() -> dict:
    return {
        "repair_family": "JAKARTA_IMPORT_MECHANICAL_SOURCE",
        "deterministic_rule_id": "JAKARTA_IMPORT_MECHANICAL_SOURCE",
        "repair_artifact": {
            "unified_diff": (
                "diff --git a/src/App.java b/src/App.java\n"
                "--- a/src/App.java\n"
                "+++ b/src/App.java\n"
                "@@\n"
                "-import javax.validation.Valid;\n"
                "+import jakarta.validation.Valid;\n"
            ),
            "patch_path": "run/repairs/proposals/patch.diff",
            "patch_checksum": "sha256:patch",
        },
        "target_files": [
            {
                "relative_path": "src/App.java",
                "absolute_path": "C:/sandbox/src/App.java",
                "before_checksum": "sha256:before",
                "proposed_checksum": "sha256:after",
            }
        ],
        "failure_evidence": {"diagnostic_line": "package javax.validation does not exist"},
        "verification_plan": {
            "command": ["mvn", "-q", "-DskipTests", "compile"],
            "cwd": "C:/sandbox",
            "llm_during_verification": False,
        },
        "containment": {
            "all_targets_under_sandbox": True,
            "legacy_target_present": False,
            "sandbox_outside_legacy": True,
        },
        "approval_apply_separate": True,
        "blockers": [],
    }


class _RecordingProposerClient:
    provider = "fake"

    def __init__(self) -> None:
        self.roles: list[str] = []
        self.prompts: list[str] = []

    def answer_with_role(
        self,
        *,
        role,
        prompt: str,
        fallback: str,
        conversation_history=None,
        output_schema_name=None,
        require_schema: bool = False,
    ):
        self.roles.append(role.value)
        self.prompts.append(prompt)
        import json as _json

        return type("Result", (), {
            "content": _json.dumps({
                "failure_hypothesis": "Model-generated hypothesis",
                "patch_summary": "Model-generated patch summary",
                "affected_paths": ["pom.xml"],
                "validation_plan": "Run mvn -q test",
            }),
            "source": "fake",
            "model_status": "live_ok",
            "provider": "fake",
            "role": role.value,
            "success": True,
            "redacted_summary": "Fake proposer response",
            "failure_reason": "",
        })()

    def answer(self, *, prompt: str, fallback: str, conversation_history=None):
        return self.answer_with_role(
            role=V2ModelRole.PROPOSER,
            prompt=prompt,
            fallback=fallback,
            conversation_history=conversation_history,
        )


class _RecordingReviewerClient:
    provider = "fake"

    def __init__(self) -> None:
        self.roles: list[str] = []
        self.prompts: list[str] = []

    def answer_with_role(
        self,
        *,
        role,
        prompt: str,
        fallback: str,
        conversation_history=None,
        output_schema_name=None,
        require_schema: bool = False,
    ):
        self.roles.append(role.value)
        self.prompts.append(prompt)
        import json as _json

        return type("Result", (), {
            "content": _json.dumps({
                "decision": "accept",
                "reasoning": "Model-generated reviewer reasoning",
                "missing_evidence": [],
                "unsafe_assumptions": [],
            }),
            "source": "fake",
            "model_status": "live_ok",
            "provider": "fake",
            "role": role.value,
            "success": True,
            "redacted_summary": "Fake reviewer response",
            "failure_reason": "",
        })()

    def answer(self, *, prompt: str, fallback: str, conversation_history=None):
        return self.answer_with_role(
            role=V2ModelRole.REVIEWER,
            prompt=prompt,
            fallback=fallback,
            conversation_history=conversation_history,
        )


class _UnavailableReviewerClient:
    provider = "fake-unavailable"

    def __init__(self) -> None:
        self.roles: list[str] = []
        self.prompts: list[str] = []

    def answer_with_role(
        self,
        *,
        role,
        prompt: str,
        fallback: str,
        conversation_history=None,
        output_schema_name=None,
        require_schema: bool = False,
    ):
        self.roles.append(role.value)
        self.prompts.append(prompt)
        return type("Result", (), {
            "content": fallback,
            "source": "deterministic",
            "model_status": "fallback",
            "provider": "deterministic",
            "role": role.value,
            "success": False,
            "redacted_summary": "Reviewer model unavailable.",
            "failure_reason": "missing_endpoint",
            "primary_failure_reason": "missing_endpoint",
            "fallback_used": False,
            "schema_validated": False,
        })()

    def answer(self, *, prompt: str, fallback: str, conversation_history=None):
        return self.answer_with_role(
            role=V2ModelRole.REVIEWER,
            prompt=prompt,
            fallback=fallback,
            conversation_history=conversation_history,
        )


class _ControlledFailureProposerClient(_RecordingProposerClient):
    def __init__(self, target_rel_path: str) -> None:
        super().__init__()
        self.target_rel_path = target_rel_path

    def answer_with_role(
        self,
        *,
        role,
        prompt: str,
        fallback: str,
        conversation_history=None,
        output_schema_name=None,
        require_schema: bool = False,
    ):
        self.roles.append(role.value)
        import json as _json

        return type("Result", (), {
            "content": _json.dumps({
                "failure_hypothesis": "Undefined controlled symbol doesNotCompile",
                "patch_summary": "Remove controlled undefined symbol in sandbox source",
                "affected_paths": [self.target_rel_path],
                "validation_plan": "Run mvn -q -DskipTests compile",
            }),
            "source": "fake",
            "model_status": "live_ok",
            "provider": "fake",
            "role": role.value,
            "success": True,
            "redacted_summary": "Fake proposer response",
            "failure_reason": "",
        })()


# ── Assistant API tests ────────────────────────────────────────────


class TestAssistantAPI:

    def test_add_message(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "user", "content": "Hello"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["role"] == "user"
        assert body["content"] == "Hello"

    def test_add_assistant_message(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "assistant", "content": "Status: ready"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "assistant"

    def test_list_messages(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        # Add two messages
        client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "user", "content": "Hi"},
            headers=_mutation_headers(),
        )
        client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "assistant", "content": "Hello"},
            headers=_mutation_headers(),
        )
        response = client.get(
            "/v1/v2/jobs/job-1/assistant/messages",
            headers={"Host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["messages"]) == 2

    def test_draft_action(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "propose_repair",
                "reason": "Need plan for stage 1",
                "stage_index": 1,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "draft"
        assert body["action_type"] == "propose_repair"

    def test_draft_action_persists(self, tmp_path: Path) -> None:
        """Draft should persist and be retrievable."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "explain_failure",
                "reason": "Fix NPE",
                "stage_index": 2,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200
        action_id = response.json()["action_id"]

        # Verify persistence
        db_path = tmp_path / "assistant_repair_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        repo = SqliteV2AssistantRepository(conn2)
        loaded = repo.get_draft(action_id)
        assert loaded is not None
        assert loaded.status == "draft"
        conn2.close()

    def test_message_persists(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-persist/assistant/messages",
            json={"job_id": "job-persist", "role": "user", "content": "Persist me"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200
        msg_id = response.json()["message_id"]

        db_path = tmp_path / "assistant_repair_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        repo = SqliteV2AssistantRepository(conn2)
        loaded = repo.get_message(msg_id)
        assert loaded is not None
        assert loaded.content == "Persist me"
        conn2.close()


# ── Repair API tests ───────────────────────────────────────────────


class TestRepairAPI:

    def test_reviewer_preflight_accepts_patch_backed_safe_package(self) -> None:
        from migration_factory.control_tower.adapters.fastapi.app import (
            _repair_patch_package_review_blockers,
        )

        assert _repair_patch_package_review_blockers(_safe_patch_package()) == []

    def test_reviewer_preflight_revises_vague_or_unsafe_packages(self) -> None:
        from migration_factory.control_tower.adapters.fastapi.app import (
            _repair_patch_package_review_blockers,
        )

        assert "proposal is missing patch package" in _repair_patch_package_review_blockers({})

        missing_checksum = _safe_patch_package()
        missing_checksum["target_files"][0]["before_checksum"] = ""
        assert "proposal target is missing before checksum" in _repair_patch_package_review_blockers(missing_checksum)

        escaping = _safe_patch_package()
        escaping["blockers"] = ["target path escapes sandbox: ../App.java"]
        assert "target path escapes sandbox: ../App.java" in _repair_patch_package_review_blockers(escaping)

        legacy = _safe_patch_package()
        legacy["containment"]["legacy_target_present"] = True
        assert "proposal contains legacy write target" in _repair_patch_package_review_blockers(legacy)

        missing_namespace_proof = _safe_patch_package()
        missing_namespace_proof["failure_evidence"] = {
            "diagnostic_line": "package jakarta.servlet.http does not exist"
        }
        missing_namespace_proof["repair_artifact"]["unified_diff"] = (
            "diff --git a/src/App.java b/src/App.java\n"
            "--- a/src/App.java\n"
            "+++ b/src/App.java\n"
            "@@\n"
            "-import jakarta.servlet.http.HttpServletRequest;\n"
            "+import javax.servlet.http.HttpServletRequest;\n"
        )
        assert (
            "proposal is missing controlled demo or dependency evidence proving javax.servlet.http is intended"
            in _repair_patch_package_review_blockers(missing_namespace_proof)
        )

    def test_create_proposal(self, tmp_path: Path) -> None:
        fake_client = _RecordingProposerClient()
        client, conn = _api_client(tmp_path, fake_model_client=fake_client)
        response = client.post(
            "/v1/v2/commands/cmd-1/repair/flow-proposal",
            json={
                "command_id": "cmd-1",
                "failure_summary": "Build failed",
                "hypothesis": "Missing import",
                "patch_summary": "Add import statement",
                "affected_paths": ["src/main.java"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "draft"
        assert body["hypothesis"] == "Model-generated hypothesis"
        assert body["patch_summary"] == "Model-generated patch summary"
        assert body["proposal_checksum"]
        assert body["proposal_model"]["status"] == "live_ok"
        assert body["proposal_model"]["provider"] == "fake"
        assert body["proposal_model"]["attempted_provider"] == "fake"
        assert body["proposal_model"]["role"] == "proposer"
        assert body["proposal_model"]["failure_reason"] == ""
        assert body["proposal_model"]["primary_failure_reason"] == ""
        assert body["proposal_model"]["fallback_used"] is False
        assert body["proposal_model"]["schema_validated"] is True
        assert body["proposal_model"]["model_invocation_id"]
        assert fake_client.roles == ["proposer"]
        invocations = SqliteUnitOfWork(conn).v1_model_invocations.list()
        assert len(invocations) == 1
        assert invocations[0].provider_kind == "fake"
        assert invocations[0].model_name == "proposer"

    def test_controlled_r6_demo_route_is_dev_only_and_creates_patch_backed_proposal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, conn = _api_client(tmp_path)
        _seed_v2_command_for_model_audit(conn, tmp_path, "cmd-r6-demo")

        disabled = client.post(
            "/v1/v2/jobs/job-cmd-r6-demo/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )
        assert disabled.status_code == 403

        monkeypatch.setenv("CONTROL_TOWER_R6_DEMO_ENABLED", "true")
        response = client.post(
            "/v1/v2/jobs/job-cmd-r6-demo/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        proposal = body["repair_proposal"]
        package = proposal["patch_package"]

        assert body["sandbox_only"] is True
        assert body["legacy_unchanged"] is True
        assert body["stage2_started"] is False
        assert body["repair_family"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
        assert proposal["command_id"].startswith("r6-demo-")
        assert proposal["context_pack_checksum"] == package["package_checksum"]
        assert proposal["context_pack_checksum"]
        assert package["repair_family"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
        assert package["deterministic_rule_id"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
        assert package["repair_artifact"]["patch_checksum"]
        assert Path(package["repair_artifact"]["patch_path"]).is_file()
        assert "import javax.servlet.http.HttpServletRequest;" in package["repair_artifact"]["unified_diff"]
        evidence = package["failure_evidence"]["controlled_demo_evidence"]
        assert evidence["controlled_demo"] is True
        assert evidence["injected_failure"] is True
        assert evidence["sandbox_only"] is True
        assert evidence["legacy_unchanged"] is True
        assert evidence["original_import_namespace"] == "javax.servlet.http"
        assert evidence["injected_import_namespace"] == "jakarta.servlet.http"
        assert evidence["proposed_import_namespace"] == "javax.servlet.http"
        assert evidence["injection_before_checksum"].startswith("sha256:")
        assert evidence["injection_after_checksum"].startswith("sha256:")
        assert package["failure_evidence"]["dependency_alignment"]["supports_namespace"] == "javax.servlet.http"

        records = SqliteV2RepairRepository(conn).list_proposals_by_command(proposal["command_id"])
        assert len(records) == 1
        assert records[0].proposal_id == proposal["proposal_id"]
        assert records[0].context_pack_checksum == package["package_checksum"]

        reviewer_client = _RecordingReviewerClient()
        client.app.state.v2_assistant_model_client = reviewer_client
        review_response = client.post(
            f"/v1/v2/commands/{proposal['command_id']}/repair/proposal/{proposal['proposal_id']}/reviewer-critique",
            json={
                "proposal_id": proposal["proposal_id"],
                "proposal_type": "repair_proposal",
                "proposal_checksum": proposal["proposal_checksum"],
                "context_pack_checksum": proposal["context_pack_checksum"],
            },
            headers=_mutation_headers(),
        )
        assert review_response.status_code == 200, review_response.text
        review_body = review_response.json()
        assert review_body["decision"] == "accept"
        assert review_body["context_pack_checksum"] == proposal["context_pack_checksum"]
        assert review_body["reviewer_model"]["provider"] == "fake"
        assert review_body["reviewer_model"]["source"] == "fake"
        assert review_body["reviewer_model"]["status"] == "live_ok"
        assert review_body["reviewer_model"]["fallback_used"] is False
        assert reviewer_client.roles == ["reviewer"]
        assert reviewer_client.prompts
        assert "controlled_demo_evidence" in reviewer_client.prompts[0]
        assert "controlled_demo_pre_injection_source" in reviewer_client.prompts[0]
        persisted = SqliteUnitOfWork(conn).v2_reviewer.list_critiques_by_proposal(proposal["proposal_id"])
        assert len(persisted) == 1
        assert persisted[0].context_pack_checksum == proposal["context_pack_checksum"]
        assert persisted[0].decision == "accept"

        browser_model_payload = client.post(
            f"/v1/v2/commands/{proposal['command_id']}/repair/proposal/{proposal['proposal_id']}/reviewer-critique",
            json={
                "proposal_id": proposal["proposal_id"],
                "proposal_type": "repair_proposal",
                "proposal_checksum": proposal["proposal_checksum"],
                "context_pack_checksum": proposal["context_pack_checksum"],
                "model_invocation_id": "browser-supplied-model-id",
            },
            headers=_mutation_headers(),
        )
        assert browser_model_payload.status_code == 422

        browser_decision_payload = client.post(
            f"/v1/v2/commands/{proposal['command_id']}/repair/proposal/{proposal['proposal_id']}/reviewer-critique",
            json={
                "proposal_id": proposal["proposal_id"],
                "proposal_type": "repair_proposal",
                "proposal_checksum": proposal["proposal_checksum"],
                "context_pack_checksum": proposal["context_pack_checksum"],
                "decision": "accept",
                "reasoning": "browser says yes",
            },
            headers=_mutation_headers(),
        )
        assert browser_decision_payload.status_code == 422

    def test_controlled_r6_reviewer_uses_local_dev_fallback_when_model_unavailable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, conn = _api_client(tmp_path)
        _seed_v2_command_for_model_audit(conn, tmp_path, "cmd-r6-local-reviewer")
        monkeypatch.setenv("CONTROL_TOWER_R6_DEMO_ENABLED", "true")

        response = client.post(
            "/v1/v2/jobs/job-cmd-r6-local-reviewer/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        proposal = response.json()["repair_proposal"]

        reviewer_client = _UnavailableReviewerClient()
        client.app.state.v2_assistant_model_client = reviewer_client
        review_response = client.post(
            f"/v1/v2/commands/{proposal['command_id']}/repair/proposal/{proposal['proposal_id']}/reviewer-critique",
            json={
                "proposal_id": proposal["proposal_id"],
                "proposal_type": "repair_proposal",
                "proposal_checksum": proposal["proposal_checksum"],
                "context_pack_checksum": proposal["context_pack_checksum"],
            },
            headers=_mutation_headers(),
        )

        assert review_response.status_code == 200, review_response.text
        body = review_response.json()
        assert body["decision"] == "accept"
        assert "Controlled local/dev R6 smoke reviewer accepted" in body["reasoning"]
        assert body["missing_evidence"] == []
        assert body["reviewer_model"]["provider"] == "local_dev_fake"
        assert body["reviewer_model"]["source"] == "controlled_r6_smoke"
        assert body["reviewer_model"]["status"] == "local_dev_fallback"
        assert body["reviewer_model"]["fallback_used"] is True
        assert body["reviewer_model"]["model_invocation_id"]
        assert reviewer_client.roles == ["reviewer"]
        persisted = SqliteUnitOfWork(conn).v2_reviewer.list_critiques_by_proposal(proposal["proposal_id"])
        assert len(persisted) == 1
        assert persisted[0].decision == "accept"

    def test_controlled_r6_reviewer_revises_when_namespace_evidence_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, conn = _api_client(tmp_path)
        _seed_v2_command_for_model_audit(conn, tmp_path, "cmd-r6-missing-evidence")
        monkeypatch.setenv("CONTROL_TOWER_R6_DEMO_ENABLED", "true")

        response = client.post(
            "/v1/v2/jobs/job-cmd-r6-missing-evidence/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        proposal = response.json()["repair_proposal"]
        package = proposal["patch_package"]
        package["failure_evidence"].pop("controlled_demo_evidence", None)
        package["failure_evidence"].pop("dependency_alignment", None)
        conn.execute(
            "UPDATE v2_repair_proposals SET patch_package_json = ? WHERE proposal_id = ?",
            (json.dumps(package, separators=(",", ":"), sort_keys=True), proposal["proposal_id"]),
        )

        reviewer_client = _RecordingReviewerClient()
        client.app.state.v2_assistant_model_client = reviewer_client
        review_response = client.post(
            f"/v1/v2/commands/{proposal['command_id']}/repair/proposal/{proposal['proposal_id']}/reviewer-critique",
            json={
                "proposal_id": proposal["proposal_id"],
                "proposal_type": "repair_proposal",
                "proposal_checksum": proposal["proposal_checksum"],
                "context_pack_checksum": proposal["context_pack_checksum"],
            },
            headers=_mutation_headers(),
        )

        assert review_response.status_code == 200, review_response.text
        body = review_response.json()
        assert body["decision"] == "revise"
        assert any(
            "proposal is missing controlled demo or dependency evidence" in item
            for item in body["missing_evidence"]
        )
        assert reviewer_client.roles == []

    def test_controlled_r6_demo_returns_409_before_sandbox_exists(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, conn = _api_client(tmp_path)
        _seed_v2_command_for_model_audit(conn, tmp_path, "cmd-no-sandbox")
        shutil.rmtree(tmp_path / "out-cmd-no-sandbox")
        monkeypatch.setenv("CONTROL_TOWER_R6_DEMO_ENABLED", "true")

        response = client.post(
            "/v1/v2/jobs/job-cmd-no-sandbox/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )

        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "R6_DEMO_SANDBOX_MISSING"
        assert "looked_run_id=run-audit" in body["error"]["message"]
        assert "expected_sandbox_artifact_key=sandbox" in body["error"]["message"]

    def test_controlled_r6_demo_resolves_failed_stage1_sandbox_from_artifact_event_after_restart(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, conn = _api_client(tmp_path)
        _seed_v2_command_for_model_audit(
            conn,
            tmp_path,
            "cmd-artifact-sandbox",
            include_sandbox_path=False,
        )
        SqliteUnitOfWork(conn).v2_events.save(
            job_id="job-cmd-artifact-sandbox",
            stage=1,
            event_type="artifact_written",
            status="completed",
            message="Artifact written: sandbox",
            payload={
                "artifact_kind": "sandbox",
                "command_id": "cmd-artifact-sandbox",
                "relative_path": ".migration/runs/run-audit/workspaces/sandbox",
            },
        )
        monkeypatch.setenv("CONTROL_TOWER_R6_DEMO_ENABLED", "true")

        response = client.post(
            "/v1/v2/jobs/job-cmd-artifact-sandbox/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run_id"] == "run-audit"
        assert body["repair_proposal"]["patch_package"]["repair_family"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"

    def test_controlled_r6_demo_rejects_after_stage2_started(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, conn = _api_client(tmp_path)
        _seed_v2_command_for_model_audit(conn, tmp_path, "cmd-stage2-started")
        SqliteUnitOfWork(conn).v2_events.save(
            job_id="job-cmd-stage2-started",
            stage=2,
            event_type="sandbox_transform_started",
            status="running",
            message="Stage2 started",
            payload={"command_id": "stage2-cmd"},
        )
        monkeypatch.setenv("CONTROL_TOWER_R6_DEMO_ENABLED", "true")

        response = client.post(
            "/v1/v2/jobs/job-cmd-stage2-started/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "R6_DEMO_STAGE2_STARTED"

    def test_controlled_r6_demo_rejects_after_stage2_command_exists(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, conn = _api_client(tmp_path)
        _seed_v2_command_for_model_audit(conn, tmp_path, "cmd-stage2-command")
        now = utc_now_text()
        SqliteUnitOfWork(conn).v2_commands.save(
            V2StageCommandRecord(
                command_id="stage2-command",
                job_id="job-cmd-stage2-command",
                stage_index=2,
                manifest_checksum="stage2-manifest",
                argv_json="[]",
                env_json="{}",
                status="queued",
                created_at=now,
                updated_at=now,
                result_json="{}",
                gate_id=None,
                decision_id=None,
            )
        )
        monkeypatch.setenv("CONTROL_TOWER_R6_DEMO_ENABLED", "true")

        response = client.post(
            "/v1/v2/jobs/job-cmd-stage2-command/repair/demo/r6-controlled",
            json={},
            headers=_mutation_headers(),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "R6_DEMO_STAGE2_STARTED"

    def test_create_proposal_surfaces_schema_validation_failure_reason(
        self,
        tmp_path: Path,
    ) -> None:
        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
        )

        class _SchemaMismatchProposerClient:
            provider = "fake"

            def answer_with_role(
                self,
                *,
                role,
                prompt: str,
                fallback: str,
                conversation_history=None,
                output_schema_name=None,
                require_schema: bool = False,
            ):
                return V2AssistantModelResult(
                    content='{"failure_hypothesis":"Draft","patch_summary":"Draft","affected_paths":[],"validation_plan":"Draft"}',
                    source="deterministic",
                    model_status="fallback",
                    provider="deterministic",
                    role=role.value,
                    success=False,
                    redacted_summary="schema mismatch",
                    failure_reason="schema_validation_failed:RepairProposal",
                    primary_failure_reason="schema_validation_failed:RepairProposal",
                    fallback_used=True,
                    schema_validated=True,
                )

            def answer(self, *, prompt: str, fallback: str, conversation_history=None):
                return self.answer_with_role(
                    role=V2ModelRole.PROPOSER,
                    prompt=prompt,
                    fallback=fallback,
                    conversation_history=conversation_history,
                )

        client, conn = _api_client(tmp_path, fake_model_client=_SchemaMismatchProposerClient())
        response = client.post(
            "/v1/v2/commands/cmd-schema/repair/flow-proposal",
            json={
                "command_id": "cmd-schema",
                "failure_summary": "Build failed",
                "hypothesis": "Missing import",
                "patch_summary": "Add import statement",
                "affected_paths": ["src/main.java"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["proposal_model"]["provider"] == "deterministic"
        assert body["proposal_model"]["attempted_provider"] == "fake"
        assert body["proposal_model"]["fallback_used"] is True
        assert body["proposal_model"]["primary_failure_reason"].startswith("schema_validation_failed")
        assert body["proposal_model"]["failure_reason"].startswith("schema_validation_failed")
        assert body["proposal_model"]["redacted_error_summary"] == "schema mismatch"
        assert body["proposal_model"]["model_invocation_id"]
        invocations = SqliteUnitOfWork(conn).v1_model_invocations.list()
        assert len(invocations) == 1
        assert invocations[0].provider_kind == "fake"
        assert invocations[0].model_name == "proposer"

    def test_create_proposal_accepts_markdown_fenced_json(
        self,
        tmp_path: Path,
    ) -> None:
        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
        )

        class _FencedProposerClient:
            provider = "fake"
            target_rel_path = "src/main/java/App.java"
            target_rel_path = "src/main/java/App.java"

            def answer_with_role(
                self,
                *,
                role,
                prompt: str,
                fallback: str,
                conversation_history=None,
                output_schema_name=None,
                require_schema: bool = False,
            ):
                return V2AssistantModelResult(
                    content=(
                        "Here is the proposal:\n"
                        "```json\n"
                        "{"
                        '"failure_hypothesis":"Root cause",'
                        '"patch_summary":"Fix issue",'
                        f'"affected_paths":["{self.target_rel_path}"],'
                        '"validation_plan":"Run mvn test"'
                        "}\n"
                        "```"
                    ),
                    source="fake",
                    model_status="live_ok",
                    provider="fake",
                    role=role.value,
                    success=True,
                    redacted_summary="Here is the proposal",
                    failure_reason="",
                )

            def answer(self, *, prompt: str, fallback: str, conversation_history=None):
                return self.answer_with_role(
                    role=V2ModelRole.PROPOSER,
                    prompt=prompt,
                    fallback=fallback,
                    conversation_history=conversation_history,
                )

        client, conn = _api_client(tmp_path, fake_model_client=_FencedProposerClient())
        response = client.post(
            "/v1/v2/commands/cmd-fenced/repair/flow-proposal",
            json={
                "command_id": "cmd-fenced",
                "failure_summary": "Build failed",
                "hypothesis": "Missing import",
                "patch_summary": "Add import statement",
                "affected_paths": ["src/main.java"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["hypothesis"] == "Root cause"
        assert body["patch_summary"] == "Fix issue"
        assert body["proposal_model"]["provider"] == "fake"
        assert body["proposal_model"]["attempted_provider"] == "fake"
        assert body["proposal_model"]["fallback_used"] is False
        assert body["proposal_model"]["schema_validated"] is True
        assert body["proposal_model"]["primary_failure_reason"] == ""
        assert body["proposal_model"]["model_invocation_id"]
        invocations = SqliteUnitOfWork(conn).v1_model_invocations.list()
        assert len(invocations) == 1
        assert invocations[0].provider_kind == "fake"
        assert invocations[0].model_name == "proposer"

    def test_create_proposal_ignores_extra_field_in_markdown_fenced_json(
        self,
        tmp_path: Path,
    ) -> None:
        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
        )

        class _ExtraFieldProposerClient:
            provider = "fake"

            def answer_with_role(
                self,
                *,
                role,
                prompt: str,
                fallback: str,
                conversation_history=None,
                output_schema_name=None,
                require_schema: bool = False,
            ):
                return V2AssistantModelResult(
                    content=(
                        "```json\n"
                        "{"
                        '"failure_hypothesis":"Root cause",'
                        '"patch_summary":"Fix issue",'
                        '"affected_paths":["pom.xml"],'
                        '"validation_plan":"Run mvn test",'
                        '"step":"extra field"'
                        "}\n"
                        "```"
                    ),
                    source="fake",
                    model_status="live_ok",
                    provider="fake",
                    role=role.value,
                    success=True,
                    redacted_summary="proposal with extra field",
                    failure_reason="",
                )

            def answer(self, *, prompt: str, fallback: str, conversation_history=None):
                return self.answer_with_role(
                    role=V2ModelRole.PROPOSER,
                    prompt=prompt,
                    fallback=fallback,
                    conversation_history=conversation_history,
                )

        client, conn = _api_client(tmp_path, fake_model_client=_ExtraFieldProposerClient())
        response = client.post(
            "/v1/v2/commands/cmd-extra-field/repair/flow-proposal",
            json={
                "command_id": "cmd-extra-field",
                "failure_summary": "Build failed",
                "hypothesis": "Missing import",
                "patch_summary": "Add import statement",
                "affected_paths": ["src/main.java"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["hypothesis"] == "Root cause"
        assert body["proposal_model"]["provider"] == "fake"
        assert body["proposal_model"]["attempted_provider"] == "fake"
        assert body["proposal_model"]["fallback_used"] is False
        assert body["proposal_model"]["schema_validated"] is True
        assert body["proposal_model"]["primary_failure_reason"] == ""

    def test_create_reviewer_critique(self, tmp_path: Path) -> None:
        target_rel_path = "src/main/java/App.java"
        proposer_client = _ControlledFailureProposerClient(target_rel_path)
        client, conn = _api_client(tmp_path, fake_model_client=proposer_client)
        _seed_v2_command_for_model_audit(
            conn,
            tmp_path,
            "cmd-review",
            target_rel_path=target_rel_path,
        )

        create_resp = client.post(
            "/v1/v2/commands/cmd-review/repair/flow-proposal",
            json={
                "command_id": "cmd-review",
                "failure_summary": "cannot find symbol variable doesNotCompile",
                "hypothesis": "Undefined controlled symbol",
                "patch_summary": "Remove controlled undefined symbol",
                "affected_paths": [target_rel_path],
            },
            headers=_mutation_headers(),
        )
        assert create_resp.status_code == 200, create_resp.text
        proposal_body = create_resp.json()
        proposal_id = proposal_body["proposal_id"]
        proposal_checksum = proposal_body["proposal_checksum"]
        assert proposal_body["target_files"][0]["relative_path"] == target_rel_path
        assert proposal_body["target_files"][0]["before_checksum"].startswith("sha256:")
        assert proposal_body["repair_artifact"]["unified_diff"]
        assert Path(proposal_body["repair_artifact"]["patch_path"]).is_file()

        reviewer_client = _RecordingReviewerClient()
        client.app.state.v2_assistant_model_client = reviewer_client

        response = client.post(
            f"/v1/v2/commands/cmd-review/repair/proposal/{proposal_id}/reviewer-critique",
            json={
                "proposal_id": proposal_id,
                "proposal_type": "repair",
                "proposal_checksum": proposal_checksum,
                "context_pack_checksum": "cp-review",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decision"] == "accept"
        assert body["reviewer_model"]["status"] == "live_ok"
        assert body["reviewer_model"]["provider"] == "fake"
        assert body["reviewer_model"]["attempted_provider"] == "fake"
        assert body["reviewer_model"]["role"] == "reviewer"
        assert body["reviewer_model"]["failure_reason"] == ""
        assert body["reviewer_model"]["primary_failure_reason"] == ""
        assert body["reviewer_model"]["fallback_used"] is False
        assert body["reviewer_model"]["schema_validated"] is True
        assert body["reviewer_model"]["model_invocation_id"]
        assert reviewer_client.roles == ["reviewer"]
        invocations = SqliteUnitOfWork(conn).v1_model_invocations.list()
        assert len(invocations) == 2
        assert {inv.model_name for inv in invocations} == {"proposer", "reviewer"}
        assert {inv.provider_kind for inv in invocations} == {"fake"}

    def test_non_demo_reviewer_model_unavailable_fails_closed_with_revise(self, tmp_path: Path) -> None:
        target_rel_path = "src/main/java/App.java"
        proposer_client = _ControlledFailureProposerClient(target_rel_path)
        client, conn = _api_client(tmp_path, fake_model_client=proposer_client)
        _seed_v2_command_for_model_audit(
            conn,
            tmp_path,
            "cmd-review-unavailable",
            target_rel_path=target_rel_path,
        )

        create_resp = client.post(
            "/v1/v2/commands/cmd-review-unavailable/repair/flow-proposal",
            json={
                "command_id": "cmd-review-unavailable",
                "failure_summary": "cannot find symbol variable doesNotCompile",
                "hypothesis": "Undefined controlled symbol",
                "patch_summary": "Remove controlled undefined symbol",
                "affected_paths": [target_rel_path],
            },
            headers=_mutation_headers(),
        )
        assert create_resp.status_code == 200, create_resp.text
        proposal_body = create_resp.json()

        reviewer_client = _UnavailableReviewerClient()
        client.app.state.v2_assistant_model_client = reviewer_client
        response = client.post(
            f"/v1/v2/commands/cmd-review-unavailable/repair/proposal/{proposal_body['proposal_id']}/reviewer-critique",
            json={
                "proposal_id": proposal_body["proposal_id"],
                "proposal_type": "repair",
                "proposal_checksum": proposal_body["proposal_checksum"],
                "context_pack_checksum": "cp-review-unavailable",
            },
            headers=_mutation_headers(),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decision"] == "revise"
        assert body["reviewer_model"]["provider"] == "deterministic"
        assert body["reviewer_model"]["source"] == "deterministic"
        assert body["reviewer_model"]["status"] == "fallback"
        assert body["reviewer_model"]["failure_reason"] == "missing_endpoint"
        assert reviewer_client.roles == ["reviewer"]

    def test_repair_model_invocations_bind_to_v2_command_without_v1_fk(self, tmp_path: Path) -> None:
        command_id = "cmd-v2-audit"
        proposer_client = _RecordingProposerClient()
        client, conn = _api_client(tmp_path, fake_model_client=proposer_client)
        _seed_v2_command_for_model_audit(conn, tmp_path, command_id)

        create_resp = client.post(
            f"/v1/v2/commands/{command_id}/repair/flow-proposal",
            json={
                "command_id": command_id,
                "failure_summary": "Build failed",
                "hypothesis": "Missing import",
                "patch_summary": "Add import statement",
                "affected_paths": ["src/main.java"],
            },
            headers=_mutation_headers(),
        )
        assert create_resp.status_code == 200, create_resp.text
        proposal_id = create_resp.json()["proposal_id"]
        proposal_checksum = create_resp.json()["proposal_checksum"]
        proposer_invocation_id = create_resp.json()["proposal_model"]["model_invocation_id"]
        assert proposer_invocation_id

        reviewer_client = _RecordingReviewerClient()
        client.app.state.v2_assistant_model_client = reviewer_client
        review_resp = client.post(
            f"/v1/v2/commands/{command_id}/repair/proposal/{proposal_id}/reviewer-critique",
            json={
                "proposal_id": proposal_id,
                "proposal_type": "repair",
                "proposal_checksum": proposal_checksum,
                "context_pack_checksum": "cp-review",
            },
            headers=_mutation_headers(),
        )
        assert review_resp.status_code == 200, review_resp.text
        reviewer_invocation_id = review_resp.json()["reviewer_model"]["model_invocation_id"]
        assert reviewer_invocation_id

        invocations = SqliteUnitOfWork(conn).v1_model_invocations.list()
        by_id = {inv.invocation_id: inv for inv in invocations}
        assert by_id[proposer_invocation_id].job_id is None
        assert by_id[proposer_invocation_id].v2_job_id == f"job-{command_id}"
        assert by_id[proposer_invocation_id].v2_command_id == command_id
        assert by_id[reviewer_invocation_id].job_id is None
        assert by_id[reviewer_invocation_id].v2_job_id == f"job-{command_id}"
        assert by_id[reviewer_invocation_id].v2_command_id == command_id

    def test_create_reviewer_critique_accepts_markdown_fenced_json(
        self,
        tmp_path: Path,
    ) -> None:
        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
        )

        class _FencedProposerClient:
            provider = "fake"
            target_rel_path = "src/main/java/App.java"

            def answer_with_role(
                self,
                *,
                role,
                prompt: str,
                fallback: str,
                conversation_history=None,
                output_schema_name=None,
                require_schema: bool = False,
            ):
                return V2AssistantModelResult(
                    content=(
                        "```json\n"
                        "{"
                        '"failure_hypothesis":"Root cause",'
                        '"patch_summary":"Fix issue",'
                        f'"affected_paths":["{self.target_rel_path}"],'
                        '"validation_plan":"Run mvn test"'
                        "}\n"
                        "```"
                    ),
                    source="fake",
                    model_status="live_ok",
                    provider="fake",
                    role=role.value,
                    success=True,
                    redacted_summary="fenced proposal",
                    failure_reason="",
                )

            def answer(self, *, prompt: str, fallback: str, conversation_history=None):
                return self.answer_with_role(
                    role=V2ModelRole.PROPOSER,
                    prompt=prompt,
                    fallback=fallback,
                    conversation_history=conversation_history,
                )

        class _FencedReviewerClient:
            provider = "fake"

            def answer_with_role(
                self,
                *,
                role,
                prompt: str,
                fallback: str,
                conversation_history=None,
                output_schema_name=None,
                require_schema: bool = False,
            ):
                return V2AssistantModelResult(
                    content=(
                        "Reviewer notes:\n"
                        "```json\n"
                        "{"
                        '"decision":"accept",'
                        '"reasoning":"Looks good",'
                        '"missing_evidence":[],'
                        '"unsafe_assumptions":[]'
                        "}\n"
                        "```"
                    ),
                    source="fake",
                    model_status="live_ok",
                    provider="fake",
                    role=role.value,
                    success=True,
                    redacted_summary="fenced reviewer critique",
                    failure_reason="",
                )

            def answer(self, *, prompt: str, fallback: str, conversation_history=None):
                return self.answer_with_role(
                    role=V2ModelRole.REVIEWER,
                    prompt=prompt,
                    fallback=fallback,
                    conversation_history=conversation_history,
                )

        client, conn = _api_client(tmp_path, fake_model_client=_FencedProposerClient())
        _seed_v2_command_for_model_audit(
            conn,
            tmp_path,
            "cmd-review-fenced",
            target_rel_path=_FencedProposerClient.target_rel_path,
        )

        create_resp = client.post(
            "/v1/v2/commands/cmd-review-fenced/repair/flow-proposal",
            json={
                "command_id": "cmd-review-fenced",
                "failure_summary": "cannot find symbol variable doesNotCompile",
                "hypothesis": "Undefined controlled symbol",
                "patch_summary": "Remove controlled undefined symbol",
                "affected_paths": [_FencedProposerClient.target_rel_path],
            },
            headers=_mutation_headers(),
        )
        assert create_resp.status_code == 200, create_resp.text
        proposal_id = create_resp.json()["proposal_id"]
        proposal_checksum = create_resp.json()["proposal_checksum"]

        client.app.state.v2_assistant_model_client = _FencedReviewerClient()
        response = client.post(
            f"/v1/v2/commands/cmd-review-fenced/repair/proposal/{proposal_id}/reviewer-critique",
            json={
                "proposal_id": proposal_id,
                "proposal_type": "repair",
                "proposal_checksum": proposal_checksum,
                "context_pack_checksum": "cp-review-fenced",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decision"] == "accept"
        assert body["reviewer_model"]["provider"] == "fake"
        assert body["reviewer_model"]["attempted_provider"] == "fake"
        assert body["reviewer_model"]["fallback_used"] is False
        assert body["reviewer_model"]["schema_validated"] is True
        assert body["reviewer_model"]["primary_failure_reason"] == ""
        assert body["reviewer_model"]["model_invocation_id"]
        invocations = SqliteUnitOfWork(conn).v1_model_invocations.list()
        assert len(invocations) == 2
        assert {inv.model_name for inv in invocations} == {"proposer", "reviewer"}
        assert {inv.provider_kind for inv in invocations} == {"fake"}

    def test_create_proposal_reports_invalid_json_diagnostics_without_secrets(
        self,
        tmp_path: Path,
    ) -> None:
        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
        )

        class _InvalidJsonProposerClient:
            provider = "fake"

            def answer_with_role(
                self,
                *,
                role,
                prompt: str,
                fallback: str,
                conversation_history=None,
                output_schema_name=None,
                require_schema: bool = False,
            ):
                return V2AssistantModelResult(
                    content=(
                        "Authorization: Bearer sk-abc123\n"
                        "C:\\Users\\ilyas\\secret.txt\n"
                        "not json at all"
                    ),
                    source="fake",
                    model_status="live_ok",
                    provider="fake",
                    role=role.value,
                    success=True,
                    redacted_summary="invalid json",
                    failure_reason="",
                )

            def answer(self, *, prompt: str, fallback: str, conversation_history=None):
                return self.answer_with_role(
                    role=V2ModelRole.PROPOSER,
                    prompt=prompt,
                    fallback=fallback,
                    conversation_history=conversation_history,
                )

        client, conn = _api_client(tmp_path, fake_model_client=_InvalidJsonProposerClient())
        response = client.post(
            "/v1/v2/commands/cmd-invalid/repair/flow-proposal",
            json={
                "command_id": "cmd-invalid",
                "failure_summary": "Build failed",
                "hypothesis": "Missing import",
                "patch_summary": "Add import statement",
                "affected_paths": ["src/main.java"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["proposal_model"]["fallback_used"] is True
        assert body["proposal_model"]["primary_failure_reason"].startswith(
            "schema_validation_failed:RepairProposal"
        )
        assert "invalid JSON output" in body["proposal_model"]["primary_failure_reason"]
        assert "sk-abc123" not in body["proposal_model"]["primary_failure_reason"]
        assert "C:\\Users\\ilyas" not in body["proposal_model"]["primary_failure_reason"]
        assert "sk-abc123" not in body["proposal_model"]["failure_reason"]
        assert "C:\\Users\\ilyas" not in body["proposal_model"]["failure_reason"]

    def test_approve_proposal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client, conn = _api_client(tmp_path)
        proposal = _seed_repair_proposal(
            conn,
            command_id="cmd-2",
            failure_summary="Error",
            hypothesis="Bug",
            patch_summary="Fix",
            affected_paths=("src/Fix.java",),
        )
        proposal_id = proposal.proposal_id
        proposal_checksum = proposal.proposal_checksum
        run_dir = _seed_repair_apply_context(
            conn,
            tmp_path,
            proposal_id=proposal_id,
            proposal_checksum=proposal_checksum,
            command_id="cmd-2",
        )

        # Even with a legacy reviewer critique, this route cannot authorize F5 apply.
        from migration_factory.control_tower.application.v2_reviewer_service import (
            V2ReviewerService,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
            SqliteV2ReviewerRepository,
        )
        reviewer_repo = SqliteV2ReviewerRepository(conn)
        reviewer_service = V2ReviewerService(reviewer_repo=reviewer_repo)
        reviewer_service.record_critique(
            proposal_id=proposal_id,
            proposal_type="repair",
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
            decision="accept",
            reasoning="Test critique — approved.",
            missing_evidence=(),
            unsafe_assumptions=(),
            model_invocation_id="reviewer-invoke-1",
        )

        critique_id = reviewer_service.check_reviewer_gate(
            proposal_id=proposal_id,
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
        ).critique_id

        response = client.post(
            f"/v1/v2/commands/cmd-2/repair/proposal/{proposal_id}/prepare-apply-context",
            json={
                "proposal_checksum": "pc-test",
                "context_pack_checksum": "cp-test",
                "reviewer_critique_id": critique_id,
                "proposer_invocation_id": "proposer-invoke-1",
                "reviewer_invocation_id": "reviewer-invoke-1",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["repair_review_context"]["proposal_id"] == proposal_id
        assert body["repair_review_context"]["reviewer_critique_id"] == critique_id
        assert body["repair_review_context"]["approval_eligible"] is True
        assert body["repair_review_context"]["sandbox_only"] is True
        assert (run_dir / "repairs" / "patch_draft_1.json").is_file()

        context_id = body["repair_review_context"]["context_id"]
        repeat_response = client.post(
            f"/v1/v2/repair-review/{context_id}/approve",
            json={
                "approval_checksum": "chk-abc",
                "approval_note": "Human approval recorded for sandbox-only apply later.",
                "approval_scope": "sandbox_only",
            },
            headers=_mutation_headers(),
        )
        assert repeat_response.status_code == 200, repeat_response.text
        repeat_body = repeat_response.json()
        assert repeat_body["approval"]["approval_status"] == "recorded"
        assert repeat_body["approval"]["approval_scope"] == "sandbox_only"
        assert repeat_body["approval"]["sandbox_only"] is True
        approval_id = repeat_body["approval"]["approval_id"]

        context_read = client.get(f"/v1/v2/repair-review/{context_id}")
        assert context_read.status_code == 200, context_read.text
        context_body = context_read.json()["repair_review_context"]
        assert context_body["context_id"] == context_id
        assert context_body["proposal_id"] == proposal_id
        assert context_body["sandbox_checksum"].startswith("sha256:")
        assert context_body["legacy_checksum"].startswith("sha256:")
        assert context_body["patch_preview_checksum"]
        assert context_body["evidence_refs"]["patch_artifact"].endswith(".diff")
        assert context_body["evidence_refs"]["patch_checksum"].startswith("sha256:")
        assert context_body["sandbox_only"] is True
        assert context_body["llm_invoked"] is False

        missing_context = client.get("/v1/v2/repair-review/not-a-context")
        assert missing_context.status_code == 404
        assert "REPAIR_REVIEW_CONTEXT_NOT_FOUND" in missing_context.text

        approval_read = client.get(
            f"/v1/v2/repair-review/{context_id}/approvals/{approval_id}"
        )
        assert approval_read.status_code == 200, approval_read.text
        approval_body = approval_read.json()["approval"]
        assert approval_body["approval_id"] == approval_id
        assert approval_body["context_id"] == context_id
        assert approval_body["approval_status"] == "recorded"
        assert approval_body["approval_scope"] == "sandbox_only"
        assert approval_body["apply_ready"] is True
        assert approval_body["llm_invoked"] is False

        unbound_approval = client.get(
            f"/v1/v2/repair-review/not-a-context/approvals/{approval_id}"
        )
        assert unbound_approval.status_code == 404
        assert "REPAIR_APPROVAL_NOT_FOUND" in unbound_approval.text

        apply_mismatch = client.post(
            f"/v1/v2/repair-review/{context_id}/apply",
            json={
                "approval_id": approval_id,
                "expected_approval_checksum": "chk-abc",
                "expected_sandbox_checksum": "wrong",
                "expected_legacy_checksum": "legacy-chk",
            },
            headers=_mutation_headers(),
        )
        assert apply_mismatch.status_code == 400
        assert "sandbox checksum mismatch" in apply_mismatch.text

        apply_missing_approval = client.post(
            f"/v1/v2/repair-review/{context_id}/apply",
            json={
                "approval_id": "missing-approval",
                "expected_approval_checksum": "chk-abc",
                "expected_sandbox_checksum": context_body["sandbox_checksum"],
                "expected_legacy_checksum": context_body["legacy_checksum"],
            },
            headers=_mutation_headers(),
        )
        assert apply_missing_approval.status_code == 400
        assert "not found for context" in apply_missing_approval.text

        monkeypatch.setattr(
            v2_repair_flow,
            "apply_patch_to_sandbox",
            lambda **kwargs: _fake_apply_result(Path(kwargs["run_dir"])),
        )
        monkeypatch.setattr(
            v2_repair_flow,
            "run_validation_after_patch",
            lambda **kwargs: _fake_validation(True),
        )

        apply_response = client.post(
            f"/v1/v2/repair-review/{context_id}/apply",
            json={
                "approval_id": approval_id,
                "expected_approval_checksum": "chk-abc",
                "expected_sandbox_checksum": context_body["sandbox_checksum"],
                "expected_legacy_checksum": context_body["legacy_checksum"],
            },
            headers=_mutation_headers(),
        )
        assert apply_response.status_code == 200, apply_response.text
        apply_body = apply_response.json()
        assert apply_body["context_id"] == context_id
        assert apply_body["approval_id"] == approval_id
        assert apply_body["repair_action"]["status"] == "applied"
        assert apply_body["repair_action"]["verification_status"] == "passed"
        assert apply_body["repair_action"]["verification_build_status"] == "BUILD_PASSED_IN_SANDBOX"
        assert apply_body["repair_action"]["verification_test_status"] == "TEST_PASSED"
        assert apply_body["repair_action"]["sandbox_only"] is True
        assert apply_body["repair_action"]["source_mutated"] is False
        assert apply_body["repair_action"]["llm_invoked"] is False

    def test_governed_repair_workflow_dry_run_end_to_end(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        output_root = tmp_path / "out"
        setup_id = _ready_setup_with_output_root(conn, str(output_root))
        _seed_migration_intelligence_artifacts(output_root)
        job_id = "job-e2e"
        run_id = "run-e2e-1"
        run_dir = Path(tmp_path / "out" / ".migration" / "runs" / run_id)
        sandbox_dir = run_dir / "sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        v2_job_repo = SqliteV2JobRepository(conn)
        v2_job_repo.save(
            V2MigrationJobRecord(
                job_id=job_id,
                setup_id=setup_id,
                setup_checksum="setup-chk",
                pipeline_id="pipeline-1",
                stage_chain_json="[]",
                status="created",
                created_at="2026-06-18T00:00:00Z",
                updated_at="2026-06-18T00:00:00Z",
                correlation_id=None,
            )
        )
        command_id = "cmd-e2e"
        SqliteV2CommandRepository(conn).save(
            V2StageCommandRecord(
                command_id=command_id,
                job_id=job_id,
                stage_index=3,
                manifest_checksum="manifest-e2e",
                argv_json="[]",
                env_json="{}",
                status="failed",
                created_at="2026-06-18T00:00:00Z",
                updated_at="2026-06-18T00:00:00Z",
                result_json=json.dumps(
                    {
                        "run_id": run_id,
                        "sandbox_path": str(sandbox_dir),
                        "modernized_app_path": str(tmp_path / "out"),
                    }
                ),
                gate_id=None,
                decision_id=None,
            )
        )
        _create_gate_with_refs(
            conn,
            job_id,
            refs=(
                "runtime_contract.json",
                "reference_delta.json",
                "post_transform_failure_classification.json",
            ),
            phase="approval_review",
            stage_index=3,
        )

        repair_client = _RecordingGovernedRepairClient()
        client.app.state.v2_assistant_model_client = repair_client

        ask_response = client.post(
            f"/v1/v2/jobs/{job_id}/assistant/ask",
            json={"question": "solve this"},
            headers=_mutation_headers(),
        )
        assert ask_response.status_code == 200, ask_response.text
        ask_body = ask_response.json()
        assert ask_body["intent"] == "solve_failure"
        assert ask_body["executed"] is False
        assert ask_body["repair_proposal"] is not None
        proposal = ask_body["repair_proposal"]
        assert proposal["status"] == "draft"
        assert proposal["proposal_id"]
        assert proposal["proposal_checksum"]
        assert ask_body["proposal_model"]["role"] == "proposer"
        assert ask_body["reviewer_model"]["role"] == "reviewer"
        assert ask_body["governance"]["human_approval_required"] is True
        assert ask_body["governance"]["no_auto_apply"] is True
        assert ask_body["governance"]["sandbox_only"] is True
        assert ask_body["governance"]["source_mutated"] is False
        assert ask_body["governance"]["stage_resumed"] is False
        assert ask_body["governance"]["reviewer_required"] is True
        assert ask_body["migration_intelligence"]["runtime_contract"]["status"] == "generated"
        assert ask_body["migration_intelligence"]["reference_delta"]["status"] == "generated"
        assert ask_body["migration_intelligence"]["post_transform_failure_classification"]["status"] == "generated"
        assert ask_body["migration_intelligence_warnings"] == []
        assert repair_client.roles == ["proposer", "reviewer"]
        assert "Human approval required" in ask_body["assistant_message"]["content"]
        assert "No auto apply" in ask_body["assistant_message"]["content"]
        assert "Sandbox only" in ask_body["assistant_message"]["content"]

        proposal_id = proposal["proposal_id"]
        proposal_checksum = proposal["proposal_checksum"]
        approval_proposal_checksum = ask_body["repair_context"]["context_pack_checksum"]
        review_context_pack_checksum = ask_body["repair_context"]["review_context_pack_checksum"]
        run_dir = _seed_repair_apply_context(
            conn,
            tmp_path,
            job_id=job_id,
            proposal_id=proposal_id,
            proposal_checksum=proposal_checksum,
            command_id=command_id,
            create_job_row=False,
            create_command_row=False,
            run_id=run_id,
        )
        from migration_factory.control_tower.application.v2_reviewer_service import (
            V2ReviewerService,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
            SqliteV2ReviewerRepository,
        )

        reviewer_repo = SqliteV2ReviewerRepository(conn)
        reviewer_service = V2ReviewerService(reviewer_repo=reviewer_repo)
        reviewer_service.record_critique(
            proposal_id=proposal_id,
            proposal_type="repair",
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
            decision="accept",
            reasoning="Dry run approved.",
            missing_evidence=(),
            unsafe_assumptions=(),
        )

        approve_response = client.post(
            f"/v1/v2/commands/{command_id}/repair/proposal/{proposal_id}/prepare-apply-context",
            json={
                "proposal_checksum": "pc-test",
                "context_pack_checksum": "cp-test",
                "reviewer_critique_id": reviewer_service.check_reviewer_gate(
                    proposal_id=proposal_id,
                    proposal_checksum="pc-test",
                    context_pack_checksum="cp-test",
                ).critique_id,
                "proposer_invocation_id": "proposer-invoke-1",
                "reviewer_invocation_id": "reviewer-invoke-1",
            },
            headers=_mutation_headers(),
        )
        assert approve_response.status_code == 200, approve_response.text
        approve_body = approve_response.json()
        assert approve_body["repair_review_context"]["proposal_id"] == proposal_id
        assert approve_body["repair_review_context"]["approval_eligible"] is True
        assert approve_body["repair_review_context"]["sandbox_only"] is True
        assert (run_dir / "repairs" / "patch_draft_1.json").is_file()

        context_id = approve_body["repair_review_context"]["context_id"]
        repeat_response = client.post(
            f"/v1/v2/repair-review/{context_id}/approve",
            json={
                "approval_checksum": "chk-end-to-end",
                "approval_note": "Human approval recorded for sandbox-only apply later.",
                "approval_scope": "sandbox_only",
            },
            headers=_mutation_headers(),
        )
        assert repeat_response.status_code == 200, repeat_response.text
        repeat_body = repeat_response.json()
        assert repeat_body["approval"]["approval_status"] == "recorded"
        assert repeat_body["approval"]["approval_scope"] == "sandbox_only"

    def test_governed_repair_workflow_dry_run_with_real_local_project_fixture(
        self,
        tmp_path: Path,
    ) -> None:
        client, conn = _api_client(tmp_path)
        output_root = tmp_path / "out"
        _seed_migration_intelligence_artifacts(output_root)
        job_id = "job-real"
        run_id = "run-real-1"
        command_id = "cmd-real"

        run_dir, legacy_root, sandbox_root, source_fixture = _seed_real_local_project_repair_apply_context(
            conn,
            tmp_path,
            job_id=job_id,
            command_id=command_id,
            run_id=run_id,
        )
        _create_gate_with_refs(
            conn,
            job_id,
            refs=(
                "runtime_contract.json",
                "reference_delta.json",
                "post_transform_failure_classification.json",
            ),
            phase="approval_review",
            stage_index=3,
        )
        source_fixture_snapshot_before = _snapshot_directory(source_fixture)
        legacy_snapshot_before = _snapshot_directory(legacy_root)
        sandbox_snapshot_before = _snapshot_directory(sandbox_root)
        target_rel_path = "src/test/java/com/total/corp/advice/App.java"
        legacy_file_before = (legacy_root / target_rel_path).read_text(encoding="utf-8")
        source_file_before = (source_fixture / target_rel_path).read_text(encoding="utf-8")

        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
        )

        class _RealLocalProjectGovernedRepairClient:
            def __init__(self) -> None:
                self.roles: list[str] = []
                self.prompts: list[str] = []

            def answer_with_role(
                self,
                *,
                role,
                prompt: str,
                fallback: str,
                conversation_history=None,
                output_schema_name=None,
                require_schema: bool = False,
            ):
                self.roles.append(role.value)
                self.prompts.append(prompt)
                if role == V2ModelRole.PROPOSER:
                    content = json.dumps({
                        "failure_hypothesis": "Legacy javax imports should move to jakarta.",
                        "patch_summary": "Prepare a sandbox-only import update from deterministic evidence.",
                        "affected_paths": [target_rel_path],
                        "validation_plan": "Review the evidence, then validate in sandbox after human approval.",
                    })
                    summary = "Proposer reply"
                else:
                    content = json.dumps({
                        "decision": "accept",
                        "reasoning": "Proposal is bounded, evidence-backed, and sandbox-only.",
                        "missing_evidence": [],
                        "unsafe_assumptions": [],
                    })
                    summary = "Reviewer reply"
                return V2AssistantModelResult(
                    content=content,
                    source="azure_openai",
                    model_status="live_ok",
                    provider="azure_openai",
                    role=role.value,
                    success=True,
                    redacted_summary=summary,
                    failure_reason="",
                )

            def answer(
                self,
                *,
                prompt: str,
                fallback: str,
                conversation_history: list[dict[str, str]] | None = None,
            ):
                return self.answer_with_role(
                    role=V2ModelRole.PROPOSER,
                    prompt=prompt,
                    fallback=fallback,
                    conversation_history=conversation_history,
                )

        repair_client = _RealLocalProjectGovernedRepairClient()
        client.app.state.v2_assistant_model_client = repair_client

        ask_response = client.post(
            f"/v1/v2/jobs/{job_id}/assistant/ask",
            json={"question": "solve this"},
            headers=_mutation_headers(),
        )
        assert ask_response.status_code == 200, ask_response.text
        ask_body = ask_response.json()
        assert ask_body["intent"] == "solve_failure"
        assert ask_body["repair_proposal"] is not None
        proposal = ask_body["repair_proposal"]
        proposal_id = proposal["proposal_id"]
        proposal_checksum = proposal["proposal_checksum"]
        review_context_pack_checksum = ask_body["repair_context"]["review_context_pack_checksum"]
        assert ask_body["proposal_model"]["role"] == "proposer"
        assert ask_body["reviewer_model"]["role"] == "reviewer"
        assert ask_body["governance"]["human_approval_required"] is True
        assert ask_body["governance"]["no_auto_apply"] is True
        assert ask_body["governance"]["sandbox_only"] is True
        assert ask_body["governance"]["source_mutated"] is False
        assert ask_body["governance"]["stage_resumed"] is False
        assert ask_body["governance"]["reviewer_required"] is True
        assert ask_body["migration_intelligence"]["runtime_contract"]["status"] == "generated"
        assert ask_body["migration_intelligence"]["reference_delta"]["status"] == "generated"
        assert ask_body["migration_intelligence"]["post_transform_failure_classification"]["status"] == "generated"
        assert repair_client.roles == ["proposer", "reviewer"]
        assert "Human approval required" in ask_body["assistant_message"]["content"]
        assert "No auto apply" in ask_body["assistant_message"]["content"]
        assert "Sandbox only" in ask_body["assistant_message"]["content"]

        draft_path = run_dir / "repairs" / "patch_draft_1.json"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "proposal_id": proposal_id,
                    "repair_proposal_checksum": proposal_checksum,
                    "target_path": target_rel_path,
                    "deterministic_rule_id": "JAKARTA_IMPORT_MECHANICAL_SOURCE",
                    "risk": "LOW",
                    "requires_human_review": False,
                    "binding_checksum": "binding-1",
                    "h2_required": False,
                    "unified_diff": _real_java_import_patch(legacy_file_before, rel_path=target_rel_path),
                    "expected_validation": ["mvn test"],
                    "limitations": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        from migration_factory.control_tower.application.v2_reviewer_service import (
            V2ReviewerService,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
            SqliteV2ReviewerRepository,
        )

        reviewer_repo = SqliteV2ReviewerRepository(conn)
        reviewer_service = V2ReviewerService(reviewer_repo=reviewer_repo)
        reviewer_service.record_critique(
            proposal_id=proposal_id,
            proposal_type="repair",
            proposal_checksum=proposal_checksum,
            context_pack_checksum=review_context_pack_checksum,
            decision="accept",
            reasoning="Dry run approved for copied local fixture.",
            missing_evidence=(),
            unsafe_assumptions=(),
            model_invocation_id="reviewer-invoke-1",
        )

        approve_response = client.post(
            f"/v1/v2/commands/{command_id}/repair/proposal/{proposal_id}/prepare-apply-context",
            json={
                "proposal_checksum": proposal_checksum,
                "context_pack_checksum": review_context_pack_checksum,
                "reviewer_critique_id": reviewer_service.check_reviewer_gate(
                    proposal_id=proposal_id,
                    proposal_checksum=proposal_checksum,
                    context_pack_checksum=review_context_pack_checksum,
                ).critique_id,
                "proposer_invocation_id": "proposer-invoke-1",
                "reviewer_invocation_id": "reviewer-invoke-1",
            },
            headers=_mutation_headers(),
        )
        assert approve_response.status_code == 200, approve_response.text
        approve_body = approve_response.json()
        assert approve_body["repair_review_context"]["proposal_id"] == proposal_id
        assert approve_body["repair_review_context"]["approval_eligible"] is True
        verification_artifact_refs = approve_body["repair_review_context"]["evidence_refs"]
        assert legacy_snapshot_before == _snapshot_directory(legacy_root)
        assert source_fixture_snapshot_before == _snapshot_directory(source_fixture)
        assert legacy_file_before == (legacy_root / target_rel_path).read_text(encoding="utf-8")
        assert source_file_before == (source_fixture / target_rel_path).read_text(encoding="utf-8")
        assert sandbox_snapshot_before == _snapshot_directory(sandbox_root)

        context_id = approve_body["repair_review_context"]["context_id"]
        repeat_response = client.post(
            f"/v1/v2/repair-review/{context_id}/approve",
            json={
                "approval_checksum": "chk-real",
                "approval_note": "Human approval recorded for sandbox-only apply later.",
                "approval_scope": "sandbox_only",
            },
            headers=_mutation_headers(),
        )
        assert repeat_response.status_code == 200, repeat_response.text
        repeat_body = repeat_response.json()
        assert repeat_body["approval"]["approval_status"] == "recorded"
        assert repeat_body["approval"]["approval_scope"] == "sandbox_only"
        assert repeat_body["repair_review_context"]["evidence_refs"] == verification_artifact_refs
        assert sandbox_snapshot_before == _snapshot_directory(sandbox_root)
        assert legacy_snapshot_before == _snapshot_directory(legacy_root)

    def test_combined_approve_apply_route_is_blocked(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-3/repair/proposal/nonexistent/approve",
            json={
                "approval_checksum": "chk",
                "proposal_checksum": "pc",
                "context_pack_checksum": "cp",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 410
        assert "LEGACY_REPAIR_APPROVAL_DISABLED" in response.text
        assert "REPAIR_APPROVE_APPLY_DISABLED" in response.text

    def test_prepare_apply_context_fails_without_durable_command_binding(
        self,
        tmp_path: Path,
    ) -> None:
        client, conn = _api_client(tmp_path)
        create_response = client.post(
            "/v1/v2/commands/cmd-orphan/repair/flow-proposal",
            json={
                "command_id": "cmd-orphan",
                "failure_summary": "Orphan command",
                "hypothesis": "No durable command row",
                "patch_summary": "Do not prepare apply context",
                "affected_paths": ["pom.xml"],
            },
            headers=_mutation_headers(),
        )
        assert create_response.status_code == 200, create_response.text
        proposal = create_response.json()

        from migration_factory.control_tower.application.v2_reviewer_service import (
            V2ReviewerService,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
            SqliteV2ReviewerRepository,
        )

        reviewer_service = V2ReviewerService(
            reviewer_repo=SqliteV2ReviewerRepository(conn)
        )
        reviewer_service.record_critique(
            proposal_id=proposal["proposal_id"],
            proposal_type="repair",
            proposal_checksum=proposal["proposal_checksum"],
            context_pack_checksum="cp-orphan",
            decision="accept",
            reasoning="Technically accepted but not command-bound.",
            missing_evidence=(),
            unsafe_assumptions=(),
        )
        critique_id = reviewer_service.check_reviewer_gate(
            proposal_id=proposal["proposal_id"],
            proposal_checksum=proposal["proposal_checksum"],
            context_pack_checksum="cp-orphan",
        ).critique_id

        response = client.post(
            f"/v1/v2/commands/cmd-orphan/repair/proposal/{proposal['proposal_id']}/prepare-apply-context",
            json={
                "proposal_checksum": proposal["proposal_checksum"],
                "context_pack_checksum": "cp-orphan",
                "reviewer_critique_id": critique_id,
                "proposer_invocation_id": "proposer-invoke-1",
                "reviewer_invocation_id": "reviewer-invoke-1",
            },
            headers=_mutation_headers(),
        )

        assert response.status_code == 400
        assert "REPAIR_CONTEXT_BINDING_FAILED" in response.text
        assert "Command 'cmd-orphan' not found" in response.text

    def test_proposal_persistence(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        proposal = _seed_repair_proposal(
            conn,
            command_id="cmd-persist",
            failure_summary="Persist test",
            hypothesis="Check persistence",
            patch_summary="Verify",
            affected_paths=("test.txt",),
        )
        proposal_id = proposal.proposal_id

        # Verify in DB
        db_path = tmp_path / "assistant_repair_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        repo = SqliteV2RepairRepository(conn2)
        loaded = repo.get_proposal(proposal_id)
        assert loaded is not None
        assert loaded.failure_summary == "Persist test"
        conn2.close()


# ── Schema validation rejection tests ───────────────────────────────


class TestSchemaValidationRejection:
    """Prove that invalid model-output-like payloads are rejected at the API."""

    def test_draft_action_rejects_extra_field(self, tmp_path: Path) -> None:
        """ActionRequest schema has additionalProperties: false.

        Extra fields are rejected either by Pydantic (INVALID_REQUEST) or
        by the schema validator (SCHEMA_VALIDATION_FAILED). Both are valid
        closed-fail behaviors.
        """
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "diagnose_failure",
                "reason": "test",
                "stage_index": 1,
                "extra_field": "should be rejected",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, f"Expected 422 for extra field, got {response.status_code}"
        body = response.json()
        err = str(body).lower()
        assert any(term in err for term in [
            "invalid_request",
            "schema_validation_failed",
            "unexpected property",
            "did not match",
        ]), f"Expected rejection message, got {body}"

    def test_draft_action_rejects_invalid_stage_index(self, tmp_path: Path) -> None:
        """ActionRequest stage_index must be 1-3."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "diagnose_failure",
                "reason": "test",
                "stage_index": 99,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, f"Expected 422 for invalid stage, got {response.status_code}"

    def test_draft_action_rejects_missing_required(self, tmp_path: Path) -> None:
        """ActionRequest requires action_type, reason, stage_index, payload_checksum."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "diagnose_failure",
                "stage_index": 1,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_repair_proposal_rejects_extra_field(self, tmp_path: Path) -> None:
        """Legacy repair proposal route is disabled before any model/schema path."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-extra/repair/flow-proposal",
            json={
                "command_id": "cmd-extra",
                "failure_summary": "Test",
                "hypothesis": "Bug",
                "patch_summary": "Fix",
                "affected_paths": ["test.txt"],
                "unauthorized_field": "should be rejected",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code in (410, 422)

    def test_repair_proposal_rejects_missing_required(self, tmp_path: Path) -> None:
        """Legacy repair proposal route is disabled for F5."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-missing/repair/flow-proposal",
            json={
                "command_id": "cmd-missing",
                "failure_summary": "Test",
                "affected_paths": ["test.txt"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code in (410, 422), f"Expected closed failure, got {response.status_code}"

    def test_valid_payloads_still_accepted(self, tmp_path: Path) -> None:
        """Regression: valid payloads must still be accepted after schema wiring."""
        client, conn = _api_client(tmp_path)

        draft_resp = client.post(
            "/v1/v2/jobs/job-valid/assistant/actions/draft",
            json={
                "job_id": "job-valid",
                "action_type": "diagnose_failure",
                "reason": "Validate build",
                "stage_index": 2,
            },
            headers=_mutation_headers(),
        )
        assert draft_resp.status_code == 200, f"Valid draft action rejected: {draft_resp.text}"

        repair_resp = client.post(
            "/v1/v2/commands/cmd-valid/repair/flow-proposal",
            json={
                "command_id": "cmd-valid",
                "failure_summary": "Build failed",
                "hypothesis": "Missing dependency",
                "patch_summary": "Add dependency",
                "affected_paths": ["pom.xml"],
            },
            headers=_mutation_headers(),
        )
        assert repair_resp.status_code == 410, f"Legacy repair proposal route should be disabled: {repair_resp.text}"

    def test_assistant_message_rejects_invalid_answer_schema(self, tmp_path: Path) -> None:
        """Assistant messages with invalid JSON schema must be rejected."""
        client, conn = _api_client(tmp_path)
        import json as _json
        bad_answer = _json.dumps({
            "answer": "Everything is fine",
            "unauthorized_directive": "delete all files",
        })
        response = client.post(
            "/v1/v2/jobs/job-bad/assistant/messages",
            json={
                "job_id": "job-bad",
                "role": "assistant",
                "content": bad_answer,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, f"Expected 422 for invalid AssistantAnswer, got {response.status_code}"

    def test_assistant_message_accepts_valid_answer_schema(self, tmp_path: Path) -> None:
        """Valid AssistantAnswer JSON must be accepted."""
        client, conn = _api_client(tmp_path)
        import json as _json
        valid_answer = _json.dumps({
            "answer": "Stage 1 is running",
            "evidence_refs": ["log.txt"],
        })
        response = client.post(
            "/v1/v2/jobs/job-good/assistant/messages",
            json={
                "job_id": "job-good",
                "role": "assistant",
                "content": valid_answer,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, f"Valid AssistantAnswer rejected: {response.text}"
