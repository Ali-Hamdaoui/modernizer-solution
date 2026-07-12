from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from migration_factory.control_tower.application.v2_final_report_service import (
    V2FinalReportService,
)
from migration_factory.control_tower.application.v2_migration_report import (
    build_detailed_migration_report,
    render_detailed_report_markdown,
)
from migration_factory.control_tower.domain.errors import StorageIntegrityError


class _Repository:
    def __init__(self, records=()):
        self.records = list(records)

    def list_by_job(self, job_id: str):
        return tuple(record for record in self.records if getattr(record, "job_id", job_id) == job_id)

    def list_by_job_and_stage(self, job_id: str, stage_index: int):
        return tuple(
            record
            for record in reversed(self.records)
            if record.job_id == job_id and record.stage_index == stage_index
        )

    def list_for_job(self, job_id: str):
        return tuple(record for record in self.records if record.job_id == job_id)

    def insert(self, record) -> None:
        self.records.append(record)


class _FailingArtifactRepository(_Repository):
    def insert(self, record) -> None:
        raise StorageIntegrityError("FOREIGN KEY constraint failed")


class _ReportModel:
    def answer(self, *, prompt: str, fallback: str):
        assert "Spring Boot 2.5 / Java 11" in prompt
        assert "Spring Boot 3.5 / Java 21" in prompt
        assert "Stage 4" not in prompt
        return SimpleNamespace(
            content=(
                "The migration followed the two selected stages. Stage 2 upgraded the "
                "framework and Stage 3 completed the Java runtime transition."
            ),
            success=True,
            model_status="live_ok",
        )


class _AnyRouteReportModel:
    def answer(self, *, prompt: str, fallback: str):
        return SimpleNamespace(
            content="The migration completed with evidence-backed metrics.",
            success=True,
            model_status="live_ok",
        )

class _Uow:
    def __init__(
        self,
        *,
        tmp_path: Path,
        commands: list[SimpleNamespace],
        events: list[SimpleNamespace],
        source_profile: str = "springboot-2.7-java11",
        target_profile: str = "springboot-3.5-java21",
    ) -> None:
        self.job = SimpleNamespace(
            job_id="job-report",
            setup_id="setup-report",
            setup_checksum="setup-checksum",
            stage_chain_json="[]",
            created_at="2026-07-09T10:00:00Z",
        )
        self.v2_jobs = SimpleNamespace(get=lambda job_id: self.job if job_id == self.job.job_id else None)
        self.v2_commands = _Repository(commands)
        self.v2_events = _Repository(events)
        self.run_configurations = SimpleNamespace(
            get_for_job=lambda job_id: SimpleNamespace(
                payload_json=json.dumps({
                    "source_profile": source_profile,
                    "target_profile": target_profile,
                })
            )
        )
        self.v2_setups = SimpleNamespace(
            get=lambda setup_id: SimpleNamespace(legacy_app_path=str(tmp_path / "source"))
        )
        self.phase_gates = SimpleNamespace(list_open=lambda job_id: ())
        self.artifact_revisions = SimpleNamespace(find_accepted=lambda job_id, stage, kind: None)
        self.artifacts = _Repository()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


def _result(path: Path, *, total_run: float, added: int, deleted: int) -> str:
    return json.dumps({
        "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        "orchestration_status": "PASS",
        "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        "build_status": "BUILD_PASSED_IN_SANDBOX",
        "test_status": "TEST_PASSED",
        "final_proof_level": "build_test_verified",
        "sandbox_path": str(path),
        "source_stack": {"spring_boot": "2.5", "java": "11"},
        "target_stack": {"spring_boot": "3.5", "java": "21"},
        "change_metrics": {
            "files_changed": 2,
            "lines_added": added,
            "lines_deleted": deleted,
        },
        "test_totals": {
            "tests": 12,
            "passed": 12,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        },
        "timing": {
            "phase_durations_seconds": {
                "analysis": 1.5,
                "sandbox_transform": 2.5,
                "total_run": total_run,
            }
        },
    })


