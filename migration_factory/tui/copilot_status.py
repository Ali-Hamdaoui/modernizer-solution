from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from migration_factory.final_report.copilot import detect_copilot_cli_status

_COPILOT_REPORT_ENV = "AI_MIGRATION_ENABLE_COPILOT_REPORT"

_CONNECTIVITY_LABELS = {
    "connected": "Connected",
    "unavailable": "Unavailable",
    "not_configured": "Not configured",
}
_REPORT_LABELS = {
    "generated": "Advisory report generated",
    "generated_with_fallback": "Advisory report generated via fallback",
    "not_generated": "Advisory report not generated for this run",
    "pending": "Advisory report pending while run is active",
    "disabled": "Copilot Assist disabled",
    "skipped": "Advisory report not generated for this run",
    "failed": "Advisory report unavailable",
}
_AUTH_LABELS = {
    "authenticated": "Authenticated",
    "unauthenticated": "Unauthenticated",
    "unknown": "Unknown",
}
_CLI_LABELS = {
    "installed": "Installed",
    "not_installed": "Not installed",
    "error": "Error",
}


def get_copilot_status_lines(
    run_dir: str | Path | None = None,
    *,
    prefer_response: bool = True,
    active_run: bool = False,
    state: dict[str, Any] | None = None,
) -> list[str]:
    response_path = Path(run_dir) / "final" / "copilot_report_response.json" if run_dir is not None else None
    response_exists = prefer_response and response_path is not None and response_path.is_file()
    payload = _read_response(response_path) if response_exists and response_path is not None else _cached_detector_payload()
    connectivity = str(payload.get("connectivity") or "not_configured")
    provider = str(payload.get("provider") or "github_copilot")
    adapter = str(payload.get("adapter") or "local_deterministic_template")
    model = str(payload.get("model") or "unknown")
    auth_status = str(payload.get("auth_status") or "unknown")
    cli_status = str(payload.get("cli_status") or "not_installed")
    report_status = str(payload.get("report_status") or payload.get("status") or "")
    report_enabled = _copilot_report_enabled(state) or response_exists
    if not response_exists:
        report_status = _missing_response_status(report_enabled=report_enabled, active_run=active_run, state=state)
    lines = [
        f"Advisory report status: {_REPORT_LABELS.get(report_status, 'Advisory report unavailable')}",
        f"Report generation: {'Enabled' if report_enabled else 'Disabled'}",
        f"Copilot Assist: {_CONNECTIVITY_LABELS.get(connectivity, 'Unavailable')}",
        f"Provider: {provider}",
        f"Adapter: {adapter}",
        f"Model: {_normalize_model(model)}",
        f"Auth: {_AUTH_LABELS.get(auth_status, 'Unknown')}",
        f"CLI: {_CLI_LABELS.get(cli_status, 'Error')}",
        "Copilot Assist is advisory and does not affect migration result.",
    ]
    report_path = _copilot_markdown_report_path(run_dir, report_status)
    if report_path is not None:
        lines.append(f"Copilot Assist report: {report_path}")
    if report_status == "generated_with_fallback":
        if str(payload.get("fallback_reason") or "").lower() == "timeout" or payload.get("timed_out") is True:
            lines.append("Copilot warning: CLI timed out, fallback used")
        else:
            lines.append("Copilot warning: CLI failed, fallback used")
    return lines


def _copilot_markdown_report_path(run_dir: str | Path | None, report_status: str) -> Path | None:
    if report_status not in {"generated", "generated_with_fallback"} or run_dir is None:
        return None
    path = Path(run_dir) / "final" / "copilot_migration_report.md"
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _read_response(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _missing_response_status(
    *,
    report_enabled: bool,
    active_run: bool,
    state: dict[str, Any] | None,
) -> str:
    if not report_enabled:
        return "disabled"
    if active_run or _copilot_report_active(state):
        return "pending"
    return "not_generated"


def _copilot_report_active(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    for key in ("copilot_report_status", "copilot_status"):
        value = str(state.get(key) or "").strip().lower()
        if value in {"active", "running", "pending", "in_progress"}:
            return True
    phase_statuses = state.get("copilot_phase_statuses")
    if isinstance(phase_statuses, dict):
        value = str(phase_statuses.get("final") or phase_statuses.get("report") or "").strip().lower()
        return value in {"active", "running", "pending", "in_progress"}
    return False


def _copilot_report_enabled(state: dict[str, Any] | None = None) -> bool:
    if isinstance(state, dict) and "copilot_report_enabled" in state:
        return state.get("copilot_report_enabled") is True
    return os.environ.get(_COPILOT_REPORT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_model(model: str) -> str:
    value = str(model or "").strip()
    while value.startswith(("configured:", "detected:")):
        value = value.split(":", 1)[1].strip()
    return value or "unknown"


_CACHED_DETECTOR_PAYLOAD: tuple[tuple[str, str, object], dict[str, Any]] | None = None


def _cached_detector_payload() -> dict[str, Any]:
    global _CACHED_DETECTOR_PAYLOAD
    cache_key = (
        os.environ.get("AI_MIGRATION_COPILOT_MODEL", ""),
        os.environ.get("AI_MIGRATION_COPILOT_PROVIDER", ""),
        detect_copilot_cli_status,
    )
    if _CACHED_DETECTOR_PAYLOAD is None or _CACHED_DETECTOR_PAYLOAD[0] != cache_key:
        _CACHED_DETECTOR_PAYLOAD = (cache_key, detect_copilot_cli_status(timeout_seconds=15.0).to_dict())
    return dict(_CACHED_DETECTOR_PAYLOAD[1])


def get_copilot_debug_status() -> dict[str, str]:
    payload = _cached_detector_payload()
    return {
        "resolved_executable_basename": str(payload.get("resolved_executable_basename") or _safe_resolved_copilot_basename()),
        "provider": str(payload.get("provider") or "github_copilot"),
        "adapter": str(payload.get("adapter") or "local_deterministic_template"),
        "model": _normalize_model(str(payload.get("model") or "unknown")),
        "auth_status": str(payload.get("auth_status") or "unknown"),
        "cli_status": str(payload.get("cli_status") or "not_installed"),
    }


def _safe_resolved_copilot_basename() -> str:
    try:
        import subprocess
        import shutil

        found = shutil.which("copilot.cmd") or shutil.which("copilot")
        if found:
            return _path_basename(found)
        where_exe = shutil.which("where.exe") or shutil.which("where")
        if not where_exe:
            return ""
        completed = subprocess.run(
            [where_exe, "copilot"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if completed.returncode != 0:
            return ""
        candidates = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
        cmd_candidate = next((candidate for candidate in candidates if _path_basename(candidate).lower() == "copilot.cmd"), "")
        candidate = cmd_candidate or (candidates[0] if candidates else "")
        if candidate:
            return _path_basename(candidate)
        return ""
    except Exception:
        return ""


def _path_basename(path: str) -> str:
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]
