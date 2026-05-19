from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO, TypeVar

import yaml

from migration_factory.agents.build_agent import run_build_agent
from migration_factory.agents.transformation_agent import run_transformation_agent
from migration_factory.agents.transformation_agent.agent import TransformationAgentError
from migration_factory.agents.transformation_agent.execution_plan import (
    TRANSFORMATION_DIR_NAME,
    TransformationExecutionPlanError,
    write_transformation_execution_plan,
)
from migration_factory.agents.transformation_agent.plan import MigrationPlan, MigrationPlanError, load_migration_plan
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
from migration_factory.contracts.migration import LedgerStatus, load_ledger


STATUS_APPROVED = "APPROVED_FOR_TRANSFORM"
STATUS_SANDBOX = "SANDBOX_PREPARED"
STATUS_RUNNING = "TRANSFORM_RUNNING"
STATUS_AWAITING_BUILD_AGENT = "TRANSFORM_AWAITING_BUILD_AGENT"
STATUS_APPLIED = "TRANSFORM_APPLIED_IN_SANDBOX"
STATUS_FAILED = "TRANSFORM_FAILED_IN_SANDBOX"
STATUS_BUILD_REQUIRED = "BUILD_VALIDATION_REQUIRED"
STATUS_BUILD_RUNNING = "BUILD_RUNNING_IN_SANDBOX"
STATUS_BUILD_PASSED = "BUILD_PASSED_IN_SANDBOX"
STATUS_BUILD_FAILED = "BUILD_FAILED_IN_SANDBOX"
STATUS_APPROVAL_FAILED = "APPROVAL_FAILED"

_T = TypeVar("_T")


class TransformV1AfterApprovalError(ValueError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    log_file = _resolve_log_file(run_dir, args.log_file)
    verbose = not args.quiet

    try:
        modernized_app = Path(args.modernized_app).expanduser().resolve()
        legacy_app = Path(args.legacy_app).expanduser().resolve()
        try:
            run_id = _ensure_approved_for_transform(run_dir, approved_by=args.approved_by)
        except (ApprovalArtifactError, TransformV1AfterApprovalError) as exc:
            print(STATUS_APPROVAL_FAILED)
            _print_failure_details(exc, log_file)
            return 1
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

        plan = load_migration_plan(generated_plan, sandbox.path)
        return _run_transformer_with_build_validation(
            sandbox_path=sandbox.path,
            plugin_xml=plugin_xml,
            generated_plan=generated_plan,
            plan=plan,
            run_dir=run_dir,
            log_file=log_file,
            verbose=verbose,
        )
    except ApprovalArtifactError as exc:
        print(STATUS_APPROVAL_FAILED)
        _print_failure_details(exc, log_file)
        return 1
    except (
        MigrationPlanError,
        RewritePluginError,
        TransformationAgentError,
        TransformationExecutionPlanError,
        TransformationWorkspaceError,
        TransformV1AfterApprovalError,
    ) as exc:
        print(STATUS_FAILED)
        _print_failure_details(exc, log_file)
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
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--quiet",
        dest="quiet",
        action="store_true",
        default=True,
        help="Keep subprocess output out of the terminal. This is the default.",
    )
    output_group.add_argument(
        "--verbose",
        dest="quiet",
        action="store_false",
        help="Stream full subprocess output to the terminal while also writing the log file.",
    )
    parser.add_argument("--log-file", help="Path for full Phase 2 subprocess output")
    return parser