def _evidence(tmp_path: Path) -> tuple[_Uow, Path]:
    source = tmp_path / "source"
    stage2 = tmp_path / "stage2"
    stage3 = tmp_path / "stage3"
    source.mkdir()
    stage2.mkdir()
    stage3.mkdir()
    (source / "App.java").write_text("class App {}\n", encoding="utf-8")
    (stage2 / "App.java").write_text("class App {\n  int value;\n}\n", encoding="utf-8")
    (stage3 / "App.java").write_text("class App {\n  long value;\n}\n", encoding="utf-8")

    commands = [
        SimpleNamespace(
            command_id="command-stage-2",
            job_id="job-report",
            stage_index=2,
            status="completed",
            created_at="2026-07-09T10:00:05Z",
            updated_at="2026-07-09T10:00:45Z",
            result_json=_result(stage2, total_run=40.0, added=8, deleted=3),
        ),
        SimpleNamespace(
            command_id="command-stage-3",
            job_id="job-report",
            stage_index=3,
            status="completed",
            created_at="2026-07-09T10:01:00Z",
            updated_at="2026-07-09T10:01:30Z",
            result_json=_result(stage3, total_run=30.0, added=4, deleted=2),
        ),
    ]
    events = [
        SimpleNamespace(
            event_id="event-1",
            job_id="job-report",
            stage=2,
            type="stage_started",
            status="running",
            message="Stage 2 started.",
            created_at="2026-07-09T10:00:05Z",
        ),
        SimpleNamespace(
            event_id="event-2",
            job_id="job-report",
            stage=2,
            type="stage_completed",
            status="completed",
            message="Stage 2 completed.",
            created_at="2026-07-09T10:00:45Z",
        ),
        SimpleNamespace(
            event_id="event-3",
            job_id="job-report",
            stage=3,
            type="stage_started",
            status="running",
            message="Stage 3 started.",
            created_at="2026-07-09T10:01:00Z",
        ),
        SimpleNamespace(
            event_id="event-4",
            job_id="job-report",
            stage=3,
            type="migration_completed",
            status="completed",
            message="Selected migration route completed.",
            created_at="2026-07-09T10:01:30Z",
        ),
    ]
    return _Uow(tmp_path=tmp_path, commands=commands, events=events), stage3


def test_report_uses_only_selected_profile_route_and_aggregates_stage_facts(tmp_path: Path) -> None:
    uow, _ = _evidence(tmp_path)

    report = build_detailed_migration_report(
        uow=uow,
        job=uow.job,
        model_client=_ReportModel(),
    )

    assert report["migration_scope"]["included_stages"] == [2, 3]
    assert report["migration_scope"]["excluded_stages"] == [4]
    assert report["summary"]["source"] == "Spring Boot 2.5 / Java 11"
    assert report["summary"]["target"] == "Spring Boot 3.5 / Java 21"
    assert report["summary"]["duration_seconds"] == 90.0
    assert report["summary"]["lines_added"] == 12
    assert report["summary"]["lines_deleted"] == 5
    assert report["summary"]["lines_changed"] == 17
    assert report["summary"]["tests"] == 24
    assert [stage["stage_index"] for stage in report["stages"]] == [2, 3]
    assert report["narrative_generation"]["source"] == "azure_openai"

    markdown = render_detailed_report_markdown(report)
    assert "## Executive Summary" in markdown
    assert "## Migration Story" in markdown
    assert "## Stage-by-Stage Technical Details" in markdown
    assert "Stage 4:" not in markdown
    assert str(tmp_path) not in markdown


