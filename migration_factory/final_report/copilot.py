from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml


PROVIDER = "github_copilot"
ADAPTER = "local_deterministic_template"
CLI_ADAPTER = "copilot_cli"
MODEL_ENV = "AI_MIGRATION_COPILOT_MODEL"
PROVIDER_ENV = "AI_MIGRATION_COPILOT_PROVIDER"
DEFAULT_COPILOT_MODEL = "gpt-5-mini"
DEFAULT_MANIFEST_RELATIVE_PATH = Path("templates") / "reports" / "copilot_final_migration_report_v1.yaml"
_REQUIRED_MANIFEST_FIELDS = {
    "id",
    "version",
    "type",
    "engine",
    "template_file",
    "output_file",
    "request_file",
    "response_file",
    "advisory_only",
    "requires",
    "optional",
}
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
_SECRET_KEY_PARTS = ("token", "secret", "password", "credential", "authorization", "auth_output")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
)


@dataclass(frozen=True)
class CopilotReportManifest:
    id: str
    version: str
    type: str
    engine: str
    template_path: Path
    output_file: Path
    request_file: Path
    response_file: Path
    advisory_only: bool
    requires: tuple[Path, ...]
    optional: tuple[Path, ...]

    def output_path(self, run_dir: str | Path) -> Path:
        return Path(run_dir) / self.output_file

    def request_path(self, run_dir: str | Path) -> Path:
        return Path(run_dir) / self.request_file

    def response_path(self, run_dir: str | Path) -> Path:
        return Path(run_dir) / self.response_file


@dataclass(frozen=True)
class CopilotAdapterStatus:
    provider: str = PROVIDER
    model: str = "unknown"
    connectivity: str = "not_configured"
    report_status: str = "skipped"
    adapter: str = ADAPTER
    auth_status: str = "unknown"
    cli_status: str = "not_installed"
    resolved_executable_path: str = ""

    @property
    def resolved_executable(self) -> str:
        return self.resolved_executable_path

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "adapter": self.adapter,
            "model": self.model,
            "connectivity": self.connectivity,
            "report_status": self.report_status,
            "auth_status": self.auth_status,
            "cli_status": self.cli_status,
            "resolved_executable_basename": _safe_executable_basename(self.resolved_executable_path),
        }


@dataclass(frozen=True)
class CopilotReportRequest:
    payload: dict[str, Any]
    warnings: list[str]
    missing_required: list[str]
    missing_optional: list[str]


def load_copilot_report_manifest(ai_hub_path: str | Path) -> CopilotReportManifest:
    manifest_path = Path(ai_hub_path) / DEFAULT_MANIFEST_RELATIVE_PATH
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"unable to read Copilot report manifest: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Copilot report manifest must be a mapping")

    missing = sorted(_REQUIRED_MANIFEST_FIELDS - set(raw))
    if missing:
        raise ValueError(f"Copilot report manifest missing required fields: {', '.join(missing)}")

    requires = raw["requires"]
    optional = raw["optional"]
    if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
        raise ValueError("Copilot report manifest requires must be a list of paths")
    if not isinstance(optional, list) or not all(isinstance(item, str) for item in optional):
        raise ValueError("Copilot report manifest optional must be a list of paths")
    if raw["engine"] != PROVIDER:
        raise ValueError("Copilot report manifest engine must be github_copilot")
    if raw["advisory_only"] is not True:
        raise ValueError("Copilot report manifest must be advisory_only")

    manifest_dir = manifest_path.parent
    template_path = manifest_dir / str(raw["template_file"])
    if not template_path.is_file():
        raise ValueError(f"Copilot report template is missing: {template_path}")

    return CopilotReportManifest(
        id=str(raw["id"]),
        version=str(raw["version"]),
        type=str(raw["type"]),
        engine=str(raw["engine"]),
        template_path=template_path,
        output_file=Path(str(raw["output_file"])),
        request_file=Path(str(raw["request_file"])),
        response_file=Path(str(raw["response_file"])),
        advisory_only=bool(raw["advisory_only"]),
        requires=tuple(Path(item) for item in requires),
        optional=tuple(Path(item) for item in optional),
    )


