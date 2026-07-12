from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.application.v2_migration_report import (
    build_detailed_migration_report,
    render_detailed_report_markdown,
    included_stages_for_job,
    terminal_stage_for_job,
)
from migration_factory.control_tower.application.v2_stage_progression import (
    TERMINAL_STAGE_INDEX,
)
from migration_factory.control_tower.domain.entities import ArtifactRecord
from migration_factory.control_tower.domain.errors import StorageIntegrityError
from migration_factory.final_report.pdf_writer import write_text_pdf_from_markdown

UnitOfWorkFactory = Callable[[], Any]

REPORT_ARTIFACT_KINDS = frozenset({
    "final_report_json",
    "final_report_markdown",
    "final_report_pdf",
})

REPORT_CONTENT_TYPES = {
    "final_report_json": "application/json",
    "final_report_markdown": "text/markdown",
    "final_report_pdf": "application/pdf",
}

_ARTIFACT_CREATED_BY = "v2-final-report-service"
_REPORT_FORMAT_MARKER = "v2-detailed"


@dataclass(frozen=True)
class V2ReportArtifactSummary:
    artifact_id: str
    kind: str
    checksum_sha256: str
    size_bytes: int
    content_type: str
    download_url: str


@dataclass(frozen=True)
class V2FinalReportEligibility:
    eligible: bool
    blockers: list[str]


@dataclass(frozen=True)
class V2FinalReportResult:
    job_id: str
    status: str
    eligible: bool
    blockers: list[str]
    generated_at: str | None
    input_checksum: str | None
    redacted_summary: str
    artifacts: tuple[V2ReportArtifactSummary, ...]


