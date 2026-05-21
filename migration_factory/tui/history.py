from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.tui.config import TuiConfig


STATUS_KEYS = (
    "analysis_status",
    "planning_status",
    "assessment_status",
    "orchestration_status",
    "approval_status",
    "transform_status",
    "build_status",
    "test_status",
)

PATH_KEYS = (
    "log_path",
    "test_report_path",
    "test_summary_path",
    "test_log_path",
    "sandbox_path",
)

REPORT_PREVIEW_CHARS = 8000
LOG_TAIL_LINES = 120

FINAL_REPORT_REFS = (
    ("final_migration_report", "Final migration report", "final/migration_report.json"),
    ("final_migration_summary", "Final migration summary", "final/migration_summary.md"),
)
BASE_REPORT_REFS = (
    ("assessment_summary", "Assessment summary", "assessment/assessment_summary.md"),
    ("approval_request", "Approval request", "planning/approval_request.json"),
    ("timing_summary", "Timing summary", "performance/timing_summary.md"),
)
COPILOT_DOC_REFS = (
    ("copilot_migration_overview", "Copilot docs - migration overview", "final/copilot_docs/migration_overview.md"),
    ("copilot_technical_changes", "Copilot docs - technical changes", "final/copilot_docs/technical_changes.md"),
    ("copilot_validation_evidence", "Copilot docs - validation evidence", "final/copilot_docs/validation_evidence.md"),
    ("copilot_risks_and_warnings", "Copilot docs - risks and warnings", "final/copilot_docs/risks_and_warnings.md"),
    ("copilot_review", "Copilot docs - review", "final/copilot_docs/copilot_review.md"),
)
PHASE_LOG_REFS = (
    ("phase2_log", "Phase 2 log", "logs/phase2_transform.log"),
    ("post_transform_test_log", "Post-transform test log", "test/post_transform/test_agent.log"),
)


@dataclass(frozen=True)
class ArtifactRef:
    name: str
    raw_ref: str
    path: Path | None


@dataclass(frozen=True)
class ArtifactViewer:
    name: str
    label: str
    path: Path | None
    status: str
    content: str = ""
    tail: bool = False


@dataclass(frozen=True)
class RunDashboard:
    run_id: str
    profile: str
    statuses: dict[str, str]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    final_status: str
    run_dir: Path
    report_refs: tuple[ArtifactRef, ...]
    artifact_viewers: tuple[ArtifactViewer, ...]
    summary_path: Path
    summary_error: str = ""


def discover_run_dashboards(config: TuiConfig) -> list[RunDashboard]:
    if not config.modernized_app_path:
        return []

    runs_root = Path(config.modernized_app_path).expanduser() / ".migration" / "runs"
    try:
        run_dirs = [path for path in runs_root.iterdir() if path.is_dir()]
    except OSError:
        return []

    run_dirs.sort(key=lambda path: (_mtime(path), path.name), reverse=True)
    dashboards: list[RunDashboard] = []
    for run_dir in run_dirs:
        try:
            dashboards.append(load_run_dashboard(run_dir))
        except Exception as exc:
            dashboards.append(_error_run_dashboard(run_dir, exc))
    return dashboards


def load_run_dashboard(run_dir: Path) -> RunDashboard:
    summary_path = run_dir / "orchestration" / "orchestration_summary.json"
    summary, summary_error = _load_summary(summary_path)

    warnings = _string_tuple(summary.get("warnings"))
    if summary_error:
        warnings = (*warnings, summary_error)

    return RunDashboard(
        run_id=_string_value(summary.get("run_id")) or run_dir.name,
        profile=(
            _string_value(summary.get("profile_id"))
            or _string_value(summary.get("profile"))
            or _string_value(summary.get("target_profile"))
        ),
        statuses=_status_values(summary),
        blockers=_string_tuple(summary.get("blockers")),
        warnings=warnings,
        final_status=_final_status(summary, summary_error),
        run_dir=run_dir,
        report_refs=_report_refs(run_dir, summary),
        artifact_viewers=_artifact_viewers(run_dir, summary),
        summary_path=summary_path,
        summary_error=summary_error,
    )


