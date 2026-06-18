from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.final_report.context_builder import write_report_context
from migration_factory.final_report.writer import generate_final_migration_report


@dataclass(frozen=True)
class V2FinalReportSnapshot:
    job_id: str
    status: str
    generated_at: str
    docs_report_json: str
    docs_report_markdown: str
    run_report_json: str
    run_report_markdown: str
    report_context: str
    total_duration_seconds: float | None
    summary: str
    change_summary: tuple[str, ...]
    warnings: tuple[str, ...]


class V2FinalReportService:
    """Generate V2 final reports on demand from deterministic run artifacts."""

    def __init__(self, *, job_repo: Any, command_repo: Any) -> None:
        self._job_repo = job_repo
        self._command_repo = command_repo
        self._repo_root = Path(__file__).resolve().parents[3]

    def get_report(self, job_id: str) -> V2FinalReportSnapshot | None:
        run_dir = self._resolve_run_dir(job_id)
        report_json_path = run_dir / "final" / "migration_report.json"
        report_markdown_path = run_dir / "final" / "migration_summary.md"
        report_context_path = run_dir / "final" / "report_context.json"
        docs_dir = self._docs_dir(job_id)
        docs_report_json_path = docs_dir / "migration_report.json"
        docs_report_markdown_path = docs_dir / "migration_summary.md"
        if not report_json_path.is_file() or not report_markdown_path.is_file():
            return None
        payload = json.loads(report_json_path.read_text(encoding="utf-8"))
        return self._snapshot_from_payload(
            job_id=job_id,
            payload=payload,
            run_report_json_path=report_json_path,
            run_report_markdown_path=report_markdown_path,
            report_context_path=report_context_path,
            docs_report_json_path=docs_report_json_path,
            docs_report_markdown_path=docs_report_markdown_path,
        )

    def generate_report(self, job_id: str) -> V2FinalReportSnapshot:
        run_dir = self._resolve_run_dir(job_id)
        summary_path = run_dir / "orchestration" / "orchestration_summary.json"
        if not summary_path.is_file():
            raise ValueError("Stage 3 orchestration summary is not available yet.")

        state = self._load_state(run_dir, summary_path)
        result = generate_final_migration_report(state)
        if result.blockers:
            raise ValueError("; ".join(result.blockers))

        report_context_path = write_report_context(run_dir)
        docs_dir = self._docs_dir(job_id)
        docs_dir.mkdir(parents=True, exist_ok=True)

        report_json_path = run_dir / "final" / "migration_report.json"
        report_markdown_path = run_dir / "final" / "migration_summary.md"
        docs_report_json_path = docs_dir / "migration_report.json"
        docs_report_markdown_path = docs_dir / "migration_summary.md"
        docs_report_context_path = docs_dir / "report_context.json"

        shutil.copyfile(report_json_path, docs_report_json_path)
        shutil.copyfile(report_markdown_path, docs_report_markdown_path)
        shutil.copyfile(report_context_path, docs_report_context_path)

        payload = json.loads(report_json_path.read_text(encoding="utf-8"))
        return self._snapshot_from_payload(
            job_id=job_id,
            payload=payload,
            run_report_json_path=report_json_path,
            run_report_markdown_path=report_markdown_path,
            report_context_path=docs_report_context_path,
            docs_report_json_path=docs_report_json_path,
            docs_report_markdown_path=docs_report_markdown_path,
            warnings=result.warnings,
        )

    def _load_state(self, run_dir: Path, summary_path: Path) -> dict[str, Any]:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid orchestration summary payload.")
        payload["run_dir"] = str(run_dir)
        artifact_refs = payload.get("artifact_refs")
        payload["artifact_refs"] = dict(artifact_refs) if isinstance(artifact_refs, dict) else {}
        return payload

    def _resolve_run_dir(self, job_id: str) -> Path:
        job = self._job_repo.get(job_id)
        if job is None:
            raise ValueError(f"V2 job {job_id!r} not found")
        commands = self._command_repo.list_by_job_and_stage(job_id, 3)
        if not commands:
            raise ValueError("Stage 3 command manifest is not available yet.")
        latest = commands[0]
        try:
            argv = json.loads(latest.argv_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Stage 3 command manifest is invalid.") from exc
        if not isinstance(argv, list):
            raise ValueError("Stage 3 command manifest argv is invalid.")
        run_id = _argv_value(argv, "--run-id")
        modernized = _argv_value(argv, "--modernized")
        if not run_id or not modernized:
            raise ValueError("Stage 3 run directory could not be derived from the command manifest.")
        return (Path(modernized) / ".migration" / "runs" / run_id).resolve()

    def _docs_dir(self, job_id: str) -> Path:
        return self._repo_root / "docs" / "migration-reports" / job_id

    def _snapshot_from_payload(
        self,
        *,
        job_id: str,
        payload: dict[str, Any],
        run_report_json_path: Path,
        run_report_markdown_path: Path,
        report_context_path: Path,
        docs_report_json_path: Path,
        docs_report_markdown_path: Path,
        warnings: list[str] | None = None,
    ) -> V2FinalReportSnapshot:
        timing = payload.get("timing")
        timing_obj = timing if isinstance(timing, dict) else {}
        change_summary = payload.get("change_summary")
        changes = tuple(str(item) for item in change_summary) if isinstance(change_summary, list) else ()
        payload_warnings = payload.get("warnings")
        merged_warnings = [*(warnings or [])]
        if isinstance(payload_warnings, list):
            merged_warnings.extend(str(item) for item in payload_warnings)
        return V2FinalReportSnapshot(
            job_id=job_id,
            status="generated",
            generated_at=str(payload.get("created_at") or ""),
            docs_report_json=_repo_relative(docs_report_json_path, self._repo_root),
            docs_report_markdown=_repo_relative(docs_report_markdown_path, self._repo_root),
            run_report_json=str(run_report_json_path),
            run_report_markdown=str(run_report_markdown_path),
            report_context=_repo_relative(report_context_path, self._repo_root),
            total_duration_seconds=_float_or_none(timing_obj.get("total_duration_seconds")),
            summary=str(payload.get("report_summary") or ""),
            change_summary=changes,
            warnings=tuple(merged_warnings),
        )

    @staticmethod
    def snapshot_to_dict(snapshot: V2FinalReportSnapshot) -> dict[str, Any]:
        return {
            "job_id": snapshot.job_id,
            "status": snapshot.status,
            "generated_at": snapshot.generated_at,
            "docs_report_json": snapshot.docs_report_json,
            "docs_report_markdown": snapshot.docs_report_markdown,
            "run_report_json": snapshot.run_report_json,
            "run_report_markdown": snapshot.run_report_markdown,
            "report_context": snapshot.report_context,
            "total_duration_seconds": snapshot.total_duration_seconds,
            "summary": snapshot.summary,
            "change_summary": list(snapshot.change_summary),
            "warnings": list(snapshot.warnings),
        }


def _argv_value(argv: list[Any], option: str) -> str:
    for index, value in enumerate(argv[:-1]):
        if value == option:
            return str(argv[index + 1])
    return ""


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
