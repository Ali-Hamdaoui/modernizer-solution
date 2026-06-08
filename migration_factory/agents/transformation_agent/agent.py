from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import time
from typing import Any

from migration_factory.agents.build_agent.detection import JavaProjectDetectionError, detect_java_project
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
from .maven_pom_patcher import MavenPomPatchError, apply_maven_pom_patch
from .plan import MigrationPlan, MigrationUnit, load_migration_plan
from .pom_patches import (
    patch_forbidden_source_patterns_allow_jakarta,
    patch_batch_config_flat_file_item_reader_constructor,
    patch_jjwt_api_parser_builder_compatibility,
    patch_maven_enforcer_java_version,
    patch_mockito_final_class_inline_mock_maker,
    patch_mockito_initmocks_to_openmocks,
    patch_test_javax_servlet_imports_to_jakarta,
    patch_junit_assertthat_to_hamcrest_matcherassert,
    patch_pom_property,
    patch_quality_rules_allow_jakarta,
    patch_security_config_authorize_http_requests,
    patch_spring_boot_test_mockbean_to_mockitobean,
    patch_spring_data_sort_constructor_usage,
    patch_spring6_exception_handler_override_signatures,
)
from .review_gates import review_powermock_legacy_test_strategy
from .review_gates import review_jakarta_hybrid_strategy
from .review_gates import review_azure_sdk_migration_playbook
from .review_gates import review_jjwt_api_migration
from .rewrite import (
    OpenRewriteExecutionContext,
    RewritePluginError,
    build_rewrite_run_command,
    normalize_openrewrite_goal,
    rewrite_plugin_version_from_xml,
)


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
    plugin_version = rewrite_plugin_version_from_xml(openrewrite_plugin_txt)

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
            plugin_version=plugin_version,
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
    plugin_version: str,
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
            recipe_artifacts = [str(item) for item in transformation.get("recipe_artifacts", [])]
            requested_goal = str(transformation.get("apply_goal") or "").strip() or None
            apply_maven_args = [str(item) for item in transformation.get("apply_maven_args", [])]
            try:
                openrewrite_context = _openrewrite_execution_context(plan, unit)
                command = build_rewrite_run_command(
                    active_recipes,
                    recipe_artifacts=recipe_artifacts,
                    plugin_version=plugin_version,
                    apply_goal=requested_goal,
                    maven_args=apply_maven_args,
                    policy=plan.openrewrite_policy,
                    context=openrewrite_context,
                )
            except RewritePluginError as exc:
                normalized_goal = normalize_openrewrite_goal(requested_goal)
                reason = (
                    f"OPENREWRITE_GOAL_FORBIDDEN unit={unit.id} "
                    f"requested_goal={requested_goal or normalized_goal} normalized_goal={normalized_goal}"
                )
                recorded_transformations.append(
                    {
                        "type": transformation_type,
                        "status": "blocked",
                        "requested_goal": requested_goal or normalized_goal,
                        "normalized_goal": normalized_goal,
                        "error_code": "OPENREWRITE_GOAL_FORBIDDEN",
                        "error_message": str(exc),
                        "active_recipes": active_recipes,
                        "recipe_artifacts": recipe_artifacts,
                    }
                )
                _mark_unit_blocked(
                    plan,
                    unit,
                    reason,
                    command_results,
                    recorded_transformations=recorded_transformations,
                )
                raise TransformationAgentError(f"{reason}: {exc}") from exc
            apply_goal = requested_goal or normalize_openrewrite_goal(None)
            print(
                f"OpenRewrite apply unit={unit.id} openrewrite_goal={apply_goal} "
                f"apply_maven_args={apply_maven_args}"
            )
            if dry_run:
                command_results.append({"command": command, "dry_run": True, "exit_code": 0})
                continue
            result = run_command(
                command,
                cwd=_rewrite_working_directory(plan.target_path),
                stream_output=stream_output,
                env=_unit_java_env(unit),
            )
            command_results.append(_command_result_to_dict(result))
            if not result.succeeded:
                _mark_unit_blocked(plan, unit, f"OpenRewrite command failed: {command}", command_results)
                raise TransformationAgentError(f"OpenRewrite command failed for {unit.id}: {command}")
            continue

        if transformation_type == "maven_enforcer_java_version":
            target_range = str(transformation.get("target_range") or "[21,)")
            patches = [] if dry_run else patch_maven_enforcer_java_version(
                plan.target_path,
                unit_id=unit.id,
                target_range=target_range,
            )
            required = transformation.get("required", True) is not False
            if required and not dry_run and not patches:
                _mark_unit_blocked(
                    plan,
                    unit,
                    "REQUIRED_POM_PATCH_NOT_APPLIED maven_enforcer_java_version",
                    command_results,
                    recorded_transformations=recorded_transformations,
                )
                raise TransformationAgentError(
                    "REQUIRED_POM_PATCH_NOT_APPLIED maven_enforcer_java_version"
                )
            for patch in patches:
                print(
                    f"unit={patch.unit} patch=maven_enforcer_java_version "
                    f"file={patch.file} old_range={patch.old_range} "
                    f"new_range={patch.new_range}"
                )
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "file": "pom.xml",
                    "patches": [
                        {
                            "file": patch.file,
                            "old_range": patch.old_range,
                            "new_range": patch.new_range,
                            "unit": patch.unit,
                        }
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "pom_property":
            property_name = str(transformation.get("property") or "")
            old_value = str(transformation.get("old_value") or "")
            new_value = str(transformation.get("new_value") or "")
            patches = [] if dry_run else patch_pom_property(
                plan.target_path,
                unit_id=unit.id,
                property_name=property_name,
                old_value=old_value,
                new_value=new_value,
            )
            required = transformation.get("required", True) is not False
            if required and not dry_run and not patches:
                _mark_unit_blocked(
                    plan,
                    unit,
                    f"REQUIRED_POM_PATCH_NOT_APPLIED pom_property {property_name}",
                    command_results,
                    recorded_transformations=recorded_transformations,
                )
                raise TransformationAgentError(
                    f"REQUIRED_POM_PATCH_NOT_APPLIED pom_property {property_name}"
                )
            for patch in patches:
                print(
                    f"unit={patch.unit} patch=pom_property file={patch.file} "
                    f"property={patch.property} old_value={patch.old_value} "
                    f"new_value={patch.new_value}"
                )
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "file": "pom.xml",
                    "patches": [
                        {
                            "file": patch.file,
                            "property": patch.property,
                            "old_value": patch.old_value,
                            "new_value": patch.new_value,
                            "unit": patch.unit,
                        }
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "maven_pom_patch":
            operations = transformation.get("operations")
            operation_list = operations if isinstance(operations, list) else []
            pom_path = str(transformation.get("pom_path") or "pom.xml")
            if dry_run:
                recorded_transformations.append(
                    {
                        "unit_id": unit.id,
                        "type": transformation_type,
                        "transformation_type": transformation_type,
                        "status": "dry_run",
                        "operation_count": len(operation_list),
                        "operations_applied": [],
                        "files_changed": [],
                    }
                )
                continue
            try:
                result = apply_maven_pom_patch(
                    plan.target_path,
                    unit_id=unit.id,
                    operations=operation_list,
                    pom_path=pom_path,
                )
            except MavenPomPatchError as exc:
                failure_record = {
                    "unit_id": unit.id,
                    "type": transformation_type,
                    "transformation_type": transformation_type,
                    "status": "failed",
                    "operation_count": len(operation_list),
                    "operations_applied": exc.operations_applied,
                    "files_changed": [],
                    "error_message": exc.message,
                    "error_code": exc.code,
                    "pom_file": exc.pom_file,
                }
                recorded_transformations.append(failure_record)
                _mark_unit_blocked(
                    plan,
                    unit,
                    f"MAVEN_POM_PATCH_FAILED {exc.code}: {exc.message}",
                    command_results,
                    recorded_transformations=recorded_transformations,
                )
                raise TransformationAgentError(
                    f"MAVEN_POM_PATCH_FAILED {exc.code}: {exc.message}"
                ) from exc

            for operation in result.operations_applied:
                print(
                    f"unit={unit.id} patch=maven_pom_patch file={result.pom_file} "
                    f"op={operation.get('op')} status={operation.get('status')}"
                )
            recorded_transformations.append(
                {
                    "unit_id": result.unit_id,
                    "type": transformation_type,
                    "transformation_type": transformation_type,
                    "status": result.status,
                    "operation_count": result.operation_count,
                    "operations_applied": result.operations_applied,
                    "files_changed": result.files_changed,
                    "pom_file": result.pom_file,
                    "error_message": None,
                }
            )
            continue

        if transformation_type == "security_authorize_http_requests":
            patches = [] if dry_run else patch_security_config_authorize_http_requests(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "batch_flat_file_item_reader_constructor":
            patches = [] if dry_run else patch_batch_config_flat_file_item_reader_constructor(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "forbidden_source_patterns_allow_jakarta":
            patches = [] if dry_run else patch_forbidden_source_patterns_allow_jakarta(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "quality_rules_allow_jakarta":
            patches = [] if dry_run else patch_quality_rules_allow_jakarta(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "spring_data_sort_by_factory_method":
            patches = [] if dry_run else patch_spring_data_sort_constructor_usage(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "spring6_exception_handler_override_alignment":
            patches = [] if dry_run else patch_spring6_exception_handler_override_signatures(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {
                            "file": patch.file,
                            "patch": patch.patch,
                            "unit": patch.unit,
                            "old_signature": patch.old_signature,
                            "new_signature": patch.new_signature,
                        }
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "spring_boot_test_mockbean_to_mockitobean":
            patches = [] if dry_run else patch_spring_boot_test_mockbean_to_mockitobean(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "mockito_initmocks_to_openmocks":
            patches = [] if dry_run else patch_mockito_initmocks_to_openmocks(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "mockito_final_class_inline_mock_maker":
            patches = [] if dry_run else patch_mockito_final_class_inline_mock_maker(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "test_javax_servlet_imports_to_jakarta":
            patches = [] if dry_run else patch_test_javax_servlet_imports_to_jakarta(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "junit_assertthat_to_hamcrest_matcherassert":
            patches = [] if dry_run else patch_junit_assertthat_to_hamcrest_matcherassert(
                plan.target_path,
                unit_id=unit.id,
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "applied" if patches else "not_applicable",
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                }
            )
            continue

        if transformation_type == "jjwt_api_compatibility_migration":
            patches = [] if dry_run else patch_jjwt_api_parser_builder_compatibility(
                plan.target_path,
                unit_id=unit.id,
            )
            review = (
                None
                if dry_run
                else review_jjwt_api_migration(
                    plan.target_path,
                    unit_id=unit.id,
                    run_id=plan.migration_id,
                )
            )
            for patch in patches:
                print(f"unit={patch.unit} patch={patch.patch} file={patch.file}")
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": (
                        "review_only"
                        if review is not None and review.detected and not patches
                        else ("applied" if patches else "not_applicable")
                    ),
                    "patches": [
                        {"file": patch.file, "patch": patch.patch, "unit": patch.unit}
                        for patch in patches
                    ],
                    "artifact_path": str(review.artifact_path) if review is not None else "",
                    "detected": bool(review.detected) if review is not None else False,
                    "source_usage_files": list(review.source_usage_files) if review is not None else [],
                    "usage_patterns": list(review.usage_patterns) if review is not None else [],
                    "human_review_required": bool(review.human_review_required) if review is not None else False,
                    "warnings": list(review.warnings) if review is not None else [],
                    "warning_message": (
                        "Legacy JJWT parser API usage remains after version alignment; manual review required before trusting Boot 3 compatibility."
                        if review is not None and review.detected
                        else ""
                    ),
                }
            )
            continue

        if transformation_type == "powermock_legacy_test_strategy_gate":
            review = (
                None
                if dry_run
                else review_powermock_legacy_test_strategy(
                    plan.target_path,
                    unit_id=unit.id,
                    run_id=plan.migration_id,
                )
            )
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "review_only" if review is not None and review.detected else "not_applicable",
                    "artifact_path": str(review.artifact_path) if review is not None else "",
                    "detected": bool(review.detected) if review is not None else False,
                    "dependencies": list(review.dependencies) if review is not None else [],
                    "usage_files": list(review.usage_files) if review is not None else [],
                    "usage_patterns": list(review.usage_patterns) if review is not None else [],
                    "risk_level": review.risk_level if review is not None else "NONE",
                    "human_review_required": bool(review.human_review_required) if review is not None else False,
                    "warning_message": (
                        "PowerMock legacy test strategy detected; manual review required before trusting Boot 3 test behavior."
                        if review is not None and review.detected
                        else ""
                    ),
                }
            )
            continue

        if transformation_type == "jakarta_hybrid_strategy_gate":
            review = (
                None
                if dry_run
                else review_jakarta_hybrid_strategy(
                    plan.target_path,
                    unit_id=unit.id,
                    run_id=plan.migration_id,
                )
            )
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "review_only" if review is not None and review.detected else "not_applicable",
                    "artifact_path": str(review.artifact_path) if review is not None else "",
                    "detected": bool(review.detected) if review is not None else False,
                    "detected_namespaces": list(review.detected_namespaces) if review is not None else [],
                    "human_review_required": bool(review.human_review_required) if review is not None else False,
                    "consumer_compatibility_warning": bool(review.consumer_compatibility_warning) if review is not None else False,
                    "warnings": list(review.warnings) if review is not None else [],
                    "warning_message": (
                        "Jakarta hybrid strategy detected high-risk javax.* usage; manual review required before blind namespace migration."
                        if review is not None and review.human_review_required
                        else ""
                    ),
                }
            )
            continue

        if transformation_type == "azure_sdk_migration_playbook_gate":
            review = (
                None
                if dry_run
                else review_azure_sdk_migration_playbook(
                    plan.target_path,
                    unit_id=unit.id,
                    run_id=plan.migration_id,
                )
            )
            recorded_transformations.append(
                {
                    "type": transformation_type,
                    "status": "review_only" if review is not None and review.detected else "not_applicable",
                    "artifact_path": str(review.artifact_path) if review is not None else "",
                    "detected": bool(review.detected) if review is not None else False,
                    "migration_mode": review.migration_mode if review is not None else "NOT_DETECTED",
                    "old_azure_dependencies": list(review.old_azure_dependencies) if review is not None else [],
                    "new_azure_dependencies": list(review.new_azure_dependencies) if review is not None else [],
                    "source_usage_files": list(review.source_usage_files) if review is not None else [],
                    "usage_patterns": list(review.usage_patterns) if review is not None else [],
                    "risk_level": review.risk_level if review is not None else "NONE",
                    "human_review_required": bool(review.human_review_required) if review is not None else False,
                    "warnings": list(review.warnings) if review is not None else [],
                    "warning_message": (
                        "Azure SDK migration review detected legacy or mixed Azure SDK usage; manual review required before changing client/runtime behavior."
                        if review is not None and review.migration_mode in {"OLD_SDK_ONLY", "MIXED_OLD_AND_NEW"}
                        else ""
                    ),
                }
            )
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
    recorded_transformations: list[dict[str, Any]] | None = None,
) -> None:
    ledger = load_ledger(plan.ledger_file)
    ledger["status"] = LedgerStatus.BLOCKED
    ledger["blocked_unit"] = unit.id
    ledger["units"].setdefault(unit.id, {})["status"] = LedgerStatus.BLOCKED
    ledger["units"][unit.id]["blocking_reason"] = reason
    ledger["units"][unit.id]["commands"] = command_results
    if recorded_transformations is not None:
        ledger["units"][unit.id]["transformations"] = recorded_transformations
    save_ledger(plan.ledger_file, ledger)


def _command_result_to_dict(result: CommandResult) -> dict[str, Any]:
    return {
        "command": result.command,
        "exit_code": result.exit_code,
        "duration_seconds": round(float(result.duration_seconds), 6),
        "stdout_tail": result.stdout[-40:],
        "stderr_tail": result.stderr[-40:],
    }


def _openrewrite_execution_context(plan: MigrationPlan, unit: MigrationUnit) -> OpenRewriteExecutionContext:
    execution_context = plan.raw.get("execution_context")
    if not isinstance(execution_context, dict):
        execution_context = {}

    workspaces = plan.raw.get("workspaces")
    sandbox_path: Path | None = None
    if isinstance(workspaces, dict):
        sandbox_workspace = workspaces.get("sandbox")
        if isinstance(sandbox_workspace, dict) and sandbox_workspace.get("path"):
            sandbox_path = Path(str(sandbox_workspace["path"])).expanduser().resolve()

    workspace_path_value = execution_context.get("workspace_path")
    if workspace_path_value:
        workspace_path = Path(str(workspace_path_value)).expanduser().resolve()
    elif sandbox_path is not None:
        workspace_path = sandbox_path
    else:
        workspace_path = plan.target_path

    run_dir_value = execution_context.get("run_dir")
    run_dir = Path(str(run_dir_value)).expanduser().resolve() if run_dir_value else None

    lock_path_value = execution_context.get("approved_plan_lock_path")
    approved_plan_lock_path = (
        Path(str(lock_path_value)).expanduser().resolve()
        if lock_path_value
        else None
    )

    approval_decision_value = execution_context.get("approval_decision")
    approval_decision = str(approval_decision_value).strip() if approval_decision_value is not None else None
    if approval_decision is None:
        approval_decision_path_value = execution_context.get("approval_decision_path")
        if approval_decision_path_value:
            approval_decision_path = Path(str(approval_decision_path_value)).expanduser().resolve()
            if approval_decision_path.is_file():
                try:
                    payload = json.loads(approval_decision_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
                if isinstance(payload, dict) and payload.get("decision") is not None:
                    approval_decision = str(payload.get("decision")).strip()
    approval_approved = str(approval_decision or "").strip().lower() == "approved"

    sandbox_execution = execution_context.get("sandbox_execution")
    if sandbox_execution is None and run_dir is not None:
        sandbox_root = run_dir / "workspaces" / "sandbox"
        try:
            workspace_path.resolve().relative_to(sandbox_root.resolve())
            sandbox_execution = True
        except ValueError:
            sandbox_execution = False

    return OpenRewriteExecutionContext(
        unit_id=unit.id,
        run_dir=run_dir,
        workspace_path=workspace_path,
        approved_plan_lock_path=approved_plan_lock_path,
        approval_decision=approval_decision,
        approval_approved=approval_approved,
        sandbox_execution=bool(sandbox_execution),
    )


def _unit_java_env(unit: MigrationUnit) -> dict[str, str] | None:
    java_home = str(unit.raw.get("java_home_used") or "").strip()
    if not java_home:
        java_home_env = str(unit.raw.get("java_home_env") or "").strip()
        if java_home_env:
            java_home = str(os.environ.get(java_home_env) or "").strip()
    if not java_home:
        return None
    env = os.environ.copy()
    env["JAVA_HOME"] = java_home
    env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def _result_from_ledger(ledger_file: Path, ledger: dict[str, Any]) -> TransformationRunResult:
    return TransformationRunResult(
        ledger_file=ledger_file,
        status=str(ledger.get("status")),
        completed_units=[str(item) for item in ledger.get("completed_units", [])],
        blocked_unit=ledger.get("blocked_unit"),
    )


def _rewrite_working_directory(target_path: Path) -> Path:
    try:
        project = detect_java_project(target_path)
    except JavaProjectDetectionError:
        return target_path
    return project.path