def _run_transformer_with_build_validation(
    *,
    sandbox_path: Path,
    plugin_xml: Path,
    generated_plan: Path,
    plan: MigrationPlan,
    run_dir: Path,
    log_file: Path,
    verbose: bool,
) -> int:
    next_unit: str | None = None
    awaited_units: set[str] = set()
    source_units_completed: set[str] = set()
    source_unit_ids = _source_changing_unit_ids(plan)
    max_transformer_runs = len(plan.units) + 1

    for _ in range(max_transformer_runs):
        print(STATUS_RUNNING)
        result = _run_with_logged_output(
            lambda: run_transformation_agent(
                sandbox_path,
                plugin_xml,
                generated_plan,
                start_unit=next_unit,
                dry_run=False,
                stream_output=True,
                wait_for_continue=False,
            ),
            log_file=log_file,
            verbose=verbose,
        )
        if verbose:
            print(f"Ledger: {result.ledger_file}")
            print(f"Transformer status: {result.status}")

        if result.status == LedgerStatus.AWAITING_BUILD_AGENT:
            if verbose:
                print(STATUS_AWAITING_BUILD_AGENT)
            ledger = load_ledger(result.ledger_file)
            unit_id = _awaiting_build_unit_id(ledger)
            if unit_id in awaited_units:
                raise TransformV1AfterApprovalError(
                    f"Transformer resumed to the same build-pending unit twice: {unit_id}"
                )
            awaited_units.add(unit_id)

            if verbose:
                print(STATUS_BUILD_REQUIRED)
            print(STATUS_BUILD_RUNNING)
            build_result = _run_with_logged_output(
                lambda: run_build_agent(
                    project_path=sandbox_path,
                    ledger_file=result.ledger_file,
                    output_dir=run_dir / "build",
                    stream_output=True,
                    validation_unit_id=unit_id,
                    source_changing_unit=unit_id in source_unit_ids,
                ),
                log_file=log_file,
                verbose=verbose,
            )
            if not build_result.succeeded:
                print(STATUS_BUILD_FAILED)
                _print_failure_details(
                    TransformV1AfterApprovalError(_build_failure_message(build_result)),
                    log_file,
                )
                return 1

            print(STATUS_BUILD_PASSED)
            if verbose:
                print(f"Build validated unit: {unit_id}")
            if unit_id in source_unit_ids:
                source_units_completed.add(unit_id)

            next_unit = _next_unit_after(plan, unit_id)
            if next_unit is None:
                if source_units_completed:
                    print(STATUS_APPLIED)
                print("Sandbox migration candidate ready.")
                return 0
            continue

        if result.blocked_unit or result.status == LedgerStatus.BLOCKED:
            print(STATUS_FAILED)
            if result.blocked_unit:
                _print_failure_details(TransformV1AfterApprovalError(f"Blocked unit: {result.blocked_unit}"), log_file)
            else:
                _print_failure_details(TransformV1AfterApprovalError("Transformer blocked"), log_file)
            return 1

        if result.status == LedgerStatus.COMPLETED:
            completed_source_units = source_unit_ids.intersection(result.completed_units)
            if completed_source_units:
                print(STATUS_APPLIED)
            print("Sandbox migration candidate ready.")
            return 0

        raise TransformV1AfterApprovalError(f"Unexpected Transformer status: {result.status}")

    raise TransformV1AfterApprovalError(
        f"Transformer resume loop exceeded {max_transformer_runs} runs for {len(plan.units)} units"
    )


class _OutputTee:
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _run_with_logged_output(callback: Callable[[], _T], *, log_file: Path, verbose: bool) -> _T:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log_stream:
        stdout: TextIO = _OutputTee(sys.stdout, log_stream) if verbose else log_stream
        stderr: TextIO = _OutputTee(sys.stderr, log_stream) if verbose else log_stream
        with redirect_stdout(stdout), redirect_stderr(stderr):
            return callback()


def _resolve_log_file(run_dir: Path, log_file: str | None) -> Path:
    if log_file:
        return Path(log_file).expanduser().resolve()
    return run_dir / "logs" / "phase2_transform.log"


def _print_failure_details(exc: Exception, log_file: Path) -> None:
    print(f"ERROR: {exc}", file=sys.stderr)
    print(f"log_file: {log_file}", file=sys.stderr)
    _print_log_tail(log_file)


def _print_log_tail(log_file: Path, *, line_count: int = 30) -> None:
    if not log_file.is_file():
        print("No log output captured.", file=sys.stderr)
        return

    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        print("No log output captured.", file=sys.stderr)
        return

    print(f"--- Last {min(line_count, len(lines))} log lines ---", file=sys.stderr)
    for line in lines[-line_count:]:
        print(line, file=sys.stderr)


def _build_failure_message(build_result: Any) -> str:
    parts = [
        f"Build result kind: {build_result.result_kind}",
        f"Build message: {build_result.message}",
    ]
    if build_result.error_contract_path:
        parts.append(f"Build error contract: {build_result.error_contract_path}")
    return "; ".join(parts)


def _awaiting_build_unit_id(ledger: dict[str, Any]) -> str:
    validation = ledger.get("build_validation", {})
    unit_id = validation.get("unit_id") or ledger.get("current_unit")
    if not unit_id:
        raise TransformV1AfterApprovalError("Transformer is awaiting build validation but ledger has no unit_id")
    return str(unit_id)


def _next_unit_after(plan: MigrationPlan, unit_id: str) -> str | None:
    unit_ids = [unit.id for unit in plan.units]
    try:
        index = unit_ids.index(unit_id)
    except ValueError as exc:
        raise TransformV1AfterApprovalError(f"Build-pending unit is not in plan: {unit_id}") from exc
    next_index = index + 1
    if next_index >= len(unit_ids):
        return None
    return unit_ids[next_index]


def _source_changing_unit_ids(plan: MigrationPlan) -> set[str]:
    source_changing_types = {"openrewrite"}
    return {
        unit.id
        for unit in plan.units
        if any(str(transformation.get("type")) in source_changing_types for transformation in unit.transformations)
    }


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
