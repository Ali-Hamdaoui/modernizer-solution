from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m migration_factory.evidence.bundle",
        description="Generate management-friendly and technical evidence bundle from factory artifacts.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--readiness-pack", default="")
    parser.add_argument("--intake-index", default="")
    parser.add_argument("--migration-wave-plan", default="")
    parser.add_argument("--consumer-validation-config", default="")
    parser.add_argument("--migration-launch-plan", default="")
    parser.add_argument("--factory-capability-inventory", default="")
    parser.add_argument("--rule-extraction-report", default="")
    parser.add_argument("--migration-report", default="")
    parser.add_argument("--orchestration-summary", default="")
    parser.add_argument("--review-artifacts-dir", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    generate_management_evidence_bundle(
        output_dir=args.output_dir,
        project_id=args.project_id or None,
        readiness_pack_path=args.readiness_pack or None,
        intake_index_path=args.intake_index or None,
        migration_wave_plan_path=args.migration_wave_plan or None,
        consumer_validation_config_path=args.consumer_validation_config or None,
        migration_launch_plan_path=args.migration_launch_plan or None,
        factory_capability_inventory_path=args.factory_capability_inventory or None,
        rule_extraction_report_path=args.rule_extraction_report or None,
        migration_report_path=args.migration_report or None,
        orchestration_summary_path=args.orchestration_summary or None,
        review_artifacts_dir=args.review_artifacts_dir or None,
    )
    return 0


def generate_management_evidence_bundle(
    *,
    output_dir: str | Path,
    project_id: str | None = None,
    readiness_pack_path: str | Path | None = None,
    intake_index_path: str | Path | None = None,
    migration_wave_plan_path: str | Path | None = None,
    consumer_validation_config_path: str | Path | None = None,
    migration_launch_plan_path: str | Path | None = None,
    factory_capability_inventory_path: str | Path | None = None,
    rule_extraction_report_path: str | Path | None = None,
    migration_report_path: str | Path | None = None,
    orchestration_summary_path: str | Path | None = None,
    review_artifacts_dir: str | Path | None = None,
) -> dict[str, Any]:
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    readiness_pack = _read_json(readiness_pack_path)
    intake_index = _read_json(intake_index_path)
    migration_wave_plan = _read_json(migration_wave_plan_path)
    consumer_validation_config = _read_json(consumer_validation_config_path)
    migration_launch_plan = _read_json(migration_launch_plan_path)
    capability_inventory = _read_json(factory_capability_inventory_path)
    rule_extraction_report = _read_json(rule_extraction_report_path)
    migration_report = _read_json(migration_report_path)
    orchestration_summary = _read_json(orchestration_summary_path)
    review_artifacts = _scan_review_artifacts(review_artifacts_dir)

    resolved_project_id = (
        str(project_id or "")
        or str(readiness_pack.get("project_id") or "")
        or _project_id_from_intake(intake_index)
        or str(migration_launch_plan.get("project_id") or "")
        or "unknown-project"
    )
    readiness_status = str(readiness_pack.get("readiness_status") or _first_project_status(intake_index) or "")
    migration_status = str(
        migration_report.get("final_status")
        or orchestration_summary.get("final_status")
        or migration_launch_plan.get("launch_status")
        or ""
    )
    deterministic_transformations = _deterministic_transformations(readiness_pack, capability_inventory)
    review_gates = _review_gates(readiness_pack, capability_inventory, review_artifacts)
    human_review_required = bool(
        readiness_pack.get("human_review_required")
        or migration_report.get("human_review_required")
        or migration_launch_plan.get("human_review_required_before_launch")
        or review_gates
    )
    consumer_validation_status = _consumer_validation_status(
        consumer_validation_config=consumer_validation_config,
        readiness_pack=readiness_pack,
        migration_report=migration_report,
    )
    production_promotion_allowed = bool(
        migration_report.get("production_allowed")
        if "production_allowed" in migration_report
        else migration_launch_plan.get("governance", {}).get("production_promotion_allowed", False)
    )
    warnings = _dedupe_preserve_order(
        [
            *list(readiness_pack.get("warnings", []) or []),
            *list(intake_index.get("warnings", []) or []),
            *list(migration_launch_plan.get("warnings", []) or []),
            *list(migration_report.get("warnings", []) or []),
            *list(orchestration_summary.get("warnings", []) or []),
            *list(review_artifacts.get("warnings", []) or []),
            *_artifact_ref_warnings(migration_report, orchestration_summary),
        ]
    )
    limitations = _limitations(
        readiness_pack=readiness_pack,
        intake_index=intake_index,
        migration_wave_plan=migration_wave_plan,
        migration_launch_plan=migration_launch_plan,
        migration_report=migration_report,
    )
    artifact_index = _artifact_index(
        readiness_pack_path=readiness_pack_path,
        intake_index_path=intake_index_path,
        migration_wave_plan_path=migration_wave_plan_path,
        consumer_validation_config_path=consumer_validation_config_path,
        migration_launch_plan_path=migration_launch_plan_path,
        factory_capability_inventory_path=factory_capability_inventory_path,
        rule_extraction_report_path=rule_extraction_report_path,
        migration_report_path=migration_report_path,
        orchestration_summary_path=orchestration_summary_path,
        review_artifacts=review_artifacts,
        migration_report=migration_report,
        orchestration_summary=orchestration_summary,
    )
    recommended_next_actions = _recommended_next_actions(
        readiness_status=readiness_status,
        migration_status=migration_status,
        human_review_required=human_review_required,
        consumer_validation_status=consumer_validation_status,
        production_promotion_allowed=production_promotion_allowed,
    )

    payload = {
        "project_id": resolved_project_id,
        "executive_summary": _executive_summary(
            readiness_status=readiness_status,
            migration_status=migration_status,
            human_review_required=human_review_required,
            production_promotion_allowed=production_promotion_allowed,
        ),
        "readiness_status": readiness_status or "not_provided",
        "migration_status": migration_status or "not_provided",
        "factory_capability_summary": _factory_capability_summary(capability_inventory),
        "deterministic_transformations_covered": deterministic_transformations,
        "review_gates_detected": review_gates,
        "human_review_required": human_review_required,
        "consumer_validation_status": consumer_validation_status,
        "migration_wave_summary": _wave_summary(migration_wave_plan),
        "launch_plan_available": bool(migration_launch_plan),
        "production_promotion_allowed": production_promotion_allowed,
        "key_warnings": warnings,
        "recommended_next_actions": recommended_next_actions,
        "artifact_index": artifact_index,
        "limitations": limitations,
    }

    management_bundle_path = output_root / "management_evidence_bundle.json"
    management_summary_path = output_root / "management_evidence_summary.md"
    technical_index_path = output_root / "technical_evidence_index.json"
    management_bundle_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    management_summary_path.write_text(_render_management_summary(payload), encoding="utf-8")
    technical_index_path.write_text(json.dumps({"project_id": resolved_project_id, "artifacts": artifact_index}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "bundle_path": str(management_bundle_path),
        "summary_path": str(management_summary_path),
        "technical_index_path": str(technical_index_path),
        "payload": payload,
    }


def _read_json(path_like: str | Path | None) -> dict[str, Any]:
    if not path_like:
        return {}
    path = Path(path_like).expanduser().resolve()
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _scan_review_artifacts(path_like: str | Path | None) -> dict[str, Any]:
    if not path_like:
        return {"artifacts": [], "warnings": []}
    root = Path(path_like).expanduser().resolve()
    if not root.is_dir():
        return {"artifacts": [], "warnings": ["Review artifacts directory not provided or missing."]}
    artifacts = []
    warnings: list[str] = []
    for path in sorted(root.glob("*.json")):
        payload = _read_json(path)
        artifacts.append(
            {
                "artifact_type": str(payload.get("gate_id") or path.stem),
                "path": str(path),
            }
        )
        if payload.get("warnings"):
            warnings.extend(str(item) for item in list(payload.get("warnings", []) or []))
    return {"artifacts": artifacts, "warnings": _dedupe_preserve_order(warnings)}


def _project_id_from_intake(payload: dict[str, Any]) -> str:
    projects = list(payload.get("projects_analyzed", []) or [])
    if len(projects) == 1 and isinstance(projects[0], dict):
        return str(projects[0].get("project_id") or "")
    return ""


def _first_project_status(payload: dict[str, Any]) -> str:
    projects = list(payload.get("projects_analyzed", []) or [])
    if len(projects) == 1 and isinstance(projects[0], dict):
        return str(projects[0].get("readiness_status") or "")
    return ""


def _deterministic_transformations(readiness_pack: dict[str, Any], capability_inventory: dict[str, Any]) -> list[str]:
    readiness_ids = [
        str(item.get("capability_id") or "")
        for item in list(readiness_pack.get("deterministic_transformations_likely_applicable", []) or [])
        if isinstance(item, dict)
    ]
    if readiness_ids:
        return _dedupe_preserve_order([item for item in readiness_ids if item])
    transforms = []
    for capability in list(capability_inventory.get("capabilities", []) or []):
        if not isinstance(capability, dict):
            continue
        if capability.get("capability_type") == "TRANSFORM" and capability.get("safe_to_auto_apply"):
            transforms.append(str(capability.get("capability_id") or ""))
    return _dedupe_preserve_order([item for item in transforms if item])


def _review_gates(readiness_pack: dict[str, Any], capability_inventory: dict[str, Any], review_artifacts: dict[str, Any]) -> list[str]:
    gate_ids = [
        str(item.get("capability_id") or "")
        for item in list(readiness_pack.get("review_gates_expected", []) or [])
        if isinstance(item, dict)
    ]
    gate_ids.extend(str(item.get("artifact_type") or "") for item in list(review_artifacts.get("artifacts", []) or []) if isinstance(item, dict))
    if gate_ids:
        return _dedupe_preserve_order([item for item in gate_ids if item])
    for capability in list(capability_inventory.get("capabilities", []) or []):
        if isinstance(capability, dict) and capability.get("capability_type") == "REVIEW_GATE":
            gate_ids.append(str(capability.get("capability_id") or ""))
    return _dedupe_preserve_order([item for item in gate_ids if item])


def _consumer_validation_status(
    *,
    consumer_validation_config: dict[str, Any],
    readiness_pack: dict[str, Any],
    migration_report: dict[str, Any],
) -> str:
    if migration_report.get("consumer_compatibility_status"):
        return str(migration_report.get("consumer_compatibility_status"))
    if consumer_validation_config.get("status"):
        return str(consumer_validation_config.get("status"))
    if readiness_pack.get("consumer_validation_suggestions"):
        return "SUGGESTED"
    return "not_provided"


def _limitations(
    *,
    readiness_pack: dict[str, Any],
    intake_index: dict[str, Any],
    migration_wave_plan: dict[str, Any],
    migration_launch_plan: dict[str, Any],
    migration_report: dict[str, Any],
) -> list[str]:
    limitations: list[str] = []
    if not readiness_pack:
        limitations.append("Readiness pack not provided.")
    if not intake_index:
        limitations.append("Intake index not provided.")
    if not migration_wave_plan:
        limitations.append("Migration wave plan not provided.")
    if not migration_launch_plan:
        limitations.append("Migration launch plan not provided.")
    if not migration_report:
        limitations.append("Migration report not provided.")
    return limitations


def _artifact_index(
    *,
    readiness_pack_path: str | Path | None,
    intake_index_path: str | Path | None,
    migration_wave_plan_path: str | Path | None,
    consumer_validation_config_path: str | Path | None,
    migration_launch_plan_path: str | Path | None,
    factory_capability_inventory_path: str | Path | None,
    rule_extraction_report_path: str | Path | None,
    migration_report_path: str | Path | None,
    orchestration_summary_path: str | Path | None,
    review_artifacts: dict[str, Any],
    migration_report: dict[str, Any],
    orchestration_summary: dict[str, Any],
) -> list[dict[str, str]]:
    entries = [
        ("readiness_pack", readiness_pack_path),
        ("intake_index", intake_index_path),
        ("migration_wave_plan", migration_wave_plan_path),
        ("consumer_validation_config", consumer_validation_config_path),
        ("migration_launch_plan", migration_launch_plan_path),
        ("factory_capability_inventory", factory_capability_inventory_path),
        ("rule_extraction_report", rule_extraction_report_path),
        ("migration_report", migration_report_path),
        ("orchestration_summary", orchestration_summary_path),
    ]
    result = []
    for artifact_type, path_like in entries:
        if not path_like:
            continue
        result.append({"artifact_type": artifact_type, "path": str(Path(path_like).expanduser().resolve())})
    for item in list(review_artifacts.get("artifacts", []) or []):
        if isinstance(item, dict):
            result.append({"artifact_type": str(item.get("artifact_type") or ""), "path": str(item.get("path") or "")})
    for artifact_type in (
        "behavioral_failure_context_pack",
        "behavioral_failure_context_summary",
        "llm_proposal_gate",
    ):
        ref = _artifact_ref(migration_report, orchestration_summary, artifact_type)
        if ref:
            result.append({"artifact_type": artifact_type, "path": ref})
    return result


def _artifact_ref_warnings(migration_report: dict[str, Any], orchestration_summary: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    context_pack = _read_json(_artifact_ref(migration_report, orchestration_summary, "behavioral_failure_context_pack"))
    if context_pack.get("human_review_required"):
        warnings.append("Behavioral failure context pack indicates human review remains required.")
    gate = _read_json(_artifact_ref(migration_report, orchestration_summary, "llm_proposal_gate"))
    reason = str(gate.get("reason") or "").strip()
    if reason:
        warnings.append(reason)
    return warnings


def _artifact_ref(migration_report: dict[str, Any], orchestration_summary: dict[str, Any], key: str) -> str:
    for payload in (migration_report, orchestration_summary):
        refs = payload.get("artifact_refs")
        if isinstance(refs, dict):
            ref = str(refs.get(key) or "").strip()
            if ref:
                return ref
    return ""


def _factory_capability_summary(capability_inventory: dict[str, Any]) -> dict[str, Any]:
    capabilities = list(capability_inventory.get("capabilities", []) or [])
    return {
        "capability_count": len(capabilities),
        "transform_capability_count": sum(1 for item in capabilities if isinstance(item, dict) and item.get("capability_type") == "TRANSFORM"),
        "review_gate_count": sum(1 for item in capabilities if isinstance(item, dict) and item.get("capability_type") == "REVIEW_GATE"),
        "reporting_capability_count": sum(1 for item in capabilities if isinstance(item, dict) and item.get("capability_type") == "REPORT"),
    }


def _wave_summary(migration_wave_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "waves": list(migration_wave_plan.get("migration_waves", []) or []),
        "cycle_count": len(list(migration_wave_plan.get("cycles", []) or [])),
        "human_review_required": bool(migration_wave_plan.get("human_review_required", False)),
    }


def _executive_summary(
    *,
    readiness_status: str,
    migration_status: str,
    human_review_required: bool,
    production_promotion_allowed: bool,
) -> str:
    if migration_status and migration_status != "not_provided":
        return (
            f"Migration status is {migration_status}. "
            f"{'Human review remains required.' if human_review_required else 'No additional human review flags detected.'} "
            f"{'Production promotion is allowed.' if production_promotion_allowed else 'Production promotion is not allowed from this bundle.'}"
        )
    return (
        f"Readiness status is {readiness_status or 'not_provided'}. "
        f"{'Human review is required before progressing.' if human_review_required else 'Automated preparation coverage is available for next steps.'}"
    )


def _recommended_next_actions(
    *,
    readiness_status: str,
    migration_status: str,
    human_review_required: bool,
    consumer_validation_status: str,
    production_promotion_allowed: bool,
) -> list[str]:
    actions: list[str] = []
    if readiness_status and readiness_status != "READY_FOR_READ_ONLY_ASSESSMENT":
        actions.append("Review readiness warnings and gates before starting or approving migration.")
    if migration_status and migration_status not in {"SANDBOX_MIGRATION_COMPLETED", "not_provided"}:
        actions.append("Review migration blockers and evidence before any next execution step.")
    if human_review_required:
        actions.append("Ensure accountable human approver reviews automated outputs and review-gate findings.")
    if consumer_validation_status in {"SUGGESTED", "READY", "NO_CONSUMERS_FOUND"}:
        actions.append("Plan downstream consumer validation before trusting shared-library migration results.")
    if not production_promotion_allowed:
        actions.append("Treat this bundle as sandbox/intake evidence only; production promotion remains blocked unless explicitly approved.")
    return _dedupe_preserve_order(actions)


def _render_management_summary(payload: dict[str, Any]) -> str:
    auto_count = len(list(payload.get("deterministic_transformations_covered", []) or []))
    review_count = len(list(payload.get("review_gates_detected", []) or []))
    lines = [
        "# Management Evidence Summary",
        "",
        f"- Project ID: {payload.get('project_id', '')}",
        f"- Executive Summary: {payload.get('executive_summary', '')}",
        f"- Readiness Status: {payload.get('readiness_status', '')}",
        f"- Migration Status: {payload.get('migration_status', '')}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- Production Promotion Allowed: {str(payload.get('production_promotion_allowed')).lower()}",
        "",
        "## Automation Coverage",
        "",
        f"- Automated deterministic transformations covered: {auto_count}",
        f"- Review gates detected: {review_count}",
        "",
        "## What Is Automated",
        "",
        "- Factory can apply deterministic transformations and produce evidence artifacts.",
        "- Factory can prepare launch, intake, and validation planning artifacts without changing application code.",
        "",
        "## What Still Needs Human Review",
        "",
        "- Review gates, compatibility risks, and policy decisions remain human-governed.",
        "- Production promotion is not implied by this bundle.",
    ]
    warnings = list(payload.get("key_warnings", []) or [])
    if warnings:
        lines.extend(["", "## Key Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings[:8])
    actions = list(payload.get("recommended_next_actions", []) or [])
    if actions:
        lines.extend(["", "## Recommended Next Actions", ""])
        lines.extend(f"- {action}" for action in actions)
    return "\n".join(lines).rstrip() + "\n"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
