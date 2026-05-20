from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from migration_factory.contracts.migration import (
    BuildValidationStatus,
    LedgerError,
    LedgerStatus,
    initialize_ledger,
    load_ledger,
    mark_unit_awaiting_build,
    mark_unit_in_progress,
    save_ledger,
)

from .executor import CommandResult, run_command
from .plan import MigrationPlan, MigrationUnit, load_migration_plan
from .rewrite import build_rewrite_run_command, inject_rewrite_plugin


class TransformationAgentError(Exception):
    pass


@dataclass(frozen=True)
class TransformationRunResult:
    ledger_file: Path
    status: str
    completed_units: list[str]
    blocked_unit: str | None = None


def run_transformation_agent(
    modernized_app_path: str | Path,
    openrewrite_plugin_txt: str | Path,
    migration_plan_path: str | Path,
    *,
    start_unit: str | None = None,
    dry_run: bool = False,
    stream_output: bool = True,
    wait_for_continue: bool = True,
) -> TransformationRunResult:
    plan = load_migration_plan(migration_plan_path, modernized_app_path)
    _ensure_target_workspace(plan.target_path)
    _ensure_ledger(plan)
    _inject_plugin_once(plan, openrewrite_plugin_txt, dry_run=dry_run)

    start_index = _resolve_start_index(plan, start_unit)
    ledger = load_ledger(plan.ledger_file)
    if start_unit is None:
        start_index = max(start_index, int(ledger.get("next_unit_index", 0)))

    for unit_index in range(start_index, len(plan.units)):
        unit = plan.units[unit_index]
        _run_unit(
            plan=plan,
            unit=unit,
            unit_index=unit_index,
            dry_run=dry_run,
            stream_output=stream_output,
        )

        if wait_for_continue:
            input(
                f"\nUnit {unit.id} is awaiting Build Agent validation.\n"
                f"Run Build Agent with --ledger-file {plan.ledger_file} in another terminal.\n"
                "Press Enter to continue to the next migration unit..."
            )

        validation = _verify_build_validation(plan.ledger_file, unit.id)
        if validation != BuildValidationStatus.PASSED:
            ledger = load_ledger(plan.ledger_file)
            return _result_from_ledger(plan.ledger_file, ledger)

    ledger = load_ledger(plan.ledger_file)
    ledger["status"] = LedgerStatus.COMPLETED
    ledger["current_unit"] = None
    ledger["build_validation"] = {
        "required": False,
        "status": BuildValidationStatus.NOT_REQUIRED,
    }
    save_ledger(plan.ledger_file, ledger)
    return _result_from_ledger(plan.ledger_file, ledger)


def _run_unit(
    *,
    plan: MigrationPlan,
    unit: MigrationUnit,
    unit_index: int,
    dry_run: bool,
    stream_output: bool,
) -> None:
    unit_started = time.monotonic()
    print(f"\nStarting {unit.id}: {unit.title or ''}".rstrip())
    mark_unit_in_progress(plan.ledger_file, unit_id=unit.id, unit_index=unit_index, title=unit.title)

    command_results: list[dict[str, Any]] = []
    recorded_transformations: list[dict[str, Any]] = []

    for transformation in unit.transformations:
        transformation_type = transformation.get("type")
        if transformation_type == "openrewrite":
            active_recipes = [str(item) for item in transformation.get("active_recipes", [])]
            command = build_rewrite_run_command(active_recipes)
            if dry_run:
                command_results.append({"command": command, "dry_run": True, "exit_code": 0})
                continue
            result = run_command(command, cwd=plan.target_path, stream_output=stream_output)
            command_results.append(_command_result_to_dict(result))
            if not result.succeeded:
                _mark_unit_blocked(plan, unit, f"OpenRewrite command failed: {command}", command_results)
                raise TransformationAgentError(f"OpenRewrite command failed for {unit.id}: {command}")
            continue

        recorded_transformations.append(
            {
                "type": transformation_type,
                "status": "recorded_not_executed",
                "description": transformation.get("description"),
            }
        )

    ledger = mark_unit_awaiting_build(
        plan.ledger_file,
        unit_id=unit.id,
        expected_files=unit.expected_files,
        checks=unit.checks,
    )
    ledger["units"][unit.id]["transformations"] = recorded_transformations
    ledger["units"][unit.id]["commands"] = command_results
    ledger["units"][unit.id]["unit_duration_seconds"] = round(time.monotonic() - unit_started, 6)
    save_ledger(plan.ledger_file, ledger)