def detect_copilot_cli_status(
    *,
    timeout_seconds: float = 15.0,
    env: Mapping[str, str] | None = None,
) -> CopilotAdapterStatus:
    """Read-only availability/auth probe for status displays.

    This intentionally never sends a prompt to Copilot. GitHub CLI auth is only
    a weak local signal that the user has GitHub credentials configured.
    """

    effective_env = env or os.environ
    model = _configured_model(effective_env)
    try:
        copilot_path = _find_copilot_command(timeout_seconds)
        if not copilot_path:
            return CopilotAdapterStatus(
                model=model,
                connectivity="not_configured",
                adapter=ADAPTER,
                auth_status="unknown",
                cli_status="not_installed",
            )

        _copilot_version_proves_cli(copilot_path, timeout_seconds)

        auth_status = _detect_gh_auth_status(timeout_seconds)
        connectivity = "connected" if auth_status == "authenticated" else "unavailable"
        return CopilotAdapterStatus(
            model=model,
            connectivity=connectivity,
            adapter=CLI_ADAPTER,
            auth_status=auth_status,
            cli_status="installed",
            resolved_executable_path=copilot_path,
        )
    except Exception:
        return CopilotAdapterStatus(
            model=model,
            connectivity="unavailable",
            adapter=ADAPTER,
            auth_status="unknown",
            cli_status="error",
        )


def build_copilot_report_request(
    run_dir: str | Path,
    manifest: CopilotReportManifest,
    *,
    context: dict[str, Any] | None = None,
    status: CopilotAdapterStatus | None = None,
) -> CopilotReportRequest:
    run_path = Path(run_dir)
    warnings: list[str] = []
    missing_required = [path.as_posix() for path in manifest.requires if not (run_path / path).is_file()]
    missing_optional = [path.as_posix() for path in manifest.optional if not (run_path / path).is_file()]
    warnings.extend(f"missing optional Copilot report artifact: {path}" for path in missing_optional)

    artifacts = {
        "required": {
            path.as_posix(): _safe_read_artifact(run_path / path, warnings)
            for path in manifest.requires
            if (run_path / path).is_file()
        },
        "optional": {
            path.as_posix(): _safe_read_artifact(run_path / path, warnings)
            for path in manifest.optional
            if (run_path / path).is_file()
        },
    }
    supplied_context = {
        **(context or {}),
        "missing_optional_inputs": ", ".join(missing_optional),
        "missing_required_inputs": ", ".join(missing_required),
    }
    base_context = _build_template_context(
        artifacts,
        supplied_context,
        manifest,
        status or CopilotAdapterStatus(),
    )
    payload = {
        "manifest": {
            "id": manifest.id,
            "version": manifest.version,
            "type": manifest.type,
            "engine": manifest.engine,
            "advisory_only": manifest.advisory_only,
            "template_file": manifest.template_path.name,
        },
        "guardrails": {
            "advisory_only": True,
            "can_approve": False,
            "can_transform": False,
            "can_mutate_source": False,
            "can_change_gates": False,
            "can_override_status": False,
            "can_create_pr": False,
            "can_deploy": False,
            "can_decide_success": False,
        },
        "paths": {
            "output_file": manifest.output_file.as_posix(),
            "request_file": manifest.request_file.as_posix(),
            "response_file": manifest.response_file.as_posix(),
        },
        "artifacts": artifacts,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "warnings": warnings,
        "template_context": base_context,
        "adapter_status": (status or CopilotAdapterStatus()).to_dict(),
        "created_at": _utc_now(),
    }
    return CopilotReportRequest(
        payload=_redact(payload),
        warnings=warnings,
        missing_required=missing_required,
        missing_optional=missing_optional,
    )


def write_copilot_report_request(run_dir: str | Path, manifest: CopilotReportManifest, payload: dict[str, Any]) -> Path:
    request_path = manifest.request_path(run_dir)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request_path


def render_copilot_report_template(template_path: str | Path, context: dict[str, Any]) -> str:
    template = Path(template_path).read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1), "")
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)
        return str(value)

    return _PLACEHOLDER_RE.sub(replace, template)


