from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


DEFAULT_APPROVAL_BY = "approver"
DEFAULT_APPROVAL_COMMENT = (
    "Approved for sandbox-only migration after readiness review. "
    "No production promotion approved."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m migration_factory.intake.launch_plan",
        description="Generate review-only migration launch commands from readiness/intake artifacts.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--readiness-pack", default="", help="Path to readiness_pack.json.")
    source.add_argument("--intake-index", default="", help="Path to intake_index.json.")
    parser.add_argument("--project-id", default="", help="Project id required when using --intake-index.")
    parser.add_argument("--legacy-app", required=True, help="Legacy/candidate app path.")
    parser.add_argument("--modernized-app", required=True, help="Modernized sandbox output path.")
    parser.add_argument("--ai-hub", required=True, help="AI hub path.")
    parser.add_argument("--profile", required=True, help="Target profile id.")
    parser.add_argument("--output-dir", required=True, help="Directory for launch plan artifacts.")
    parser.add_argument("--run-id-prefix", default="", help="Optional run id prefix.")
    parser.add_argument("--approved-by", default=DEFAULT_APPROVAL_BY, help="Approval template approver.")
    parser.add_argument("--approval-comments", default="", help="Approval template comments override.")
    parser.add_argument("--java-home-11", default="", help="Optional JAVA_HOME_11 value.")
    parser.add_argument("--java-home-17", default="", help="Optional JAVA_HOME_17 value.")
    parser.add_argument("--maven-opts", default="", help="Optional MAVEN_OPTS value.")
    parser.add_argument("--force-resume-on-insufficient-info", action="store_true", help="Generate resume command even when readiness is insufficient.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        generate_migration_launch_plan(
            readiness_pack_path=args.readiness_pack or None,
            intake_index_path=args.intake_index or None,
            selected_project_id=args.project_id or None,
            legacy_app_path=args.legacy_app,
            modernized_output_path=args.modernized_app,
            ai_hub_path=args.ai_hub,
            profile_id=args.profile,
            output_dir=args.output_dir,
            run_id_prefix=args.run_id_prefix or None,
            approved_by=args.approved_by,
            approval_comments=args.approval_comments or None,
            java_home_11=args.java_home_11 or None,
            java_home_17=args.java_home_17 or None,
            maven_opts=args.maven_opts or None,
            force_resume_on_insufficient_information=bool(args.force_resume_on_insufficient_info),
        )
    except ValueError as exc:
        parser.error(str(exc))
    return 0