def resolve_artifact_ref(run_dir: Path, ref: str) -> Path | None:
    if not ref:
        return None

    raw_path = Path(ref).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve(strict=False)

    root = run_dir.resolve(strict=False)
    candidate = (root / raw_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _load_summary(summary_path: Path) -> tuple[dict[str, Any], str]:
    if not summary_path.exists():
        return {}, "orchestration_summary.json missing"

    try:
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {}, f"orchestration_summary.json unreadable: {exc}"

    if not isinstance(raw, dict):
        return {}, "orchestration_summary.json must be a JSON object"
    return raw, ""


def _error_run_dashboard(run_dir: Path, exc: Exception) -> RunDashboard:
    summary_path = run_dir / "orchestration" / "orchestration_summary.json"
    message = f"run dashboard unreadable: {type(exc).__name__}: {exc}"
    return RunDashboard(
        run_id=run_dir.name,
        profile="",
        statuses={},
        blockers=(),
        warnings=(message,),
        final_status="ERROR",
        run_dir=run_dir,
        report_refs=(),
        artifact_viewers=(),
        summary_path=summary_path,
        summary_error=message,
    )


def _status_values(summary: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for key in STATUS_KEYS:
        value = _string_value(summary.get(key))
        if value:
            statuses[key] = value
    return statuses


def _final_status(summary: dict[str, Any], summary_error: str) -> str:
    value = _string_value(summary.get("final_status"))
    if value:
        return value
    return "INCOMPLETE" if summary_error else "UNKNOWN"


def _report_refs(run_dir: Path, summary: dict[str, Any]) -> tuple[ArtifactRef, ...]:
    refs: list[ArtifactRef] = []

    artifact_refs = summary.get("artifact_refs")
    if isinstance(artifact_refs, dict):
        for name, raw_ref in artifact_refs.items():
            ref = _string_value(raw_ref)
            if ref:
                refs.append(
                    ArtifactRef(
                        name=str(name),
                        raw_ref=ref,
                        path=resolve_artifact_ref(run_dir, ref),
                    )
                )

    for key in PATH_KEYS:
        ref = _string_value(summary.get(key))
        if ref:
            refs.append(
                ArtifactRef(
                    name=key,
                    raw_ref=ref,
                    path=resolve_artifact_ref(run_dir, ref),
                )
            )

    return tuple(refs)


def _artifact_viewers(run_dir: Path, summary: dict[str, Any]) -> tuple[ArtifactViewer, ...]:
    artifact_refs = summary.get("artifact_refs")
    refs = artifact_refs if isinstance(artifact_refs, dict) else {}
    viewers: list[ArtifactViewer] = [
        _viewer_from_ref(run_dir, refs, key, label, fallback, tail=False)
        for key, label, fallback in BASE_REPORT_REFS
    ]

    if _is_successful_full_sandbox(summary):
        viewers.extend(
            _viewer_from_ref(run_dir, refs, key, label, fallback, tail=False)
            for key, label, fallback in FINAL_REPORT_REFS
        )
        viewers.extend(
            _viewer_from_ref(run_dir, refs, key, label, fallback, tail=False)
            for key, label, fallback in COPILOT_DOC_REFS
            if _has_ref_or_file(run_dir, refs, key, fallback)
        )

    viewers.extend(
        _viewer_from_ref(run_dir, refs, key, label, fallback, tail=True)
        for key, label, fallback in PHASE_LOG_REFS
        if _has_ref_or_file(run_dir, refs, key, fallback)
    )

    for key, label in (
        ("log_path", "Orchestration log"),
        ("test_log_path", "Test log"),
    ):
        ref = _string_value(summary.get(key))
        if ref:
            viewers.append(_viewer(run_dir, key, label, ref, tail=True))

    return tuple(viewers)


def _viewer_from_ref(
    run_dir: Path,
    refs: dict[Any, Any],
    key: str,
    label: str,
    fallback: str,
    *,
    tail: bool,
) -> ArtifactViewer:
    ref = _string_value(refs.get(key)) or fallback
    return _viewer(run_dir, key, label, ref, tail=tail)


def _viewer(
    run_dir: Path,
    key: str,
    label: str,
    ref: str,
    *,
    tail: bool,
) -> ArtifactViewer:
    path = resolve_artifact_ref(run_dir, ref)
    if path is None:
        return ArtifactViewer(name=key, label=label, path=None, status="unsafe ref", tail=tail)
    if not path.is_file():
        return ArtifactViewer(name=key, label=label, path=path, status="missing", tail=tail)
    content = _tail_text(path) if tail else _preview_text(path)
    return ArtifactViewer(name=key, label=label, path=path, status="present", content=content, tail=tail)


def _has_ref_or_file(run_dir: Path, refs: dict[Any, Any], key: str, fallback: str) -> bool:
    ref = _string_value(refs.get(key))
    if ref:
        return True
    path = resolve_artifact_ref(run_dir, fallback)
    return bool(path and path.is_file())


def _is_successful_full_sandbox(summary: dict[str, Any]) -> bool:
    mode = _string_value(summary.get("mode"))
    if mode == "read_only_assessment":
        return False
    return (
        (not mode or mode == "full_sandbox_migration")
        and _string_value(summary.get("orchestration_status")) == "PASS"
        and _string_value(summary.get("approval_status")) == "COMPLETED"
        and _string_value(summary.get("approval_decision")) == "approved"
        and _string_value(summary.get("final_status")) == "TRANSFORM_APPLIED_IN_SANDBOX"
    )


def _preview_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"unreadable: {exc}"
    if len(text) > REPORT_PREVIEW_CHARS:
        return text[:REPORT_PREVIEW_CHARS] + "\n... truncated ..."
    return text


def _tail_text(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"unreadable: {exc}"
    tail = lines[-LOG_TAIL_LINES:]
    prefix = [f"... showing last {LOG_TAIL_LINES} lines ..."] if len(lines) > LOG_TAIL_LINES else []
    return "\n".join([*prefix, *tail])


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value if item is not None)
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if item is not None)
    if value:
        return (str(value),)
    return ()


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
