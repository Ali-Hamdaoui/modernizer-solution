from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from migration_factory.contracts import SCHEMA_VERSION


@dataclass(frozen=True)
class FinalReportResult:
    artifact_refs: dict[str, str]
    blockers: list[str]
    warnings: list[str]


_COPILOT_STATEMENT_ENV = "AI_MIGRATION_ENABLE_COPILOT_STATEMENT"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_SANDBOX_ONLY_DISCLAIMER = (
    "This is a sandbox migration candidate only; no production promotion, no PR, no deployment."
)


def generate_final_migration_report(state: dict[str, Any]) -> FinalReportResult:
    run_dir = Path(str(state.get("run_dir") or ""))
    artifact_refs = dict(state.get("artifact_refs", {}) or {})
    blockers: list[str] = []
    warnings: list[str] = []

    if not run_dir:
        return FinalReportResult(artifact_refs={}, blockers=["run_dir is required"], warnings=[])

    required_ref_names = (
        "approval_decision",
        "approved_plan_lock",
        "transformation_execution_plan",
        "migration_ledger",
        "orchestration_summary",
        "post_transform_test_report",
    )
    for ref_name in required_ref_names:
        ref = str(artifact_refs.get(ref_name) or "")
        if not ref:
            blockers.append(f"missing required artifact ref for final report: {ref_name}")
            continue
        if not Path(ref).is_file():
            blockers.append(f"missing required artifact file for final report: {ref_name}")

    if blockers:
        return FinalReportResult(artifact_refs={}, blockers=blockers, warnings=warnings)

    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    json_path = final_dir / "migration_report.json"
    md_path = final_dir / "migration_summary.md"

    assessment_report = _read_json(run_dir / "assessment" / "assessment_report.json", warnings)
    approval_decision = _read_json(Path(artifact_refs["approval_decision"]), warnings)
    approved_plan_lock = _read_json(Path(artifact_refs["approved_plan_lock"]), warnings)
    execution_plan = _read_yaml(Path(artifact_refs["transformation_execution_plan"]), warnings)
    test_report = _read_json(Path(artifact_refs["post_transform_test_report"]), warnings)
    orchestration_summary = _read_json(Path(artifact_refs["orchestration_summary"]), warnings)

    test_status = str(state.get("test_status") or "")
    totals = dict(state.get("test_totals", {}) or {})
    if isinstance(test_report, dict):
        test_status = str(test_report.get("test_status") or test_status)
        report_totals = test_report.get("totals")
        if isinstance(report_totals, dict):
            totals = dict(report_totals)

    source_stack = _object_or_empty((assessment_report or {}).get("source_stack"))
    target_stack = _object_or_empty((assessment_report or {}).get("target_stack"))
    recipes = _extract_recipes(execution_plan or {})

    report_payload = {
        "run_id": state.get("run_id", ""),
        "source_stack": source_stack,
        "target_stack": target_stack,
        "approval": {
            "status": state.get("approval_status", ""),
            "decision": (approval_decision or {}).get("decision", state.get("approval_decision")),
            "approved_by": state.get("approved_by", ""),
            "approval_ref": artifact_refs.get("approval_decision", ""),
        },
        "lock_status": {
            "status": "LOCKED" if isinstance(approved_plan_lock, dict) else "UNKNOWN",
            "lock_ref": artifact_refs.get("approved_plan_lock", ""),
        },
        "transform_status": state.get("transform_status", ""),
        "build_status": state.get("build_status", ""),
        "test_status": test_status,
        "test_totals": totals,
        "recipes": recipes,
        "artifact_refs": {
            **artifact_refs,
            "final_migration_report": str(json_path),
            "final_migration_summary": str(md_path),
        },
        "timing": {
            "timing_report": artifact_refs.get("timing_report", ""),
            "timing_summary": artifact_refs.get("timing_summary", ""),
        },
        "warnings": list(state.get("warnings", []) or []),
        "limitations": [
            "No production promotion performed.",
            "No pull request creation performed.",
        ],
        "sandbox_path": state.get("sandbox_path", ""),
        "log_paths": _collect_log_paths(state, artifact_refs, test_report, orchestration_summary),
        "created_at": _utc_now(),
    }
    if warnings:
        report_payload["warnings"] = [
            *list(report_payload.get("warnings", []) or []),
            *warnings,
        ]

    generated_artifact_refs: dict[str, str] = {
        "final_migration_report": str(json_path),
        "final_migration_summary": str(md_path),
    }
    if _copilot_statement_enabled():
        try:
            copilot_artifact_refs = _generate_copilot_advisory_statement(report_payload, final_dir)
        except Exception as exc:  # pragma: no cover - exercised through monkeypatched failure
            warning = f"copilot advisory statement generation failed: {exc}"
            warnings.append(warning)
            report_payload["warnings"] = [
                *list(report_payload.get("warnings", []) or []),
                warning,
            ]
        else:
            generated_artifact_refs.update(copilot_artifact_refs)
            report_payload["artifact_refs"] = {
                **dict(report_payload.get("artifact_refs", {}) or {}),
                **copilot_artifact_refs,
            }

    json_path.write_text(json.dumps(report_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_build_markdown_summary(report_payload), encoding="utf-8")
    return FinalReportResult(
        artifact_refs=generated_artifact_refs,
        blockers=[],
        warnings=warnings,
    )


def _build_markdown_summary(payload: dict[str, Any]) -> str:
    totals = payload.get("test_totals", {}) or {}
    lines = [
        "# Migration Summary",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Approval: {payload.get('approval', {}).get('decision', '')}",
        f"- Transform: {payload.get('transform_status', '')}",
        f"- Build: {payload.get('build_status', '')}",
        f"- Test: {payload.get('test_status', '')}",
        (
            "- Test Totals: "
            f"tests={totals.get('tests', 0)} "
            f"passed={totals.get('passed', 0)} "
            f"failures={totals.get('failures', 0)} "
            f"errors={totals.get('errors', 0)} "
            f"skipped={totals.get('skipped', 0)}"
        ),
        "- Scope Limits: no production promotion, no PR creation",
        "",
        "POC-ready sandbox migration artifacts are captured under this run directory.",
    ]
    statement = payload.get("copilot_advisory_statement")
    if isinstance(statement, dict):
        artifact_refs = statement.get("artifact_refs", {})
        json_ref = artifact_refs.get("json", "") if isinstance(artifact_refs, dict) else ""
        md_ref = artifact_refs.get("markdown", "") if isinstance(artifact_refs, dict) else ""
        lines.extend(
            [
                "",
                "## Copilot Advisory Statement",
                "",
                _SANDBOX_ONLY_DISCLAIMER,
                "",
                f"- JSON: {json_ref}",
                f"- Markdown: {md_ref}",
            ]
        )
    return "\n".join(lines) + "\n"


def _copilot_statement_enabled() -> bool:
    return os.getenv(_COPILOT_STATEMENT_ENV, "").strip().lower() in _TRUE_VALUES


def _generate_copilot_advisory_statement(payload: dict[str, Any], final_dir: Path) -> dict[str, str]:
    json_path = final_dir / "copilot_migration_statement.json"
    md_path = final_dir / "copilot_migration_statement.md"
    statement_payload = _build_copilot_statement_payload(payload, json_path, md_path)
    json_path.write_text(json.dumps(statement_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_build_copilot_statement_markdown(statement_payload), encoding="utf-8")
    payload["copilot_advisory_statement"] = {
        "status": "USED",
        "provider": statement_payload["provider"],
        "adapter": statement_payload["adapter"],
        "disclaimer": statement_payload["disclaimer"],
        "artifact_refs": {
            "json": str(json_path),
            "markdown": str(md_path),
        },
    }
    return {
        "copilot_migration_statement_json": str(json_path),
        "copilot_migration_statement_md": str(md_path),
    }


def _build_copilot_statement_payload(payload: dict[str, Any], json_path: Path, md_path: Path) -> dict[str, Any]:
    artifact_refs = dict(payload.get("artifact_refs", {}) or {})
    approval = dict(payload.get("approval", {}) or {})
    timing = dict(payload.get("timing", {}) or {})
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": payload.get("run_id", ""),
        "provider": "github_copilot",
        "adapter": "local_template_stub",
        "status": "USED",
        "advisory_only": True,
        "can_approve": False,
        "can_transform": False,
        "can_change_gates": False,
        "can_mutate_source": False,
        "can_override_status": False,
        "disclaimer": _SANDBOX_ONLY_DISCLAIMER,
        "facts": {
            "approval_decision": approval.get("decision", ""),
            "approval_status": approval.get("status", ""),
            "approved_plan_lock": artifact_refs.get("approved_plan_lock", ""),
            "transform_status": payload.get("transform_status", ""),
            "build_status": payload.get("build_status", ""),
            "test_status": payload.get("test_status", ""),
            "test_totals": dict(payload.get("test_totals", {}) or {}),
            "target_versions": dict(payload.get("target_stack", {}) or {}),
            "warnings": list(payload.get("warnings", []) or []),
            "timing": {
                **timing,
                "timing_report": artifact_refs.get("timing_report", timing.get("timing_report", "")),
                "timing_summary": artifact_refs.get("timing_summary", timing.get("timing_summary", "")),
            },
            "limitations": list(payload.get("limitations", []) or []),
            "sandbox_path": payload.get("sandbox_path", ""),
        },
        "statement": _statement_text(payload),
        "artifact_refs": {
            "self": str(json_path),
            "markdown": str(md_path),
        },
        "created_at": _utc_now(),
    }


def _statement_text(payload: dict[str, Any]) -> str:
    approval = dict(payload.get("approval", {}) or {})
    totals = dict(payload.get("test_totals", {}) or {})
    target_stack = dict(payload.get("target_stack", {}) or {})
    target_versions = ", ".join(f"{key}={value}" for key, value in sorted(target_stack.items())) or "not recorded"
    return (
        "GitHub Copilot advisory review is based only on deterministic final report facts. "
        f"Approval decision is {approval.get('decision', '')}; "
        f"transform status is {payload.get('transform_status', '')}; "
        f"build status is {payload.get('build_status', '')}; "
        f"test status is {payload.get('test_status', '')} with "
        f"{totals.get('tests', 0)} tests, {totals.get('passed', 0)} passed, "
        f"{totals.get('failures', 0)} failures, {totals.get('errors', 0)} errors, "
        f"and {totals.get('skipped', 0)} skipped. "
        f"Target versions: {target_versions}. "
        f"Sandbox path: {payload.get('sandbox_path', '')}. "
        f"{_SANDBOX_ONLY_DISCLAIMER}"
    )


def _build_copilot_statement_markdown(payload: dict[str, Any]) -> str:
    facts = dict(payload.get("facts", {}) or {})
    totals = dict(facts.get("test_totals", {}) or {})
    lines = [
        "# Copilot Advisory Statement",
        "",
        str(payload.get("disclaimer", _SANDBOX_ONLY_DISCLAIMER)),
        "",
        "## Guardrails",
        "",
        f"- advisory_only: {str(payload.get('advisory_only')).lower()}",
        f"- can_approve: {str(payload.get('can_approve')).lower()}",
        f"- can_transform: {str(payload.get('can_transform')).lower()}",
        f"- can_change_gates: {str(payload.get('can_change_gates')).lower()}",
        f"- can_mutate_source: {str(payload.get('can_mutate_source')).lower()}",
        f"- can_override_status: {str(payload.get('can_override_status')).lower()}",
        "",
        "## Deterministic Facts",
        "",
        f"- Approval decision: {facts.get('approval_decision', '')}",
        f"- Approved plan lock: {facts.get('approved_plan_lock', '')}",
        f"- Transform status: {facts.get('transform_status', '')}",
        f"- Build status: {facts.get('build_status', '')}",
        f"- Test status: {facts.get('test_status', '')}",
        (
            "- Test totals: "
            f"tests={totals.get('tests', 0)} "
            f"passed={totals.get('passed', 0)} "
            f"failures={totals.get('failures', 0)} "
            f"errors={totals.get('errors', 0)} "
            f"skipped={totals.get('skipped', 0)}"
        ),
        f"- Target versions: {json.dumps(facts.get('target_versions', {}), sort_keys=True)}",
        f"- Timing summary: {dict(facts.get('timing', {}) or {}).get('timing_summary', '')}",
        f"- Sandbox path: {facts.get('sandbox_path', '')}",
        "",
        "## Advisory",
        "",
        str(payload.get("statement", "")),
    ]
    warnings = list(facts.get("warnings", []) or [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    limitations = list(facts.get("limitations", []) or [])
    if limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {limitation}" for limitation in limitations)
    return "\n".join(lines) + "\n"


def _collect_log_paths(
    state: dict[str, Any],
    artifact_refs: dict[str, str],
    test_report: dict[str, Any] | None,
    orchestration_summary: dict[str, Any] | None,
) -> dict[str, str]:
    log_paths: dict[str, str] = {}
    for key in ("phase2_log", "post_transform_test_log"):
        ref = str(artifact_refs.get(key) or "")
        if ref:
            log_paths[key] = ref
    transform_log = str(state.get("transform_log_path") or "")
    if transform_log:
        log_paths["transform_log_path"] = transform_log
    if isinstance(test_report, dict):
        test_log_path = str(test_report.get("test_log_path") or "")
        source_log_path = str(test_report.get("source_log_path") or "")
        if test_log_path:
            log_paths["test_log_path"] = test_log_path
        if source_log_path:
            log_paths["source_log_path"] = source_log_path
    if isinstance(orchestration_summary, dict):
        orchestration_log = str(orchestration_summary.get("log_path") or "")
        if orchestration_log:
            log_paths["orchestration_log_path"] = orchestration_log
    return log_paths


def _extract_recipes(execution_plan: dict[str, Any]) -> list[str]:
    recipes: list[str] = []
    for key in ("recipes", "openrewrite_recipes"):
        value = execution_plan.get(key)
        if isinstance(value, list):
            recipes.extend(str(item) for item in value if isinstance(item, (str, int, float)))
    if recipes:
        return recipes
    steps = execution_plan.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_recipes = step.get("recipes")
            if isinstance(step_recipes, list):
                recipes.extend(str(item) for item in step_recipes if isinstance(item, (str, int, float)))
    return recipes


def _object_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _read_json(path: Path, warnings: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"unable to parse {path.name}: {exc}")
        return None
    if isinstance(payload, dict):
        return payload
    warnings.append(f"unexpected payload type for {path.name}")
    return None


def _read_yaml(path: Path, warnings: list[str]) -> dict[str, Any] | None:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        warnings.append(f"unable to parse {path.name}: {exc}")
        return None
    if isinstance(payload, dict):
        return payload
    warnings.append(f"unexpected payload type for {path.name}")
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