def generate_migration_launch_plan(
    *,
    readiness_pack_path: str | Path | None = None,
    intake_index_path: str | Path | None = None,
    selected_project_id: str | None = None,
    legacy_app_path: str | Path,
    modernized_output_path: str | Path,
    ai_hub_path: str | Path,
    profile_id: str,
    output_dir: str | Path,
    run_id_prefix: str | None = None,
    approved_by: str | None = None,
    approval_comments: str | None = None,
    java_home_11: str | None = None,
    java_home_17: str | None = None,
    maven_opts: str | None = None,
    force_resume_on_insufficient_information: bool = False,
) -> dict[str, Any]:
    source_payload = _load_source_payload(
        readiness_pack_path=readiness_pack_path,
        intake_index_path=intake_index_path,
        selected_project_id=selected_project_id,
    )
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    legacy_app = Path(legacy_app_path).expanduser().resolve()
    modernized_app = Path(modernized_output_path).expanduser().resolve()
    ai_hub = Path(ai_hub_path).expanduser().resolve()

    project_id = str(source_payload.get("project_id") or selected_project_id or legacy_app.name)
    readiness_status = str(source_payload.get("readiness_status") or "INSUFFICIENT_INFORMATION")
    readiness_warnings = list(source_payload.get("warnings", []) or [])
    human_review_required_before_launch = readiness_status == "NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION"
    blocked_for_insufficient_information = readiness_status == "INSUFFICIENT_INFORMATION"
    run_prefix = str(run_id_prefix or project_id).strip() or "migration"
    consumer_config_path = str(source_payload.get("consumer_validation_config_path") or "")
    run_id_example = f"{run_prefix}-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

    derived_warning_comment = _derived_approval_comment(
        base_comment=approval_comments or DEFAULT_APPROVAL_COMMENT,
        readiness_status=readiness_status,
        warnings=readiness_warnings,
    )
    runner_command = (
        f'python -m migration_factory.orchestrator.runner --run-id "{run_id_example}" '
        f'--legacy "{legacy_app}" --modernized "{modernized_app}" --ai-hub "{ai_hub}" '
        f'--profile {profile_id} --mode read_only_assessment'
    )
    run_dir_expr = f'{modernized_app}\\.migration\\runs\\{run_id_example}'
    approval_command = (
        f'python -m migration_factory.approval.approve_run --run-dir "{run_dir_expr}" '
        f'--run-id "{run_id_example}" --approved-by "{approved_by or DEFAULT_APPROVAL_BY}" '
        f'--decision approved --comments "{_escape_ps(derived_warning_comment)}"'
    )
    resume_allowed = force_resume_on_insufficient_information or not blocked_for_insufficient_information
    resume_command = (
        f'python -m migration_factory.orchestrator.resume --run-id "{run_id_example}" '
        f'--run-dir "{run_dir_expr}" --decision approved --approved-by "{approved_by or DEFAULT_APPROVAL_BY}" '
        f'--comments "{_escape_ps(derived_warning_comment)}"'
    )

    env_section = {
        "JAVA_HOME_11": str(java_home_11 or ""),
        "JAVA_HOME_17": str(java_home_17 or ""),
        "MAVEN_OPTS": str(maven_opts or ""),
    }
    warnings = list(readiness_warnings)
    if human_review_required_before_launch:
        warnings.append("Readiness pack requires human review before launch; do not approve blindly.")
    if blocked_for_insufficient_information:
        warnings.append("Readiness pack has insufficient information; resume command blocked until more metadata is collected.")

    payload = {
        "project_id": project_id,
        "source_artifact_type": source_payload.get("_source_artifact_type", ""),
        "source_artifact_path": str(source_payload.get("_source_artifact_path") or ""),
        "readiness_status": readiness_status,
        "human_review_required_before_launch": human_review_required_before_launch,
        "launch_status": "BLOCKED_FOR_INSUFFICIENT_INFORMATION" if blocked_for_insufficient_information else "READY_FOR_REVIEW",
        "legacy_app_path": str(legacy_app),
        "modernized_output_path": str(modernized_app),
        "ai_hub_path": str(ai_hub),
        "profile_id": str(profile_id),
        "run_id_prefix": run_prefix,
        "run_id_example": run_id_example,
        "run_dir_expression": run_dir_expr,
        "environment": env_section,
        "commands": {
            "runner": runner_command,
            "approval_template": approval_command,
            "resume_template": resume_command if resume_allowed else "",
        },
        "governance": {
            "sandbox_only": True,
            "production_promotion_allowed": False,
            "human_approval_required": True,
        },
        "warnings": _dedupe_preserve_order([warning for warning in warnings if warning]),
        "consumer_validation_config_path": consumer_config_path,
        "recommended_next_actions": _recommended_next_actions(
            blocked_for_insufficient_information=blocked_for_insufficient_information,
            human_review_required_before_launch=human_review_required_before_launch,
            consumer_config_path=consumer_config_path,
        ),
    }

    json_path = output_root / "migration_launch_plan.json"
    ps1_path = output_root / "migration_launch_commands.ps1"
    summary_path = output_root / "migration_launch_summary.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ps1_path.write_text(_render_ps1(payload), encoding="utf-8")
    summary_path.write_text(_render_summary(payload), encoding="utf-8")
    return {
        "report_path": str(json_path),
        "commands_path": str(ps1_path),
        "summary_path": str(summary_path),
        "payload": payload,
    }