def generate_copilot_report_skeleton(
    run_dir: str | Path,
    ai_hub_path: str | Path,
    *,
    context: dict[str, Any] | None = None,
    status: CopilotAdapterStatus | None = None,
) -> dict[str, Any]:
    manifest = load_copilot_report_manifest(ai_hub_path)
    effective_status = status or CopilotAdapterStatus(connectivity="not_configured", report_status="generated")
    request = build_copilot_report_request(
        run_dir,
        manifest,
        context=context,
        status=effective_status,
    )
    if request.missing_required:
        response_path = _write_copilot_report_response(
            run_dir,
            manifest,
            _build_response_payload(
                effective_status,
                manifest,
                report_status="skipped",
                warnings=[
                    *request.warnings,
                    "missing required Copilot report artifacts: "
                    + ", ".join(request.missing_required),
                ],
            ),
        )
        write_copilot_report_request(run_dir, manifest, request.payload)
        raise ValueError(
            "missing required Copilot report artifacts: " + ", ".join(request.missing_required)
        )

    request_path = write_copilot_report_request(run_dir, manifest, request.payload)
    report_path = manifest.output_path(run_dir)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_copilot_report_template(manifest.template_path, request.payload["template_context"]),
        encoding="utf-8",
    )
    response_payload = _build_response_payload(
        effective_status,
        manifest,
        report_status="generated",
        warnings=request.warnings,
    )
    response_path = _write_copilot_report_response(run_dir, manifest, response_payload)
    return {
        "artifact_refs": {
            "copilot_report_request": str(request_path),
            "copilot_report_response": str(response_path),
            "copilot_migration_report": str(report_path),
        },
        "warnings": request.warnings,
        "response": response_payload,
    }