class V2FinalReportService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        model_client: Any | None = None,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._model_client = model_client

    def get_report_status(self, job_id: str) -> V2FinalReportResult:
        with self._uow_factory() as uow:
            job = uow.v2_jobs.get(job_id) if hasattr(uow, "v2_jobs") else None
            if job is None:
                raise ValueError(f"V2 job {job_id!r} not found")

            eligibility = self._evaluate_eligibility(uow, job_id, job=job)
            artifacts = self._load_report_artifacts(uow, job_id, job=job)

            status = "not_generated"
            generated_at = None
            input_checksum = None
            redacted_summary = ""
            if artifacts:
                status = "generated"
                generated_at = artifacts[0].generated_at if hasattr(artifacts[0], "generated_at") else None
                input_checksum = artifacts[0].input_checksum if hasattr(artifacts[0], "input_checksum") else None
                redacted_summary = "Final report generated for this migration."

            return V2FinalReportResult(
                job_id=job_id,
                status=status,
                eligible=eligibility.eligible,
                blockers=eligibility.blockers,
                generated_at=generated_at,
                input_checksum=input_checksum,
                redacted_summary=redacted_summary,
                artifacts=tuple(
                    V2ReportArtifactSummary(
                        artifact_id=a.artifact_id,
                        kind=a.kind,
                        checksum_sha256=a.checksum_sha256,
                        size_bytes=a.size_bytes,
                        content_type=a.content_type,
                        download_url=a.download_url,
                    )
                    for a in artifacts
                ),
            )

    def generate_report(
        self,
        job_id: str,
    ) -> V2FinalReportResult:
        with self._uow_factory() as uow:
            job = uow.v2_jobs.get(job_id) if hasattr(uow, "v2_jobs") else None
            if job is None:
                raise ValueError(f"V2 job {job_id!r} not found")

            eligibility = self._evaluate_eligibility(uow, job_id, job=job)
            if not eligibility.eligible:
                return V2FinalReportResult(
                    job_id=job_id,
                    status="blocked",
                    eligible=False,
                    blockers=eligibility.blockers,
                    generated_at=None,
                    input_checksum=None,
                    redacted_summary="",
                    artifacts=(),
                )

            # Idempotency: return existing artifacts if already generated
            existing = self._load_report_artifacts(uow, job_id, job=job)
            if existing:
                return V2FinalReportResult(
                    job_id=job_id,
                    status="generated",
                    eligible=True,
                    blockers=[],
                    generated_at=existing[0].generated_at,
                    input_checksum=existing[0].input_checksum,
                    redacted_summary="Final report generated for this migration.",
                    artifacts=tuple(
                        V2ReportArtifactSummary(
                            artifact_id=a.artifact_id,
                            kind=a.kind,
                            checksum_sha256=a.checksum_sha256,
                            size_bytes=a.size_bytes,
                            content_type=a.content_type,
                            download_url=a.download_url,
                        )
                        for a in existing
                    ),
                )

            artifacts = self._generate_report_artifacts(uow, job_id)

            return V2FinalReportResult(
                job_id=job_id,
                status="generated",
                eligible=True,
                blockers=[],
                generated_at=artifacts[0].generated_at if artifacts else None,
                input_checksum=artifacts[0].input_checksum if artifacts else None,
                redacted_summary="Final report generated for this migration.",
                artifacts=tuple(
                    V2ReportArtifactSummary(
                        artifact_id=a.artifact_id,
                        kind=a.kind,
                        checksum_sha256=a.checksum_sha256,
                        size_bytes=a.size_bytes,
                        content_type=a.content_type,
                        download_url=a.download_url,
                    )
                    for a in artifacts
                ),
            )

    def resolve_report_artifact(
        self,
        job_id: str,
        artifact_id: str,
    ) -> "_ArtifactSnapshot":
        with self._uow_factory() as uow:
            job = uow.v2_jobs.get(job_id) if hasattr(uow, "v2_jobs") else None
            if job is None:
                raise ValueError(f"V2 job {job_id!r} not found")

            for artifact in self._load_report_artifacts(uow, job_id, job=job):
                if artifact.artifact_id == artifact_id:
                    return artifact

        raise LookupError(f"V2 report artifact {artifact_id!r} not found")

    def _evaluate_eligibility(
        self,
        uow: Any,
        job_id: str,
        *,
        job: Any | None = None,
    ) -> V2FinalReportEligibility:
        blockers: list[str] = []
        events = _job_events(uow, job_id)
        completed_stages = _completed_stages_from_events(events)

        if job is None and hasattr(uow, "v2_jobs"):
            job = uow.v2_jobs.get(job_id)
        included_stages = (
            included_stages_for_job(uow, job)
            if job is not None
            else (TERMINAL_STAGE_INDEX,)
        )
        terminal_stage = (
            max(included_stages)
            if included_stages
            else 0
        )
        if terminal_stage <= 0:
            blockers.append("This migration route contains no stages to report.")
        else:
            for stage_index in included_stages:
                completed_by_event = stage_index in completed_stages
                commands = (
                    uow.v2_commands.list_by_job_and_stage(job_id, stage_index)
                    if hasattr(uow, "v2_commands")
                    else []
                )
                if not commands:
                    if not completed_by_event:
                        blockers.append(f"Stage {stage_index} has not been started yet.")
                    continue
                latest = commands[0]
                if latest.status != "completed" and not completed_by_event:
                    blockers.append(
                        f"Stage {stage_index} is not completed "
                        f"(status: {latest.status})."
                    )
                    continue
                if latest.result_json is not None:
                    try:
                        result = json.loads(latest.result_json)
                    except (json.JSONDecodeError, TypeError):
                        result = {}
                    if not _looks_like_success(result) and not completed_by_event:
                        blockers.append(f"Stage {stage_index} did not complete successfully.")

        if hasattr(uow, "phase_gates"):
            open_gates = uow.phase_gates.list_open(job_id) if hasattr(uow.phase_gates, "list_open") else []
            if open_gates:
                blockers.append("There are open phase gates that must be resolved.")

        eligible = len(blockers) == 0
        return V2FinalReportEligibility(eligible=eligible, blockers=blockers)

    def _load_report_artifacts(
        self,
        uow: Any,
        job_id: str,
        *,
        job: Any | None = None,
    ) -> list[_ArtifactSnapshot]:
        snapshots: list[_ArtifactSnapshot] = []
        if hasattr(uow, "artifacts") and hasattr(uow.artifacts, "list_for_job"):
            records = uow.artifacts.list_for_job(job_id)
            for rec in records:
                if rec.artifact_type not in REPORT_ARTIFACT_KINDS:
                    continue
                normalized_path = str(
                    getattr(rec, "normalized_relative_path", "") or ""
                ).replace("\\", "/")
                if f"/{_REPORT_FORMAT_MARKER}/" not in f"/{normalized_path}":
                    continue
                snapshots.append(_ArtifactSnapshot(
                    artifact_id=rec.artifact_id,
                    kind=rec.artifact_type,
                    checksum_sha256=rec.checksum,
                    size_bytes=rec.size_bytes,
                    content_type=rec.content_type or "",
                    download_url=f"/v1/v2/jobs/{job_id}/report-artifacts/{rec.artifact_id}/download",
                    generated_at=rec.created_at,
                    input_checksum=rec.checksum,
                    file_path=Path(str(rec.relative_path)),
                ))
        if snapshots:
            return snapshots
        return self._load_filesystem_report_artifacts(uow, job_id, job=job)

    def _generate_report_artifacts(
        self,
        uow: Any,
        job_id: str,
    ) -> list[_ArtifactSnapshot]:
        result: list[_ArtifactSnapshot] = []
        state: dict[str, Any] = {}
        report_dir = None
        job = uow.v2_jobs.get(job_id) if hasattr(uow, "v2_jobs") else None
        if job is None:
            raise ValueError(f"V2 job {job_id!r} not found")
        terminal_stage = terminal_stage_for_job(uow, job)

        if hasattr(uow, "v2_commands"):
            commands = uow.v2_commands.list_by_job_and_stage(job_id, terminal_stage)
            if commands and commands[0].result_json:
                try:
                    state = json.loads(commands[0].result_json)
                except (json.JSONDecodeError, TypeError):
                    state = {}
                if isinstance(state, dict):
                    sandbox_path = state.get("sandbox_path")
                    if sandbox_path:
                        report_dir = Path(str(sandbox_path)) / "final"
                        state["run_dir"] = str(Path(str(sandbox_path)))

        if report_dir is None:
            report_dir = Path(f"reports/{job_id}")
            state["run_dir"] = str(Path.cwd() / "reports" / job_id)

        report_dir.mkdir(parents=True, exist_ok=True)

        input_checksum = _compute_report_input_checksum(uow, job)

        # Idempotency: check if artifacts with same input checksum already exist
        existing = self._load_report_artifacts(uow, job_id, job=job)
        if existing:
            return existing

        report = build_detailed_migration_report(
            uow=uow,
            job=job,
            model_client=self._model_client,
        )
        json_path = report_dir / "detailed_migration_report_v2.json"
        md_path = report_dir / "detailed_migration_report_v2.md"
        pdf_path = report_dir / "detailed_migration_report_v2.pdf"

        json_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        md_path.write_text(
            render_detailed_report_markdown(report),
            encoding="utf-8",
        )
        write_text_pdf_from_markdown(str(md_path), str(pdf_path))

        from migration_factory.control_tower.domain.checksums import utc_now_text
        created_at = utc_now_text()

        for artifact_info in [
            (json_path, "final_report_json", "application/json"),
            (md_path, "final_report_markdown", "text/markdown"),
            (pdf_path, "final_report_pdf", "application/pdf"),
        ]:
            path, kind, content_type = artifact_info
            if not path.is_file():
                continue
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            size = path.stat().st_size
            artifact_id = f"report-{uuid4().hex}"
            relative_path = str(path.resolve())
            normalized = f"reports/{job_id}/{_REPORT_FORMAT_MARKER}/{kind}"
            artifact_record = ArtifactRecord(
                artifact_id=artifact_id,
                job_id=job_id,
                stage_run_id=None,
                artifact_type=kind,
                registered_root_id="",
                relative_path=relative_path,
                normalized_relative_path=normalized,
                content_type=content_type,
                size_bytes=size,
                checksum_algorithm="sha256",
                checksum=sha256,
                created_at=created_at,
                created_by=_ARTIFACT_CREATED_BY,
            )
            snapshot = _snapshot_from_report_file(
                path=path,
                job_id=job_id,
                kind=kind,
                content_type=content_type,
                checksum_sha256=sha256,
                size_bytes=size,
                generated_at=created_at,
                input_checksum=input_checksum,
            )
            if hasattr(uow, "artifacts") and hasattr(uow.artifacts, "insert"):
                try:
                    uow.artifacts.insert(artifact_record)
                    snapshot = _ArtifactSnapshot(
                        artifact_id=artifact_id,
                        kind=kind,
                        checksum_sha256=sha256,
                        size_bytes=size,
                        content_type=content_type,
                        download_url=f"/v1/v2/jobs/{job_id}/report-artifacts/{artifact_id}/download",
                        generated_at=created_at,
                        input_checksum=input_checksum,
                        file_path=path,
                    )
                except StorageIntegrityError as exc:
                    if not _is_legacy_artifact_fk_failure(exc):
                        raise
            result.append(snapshot)

        return result

    def _load_filesystem_report_artifacts(
        self,
        uow: Any,
        job_id: str,
        *,
        job: Any | None = None,
    ) -> list["_ArtifactSnapshot"]:
        for report_dir in _candidate_report_dirs(uow, job_id, job=job):
            snapshots: list[_ArtifactSnapshot] = []
            for filename, kind, content_type in _REPORT_FILE_SPECS:
                path = report_dir / filename
                if not path.is_file():
                    continue
                snapshots.append(_snapshot_from_report_file(
                    path=path,
                    job_id=job_id,
                    kind=kind,
                    content_type=content_type,
                ))
            if len(snapshots) == len(_REPORT_FILE_SPECS):
                return snapshots
        return []


