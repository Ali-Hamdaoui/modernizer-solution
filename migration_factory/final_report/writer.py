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

    failure_report = _is_failed_sandbox_report(state)
    required_ref_names = (
        "approval_decision",
        "approved_plan_lock",
        "transformation_execution_plan",
        "migration_ledger",
        "orchestration_summary",
    )
    if not failure_report:
        required_ref_names = (*required_ref_names, "post_transform_test_report")
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
    orchestration_summary = _read_json(Path(artifact_refs["orchestration_summary"]), warnings)
    migration_plan = _read_yaml(run_dir / "planning" / "migration_plan.yaml", warnings)
    test_report = _read_optional_json(artifact_refs.get("post_transform_test_report"), warnings)
    build_error_contract = _read_optional_json(artifact_refs.get("build_error_contract"), warnings)
    failure_classification_path = str(
        artifact_refs.get("post_transform_failure_classification")
        or (build_error_contract or {}).get("failure_classification_path")
        or ""
    )
    failure_classification = _read_optional_json(failure_classification_path, warnings)

    test_status = str(state.get("test_status") or "")
    test_severity = ""
    test_message = ""
    test_warnings: list[str] = []
    totals = dict(state.get("test_totals", {}) or {})
    if isinstance(test_report, dict):
        test_status = str(test_report.get("test_status") or test_status)
        test_severity = str(test_report.get("severity") or "")
        test_message = str(test_report.get("message") or "")
        raw_warnings = test_report.get("warnings")
        if isinstance(raw_warnings, list):
            test_warnings = [str(item) for item in raw_warnings]
        report_totals = test_report.get("totals")
        if isinstance(report_totals, dict):
            totals = dict(report_totals)

    source_stack = _object_or_empty((assessment_report or {}).get("source_stack"))
    target_stack = {
        **_object_or_empty((migration_plan or {}).get("target_stack")),
        **_object_or_empty((assessment_report or {}).get("target_stack")),
    }
    recipes = _extract_recipes(execution_plan or {})
    profile_governance = _object_or_empty((migration_plan or {}).get("profile_governance"))
    selected_route_id = str((migration_plan or {}).get("selected_route_id") or "")
    route_strategy = str((migration_plan or {}).get("route_strategy") or "")
    selected_hops = _list_or_empty((migration_plan or {}).get("selected_hops"))
    boot4_warnings = _boot4_warnings(target_stack, state, assessment_report, migration_plan)
    test_confidence = _test_confidence_level(test_status)
    zero_test_warnings = _zero_test_warnings(test_status)
    report_warnings = _dedupe_preserve_order(
        [
            *list(state.get("warnings", []) or []),
            *test_warnings,
            *zero_test_warnings,
            *boot4_warnings,
        ]
    )
    strategy = route_strategy or str(profile_governance.get("strategy") or "")
    failed_unit = _failed_unit(state, build_error_contract)
    failure_category_counts = _failure_category_counts(build_error_contract, failure_classification)
    top_failed_tests = _top_failed_tests(failure_classification)
    human_review_required = failure_report or bool((migration_plan or {}).get("requires_human_approval", True))
    classification_ref = (
        failure_classification_path if failure_classification_path and Path(failure_classification_path).is_file() else ""
    )
    build_error_ref = str(artifact_refs.get("build_error_contract") or "")
    consumer_compatibility = _read_optional_json(artifact_refs.get("consumer_compatibility_report"), warnings)

    report_payload = {
        "run_id": state.get("run_id", ""),
        "final_status": state.get("final_status", ""),
        "orchestration_status": state.get("orchestration_status", ""),
        "source_stack": source_stack,
        "target_stack": target_stack,
        "risk_level": profile_governance.get("risk_level") or (migration_plan or {}).get("risk", ""),
        "strategy": strategy,
        "selected_route_id": selected_route_id,
        "route_strategy": route_strategy,
        "selected_hops": selected_hops,
        "fallback_profile": profile_governance.get("fallback_profile", ""),
        "production_allowed": (
            False if profile_governance.get("production_allowed") is None else profile_governance.get("production_allowed")
        ),
        "sandbox_migration_executed": _sandbox_migration_executed(state),
        "production_promotion_executed": False,
        "human_review_required": human_review_required,
        "requires_human_approval": (migration_plan or {}).get("requires_human_approval", True),
        "failed_unit": failed_unit,
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
        "test_severity": test_severity,
        "test_message": test_message,
        "test_confidence": test_confidence,
        "test_totals": totals,
        "build_error_contract_path": build_error_ref,
        "post_transform_failure_classification_path": classification_ref,
        "consumer_compatibility_status": str((consumer_compatibility or {}).get("status") or ""),
        "consumer_compatibility_report_path": str(artifact_refs.get("consumer_compatibility_report") or ""),
        "category_counts": failure_category_counts,
        "top_affected_tests": top_failed_tests,
        "recipes": recipes,
        "executed_recipes": recipes,
        "boot4_warnings": boot4_warnings,
        "artifact_refs": {
            **artifact_refs,
            "final_migration_report": str(json_path),
            "final_migration_summary": str(md_path),
        },
        "timing": {
            "timing_report": artifact_refs.get("timing_report", ""),
            "timing_summary": artifact_refs.get("timing_summary", ""),
        },
        "warnings": report_warnings,
        "limitations": [
            "No production promotion performed.",
            "No pull request creation performed.",
            "No deployment performed.",
            "No automatic merge performed.",
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
    target_stack = dict(payload.get("target_stack", {}) or {})
    recipes = list(payload.get("recipes", []) or [])
    lines = [
        "# Migration Summary",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Target Java: {target_stack.get('java', '')}",
        f"- Target Spring Boot: {target_stack.get('spring_boot', '')}",
        f"- Target Spring Framework: {target_stack.get('spring_framework', '')}",
        f"- Risk Level: {payload.get('risk_level', '')}",
        f"- Strategy: {payload.get('strategy', '')}",
        f"- Selected Route ID: {payload.get('selected_route_id', '')}",
        f"- Route Strategy: {payload.get('route_strategy', '')}",
        f"- Fallback Profile: {payload.get('fallback_profile', '')}",
        f"- Production Allowed: {str(payload.get('production_allowed')).lower()}",
        f"- Sandbox Migration Executed: {str(payload.get('sandbox_migration_executed')).lower()}",
        f"- Production Promotion Executed: {str(payload.get('production_promotion_executed')).lower()}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- Approval: {payload.get('approval', {}).get('decision', '')}",
        f"- Final Status: {payload.get('final_status', '')}",
        f"- Orchestration Status: {payload.get('orchestration_status', '')}",
        f"- Failed Unit: {payload.get('failed_unit', '')}",
        f"- Transform: {payload.get('transform_status', '')}",
        f"- Build: {payload.get('build_status', '')}",
        f"- Test: {payload.get('test_status', '')}",
        f"- Test Severity: {payload.get('test_severity', '')}",
        f"- Test Message: {payload.get('test_message', '')}",
        f"- Test Confidence: {payload.get('test_confidence', '')}",
        (
            "- Test Totals: "
            f"tests={totals.get('tests', 0)} "
            f"passed={totals.get('passed', 0)} "
            f"failures={totals.get('failures', 0)} "
            f"errors={totals.get('errors', 0)} "
            f"skipped={totals.get('skipped', 0)}"
        ),
        f"- Executed Recipes: {', '.join(str(recipe) for recipe in recipes) if recipes else 'none'}",
        "- Scope Limits: no production promotion, no PR creation, no deployment, no automatic merge",
        "",
        (
            "Sandbox migration failed with classified post-transform test failures."
            if _is_failure_payload(payload)
            else "POC-ready sandbox migration artifacts are captured under this run directory."
        ),
    ]
    if payload.get("build_error_contract_path") or payload.get("post_transform_failure_classification_path"):
        lines.extend(["", "## Failure Artifacts", ""])
        if payload.get("build_error_contract_path"):
            lines.append(f"- Build Error Contract: {payload.get('build_error_contract_path', '')}")
        if payload.get("post_transform_failure_classification_path"):
            lines.append(
                "- Post-transform Failure Classification: "
                f"{payload.get('post_transform_failure_classification_path', '')}"
            )
        remediation_ref = dict(payload.get("artifact_refs", {}) or {}).get("remediation_plan", "")
        if remediation_ref:
            lines.append(f"- Remediation Plan: {remediation_ref}")
        behavioral_context_ref = dict(payload.get("artifact_refs", {}) or {}).get("behavioral_failure_context_pack", "")
        if behavioral_context_ref:
            lines.append(f"- Behavioral Failure Context Pack: {behavioral_context_ref}")
        llm_gate_ref = dict(payload.get("artifact_refs", {}) or {}).get("llm_proposal_gate", "")
        if llm_gate_ref:
            lines.append(f"- LLM Proposal Gate: {llm_gate_ref}")
        api_contract_ref = dict(payload.get("artifact_refs", {}) or {}).get("api_contract_review", "")
        if api_contract_ref:
            lines.append(f"- API Contract Review: {api_contract_ref}")
        legacy_equivalence_ref = dict(payload.get("artifact_refs", {}) or {}).get("legacy_behavior_equivalence_report", "")
        if legacy_equivalence_ref:
            lines.append(f"- Legacy Behavior Equivalence: {legacy_equivalence_ref}")
        test_context_ref = dict(payload.get("artifact_refs", {}) or {}).get("test_context_repair_proposal", "")
        if test_context_ref:
            lines.append(f"- Test Context Repair Proposal: {test_context_ref}")
        legacy_guided_ref = dict(payload.get("artifact_refs", {}) or {}).get("legacy_guided_patch_proposal", "")
        if legacy_guided_ref:
            lines.append(f"- Legacy Guided Patch Proposal: {legacy_guided_ref}")
        mockito_placement_ref = dict(payload.get("artifact_refs", {}) or {}).get("mockito_bean_placement_report", "")
        if mockito_placement_ref:
            lines.append(f"- MockitoBean Placement Report: {mockito_placement_ref}")
        strategy_ref = dict(payload.get("artifact_refs", {}) or {}).get("behavioral_remediation_strategy", "")
        if strategy_ref:
            lines.append(f"- Behavioral Remediation Strategy: {strategy_ref}")
        approved_patch_ref = dict(payload.get("artifact_refs", {}) or {}).get("approved_patch_apply_result", "")
        if approved_patch_ref:
            lines.append(f"- Approved Patch Apply: {approved_patch_ref}")
    consumer_report_ref = dict(payload.get("artifact_refs", {}) or {}).get("consumer_compatibility_report", "")
    consumer_summary_ref = dict(payload.get("artifact_refs", {}) or {}).get("consumer_compatibility_summary", "")
    consumer_status = str(payload.get("consumer_compatibility_status") or "")
    if consumer_report_ref or consumer_summary_ref or consumer_status:
        lines.extend(["", "## Consumer Compatibility Validation", ""])
        if consumer_status:
            lines.append(f"- Status: {consumer_status}")
        if consumer_report_ref:
            lines.append(f"- Report: {consumer_report_ref}")
        if consumer_summary_ref:
            lines.append(f"- Summary: {consumer_summary_ref}")
    category_counts = dict(payload.get("category_counts", {}) or {})
    if category_counts:
        lines.extend(["", "## Failure Categories", ""])
        for category, count in category_counts.items():
            lines.append(f"- {category}: {count}")
    top_affected_tests = list(payload.get("top_affected_tests", []) or [])
    if top_affected_tests:
        lines.extend(["", "## Top Affected Tests", ""])
        for row in top_affected_tests:
            if not isinstance(row, dict):
                continue
            lines.append(
                "- "
                f"{row.get('test_class', '')}.{row.get('test_method', '')}: "
                f"{row.get('category', '')} ({row.get('count', 0)})"
            )
    selected_hops = list(payload.get("selected_hops", []) or [])
    if selected_hops:
        lines.extend(["", "## Selected Hops", ""])
        for hop in selected_hops:
            if not isinstance(hop, dict):
                continue
            lines.append(f"- {hop.get('id', '')}")
    boot4_warnings = list(payload.get("boot4_warnings", []) or [])
    if boot4_warnings:
        lines.extend(["", "## Boot 4 Warnings", ""])
        lines.extend(f"- {warning}" for warning in boot4_warnings)
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


def _test_confidence_level(test_status: str) -> str:
    if test_status == "TEST_PASSED":
        return "HIGHER"
    if test_status in {"NO_TESTS_FOUND", "NO_TESTS_EXECUTED"}:
        return "LOWER"
    return "UNKNOWN"


def _zero_test_warnings(test_status: str) -> list[str]:
    if test_status not in {"NO_TESTS_FOUND", "NO_TESTS_EXECUTED"}:
        return []
    return [
        "Build passed, but no automated tests were found or executed.",
        "Migration confidence is lower because no automated tests exist.",
    ]


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
    migration_units = execution_plan.get("migration_units")
    if isinstance(migration_units, list):
        for unit in migration_units:
            if not isinstance(unit, dict):
                continue
            transformations = unit.get("transformations")
            if not isinstance(transformations, list):
                continue
            for transformation in transformations:
                if not isinstance(transformation, dict):
                    continue
                active_recipes = transformation.get("active_recipes")
                if isinstance(active_recipes, list):
                    recipes.extend(
                        str(item) for item in active_recipes if isinstance(item, (str, int, float))
                    )
    return recipes


def _boot4_warnings(
    target_stack: dict[str, Any],
    state: dict[str, Any],
    assessment_report: dict[str, Any] | None,
    migration_plan: dict[str, Any] | None,
) -> list[str]:
    spring_boot = str(target_stack.get("spring_boot", ""))
    if not spring_boot.startswith("4."):
        return []

    collected: list[str] = []
    for source in (
        state.get("warnings", []),
        (assessment_report or {}).get("warnings", []),
        (migration_plan or {}).get("warnings", []),
    ):
        if isinstance(source, list):
            collected.extend(str(item) for item in source)
    defaults = [
        "Spring Framework 7.x is required for Spring Boot 4.",
        "Jakarta EE 11 / Servlet 6.1 baseline applies.",
        "Boot 3 deprecated APIs removed in Boot 4 must be reviewed.",
        "Spring Cloud compatibility must be reviewed.",
        "Spring Security, Spring Data, Hibernate, and custom starter risk requires human review.",
        "javax.* leftovers must be eliminated.",
        "Maven >= 3.6.3 and Java 21 runtime validation are required for this sandbox profile.",
        "Official Boot guidance prefers latest 3.5.x before Boot 4; direct migration must use the fallback profile if unstable.",
    ]
    deduped: list[str] = []
    for warning in [*collected, *defaults]:
        if warning and warning not in deduped:
            deduped.append(warning)
    return deduped


def _object_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _list_or_empty(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _sandbox_migration_executed(state: dict[str, Any]) -> bool:
    transform_status = str(state.get("transform_status") or "")
    build_status = str(state.get("build_status") or "")
    test_status = str(state.get("test_status") or "")
    artifact_refs = dict(state.get("artifact_refs", {}) or {})
    return bool(
        transform_status
        or build_status
        or test_status
        or artifact_refs.get("migration_ledger")
        or artifact_refs.get("transformation_execution_plan")
    )


def _is_failed_sandbox_report(state: dict[str, Any]) -> bool:
    return (
        str(state.get("mode") or "") == "full_sandbox_migration"
        and str(state.get("approval_status") or "") == "COMPLETED"
        and str(state.get("approval_decision") or "") == "approved"
        and str(state.get("orchestration_status") or "") == "FAIL"
        and _sandbox_migration_executed(state)
    )


def _is_failure_payload(payload: dict[str, Any]) -> bool:
    return str(payload.get("orchestration_status") or "") == "FAIL"


def _read_optional_json(path_like: Any, warnings: list[str]) -> dict[str, Any] | None:
    path_text = str(path_like or "").strip()
    if not path_text:
        return None
    return _read_json(Path(path_text), warnings)


def _failed_unit(state: dict[str, Any], build_error_contract: dict[str, Any] | None) -> str:
    if isinstance(build_error_contract, dict):
        for key in ("unit_id", "target_unit"):
            value = str(build_error_contract.get(key) or "").strip()
            if value:
                return value
    return str(state.get("current_unit") or state.get("current_phase") or "")


def _failure_category_counts(
    build_error_contract: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
) -> dict[str, int]:
    if isinstance(failure_classification, dict):
        counts = failure_classification.get("category_counts")
        if isinstance(counts, dict):
            return {str(key): int(value) for key, value in counts.items()}
    if isinstance(build_error_contract, dict):
        counts = build_error_contract.get("failure_categories")
        if isinstance(counts, dict):
            return {str(key): int(value) for key, value in counts.items()}
    return {}


def _top_failed_tests(failure_classification: dict[str, Any] | None, *, limit: int = 8) -> list[dict[str, Any]]:
    failures = (failure_classification or {}).get("failures")
    if not isinstance(failures, list):
        return []

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for item in failures:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("test_class") or ""),
            str(item.get("test_method") or ""),
            str(item.get("category") or ""),
        )
        if key not in grouped:
            grouped[key] = {
                "test_class": key[0],
                "test_method": key[1],
                "category": key[2],
                "symptom": str(item.get("symptom") or ""),
                "suggested_next_action": str(item.get("suggested_next_action") or ""),
                "count": 0,
            }
            order.append(key)
        grouped[key]["count"] = int(grouped[key]["count"]) + 1

    ranked = sorted(
        (grouped[key] for key in order),
        key=lambda row: (-int(row.get("count", 0)), str(row.get("test_class", "")), str(row.get("test_method", ""))),
    )
    return ranked[:limit]


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