def generate_copilot_report(
    run_dir: str | Path,
    ai_hub_path: str | Path,
    *,
    context: dict[str, Any] | None = None,
    status: CopilotAdapterStatus | None = None,
    timeout_seconds: float = 120.0,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    effective_env = env or os.environ
    provider = str(effective_env.get(PROVIDER_ENV, "")).strip().lower()
    if provider != CLI_ADAPTER:
        return generate_copilot_report_skeleton(run_dir, ai_hub_path, context=context, status=status)
    return _generate_copilot_cli_report(
        run_dir,
        ai_hub_path,
        context=context,
        status=status,
        timeout_seconds=timeout_seconds,
        env=effective_env,
    )


def write_failed_copilot_report_response(
    run_dir: str | Path,
    ai_hub_path: str | Path,
    *,
    warning: str,
    report_status: str = "failed",
) -> dict[str, Any]:
    manifest = load_copilot_report_manifest(ai_hub_path)
    response_payload = _build_response_payload(
        CopilotAdapterStatus(connectivity="not_configured", report_status=report_status),
        manifest,
        report_status=report_status,
        warnings=[warning],
    )
    response_path = _write_copilot_report_response(run_dir, manifest, response_payload)
    return {
        "artifact_refs": {"copilot_report_response": str(response_path)},
        "warnings": [warning],
        "response": response_payload,
    }


def _build_template_context(
    artifacts: dict[str, Any],
    supplied: dict[str, Any],
    manifest: CopilotReportManifest,
    status: CopilotAdapterStatus,
) -> dict[str, Any]:
    final_report = _artifact_payload(artifacts, "final/migration_report.json")
    orchestration = _artifact_payload(artifacts, "orchestration/orchestration_summary.json")
    approval = _artifact_payload(artifacts, "approval/approval_decision.json")
    approved_lock = _artifact_payload(artifacts, "approval/approved_plan_lock.json")
    test_report = _artifact_payload(artifacts, "test/post_transform/test_report.json")
    timing = _artifact_payload(artifacts, "performance/timing_report.json")
    source_stack = _dict(final_report.get("source_stack"))
    target_stack = _dict(final_report.get("target_stack"))
    test_totals = _dict(final_report.get("test_totals") or test_report.get("totals"))
    approval_info = _dict(final_report.get("approval"))
    warnings = list(final_report.get("warnings", []) or [])
    blockers = list(orchestration.get("blockers", []) or [])
    missing_optional = supplied.get("missing_optional_inputs", "")
    application_name = supplied.get("application_name") or Path(str(supplied.get("legacy_app_path") or "")).name
    live_generation = status.adapter == CLI_ADAPTER and status.report_status == "generated"
    fallback_used = status.report_status == "generated_with_fallback" or status.adapter != CLI_ADAPTER

    context = {
        "run_id": final_report.get("run_id") or orchestration.get("run_id") or supplied.get("run_id", ""),
        "application_name": application_name,
        "profile_id": supplied.get("profile_id", ""),
        "mode": supplied.get("mode", ""),
        "legacy_app_path": supplied.get("legacy_app_path", ""),
        "sandbox_path": final_report.get("sandbox_path") or supplied.get("sandbox_path", ""),
        "final_verdict": supplied.get("final_verdict") or final_report.get("final_status", ""),
        "orchestration_status": orchestration.get("orchestration_status") or final_report.get("orchestration_status", ""),
        "generated_at": _utc_now(),
        "preflight_status": supplied.get("preflight_status", ""),
        "analysis_status": supplied.get("analysis_status", ""),
        "planning_status": supplied.get("planning_status", ""),
        "assessment_status": supplied.get("assessment_status", ""),
        "approval_status": approval_info.get("status") or final_report.get("approval_status", ""),
        "transform_status": final_report.get("transform_status", ""),
        "build_status": final_report.get("build_status", ""),
        "test_status": final_report.get("test_status") or test_report.get("test_status", ""),
        "final_report_status": "generated",
        "source_java_version": source_stack.get("java", ""),
        "target_java_version": target_stack.get("java", ""),
        "source_spring_boot_version": source_stack.get("spring_boot", ""),
        "target_spring_boot_version": target_stack.get("spring_boot", ""),
        "source_spring_framework_version": source_stack.get("spring_framework", ""),
        "target_spring_framework_version": target_stack.get("spring_framework", ""),
        "source_build_tool": source_stack.get("build_tool", ""),
        "target_build_tool": target_stack.get("build_tool") or target_stack.get("build", ""),
        "source_packaging": source_stack.get("packaging", ""),
        "target_packaging": target_stack.get("packaging", ""),
        "migration_type": "sandbox",
        "profile_risk_level": final_report.get("risk_level", ""),
        "requires_human_approval": final_report.get("requires_human_approval", ""),
        "production_allowed": final_report.get("production_allowed", ""),
        "fallback_profile": final_report.get("fallback_profile", ""),
        "approval_decision": approval.get("decision") or approval_info.get("decision", ""),
        "approved_by": approval.get("approved_by") or approval_info.get("approved_by", ""),
        "decided_at": approval.get("decided_at", ""),
        "approval_source": approval.get("source", ""),
        "approval_comments": approval.get("comments", ""),
        "approval_summary": approval.get("summary", ""),
        "source_mutation_status": "not_mutated",
        "openrewrite_status": final_report.get("transform_status", ""),
        "deterministic_patch_status": final_report.get("transform_status", ""),
        "ledger_status": "present" if _artifact_payload(artifacts, "workspaces/sandbox/.migration/ledger.json") else "missing",
        "tests_run": test_totals.get("tests", 0),
        "tests_passed": test_totals.get("passed", 0),
        "tests_failed": test_totals.get("failures", 0),
        "test_errors": test_totals.get("errors", 0),
        "tests_skipped": test_totals.get("skipped", 0),
        "copilot_input_package_status": "ready",
        "missing_optional_inputs": missing_optional,
        "missing_required_inputs": "",
        "copilot_provider": status.provider,
        "copilot_adapter": status.adapter,
        "copilot_connectivity": status.connectivity,
        "copilot_model": _normalize_model(status.model),
        "copilot_model_source": _model_source(status.model),
        "copilot_prompt_template_id": manifest.id,
        "copilot_prompt_template_version": manifest.version,
        "copilot_enabled": "true",
        "copilot_auth_status": status.auth_status,
        "copilot_cli_status": status.cli_status,
        "copilot_available": "true" if live_generation else "false",
        "copilot_live_generation": "true" if live_generation else "false",
        "copilot_fallback_used": "true" if fallback_used else "false",
        "copilot_fallback_reason": (
            "local deterministic template used; live Copilot CLI is not called"
            if fallback_used
            else ""
        ),
        "approved_plan_lock_status": "present" if approved_lock else "missing",
        "orchestration_artifacts_valid": orchestration.get("orchestration_artifacts_valid", ""),
        "final_stop_reason": "sandbox migration candidate only",
        "final_conclusion": supplied.get("final_conclusion", ""),
        "recommended_next_step": supplied.get("recommended_next_step", "manual review"),
        "total_machine_duration": _total_machine_duration(timing),
        "risk_summary": "; ".join(str(item) for item in warnings[:3]),
        "manual_review_notes": "",
        "test_notes": "",
        "build_notes": "",
    }
    for index, warning in enumerate(warnings[:3], start=1):
        context[f"warning_{index}_code"] = str(warning)
        context[f"warning_{index}_impact"] = "review"
        context[f"warning_{index}_action"] = "manual review"
    for index, blocker in enumerate(blockers[:2], start=1):
        context[f"blocker_{index}"] = str(blocker)
        context[f"blocker_{index}_status"] = "open"
    context.update(_timing_template_context(timing))
    context.update(_build_command_context(timing, test_report, final_report))
    patch_defaults = {
        key: "None recorded for this profile"
        for key in _template_only_defaults()
        if key.startswith("patch_") or key == "deterministic_patch_summary"
    }
    context.update({key: "not_available" for key in _template_only_defaults() if key not in context})
    context.update({key: value for key, value in patch_defaults.items() if context.get(key) == "not_available"})
    context.update({key: value for key, value in supplied.items() if key not in {"missing_optional_inputs"}})
    return _redact({key: _display_value(value) for key, value in context.items()})


def _build_response_payload(
    status: CopilotAdapterStatus,
    manifest: CopilotReportManifest,
    *,
    report_status: str,
    warnings: list[str],
) -> dict[str, Any]:
    return _redact(
        {
            "provider": PROVIDER,
            "adapter": status.adapter,
            "connectivity": status.connectivity,
            "model": _normalize_model(status.model),
            "auth_status": status.auth_status,
            "cli_status": status.cli_status,
            "resolved_executable_basename": _safe_executable_basename(status.resolved_executable),
            "report_status": report_status,
            "advisory_only": True,
            "can_approve": False,
            "can_transform": False,
            "can_change_gates": False,
            "can_mutate_source": False,
            "can_override_status": False,
            "can_create_pr": False,
            "can_deploy": False,
            "report_file": manifest.output_file.as_posix(),
            "request_file": manifest.request_file.as_posix(),
            "warnings": warnings,
            "created_at": _utc_now(),
        }
    )


def _write_copilot_report_response(
    run_dir: str | Path,
    manifest: CopilotReportManifest,
    payload: dict[str, Any],
) -> Path:
    response_path = manifest.response_path(run_dir)
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return response_path


def _template_only_defaults() -> tuple[str, ...]:
    return (
        "java_gap_status", "java_gap_notes", "boot_gap_status", "boot_gap_notes",
        "framework_gap_status", "framework_gap_notes", "jakarta_status", "jakarta_notes",
        "security_status", "security_notes", "batch_status", "batch_notes",
        "test_dependency_status", "test_dependency_notes", "preflight_started_at",
        "preflight_ended_at", "preflight_duration", "analysis_started_at", "analysis_ended_at",
        "analysis_duration", "planning_started_at", "planning_ended_at", "planning_duration",
        "assessment_started_at", "assessment_ended_at", "assessment_duration", "approval_started_at",
        "approval_ended_at", "sandbox_prep_status", "sandbox_prep_started_at", "sandbox_prep_ended_at",
        "sandbox_prep_duration", "transform_started_at", "transform_ended_at", "transform_duration",
        "build_started_at", "build_ended_at", "build_duration", "test_started_at", "test_ended_at",
        "test_duration", "final_report_started_at", "final_report_ended_at", "final_report_duration",
        "patch_1_id", "patch_1_file", "patch_1_reason", "patch_1_status",
        "patch_2_id", "patch_2_file", "patch_2_reason", "patch_2_status",
        "patch_3_id", "patch_3_file", "patch_3_reason", "patch_3_status",
        "patch_4_id", "patch_4_file", "patch_4_reason", "patch_4_status",
        "deterministic_patch_summary", "baseline_java_runtime", "baseline_build_command",
        "baseline_build_status", "target_java_runtime", "target_build_command", "target_build_status",
        "build_report_path", "build_log_path", "review_focus_1", "review_focus_2",
        "review_focus_3", "review_focus_4",
    )


def _generate_copilot_cli_report(
    run_dir: str | Path,
    ai_hub_path: str | Path,
    *,
    context: dict[str, Any] | None,
    status: CopilotAdapterStatus | None,
    timeout_seconds: float,
    env: Mapping[str, str],
) -> dict[str, Any]:
    manifest = load_copilot_report_manifest(ai_hub_path)
    detected_status = status or detect_copilot_cli_status(timeout_seconds=15.0, env=env)
    cli_status = CopilotAdapterStatus(
        provider=PROVIDER,
        adapter=CLI_ADAPTER,
        model=_configured_model(env),
        connectivity=detected_status.connectivity,
        report_status="generated",
        auth_status=detected_status.auth_status,
        cli_status=detected_status.cli_status,
        resolved_executable_path=detected_status.resolved_executable_path,
    )
    request = build_copilot_report_request(run_dir, manifest, context=context, status=cli_status)
    if request.missing_required:
        write_copilot_report_request(run_dir, manifest, request.payload)
        warning = "missing required Copilot report artifacts: " + ", ".join(request.missing_required)
        response_path = _write_copilot_report_response(
            run_dir,
            manifest,
            _build_response_payload(cli_status, manifest, report_status="skipped", warnings=[*request.warnings, warning]),
        )
        raise ValueError(warning)

    request_path = write_copilot_report_request(run_dir, manifest, request.payload)
    prompt = _build_strict_copilot_prompt(request.payload)
    warning = ""
    try:
        markdown = _invoke_copilot_cli(prompt, cli_status.model, timeout_seconds, cli_status.resolved_executable_path)
        report_status = "generated"
        response_status = cli_status
    except Exception as exc:
        report_status = "generated_with_fallback"
        path_present = bool(cli_status.resolved_executable_path)
        warning = (
            "copilot CLI report generation failed; used deterministic fallback: "
            + _safe_exception_hint(exc)
            + f" (internal_resolved_executable_path_present={str(path_present).lower()})"
        )
        response_status = CopilotAdapterStatus(
            provider=PROVIDER,
            adapter=ADAPTER,
            model=cli_status.model,
            connectivity=cli_status.connectivity,
            report_status=report_status,
            auth_status=cli_status.auth_status,
            cli_status=cli_status.cli_status,
            resolved_executable_path=cli_status.resolved_executable_path,
        )
        fallback_request = build_copilot_report_request(
            run_dir,
            manifest,
            context=context,
            status=response_status,
        )
        markdown = render_copilot_report_template(
            manifest.template_path,
            fallback_request.payload["template_context"],
        )

    report_path = manifest.output_path(run_dir)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    warnings = [*request.warnings, *([warning] if warning else [])]
    response_payload = _build_response_payload(
        response_status,
        manifest,
        report_status=report_status,
        warnings=warnings,
    )
    response_path = _write_copilot_report_response(run_dir, manifest, response_payload)
    return {
        "artifact_refs": {
            "copilot_report_request": str(request_path),
            "copilot_report_response": str(response_path),
            "copilot_migration_report": str(report_path),
        },
        "warnings": warnings,
        "response": response_payload,
    }


def _build_strict_copilot_prompt(request_payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Generate a final migration report in Markdown from this JSON request.",
            "Use only the facts in the JSON. Do not request input. Do not run commands. Do not write files.",
            "Preserve these guardrails: advisory_only=true, can_approve=false, can_transform=false, "
            "can_change_gates=false, can_mutate_source=false, can_override_status=false, "
            "can_create_pr=false, can_deploy=false.",
            "Return Markdown only.",
            json.dumps(request_payload, indent=2, sort_keys=True),
        ]
    )