@dataclass
class _ArtifactSnapshot:
    artifact_id: str
    kind: str
    checksum_sha256: str
    size_bytes: int
    content_type: str
    download_url: str
    generated_at: str | None = None
    input_checksum: str | None = None
    file_path: Path | None = None


_REPORT_FILE_SPECS = (
    ("detailed_migration_report_v2.json", "final_report_json", "application/json"),
    ("detailed_migration_report_v2.md", "final_report_markdown", "text/markdown"),
    ("detailed_migration_report_v2.pdf", "final_report_pdf", "application/pdf"),
)


def _candidate_report_dirs(
    uow: Any,
    job_id: str,
    *,
    job: Any | None = None,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if job is not None and hasattr(uow, "v2_commands"):
        try:
            terminal_stage = terminal_stage_for_job(uow, job)
            commands = uow.v2_commands.list_by_job_and_stage(job_id, terminal_stage)
        except Exception:
            commands = ()
        if commands and getattr(commands[0], "result_json", None):
            try:
                state = json.loads(commands[0].result_json)
            except (json.JSONDecodeError, TypeError):
                state = {}
            if isinstance(state, dict) and state.get("sandbox_path"):
                candidates.append(Path(str(state["sandbox_path"])) / "final")
    candidates.append(Path("reports") / job_id)

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return tuple(deduped)


def _snapshot_from_report_file(
    *,
    path: Path,
    job_id: str,
    kind: str,
    content_type: str,
    checksum_sha256: str | None = None,
    size_bytes: int | None = None,
    generated_at: str | None = None,
    input_checksum: str | None = None,
) -> _ArtifactSnapshot:
    if checksum_sha256 is None:
        checksum_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if size_bytes is None:
        size_bytes = path.stat().st_size
    if generated_at is None:
        generated_at = _mtime_text(path)
    artifact_id = f"report-{kind}-{checksum_sha256[:12]}"
    return _ArtifactSnapshot(
        artifact_id=artifact_id,
        kind=kind,
        checksum_sha256=checksum_sha256,
        size_bytes=size_bytes,
        content_type=content_type,
        download_url=f"/v1/v2/jobs/{job_id}/report-artifacts/{artifact_id}/download",
        generated_at=generated_at,
        input_checksum=input_checksum or checksum_sha256,
        file_path=path,
    )


def _mtime_text(path: Path) -> str:
    return (
        datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_legacy_artifact_fk_failure(exc: StorageIntegrityError) -> bool:
    return "FOREIGN KEY constraint failed" in str(exc)


def _looks_like_success(result: dict[str, Any]) -> bool:
    failure_markers = {
        "FAIL",
        "FAILED",
        "ERROR",
        "BUILD_FAILED",
        "TEST_FAILED",
        "TRANSFORM_FAILED",
    }
    status_values = [
        str(value or "").strip().upper()
        for value in (
            result.get("final_status"),
            result.get("status"),
            result.get("orchestration_status"),
            result.get("transform_status"),
            result.get("build_status"),
            result.get("test_status"),
        )
    ]
    if any(
        value in failure_markers
        or value.endswith("_FAILED")
        or "FAILED" in value
        or value.endswith("_ERROR")
        for value in status_values
    ):
        return False
    success_markers = {
        "PASS",
        "COMPLETED",
        "TRANSFORM_APPLIED_IN_SANDBOX",
        "BUILD_PASSED_IN_SANDBOX",
        "TEST_PASSED",
    }
    return any(
        value in success_markers
        or value.endswith("_PASSED")
        for value in status_values
    )


def _job_events(uow: Any, job_id: str) -> tuple[Any, ...]:
    repository = getattr(uow, "v2_events", None)
    if repository is None or not hasattr(repository, "list_by_job"):
        return ()
    return tuple(repository.list_by_job(job_id))


def _completed_stages_from_events(events: tuple[Any, ...]) -> set[int]:
    completed: set[int] = set()
    for event in events:
        event_type = str(getattr(event, "type", "") or "")
        payload = _event_payload(event)
        if event_type == "stage_completed":
            _add_stage(completed, getattr(event, "stage", None))
        elif event_type in {"migration_completed", "job_completed"}:
            _add_stage(completed, getattr(event, "stage", None))
            _add_stage(completed, payload.get("from_stage"))
            _add_stage(completed, payload.get("to_stage"))
        elif event_type == "next_stage_queued":
            _add_stage(completed, payload.get("from_stage"))
    return completed


def _add_stage(stages: set[int], value: Any) -> None:
    try:
        stage_index = int(value)
    except (TypeError, ValueError):
        return
    if stage_index > 0:
        stages.add(stage_index)


def _event_payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", None)
    if isinstance(payload, dict):
        return payload
    payload_json = getattr(event, "payload_json", None)
    if isinstance(payload_json, dict):
        return payload_json
    if isinstance(payload_json, str) and payload_json.strip():
        try:
            parsed = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _compute_input_checksum(state: dict[str, Any]) -> str:
    raw = json.dumps(state, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _compute_report_input_checksum(uow: Any, job: Any) -> str:
    commands = []
    if hasattr(uow, "v2_commands") and hasattr(uow.v2_commands, "list_by_job"):
        for command in uow.v2_commands.list_by_job(job.job_id):
            commands.append({
                "command_id": command.command_id,
                "stage_index": command.stage_index,
                "status": command.status,
                "updated_at": command.updated_at,
                "result_json": command.result_json,
            })
    events = []
    if hasattr(uow, "v2_events") and hasattr(uow.v2_events, "list_by_job"):
        for event in uow.v2_events.list_by_job(job.job_id):
            events.append({
                "event_id": event.event_id,
                "stage": event.stage,
                "type": event.type,
                "status": event.status,
                "created_at": event.created_at,
            })
    return _compute_input_checksum({
        "job_id": job.job_id,
        "setup_checksum": job.setup_checksum,
        "stage_chain_json": job.stage_chain_json,
        "commands": commands,
        "events": events,
    })