def _load_source_payload(
    *,
    readiness_pack_path: str | Path | None,
    intake_index_path: str | Path | None,
    selected_project_id: str | None,
) -> dict[str, Any]:
    if readiness_pack_path:
        path = Path(readiness_pack_path).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Readiness pack is not a JSON object: {path}")
        payload["_source_artifact_type"] = "readiness_pack"
        payload["_source_artifact_path"] = str(path)
        return payload
    if not intake_index_path:
        raise ValueError("Either readiness_pack_path or intake_index_path is required.")
    path = Path(intake_index_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Intake index is not a JSON object: {path}")
    if not selected_project_id:
        raise ValueError("selected_project_id is required when using intake_index_path.")
    for item in list(payload.get("projects_analyzed", []) or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("project_id") or "") != selected_project_id:
            continue
        readiness_path = Path(str(item.get("readiness_pack_path") or "")).expanduser().resolve()
        readiness_payload = json.loads(readiness_path.read_text(encoding="utf-8"))
        if not isinstance(readiness_payload, dict):
            raise ValueError(f"Readiness pack is not a JSON object: {readiness_path}")
        readiness_payload["_source_artifact_type"] = "intake_index"
        readiness_payload["_source_artifact_path"] = str(path)
        consumer_config_path = str((payload.get("consumer_validation_config_paths") or {}).get(selected_project_id) or "")
        readiness_payload["consumer_validation_config_path"] = consumer_config_path
        return readiness_payload
    raise ValueError(f"Project id not found in intake index: {selected_project_id}")


def _derived_approval_comment(*, base_comment: str, readiness_status: str, warnings: list[str]) -> str:
    parts = [base_comment.strip()]
    if readiness_status == "NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION":
        parts.append("Readiness requires human review before sandbox launch.")
    for warning in warnings[:3]:
        parts.append(f"Readiness warning: {warning}")
    parts.append("Sandbox-only migration. No production promotion approved.")
    return " ".join(part for part in parts if part)


def _recommended_next_actions(
    *,
    blocked_for_insufficient_information: bool,
    human_review_required_before_launch: bool,
    consumer_config_path: str,
) -> list[str]:
    actions: list[str] = []
    if blocked_for_insufficient_information:
        actions.append("Collect missing readiness information before approving or resuming sandbox migration.")
    if human_review_required_before_launch:
        actions.append("Review readiness warnings and risk gates before executing approval command.")
    if consumer_config_path:
        actions.append("Keep generated consumer validation config ready for post-migration downstream validation.")
    if not actions:
        actions.append("Review generated commands, then run read-only assessment and approval flow when ready.")
    return actions


def _render_ps1(payload: dict[str, Any]) -> str:
    env = dict(payload.get("environment", {}) or {})
    lines = [
        f'$env:PYTHONPATH="."',
    ]
    if env.get("JAVA_HOME_11"):
        lines.append(f'$env:JAVA_HOME_11="{env["JAVA_HOME_11"]}"')
    if env.get("JAVA_HOME_17"):
        lines.append(f'$env:JAVA_HOME_17="{env["JAVA_HOME_17"]}"')
    if env.get("MAVEN_OPTS"):
        lines.append(f'$env:MAVEN_OPTS="{_escape_ps(env["MAVEN_OPTS"])}"')
    lines.extend(
        [
            f'$RUN_ID="{payload.get("run_id_example", "")}"',
            f'$LEGACY_APP="{payload.get("legacy_app_path", "")}"',
            f'$MODERNIZED_APP="{payload.get("modernized_output_path", "")}"',
            f'$AI_HUB="{payload.get("ai_hub_path", "")}"',
            f'$PROFILE="{payload.get("profile_id", "")}"',
            f'$RUN_DIR="{payload.get("run_dir_expression", "")}"',
            "",
            payload.get("commands", {}).get("runner", ""),
            "",
            "# Approval template",
            payload.get("commands", {}).get("approval_template", ""),
            "",
            "# Resume template",
        ]
    )
    resume = str(payload.get("commands", {}).get("resume_template") or "")
    if resume:
        lines.append(resume)
    else:
        lines.append("# Resume command blocked until readiness information is complete.")
    return "\n".join(lines).rstrip() + "\n"


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Migration Launch Summary",
        "",
        f'- Project ID: {payload.get("project_id", "")}',
        f'- Launch Status: {payload.get("launch_status", "")}',
        f'- Readiness Status: {payload.get("readiness_status", "")}',
        f'- Human Review Required Before Launch: {str(payload.get("human_review_required_before_launch")).lower()}',
        "",
        "## Commands",
        "",
        "- Runner command generated",
        "- Approval template generated",
        "- Resume template generated" if payload.get("commands", {}).get("resume_template") else "- Resume template blocked",
    ]
    consumer_config_path = str(payload.get("consumer_validation_config_path") or "")
    if consumer_config_path:
        lines.extend(["", "## Consumer Validation", "", f"- Config: {consumer_config_path}"])
    warnings = list(payload.get("warnings", []) or [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).rstrip() + "\n"


def _escape_ps(value: str) -> str:
    return str(value).replace('"', '`"')


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