def _verify_build_validation(ledger_file: Path, unit_id: str) -> str:
    ledger = load_ledger(ledger_file)
    validation = ledger.get("build_validation", {})
    status = validation.get("status")
    validation_unit = validation.get("unit_id")

    if status == BuildValidationStatus.PASSED and validation_unit == unit_id:
        print(f"Build validation passed for {unit_id}.")
        return BuildValidationStatus.PASSED

    if status == BuildValidationStatus.FAILED and validation_unit == unit_id:
        print(f"Build validation failed for {unit_id}. Transformation is blocked.")
        return BuildValidationStatus.FAILED

    print(f"Build validation is still pending for {unit_id}. Transformation is blocked.")
    return BuildValidationStatus.PENDING


def _inject_plugin_once(plan: MigrationPlan, plugin_txt_path: str | Path, *, dry_run: bool) -> None:
    ledger = load_ledger(plan.ledger_file)
    if ledger.get("openrewrite_plugin", {}).get("injected"):
        return

    if dry_run:
        ledger["openrewrite_plugin"] = {
            "injected": False,
            "dry_run": True,
            "plugin_txt_path": str(Path(plugin_txt_path).expanduser().resolve()),
        }
        save_ledger(plan.ledger_file, ledger)
        return

    injection = inject_rewrite_plugin(plan.target_path, plugin_txt_path)
    ledger["openrewrite_plugin"] = {
        "injected": True,
        "pom_path": str(injection.pom_path),
        "coordinates": list(injection.coordinates),
    }
    save_ledger(plan.ledger_file, ledger)


def _ensure_ledger(plan: MigrationPlan) -> None:
    if plan.ledger_file.is_file():
        return
    initialize_ledger(
        plan.ledger_file,
        migration_id=plan.migration_id,
        migration_name=plan.migration_name,
        total_units=len(plan.units),
        target_path=plan.target_path,
    )


def _ensure_target_workspace(target_path: Path) -> None:
    if not target_path.is_dir():
        raise TransformationAgentError(f"Modernized app path does not exist or is not a directory: {target_path}")


def _resolve_start_index(plan: MigrationPlan, start_unit: str | None) -> int:
    if start_unit is None:
        return 0
    for index, unit in enumerate(plan.units):
        if unit.id == start_unit:
            return index
    raise TransformationAgentError(f"Unknown migration unit: {start_unit}")


def _mark_unit_blocked(
    plan: MigrationPlan,
    unit: MigrationUnit,
    reason: str,
    command_results: list[dict[str, Any]],
) -> None:
    ledger = load_ledger(plan.ledger_file)
    ledger["status"] = LedgerStatus.BLOCKED
    ledger["blocked_unit"] = unit.id
    ledger["units"].setdefault(unit.id, {})["status"] = LedgerStatus.BLOCKED
    ledger["units"][unit.id]["blocking_reason"] = reason
    ledger["units"][unit.id]["commands"] = command_results
    save_ledger(plan.ledger_file, ledger)


def _command_result_to_dict(result: CommandResult) -> dict[str, Any]:
    return {
        "command": result.command,
        "exit_code": result.exit_code,
        "duration_seconds": round(float(result.duration_seconds), 6),
        "stdout_tail": result.stdout[-40:],
        "stderr_tail": result.stderr[-40:],
    }


def _result_from_ledger(ledger_file: Path, ledger: dict[str, Any]) -> TransformationRunResult:
    return TransformationRunResult(
        ledger_file=ledger_file,
        status=str(ledger.get("status")),
        completed_units=[str(item) for item in ledger.get("completed_units", [])],
        blocked_unit=ledger.get("blocked_unit"),
    )