def test_report_metrics_fall_back_to_sandbox_event_when_command_result_has_no_metrics(tmp_path: Path) -> None:
    source = tmp_path / "source"
    sandbox = tmp_path / "source" / ".migration" / "runs" / "v2-job" / "workspaces" / "sandbox"
    source.mkdir(parents=True)
    sandbox.mkdir(parents=True)
    (source / "pom.xml").write_text(
        "<project>\n  <spring.boot.version>2.1.0</spring.boot.version>\n</project>\n",
        encoding="utf-8",
    )
    (source / "App.java").write_text("class App {}\n", encoding="utf-8")
    (sandbox / "pom.xml").write_text(
        "<project>\n  <spring.boot.version>2.7.18</spring.boot.version>\n</project>\n",
        encoding="utf-8",
    )
    (sandbox / "App.java").write_text("class App {\n  String version = \"2.7\";\n}\n", encoding="utf-8")
    (sandbox / "NewConfig.java").write_text("class NewConfig {}\n", encoding="utf-8")

    command = SimpleNamespace(
        command_id="command-stage-1",
        job_id="job-report",
        stage_index=1,
        status="manifest_ready",
        created_at="2026-07-09T10:00:05Z",
        updated_at="2026-07-09T10:00:45Z",
        result_json=None,
    )
    events = [
        SimpleNamespace(
            event_id="event-stage-1-completed",
            job_id="job-report",
            stage=1,
            type="stage_completed",
            status="completed",
            message="Stage 1 completed.",
            payload={"sandbox_path": str(sandbox)},
            created_at="2026-07-09T10:00:45Z",
        )
    ]
    uow = _Uow(
        tmp_path=tmp_path,
        commands=[command],
        events=events,
        source_profile="springboot-2.1-java11",
        target_profile="springboot-2.7-java11",
    )

    report = build_detailed_migration_report(
        uow=uow,
        job=uow.job,
        model_client=_AnyRouteReportModel(),
    )

    assert report["summary"]["files_changed"] == 3
    assert report["summary"]["lines_added"] > 0
    assert report["summary"]["lines_deleted"] > 0
    assert report["summary"]["lines_changed"] == (
        report["summary"]["lines_added"] + report["summary"]["lines_deleted"]
    )
    assert report["stages"][0]["change_metrics"]["source"] == "source_tree_comparison"

def test_report_metrics_ignore_next_stage_queued_input_path_as_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    prior_stage_sandbox = tmp_path / "stage1"
    source.mkdir()
    prior_stage_sandbox.mkdir()
    (source / "App.java").write_text("class App {}\n", encoding="utf-8")
    (prior_stage_sandbox / "App.java").write_text("class App {}\n", encoding="utf-8")

    command = SimpleNamespace(
        command_id="command-stage-2",
        job_id="job-report",
        stage_index=2,
        status="manifest_ready",
        created_at="2026-07-09T10:00:05Z",
        updated_at="2026-07-09T10:00:45Z",
        result_json=None,
    )
    events = [
        SimpleNamespace(
            event_id="event-next-stage-queued",
            job_id="job-report",
            stage=2,
            type="next_stage_queued",
            status="queued",
            message="Stage 2 queued from prior stage output.",
            payload={"sandbox_path": str(prior_stage_sandbox)},
            created_at="2026-07-09T10:00:45Z",
        )
    ]
    uow = _Uow(
        tmp_path=tmp_path,
        commands=[command],
        events=events,
        source_profile="springboot-2.7-java11",
        target_profile="springboot-3.5-java21",
    )

    report = build_detailed_migration_report(
        uow=uow,
        job=uow.job,
        model_client=_AnyRouteReportModel(),
    )

    assert report["summary"]["files_changed"] == 0
    assert report["stages"][0]["change_metrics"]["source"] == "not_captured"

def test_service_eligibility_targets_route_terminal_stage_not_stage_four(tmp_path: Path) -> None:
    uow, _ = _evidence(tmp_path)
    service = V2FinalReportService(lambda: uow, model_client=_ReportModel())

    eligibility = service._evaluate_eligibility(uow, uow.job.job_id, job=uow.job)

    assert eligibility.eligible is True
    assert eligibility.blockers == []


def test_service_eligibility_allows_completed_one_step_route_without_artifacts(tmp_path: Path) -> None:
    command = SimpleNamespace(
        command_id="command-stage-4",
        job_id="job-report",
        stage_index=4,
        status="completed",
        created_at="2026-07-09T10:00:05Z",
        updated_at="2026-07-09T10:00:45Z",
        result_json=None,
    )
    events = [
        SimpleNamespace(
            event_id="event-stage-4-started",
            job_id="job-report",
            stage=4,
            type="stage_started",
            status="running",
            message="Stage 4 started.",
            created_at="2026-07-09T10:00:05Z",
        ),
        SimpleNamespace(
            event_id="event-route-completed",
            job_id="job-report",
            stage=4,
            type="migration_completed",
            status="completed",
            message="Selected migration route completed.",
            payload={"from_stage": 4, "to_stage": None, "reason": "migration_completed"},
            created_at="2026-07-09T10:00:45Z",
        ),
    ]
    uow = _Uow(
        tmp_path=tmp_path,
        commands=[command],
        events=events,
        source_profile="springboot-3.5-java21",
        target_profile="springboot-4.0-java21",
    )
    service = V2FinalReportService(lambda: uow, model_client=_ReportModel())

    eligibility = service._evaluate_eligibility(uow, uow.job.job_id, job=uow.job)

    assert eligibility.eligible is True
    assert eligibility.blockers == []


