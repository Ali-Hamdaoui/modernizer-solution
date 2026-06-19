from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.final_report.context_builder import write_report_context
from migration_factory.final_report.pdf_writer import write_text_pdf_from_markdown
from migration_factory.final_report.writer import generate_final_migration_report


@dataclass(frozen=True)
class V2FinalReportSnapshot:
    job_id: str
    status: str
    generated_at: str
    docs_report_json: str
    docs_report_markdown: str
    docs_report_pdf: str
    run_report_json: str
    run_report_markdown: str
    run_report_pdf: str
    report_context: str
    total_duration_seconds: float | None
    summary: str
    change_summary: tuple[str, ...]
    warnings: tuple[str, ...]
    full_migration_source_stack: dict[str, Any]
    full_migration_target_stack: dict[str, Any]
    pipeline_history: tuple[dict[str, Any], ...]


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
        report_pdf_path = run_dir / "final" / "full_migration_report.pdf"
        report_context_path = run_dir / "final" / "report_context.json"
        docs_dir = self._docs_dir(job_id)
        docs_report_json_path = docs_dir / "migration_report.json"
        docs_report_markdown_path = self._docs_markdown_path(job_id)
        docs_report_pdf_path = self._docs_pdf_path(job_id)
        if not report_json_path.is_file() or not report_markdown_path.is_file():
            return None
        if not report_pdf_path.is_file():
            write_text_pdf_from_markdown(report_markdown_path, report_pdf_path)
        if not docs_report_pdf_path.is_file():
            docs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(report_pdf_path, docs_report_pdf_path)
        payload = json.loads(report_json_path.read_text(encoding="utf-8"))
        return self._snapshot_from_payload(
            job_id=job_id,
            payload=payload,
            run_report_json_path=report_json_path,
            run_report_markdown_path=report_markdown_path,
            run_report_pdf_path=report_pdf_path,
            report_context_path=report_context_path,
            docs_report_json_path=docs_report_json_path,
            docs_report_markdown_path=docs_report_markdown_path,
            docs_report_pdf_path=docs_report_pdf_path,
        )

    def generate_report(self, job_id: str) -> V2FinalReportSnapshot:
        _, run_dir = self._resolve_latest_stage_run(job_id)
        summary_path = run_dir / "orchestration" / "orchestration_summary.json"
        if not summary_path.is_file():
            raise ValueError("The latest stage orchestration summary is not available yet.")

        state = self._load_state(job_id, run_dir, summary_path)
        result = generate_final_migration_report(state)
        if result.blockers:
            raise ValueError("; ".join(result.blockers))

        report_context_path = write_report_context(run_dir)
        docs_dir = self._docs_dir(job_id)
        docs_dir.mkdir(parents=True, exist_ok=True)

        report_json_path = run_dir / "final" / "migration_report.json"
        report_markdown_path = run_dir / "final" / "migration_summary.md"
        report_pdf_path = run_dir / "final" / "full_migration_report.pdf"
        docs_report_json_path = docs_dir / "migration_report.json"
        docs_report_markdown_path = self._docs_markdown_path(job_id)
        docs_report_pdf_path = self._docs_pdf_path(job_id)
        docs_report_context_path = docs_dir / "report_context.json"

        self._cleanup_docs_markdown(docs_dir, docs_report_markdown_path)
        shutil.copyfile(report_json_path, docs_report_json_path)
        shutil.copyfile(report_markdown_path, docs_report_markdown_path)
        write_text_pdf_from_markdown(report_markdown_path, report_pdf_path)
        shutil.copyfile(report_pdf_path, docs_report_pdf_path)
        shutil.copyfile(report_context_path, docs_report_context_path)

        payload = json.loads(report_json_path.read_text(encoding="utf-8"))
        return self._snapshot_from_payload(
            job_id=job_id,
            payload=payload,
            run_report_json_path=report_json_path,
            run_report_markdown_path=report_markdown_path,
            run_report_pdf_path=report_pdf_path,
            report_context_path=docs_report_context_path,
            docs_report_json_path=docs_report_json_path,
            docs_report_markdown_path=docs_report_markdown_path,
            docs_report_pdf_path=docs_report_pdf_path,
            warnings=result.warnings,
        )

    def _load_state(self, job_id: str, run_dir: Path, summary_path: Path) -> dict[str, Any]:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid orchestration summary payload.")
        payload["run_dir"] = str(run_dir)
        artifact_refs = payload.get("artifact_refs")
        payload["artifact_refs"] = dict(artifact_refs) if isinstance(artifact_refs, dict) else {}
        pipeline_history = self._build_pipeline_history(job_id)
        payload["pipeline_history"] = pipeline_history["stages"]
        payload["full_migration_source_stack"] = pipeline_history["source_stack"]
        payload["full_migration_target_stack"] = pipeline_history["target_stack"]
        return payload

    def _resolve_run_dir(self, job_id: str) -> Path:
        _, run_dir = self._resolve_latest_stage_run(job_id)
        return run_dir

    def _resolve_latest_stage_run(self, job_id: str) -> tuple[int, Path]:
        job = self._job_repo.get(job_id)
        if job is None:
            raise ValueError(f"V2 job {job_id!r} not found")
        commands = self._list_commands(job_id)
        if not commands:
            raise ValueError("No stage command manifest is available yet.")
        fallback: tuple[int, Path] | None = None
        for command in sorted(commands, key=lambda item: int(getattr(item, "stage_index", 0)), reverse=True):
            run_dir = self._command_run_dir(command)
            if run_dir is None:
                continue
            if fallback is None:
                fallback = (int(getattr(command, "stage_index", 0)), run_dir)
            if (run_dir / "orchestration" / "orchestration_summary.json").is_file():
                return int(getattr(command, "stage_index", 0)), run_dir
        if fallback is not None:
            return fallback
        raise ValueError("A stage run directory could not be derived from the command manifests.")

    def _build_pipeline_history(self, job_id: str) -> dict[str, Any]:
        job = self._job_repo.get(job_id)
        if job is None:
            raise ValueError(f"V2 job {job_id!r} not found")
        try:
            planned_stages = json.loads(getattr(job, "stage_chain_json", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            planned_stages = []
        commands_by_stage = {
            int(getattr(command, "stage_index", 0)): command
            for command in self._list_commands(job_id)
            if int(getattr(command, "stage_index", 0)) > 0
        }
        stages: list[dict[str, Any]] = []
        for raw_stage in planned_stages:
            if not isinstance(raw_stage, dict):
                continue
            stage_index = int(raw_stage.get("stage_index") or 0)
            if stage_index <= 0:
                continue
            stage_def = _stage_definition(stage_index)
            command = commands_by_stage.get(stage_index)
            run_dir = self._command_run_dir(command) if command is not None else None
            summary = _read_optional_json(run_dir / "orchestration" / "orchestration_summary.json") if run_dir is not None else None
            assessment = _read_optional_json(run_dir / "assessment" / "assessment_report.json") if run_dir is not None else None
            timing = _read_optional_json(run_dir / "performance" / "timing_report.json") if run_dir is not None else None
            phase_map = timing.get("phase_durations_seconds") if isinstance(timing, dict) else {}
            total_duration = phase_map.get("total_run") if isinstance(phase_map, dict) else None
            artifact_refs = summary.get("artifact_refs") if isinstance(summary, dict) else {}
            artifact_refs = artifact_refs if isinstance(artifact_refs, dict) else {}
            source_stack = _stage_stack(assessment, "source_stack", stage_def["source_stack"])
            target_stack = _stage_stack(assessment, "target_stack", stage_def["target_stack"])
            stages.append(
                {
                    "stage_index": stage_index,
                    "pipeline_stage": str(raw_stage.get("pipeline_stage") or f"Stage {stage_index}"),
                    "input_source_kind": str(raw_stage.get("input_source_kind") or ""),
                    "profile": stage_def["profile"],
                    "source_stack": source_stack,
                    "target_stack": target_stack,
                    "planned_final_target": stage_index == 4,
                    "chain_status": str(summary.get("final_status") or raw_stage.get("chain_status") or "pending") if isinstance(summary, dict) else str(raw_stage.get("chain_status") or "pending"),
                    "build_status": str(summary.get("build_status") or "") if isinstance(summary, dict) else "",
                    "test_status": str(summary.get("test_status") or "") if isinstance(summary, dict) else "",
                    "transform_status": str(summary.get("transform_status") or "") if isinstance(summary, dict) else "",
                    "run_id": str(summary.get("run_id") or _command_run_id(command) or "") if isinstance(summary, dict) else str(_command_run_id(command) or ""),
                    "run_dir": str(run_dir) if run_dir is not None else "",
                    "duration_seconds": _float_or_none(total_duration),
                    "artifact_refs": {
                        key: str(value)
                        for key, value in artifact_refs.items()
                    },
                }
            )
        full_source_stack = stages[0]["source_stack"] if stages else dict(_stage_definition(1)["source_stack"])
        completed_target_stack = _completed_stage_target_stack(stages)
        full_target_stack = completed_target_stack or (stages[-1]["target_stack"] if stages else dict(_stage_definition(4)["target_stack"]))
        return {
            "source_stack": dict(full_source_stack),
            "target_stack": dict(full_target_stack),
            "stages": stages,
        }

    def _list_commands(self, job_id: str) -> tuple[Any, ...]:
        if hasattr(self._command_repo, "list_by_job"):
            return tuple(self._command_repo.list_by_job(job_id))
        commands: list[Any] = []
        for stage_index in (1, 2, 3, 4):
            if hasattr(self._command_repo, "list_by_job_and_stage"):
                commands.extend(self._command_repo.list_by_job_and_stage(job_id, stage_index))
        return tuple(commands)

    def _command_run_dir(self, command: Any | None) -> Path | None:
        if command is None:
            return None
        try:
            argv = json.loads(getattr(command, "argv_json", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(argv, list):
            return None
        run_id = _argv_value(argv, "--run-id")
        modernized = _argv_value(argv, "--modernized")
        if not run_id or not modernized:
            return None
        return (Path(modernized) / ".migration" / "runs" / run_id).resolve()

    def _docs_dir(self, job_id: str) -> Path:
        return self._repo_root / "docs" / "migration-reports" / job_id

    def _docs_markdown_path(self, job_id: str) -> Path:
        return self._docs_dir(job_id) / "full_migration_report.md"

    def _docs_pdf_path(self, job_id: str) -> Path:
        return self._docs_dir(job_id) / "full_migration_report.pdf"

    def _cleanup_docs_markdown(self, docs_dir: Path, keep_path: Path) -> None:
        for path in docs_dir.glob("*.md"):
            if path.resolve() == keep_path.resolve():
                continue
            path.unlink(missing_ok=True)

    def _snapshot_from_payload(
        self,
        *,
        job_id: str,
        payload: dict[str, Any],
        run_report_json_path: Path,
        run_report_markdown_path: Path,
        run_report_pdf_path: Path,
        report_context_path: Path,
        docs_report_json_path: Path,
        docs_report_markdown_path: Path,
        docs_report_pdf_path: Path,
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
            docs_report_pdf=_repo_relative(docs_report_pdf_path, self._repo_root),
            run_report_json=str(run_report_json_path),
            run_report_markdown=str(run_report_markdown_path),
            run_report_pdf=str(run_report_pdf_path),
            report_context=_repo_relative(report_context_path, self._repo_root),
            total_duration_seconds=_float_or_none(timing_obj.get("total_duration_seconds")),
            summary=str(payload.get("report_summary") or ""),
            change_summary=changes,
            warnings=tuple(merged_warnings),
            full_migration_source_stack=dict(payload.get("full_migration_source_stack", {}) or {}),
            full_migration_target_stack=dict(payload.get("full_migration_target_stack", {}) or {}),
            pipeline_history=tuple(
                dict(item) for item in list(payload.get("pipeline_history", []) or []) if isinstance(item, dict)
            ),
        )

    @staticmethod
    def snapshot_to_dict(snapshot: V2FinalReportSnapshot) -> dict[str, Any]:
        return {
            "job_id": snapshot.job_id,
            "status": snapshot.status,
            "generated_at": snapshot.generated_at,
            "docs_report_json": snapshot.docs_report_json,
            "docs_report_markdown": snapshot.docs_report_markdown,
            "docs_report_pdf": snapshot.docs_report_pdf,
            "run_report_json": snapshot.run_report_json,
            "run_report_markdown": snapshot.run_report_markdown,
            "run_report_pdf": snapshot.run_report_pdf,
            "report_context": snapshot.report_context,
            "total_duration_seconds": snapshot.total_duration_seconds,
            "summary": snapshot.summary,
            "change_summary": list(snapshot.change_summary),
            "warnings": list(snapshot.warnings),
            "full_migration_source_stack": dict(snapshot.full_migration_source_stack),
            "full_migration_target_stack": dict(snapshot.full_migration_target_stack),
            "pipeline_history": [dict(item) for item in snapshot.pipeline_history],
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


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _command_run_id(command: Any | None) -> str | None:
    if command is None:
        return None
    try:
        argv = json.loads(getattr(command, "argv_json", "[]") or "[]")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(argv, list):
        return None
    run_id = _argv_value(argv, "--run-id")
    return run_id or None


def _stage_definition(stage_index: int) -> dict[str, Any]:
    definitions = {
        1: {
            "profile": "springboot-2.1.6-to-2.7-java11",
            "source_stack": {"spring_boot": "2.1.6", "java": "11"},
            "target_stack": {"spring_boot": "2.7.x", "java": "11"},
        },
        2: {
            "profile": "springboot-2.7-to-3.5-java17",
            "source_stack": {"spring_boot": "2.7.x", "java": "11"},
            "target_stack": {"spring_boot": "3.5.x", "java": "17"},
        },
        3: {
            "profile": "springboot-3.5-java17-to-java21",
            "source_stack": {"spring_boot": "3.5.x", "java": "17"},
            "target_stack": {"spring_boot": "3.5.x", "java": "21"},
        },
        4: {
            "profile": "springboot-3.5-java21-to-4.0-java21",
            "source_stack": {"spring_boot": "3.5.x", "java": "21"},
            "target_stack": {"spring_boot": "4.0.x", "java": "21"},
        },
    }
    return definitions.get(stage_index, {
        "profile": f"stage-{stage_index}",
        "source_stack": {},
        "target_stack": {},
    })


def _stage_stack(
    assessment: dict[str, Any] | None,
    key: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(assessment, dict):
        value = assessment.get(key)
        if isinstance(value, dict):
            return dict(value)
    return dict(fallback)


def _completed_stage_target_stack(stages: list[dict[str, Any]]) -> dict[str, Any]:
    for stage in reversed(stages):
        if str(stage.get("chain_status") or "").lower() in {"pending", "failed", "blocked", ""}:
            continue
        target_stack = stage.get("target_stack")
        if isinstance(target_stack, dict):
            return dict(target_stack)
    return {}