def _invoke_copilot_cli(prompt: str, model: str, timeout_seconds: float, resolved_executable_path: str = "") -> str:
    command = resolved_executable_path
    if not command:
        raise FileNotFoundError("Copilot executable path was not resolved for live call")
    completed = subprocess.run(
        [command, "-p", prompt, "-s", "--no-ask-user", "--model", model or DEFAULT_COPILOT_MODEL],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        raise RuntimeError("copilot CLI returned non-zero status")
    if not output:
        raise RuntimeError("copilot CLI returned empty output")
    if _looks_like_prompt_for_input(output) or _looks_like_prompt_for_input(completed.stderr or ""):
        raise RuntimeError("copilot CLI requested interactive input")
    return _redact(output)


def _looks_like_prompt_for_input(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("ask user", "continue?", "confirm", "waiting for input"))


def _artifact_payload(artifacts: dict[str, Any], relative_path: str) -> dict[str, Any]:
    required = _dict(artifacts.get("required"))
    optional = _dict(artifacts.get("optional"))
    payload = required.get(relative_path) or optional.get(relative_path) or {}
    return payload if isinstance(payload, dict) else {}


def _safe_read_artifact(path: Path, warnings: list[str]) -> Any:
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        warnings.append(f"unable to read Copilot report artifact {path.name}: {exc}")
        return {}
    return _redact(payload)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _model_source(model: str) -> str:
    return "configured" if model and model != "unknown" else "unknown"


def _configured_model(env: Mapping[str, str]) -> str:
    configured = str(env.get(MODEL_ENV, "")).strip()
    if configured:
        return _normalize_model(str(_redact(configured)))
    return DEFAULT_COPILOT_MODEL


def _normalize_model(model: str) -> str:
    value = str(model or "").strip()
    while value.startswith(("configured:", "detected:")):
        value = value.split(":", 1)[1].strip()
    return value or DEFAULT_COPILOT_MODEL


def _find_copilot_command(timeout_seconds: float) -> str | None:
    preferred_names = ("copilot.cmd", "copilot") if os.name == "nt" else ("copilot",)
    for name in preferred_names:
        found = shutil.which(name)
        if found:
            return found
    where_commands = tuple(dict.fromkeys(item for item in (shutil.which("where.exe"), shutil.which("where")) if item))
    for where_exe in where_commands:
        try:
            completed = subprocess.run(
                [where_exe, "copilot"],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, TimeoutError):
            continue
        if completed.returncode != 0:
            continue
        candidates = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
        cmd_candidate = next(
            (candidate for candidate in candidates if _path_basename(candidate).lower() == "copilot.cmd"),
            None,
        )
        if cmd_candidate and _looks_like_copilot_command(cmd_candidate):
            return cmd_candidate
        for candidate in candidates:
            if _looks_like_copilot_command(candidate):
                return candidate
    return None


def _copilot_version_proves_cli(command: str, timeout_seconds: float) -> bool:
    try:
        completed = subprocess.run(
            [command, "version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return False
    return _looks_like_copilot_version(completed.stdout or "")


def _detect_gh_auth_status(timeout_seconds: float) -> str:
    gh_path = shutil.which("gh")
    if not gh_path:
        return "unknown"
    try:
        completed = subprocess.run(
            [gh_path, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return "unknown"
    auth_text = f"{completed.stdout or ''}\n{completed.stderr or ''}".lower()
    return "authenticated" if completed.returncode == 0 and "logged in" in auth_text else "unknown"


def _looks_like_copilot_command(path: str) -> bool:
    name = _path_basename(path).lower()
    return name in {"copilot", "copilot.exe", "copilot.cmd", "copilot.bat"} or name.startswith("copilot.")


def _looks_like_copilot_version(text: str) -> bool:
    lowered = text.lower()
    return "github copilot cli" in lowered or "copilot cli" in lowered


def _safe_executable_basename(path: str) -> str:
    return _path_basename(path) if path else ""


def _path_basename(path: str) -> str:
    return re.split(r"[\\/]", str(path))[-1]


def _safe_exception_hint(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError) and not str(exc):
        return "FileNotFoundError: Copilot executable path was not resolved for live call"
    message = str(exc).strip()
    if isinstance(exc, FileNotFoundError) and "resolved for live call" not in message:
        message = "Copilot executable path was not resolved for live call"
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {_redact(message)}"


def _timing_template_context(timing: dict[str, Any]) -> dict[str, Any]:
    phase_durations = _dict(timing.get("phase_durations_seconds"))
    result: dict[str, Any] = {}
    phase_names = {
        "preflight": "preflight",
        "analysis": "analysis",
        "planning": "planning",
        "assessment": "assessment",
        "approval": "approval",
        "sandbox_prep": "sandbox_prep",
        "transform": "transform",
        "build": "build",
        "test": "test",
        "final_report": "final_report",
    }
    for phase, prefix in phase_names.items():
        if phase in phase_durations:
            result[f"{prefix}_duration"] = f"{phase_durations[phase]}s"
    return result


def _build_command_context(timing: dict[str, Any], test_report: dict[str, Any], final_report: dict[str, Any]) -> dict[str, Any]:
    commands = [row for row in list(timing.get("commands", []) or []) if isinstance(row, dict)]
    build_command = _first_command(commands, ("build", "maven", "mvn"))
    test_command = _first_command(commands, ("test", "surefire", "mvn"))
    return {
        "target_build_command": build_command or test_command,
        "target_build_status": final_report.get("build_status", ""),
        "target_java_runtime": test_report.get("java_runtime") or final_report.get("target_java_runtime", ""),
        "build_report_path": final_report.get("build_report_path", ""),
        "build_log_path": final_report.get("build_log_path") or test_report.get("test_log_path", ""),
        "test_notes": "Command: " + test_command if test_command else "",
    }


def _first_command(commands: list[dict[str, Any]], markers: tuple[str, ...]) -> str:
    for row in commands:
        label = str(row.get("label") or "").lower()
        command = " ".join(str(part) for part in list(row.get("command") or []) if str(part))
        haystack = f"{label} {command}".lower()
        if any(marker in haystack for marker in markers):
            return command
    return ""


def _total_machine_duration(timing: dict[str, Any]) -> str:
    phase_durations = _dict(timing.get("phase_durations_seconds"))
    value = phase_durations.get("total_run") or timing.get("total_machine_duration")
    return f"{value}s" if isinstance(value, (int, float)) else str(value or "")


def _display_value(value: Any) -> Any:
    if value is None:
        return "not_available"
    if isinstance(value, str):
        return value if value.strip() else "not_available"
    return value


def _redact(value: Any, key: str = "") -> Any:
    if any(part in key.lower() for part in _SECRET_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_VALUE_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def debug_status_payload(env: Mapping[str, str] | None = None) -> dict[str, str]:
    effective_env = env or os.environ
    status = detect_copilot_cli_status(timeout_seconds=15.0, env=effective_env)
    report_provider = str(effective_env.get(PROVIDER_ENV, "")).strip() or status.adapter
    return {
        "provider": CLI_ADAPTER if report_provider == CLI_ADAPTER else status.provider,
        "model": _configured_model(effective_env),
        "cli_status": status.cli_status,
        "auth_status": status.auth_status,
        "resolved_executable_basename": _safe_executable_basename(status.resolved_executable),
        "report_provider": report_provider,
    }


def _print_debug_status() -> None:
    for key, value in debug_status_payload().items():
        print(f"{key}={value}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Copilot final report diagnostics")
    parser.add_argument("--debug-status", action="store_true", help="print debug-safe Copilot report status")
    args = parser.parse_args()
    if args.debug_status:
        _print_debug_status()
        return
    parser.print_help()


if __name__ == "__main__":
    main()