def test_service_blocks_report_when_an_earlier_included_stage_is_missing(tmp_path: Path) -> None:
    uow, _ = _evidence(tmp_path)
    uow.v2_commands.records = [
        command for command in uow.v2_commands.records if command.stage_index == 3
    ]
    uow.v2_events.records = [
        event for event in uow.v2_events.records if event.stage != 2
    ]
    service = V2FinalReportService(lambda: uow, model_client=_ReportModel())

    eligibility = service._evaluate_eligibility(uow, uow.job.job_id, job=uow.job)

    assert eligibility.eligible is False
    assert "Stage 2 has not been started yet." in eligibility.blockers


def test_legacy_report_artifacts_do_not_block_detailed_report_generation(tmp_path: Path) -> None:
    uow, _ = _evidence(tmp_path)
    uow.artifacts.records.append(SimpleNamespace(
        artifact_id="legacy-report",
        job_id=uow.job.job_id,
        artifact_type="final_report_pdf",
        normalized_relative_path=f"reports/{uow.job.job_id}/final_report_pdf",
        checksum="legacy-checksum",
        size_bytes=10,
        content_type="application/pdf",
        created_at="2026-07-08T00:00:00Z",
    ))
    service = V2FinalReportService(lambda: uow, model_client=_ReportModel())

    status = service.get_report_status(uow.job.job_id)

    assert status.status == "not_generated"
    assert status.eligible is True
    assert status.artifacts == ()


def test_service_generates_json_markdown_and_downloadable_pdf(tmp_path: Path) -> None:
    uow, terminal_path = _evidence(tmp_path)
    service = V2FinalReportService(lambda: uow, model_client=_ReportModel())

    result = service.generate_report(uow.job.job_id)

    assert result.status == "generated"
    assert result.eligible is True
    assert {artifact.kind for artifact in result.artifacts} == {
        "final_report_json",
        "final_report_markdown",
        "final_report_pdf",
    }
    pdf = next(record for record in uow.artifacts.records if record.artifact_type == "final_report_pdf")
    pdf_path = Path(pdf.relative_path)
    assert pdf_path == terminal_path / "final" / "detailed_migration_report_v2.pdf"
    assert pdf_path.read_bytes().startswith(b"%PDF-1.4")


def test_service_returns_file_backed_artifacts_when_legacy_artifact_fk_fails(tmp_path: Path) -> None:
    uow, terminal_path = _evidence(tmp_path)
    uow.artifacts = _FailingArtifactRepository()
    service = V2FinalReportService(lambda: uow, model_client=_ReportModel())

    result = service.generate_report(uow.job.job_id)

    assert result.status == "generated"
    assert result.eligible is True
    assert {artifact.kind for artifact in result.artifacts} == {
        "final_report_json",
        "final_report_markdown",
        "final_report_pdf",
    }
    pdf = next(artifact for artifact in result.artifacts if artifact.kind == "final_report_pdf")
    assert pdf.artifact_id.startswith("report-final_report_pdf-")

    status = service.get_report_status(uow.job.job_id)
    resolved = service.resolve_report_artifact(uow.job.job_id, pdf.artifact_id)

    assert status.status == "generated"
    assert {artifact.artifact_id for artifact in status.artifacts} == {
        artifact.artifact_id for artifact in result.artifacts
    }
    assert resolved.file_path == terminal_path / "final" / "detailed_migration_report_v2.pdf"
    assert resolved.checksum_sha256 == pdf.checksum_sha256
    assert resolved.file_path.read_bytes().startswith(b"%PDF-1.4")
