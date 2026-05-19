from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from migration_factory.agents.transformation_agent import run_transformation_agent
from migration_factory.agents.transformation_agent.agent import TransformationAgentError
from migration_factory.agents.transformation_agent.execution_plan import (
    TRANSFORMATION_DIR_NAME,
    TransformationExecutionPlanError,
    write_transformation_execution_plan,
)
from migration_factory.agents.transformation_agent.plan import MigrationPlanError
from migration_factory.agents.transformation_agent.rewrite import RewritePluginError
from migration_factory.agents.transformation_agent.workspace import (
    TransformationWorkspaceError,
    prepare_sandbox_workspace,
)
from migration_factory.approval import (
    ApprovalArtifactError,
    check_approval_decision,
    check_approved_plan_lock,
    read_approval_decision,
)


STATUS_APPROVED = "APPROVED_FOR_TRANSFORM"
STATUS_SANDBOX = "SANDBOX_PREPARED"
STATUS_RUNNING = "TRANSFORM_RUNNING"
STATUS_APPLIED = "TRANSFORM_APPLIED_IN_SANDBOX"
STATUS_FAILED = "TRANSFORM_FAILED_IN_SANDBOX"


class TransformV1AfterApprovalError(ValueError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        run_dir = Path(args.run_dir).expanduser().resolve()
        modernized_app = Path(args.modernized_app).expanduser().resolve()
        legacy_app = Path(args.legacy_app).expanduser().resolve()
        run_id = _ensure_approved_for_transform(run_dir, approved_by=args.approved_by)
        _ensure_run_dir_matches_modernized_app(run_dir, modernized_app, run_id)
        print(STATUS_APPROVED)

        generated_plan = write_transformation_execution_plan(modernized_app, run_id)
        plugin_xml = _write_openrewrite_plugin_xml(run_dir, args.ai_hub, args.profile)
        sandbox = prepare_sandbox_workspace(
            legacy_app_path=legacy_app,
            modernized_app_path=modernized_app,
            run_dir=run_dir,
        )
        _force_plan_target(generated_plan, sandbox.path)
        print(STATUS_SANDBOX)

        print(STATUS_RUNNING)
        result = run_transformation_agent(
            sandbox.path,
            plugin_xml,
            generated_plan,
            dry_run=False,
            wait_for_continue=False,
        )
        print(f"Ledger: {result.ledger_file}")
        print(f"Transformer status: {result.status}")
        if result.blocked_unit:
            print(STATUS_FAILED)
            print(f"Blocked unit: {result.blocked_unit}")
            return 1
        print(STATUS_APPLIED)
        return 0
    except (
        ApprovalArtifactError,
        MigrationPlanError,
        RewritePluginError,
        TransformationAgentError,
        TransformationExecutionPlanError,
        TransformationWorkspaceError,
        TransformV1AfterApprovalError,
    ) as exc:
        print(STATUS_FAILED)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transform-v1-after-approval",
        description="Apply the V1 Transformer in a sandbox after human approval.",
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--legacy-app", required=True)
    parser.add_argument("--modernized-app", required=True)
    parser.add_argument("--ai-hub", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--approved-by", required=True)
    return parser


def _ensure_approved_for_transform(run_dir: Path, *, approved_by: str) -> str:
    decision_errors = check_approval_decision(run_dir)
    if decision_errors:
        raise TransformV1AfterApprovalError("; ".join(decision_errors))

    decision = read_approval_decision(run_dir)
    run_id = str(decision.get("run_id") or "")
    if not run_id:
        raise TransformV1AfterApprovalError("approval_decision.json missing run_id")
    if decision.get("decision") != "approved":
        raise TransformV1AfterApprovalError(
            f"approval_decision.json decision must be approved, got {decision.get('decision')!r}"
        )
    if decision.get("decided_by") != approved_by:
        raise TransformV1AfterApprovalError(
            f"approval_decision.json decided_by must match --approved-by {approved_by!r}"
        )

    lock_errors = check_approved_plan_lock(run_dir, expected_run_id=run_id)
    if lock_errors:
        raise TransformV1AfterApprovalError("; ".join(lock_errors))
    return run_id


def _ensure_run_dir_matches_modernized_app(run_dir: Path, modernized_app: Path, run_id: str) -> None:
    expected = modernized_app / ".migration" / "runs" / run_id
    if run_dir != expected.resolve():
        raise TransformV1AfterApprovalError(
            f"--run-dir must match --modernized-app .migration/runs/{run_id}: {expected}"
        )


def _force_plan_target(plan_path: Path, sandbox_path: Path) -> None:
    payload = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise TransformV1AfterApprovalError(f"Transformer plan must be a YAML mapping: {plan_path}")
    workspaces = payload.setdefault("workspaces", {})
    if not isinstance(workspaces, dict):
        raise TransformV1AfterApprovalError("Transformer plan workspaces must be a mapping")
    target = workspaces.setdefault("target", {})
    if not isinstance(target, dict):
        raise TransformV1AfterApprovalError("Transformer plan workspaces.target must be a mapping")

    target["path"] = str(sandbox_path.resolve())
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_openrewrite_plugin_xml(run_dir: Path, ai_hub: str, profile: str) -> Path:
    source = _load_rewrite_plugin_source(run_dir, ai_hub, profile)
    plugin = _coordinate(source["plugin"], "plugin")
    recipe_artifacts = [_coordinate(item, "recipe_artifacts") for item in _as_list(source.get("recipe_artifacts"))]

    plugin_xml = _plugin_xml(plugin, recipe_artifacts)
    output_path = run_dir / TRANSFORMATION_DIR_NAME / "openrewrite-plugin.xml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(plugin_xml, encoding="utf-8")
    return output_path


def _load_rewrite_plugin_source(run_dir: Path, ai_hub: str, profile: str) -> dict[str, Any]:
    rewrite_plan_path = run_dir / "analysis" / "rewrite_plugin_plan.json"
    if rewrite_plan_path.is_file():
        try:
            payload = json.loads(rewrite_plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TransformV1AfterApprovalError(f"Invalid JSON artifact {rewrite_plan_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise TransformV1AfterApprovalError(f"Artifact must be a JSON object: {rewrite_plan_path}")
        if payload.get("plugin"):
            return payload

    catalog = _load_ai_hub_openrewrite_catalog(ai_hub, profile)
    if catalog.get("plugin"):
        return catalog
    raise TransformV1AfterApprovalError("OpenRewrite plugin coordinate not found in run artifacts or AI Hub")


def _load_ai_hub_openrewrite_catalog(ai_hub: str, profile: str) -> dict[str, Any]:
    hub_path = Path(ai_hub).expanduser().resolve()
    profile_path = hub_path / "profiles" / f"{profile}.yaml"
    if not profile_path.is_file():
        raise TransformV1AfterApprovalError(f"AI Hub profile not found: {profile_path}")

    profile_payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    try:
        catalog_rel = profile_payload["openrewrite"]["catalog_path"]
    except (KeyError, TypeError) as exc:
        raise TransformV1AfterApprovalError("Profile missing openrewrite.catalog_path") from exc

    catalog_path = (hub_path / str(catalog_rel)).resolve()
    if catalog_path != hub_path and hub_path not in catalog_path.parents:
        raise TransformV1AfterApprovalError(f"Catalog path escapes AI Hub: {catalog_rel}")
    if not catalog_path.is_file():
        raise TransformV1AfterApprovalError(f"OpenRewrite catalog not found: {catalog_path}")

    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    try:
        plugin = _coord_from_mapping(catalog["plugin"])
    except (KeyError, TypeError) as exc:
        raise TransformV1AfterApprovalError(f"Invalid OpenRewrite catalog plugin: {exc}") from exc
    return {
        "plugin": plugin,
        "recipe_artifacts": [_coord_from_mapping(item) for item in catalog.get("recipe_artifacts", [])],
    }


def _coord_from_mapping(value: Any) -> str:
    if not isinstance(value, dict):
        raise TransformV1AfterApprovalError("coordinate must be a mapping")
    try:
        return f"{value['group_id']}:{value['artifact_id']}:{value['version']}"
    except KeyError as exc:
        raise TransformV1AfterApprovalError(f"coordinate missing {exc.args[0]}") from exc


def _coordinate(value: Any, label: str) -> tuple[str, str, str]:
    parts = str(value).split(":")
    if len(parts) != 3 or not all(parts):
        raise TransformV1AfterApprovalError(f"{label} coordinate must be groupId:artifactId:version")
    return parts[0], parts[1], parts[2]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _plugin_xml(plugin: tuple[str, str, str], recipe_artifacts: list[tuple[str, str, str]]) -> str:
    group_id, artifact_id, version = plugin
    lines = [
        "<plugin>",
        f"  <groupId>{group_id}</groupId>",
        f"  <artifactId>{artifact_id}</artifactId>",
        f"  <version>{version}</version>",
    ]
    if recipe_artifacts:
        lines.append("  <dependencies>")
        for dep_group, dep_artifact, dep_version in recipe_artifacts:
            lines.extend(
                [
                    "    <dependency>",
                    f"      <groupId>{dep_group}</groupId>",
                    f"      <artifactId>{dep_artifact}</artifactId>",
                    f"      <version>{dep_version}</version>",
                    "    </dependency>",
                ]
            )
        lines.append("  </dependencies>")
    lines.append("</plugin>")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
