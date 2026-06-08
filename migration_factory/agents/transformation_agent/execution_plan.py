from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from migration_factory.approval import (
    check_approval_decision,
    check_approved_plan_lock,
    read_approval_decision,
)

from .rewrite import (
    OpenRewritePolicy,
    default_openrewrite_policy,
    normalize_openrewrite_goal,
    openrewrite_policy_from_mapping,
)


TRANSFORMATION_PLAN_SCHEMA_VERSION = "1.3"
TRANSFORMATION_DIR_NAME = "transformation"
TRANSFORMATION_EXECUTION_PLAN = "transformation_execution_plan.yaml"
DEFAULT_AZURE_MESSAGING_SERVICEBUS_VERSION = "7.17.16"


class TransformationExecutionPlanError(ValueError):
    """Raised when approved planning artifacts cannot be adapted for Transformer."""


def write_transformation_execution_plan(
    modernized_app_path: str | Path,
    run_id: str,
) -> Path:
    app_path = Path(modernized_app_path).expanduser().resolve()
    run_dir = app_path / ".migration" / "runs" / run_id

    _ensure_approved(run_dir, run_id)

    migration_plan = _read_yaml_mapping(run_dir / "planning" / "migration_plan.yaml")
    migration_units = _read_yaml_mapping(run_dir / "planning" / "migration_units.yaml")
    assessment_report = _read_json_mapping(run_dir / "assessment" / "assessment_report.json")
    rewrite_plugin_plan = _read_optional_json_mapping(run_dir / "analysis" / "rewrite_plugin_plan.json")
    dependency_graph = _read_optional_json_mapping(run_dir / "analysis" / "dependency_graph.json")

    payload = _build_transformer_plan(
        app_path=app_path,
        run_dir=run_dir,
        run_id=run_id,
        migration_plan=migration_plan,
        migration_units=migration_units,
        analysis_report=_read_json_mapping(run_dir / "analysis" / "analysis_report.json"),
        assessment_report=assessment_report,
        rewrite_plugin_plan=rewrite_plugin_plan,
        dependency_graph=dependency_graph,
    )

    output_path = run_dir / TRANSFORMATION_DIR_NAME / TRANSFORMATION_EXECUTION_PLAN
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_dump_yaml(payload), encoding="utf-8")
    return output_path


def _ensure_approved(run_dir: Path, run_id: str) -> None:
    decision_errors = check_approval_decision(run_dir, expected_run_id=run_id)
    if decision_errors:
        raise TransformationExecutionPlanError("; ".join(decision_errors))

    lock_errors = check_approved_plan_lock(run_dir, expected_run_id=run_id)
    if lock_errors:
        raise TransformationExecutionPlanError("; ".join(lock_errors))

    decision = read_approval_decision(run_dir).get("decision")
    if decision != "approved":
        raise TransformationExecutionPlanError(
            f"approval_decision.json decision must be approved, got {decision!r}"
        )


def _build_transformer_plan(
    *,
    app_path: Path,
    run_dir: Path,
    run_id: str,
    migration_plan: dict[str, Any],
    migration_units: dict[str, Any],
    analysis_report: dict[str, Any],
    assessment_report: dict[str, Any],
    rewrite_plugin_plan: dict[str, Any] | None,
    dependency_graph: dict[str, Any] | None,
) -> dict[str, Any]:
    units = migration_units.get("units")
    if not isinstance(units, list) or not units:
        raise TransformationExecutionPlanError("planning/migration_units.yaml must contain units")

    global_openrewrite = _global_openrewrite_config(rewrite_plugin_plan)
    has_unit_openrewrite = any(_unit_openrewrite_config(unit, global_openrewrite) is not None for unit in units)
    first_write_unit = _first_write_unit_id(units) if global_openrewrite["active_recipes"] and not has_unit_openrewrite else None
    profile = migration_plan.get("profile") or assessment_report.get("profile")
    tooling_versions = _mapping_of_strings(migration_plan.get("tooling_versions"))
    framework_versions = _mapping_of_strings(migration_plan.get("framework_versions"))
    validation_signals = _detected_validation_usage(app_path, analysis_report, dependency_graph)
    legacy_azure_servicebus_signals = _detected_legacy_azure_servicebus_usage(
        app_path,
        analysis_report,
        dependency_graph,
    )

    return {
        "schema_version": TRANSFORMATION_PLAN_SCHEMA_VERSION,
        "migration": {
            "id": run_id,
            "name": str(profile or run_id),
        },
        "workspaces": {
            "target": {
                "path": str(app_path),
                "migration_dir": ".migration",
                "ledger_file": ".migration/ledger.json",
            },
            "sandbox": {
                "path": str((run_dir / "workspaces" / "sandbox").resolve()),
            },
        },
        "execution_context": {
            "run_dir": str(run_dir.resolve()),
            "sandbox_execution": True,
            "workspace_path": str((run_dir / "workspaces" / "sandbox").resolve()),
            "approval_decision_path": str((run_dir / "approval" / "approval_decision.json").resolve()),
            "approved_plan_lock_path": str((run_dir / "approval" / "approved_plan_lock.json").resolve()),
        },
        "policies": {
            "openrewrite": _openrewrite_policy_payload(app_path, rewrite_plugin_plan),
        },
        "migration_units": [
            _adapt_unit(
                unit,
                global_openrewrite=global_openrewrite,
                first_write_unit=first_write_unit,
                dependency_graph=dependency_graph,
                tooling_versions=tooling_versions,
                framework_versions=framework_versions,
                validation_signals=validation_signals,
                legacy_azure_servicebus_signals=legacy_azure_servicebus_signals,
            )
            for unit in units
        ],
    }


def _adapt_unit(
    raw_unit: Any,
    *,
    global_openrewrite: dict[str, Any],
    first_write_unit: str | None,
    dependency_graph: dict[str, Any] | None,
    tooling_versions: dict[str, str],
    framework_versions: dict[str, str],
    validation_signals: list[str],
    legacy_azure_servicebus_signals: list[str],
) -> dict[str, Any]:
    if not isinstance(raw_unit, dict):
        raise TransformationExecutionPlanError("planning/migration_units.yaml units must be mappings")

    unit_id = raw_unit.get("id")
    if not unit_id:
        raise TransformationExecutionPlanError("planning/migration_units.yaml unit missing id")
    unit_id = str(unit_id)

    transformations: list[dict[str, Any]] = []
    unit_openrewrite = _unit_openrewrite_config(raw_unit, global_openrewrite)
    if unit_openrewrite is not None:
        openrewrite_transformation = {"type": "openrewrite", **unit_openrewrite}
        transformations.append(openrewrite_transformation)
    elif global_openrewrite["active_recipes"] and unit_id == first_write_unit:
        openrewrite_transformation = {
            "type": "openrewrite",
            "active_recipes": list(global_openrewrite["active_recipes"]),
        }
        if global_openrewrite["recipe_artifacts"]:
            openrewrite_transformation["recipe_artifacts"] = list(global_openrewrite["recipe_artifacts"])
        transformations.append(openrewrite_transformation)
    transformations.extend(
        _deterministic_source_transformations(
            raw_unit,
            dependency_graph,
            tooling_versions,
            framework_versions,
            validation_signals,
            legacy_azure_servicebus_signals,
        )
    )
    transformations.append(
        {
            "type": "custom_code_change",
            "description": str(raw_unit.get("goal") or raw_unit.get("title") or unit_id),
        }
    )

    return {
        "id": unit_id,
        "title": raw_unit.get("goal") or raw_unit.get("title"),
        "java_home_env": _string_or_none(raw_unit.get("java_home_env")),
        "java_home_used": _resolve_java_home(_string_or_none(raw_unit.get("java_home_env"))),
        "hop_id": _string_or_none(raw_unit.get("hop_id")),
        "expected_files": _expected_files(raw_unit),
        "transformations": transformations,
        "checks": _checks(raw_unit),
    }


def _expected_files(unit: dict[str, Any]) -> list[str]:
    for key in ("expected_files", "expected_source_files", "expected_artifacts"):
        values = unit.get(key)
        if values is not None:
            return _string_list(values)
    return []


def _checks(unit: dict[str, Any]) -> list[dict[str, Any]]:
    validation = _string_list(unit.get("validation"))
    if not validation:
        return []

    return [
        {
            "id": "validation",
            "command": " ".join(validation),
            "required": _is_required_check(unit.get("required")),
        }
    ]


def _is_required_check(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    text = str(value).strip().lower()
    if text in {"no", "false", "auto"}:
        return False
    if text in {"yes", "true"}:
        return True
    return True


def _first_write_unit_id(units: list[Any]) -> str | None:
    for unit in units:
        if isinstance(unit, dict) and unit.get("writes_source") is True and unit.get("id"):
            return str(unit["id"])
    for unit in units:
        if isinstance(unit, dict) and unit.get("id"):
            return str(unit["id"])
    return None


def _first_write_unit_index(units: list[Any]) -> int:
    for index, unit in enumerate(units):
        if isinstance(unit, dict) and unit.get("writes_source") is True and unit.get("id"):
            return index
    return 0


def _global_openrewrite_config(rewrite_plugin_plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = rewrite_plugin_plan or {}
    return {
        "active_recipes": _string_list(plan.get("active_recipes")),
        "recipe_artifacts": _string_list(plan.get("recipe_artifacts")),
    }


def _openrewrite_policy_payload(app_path: Path, rewrite_plugin_plan: dict[str, Any] | None) -> dict[str, Any]:
    canonical_policy = _load_ai_hub_openrewrite_policy(app_path)
    artifact_policy = _policy_from_plan_metadata(rewrite_plugin_plan)
    effective_policy = _merge_openrewrite_policies(canonical_policy, artifact_policy)
    return {
        "preview_allowed": effective_policy.preview_allowed,
        "apply_allowed": effective_policy.apply_allowed,
        "sandbox_apply_allowed": effective_policy.sandbox_apply_allowed,
        "sandbox_apply_requires_approval": effective_policy.sandbox_apply_requires_approval,
        "sandbox_apply_requires_plan_lock": effective_policy.sandbox_apply_requires_plan_lock,
        "sandbox_apply_requires_workspace_under_run": effective_policy.sandbox_apply_requires_workspace_under_run,
        "allowed_preview_goals": list(effective_policy.allowed_preview_goals),
        "allowed_sandbox_apply_goals": list(effective_policy.allowed_sandbox_apply_goals),
        "forbidden_apply_goals": list(effective_policy.forbidden_apply_goals),
    }


def _load_ai_hub_openrewrite_policy(app_path: Path) -> OpenRewritePolicy:
    path = _canonical_transformation_policy_path(app_path)
    if path is None or not path.is_file():
        return default_openrewrite_policy()
    try:
        payload = _read_yaml_file(path)
    except Exception:
        return default_openrewrite_policy()
    openrewrite = payload.get("openrewrite")
    if not isinstance(openrewrite, dict):
        return default_openrewrite_policy()
    required_keys = {
        "preview_allowed",
        "apply_allowed",
        "allowed_preview_goals",
        "forbidden_apply_goals",
    }
    if not required_keys.issubset(openrewrite):
        return default_openrewrite_policy()
    return openrewrite_policy_from_mapping(openrewrite)


def _canonical_transformation_policy_path(app_path: Path) -> Path | None:
    resolved_app_path = app_path.expanduser().resolve()
    for base in (resolved_app_path, *resolved_app_path.parents):
        candidate = base / "modernizer-solution-ai-hub" / "policies" / "transformation.yaml"
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[3] / "modernizer-solution-ai-hub" / "policies" / "transformation.yaml"


def _policy_from_plan_metadata(rewrite_plugin_plan: dict[str, Any] | None) -> OpenRewritePolicy | None:
    plan = rewrite_plugin_plan or {}
    openrewrite = plan.get("openrewrite") if isinstance(plan.get("openrewrite"), dict) else {}
    if not isinstance(plan, dict):
        return None
    has_top_level = any(
        key in plan
        for key in (
            "preview_allowed",
            "apply_allowed",
            "preview_goals",
            "forbidden_apply_goals",
            "apply_goals_forbidden",
            "sandbox_apply_allowed",
            "sandbox_apply_requires_approval",
            "sandbox_apply_requires_plan_lock",
            "sandbox_apply_requires_workspace_under_run",
            "allowed_sandbox_apply_goals",
        )
    )
    has_nested = any(
        key in openrewrite
        for key in (
            "preview_allowed",
            "apply_allowed",
            "allowed_preview_goals",
            "forbidden_apply_goals",
            "sandbox_apply_allowed",
            "sandbox_apply_requires_approval",
            "sandbox_apply_requires_plan_lock",
            "sandbox_apply_requires_workspace_under_run",
            "allowed_sandbox_apply_goals",
        )
    )
    if not has_top_level and not has_nested:
        return None

    metadata: dict[str, Any] = {}
    preview_allowed = plan.get("preview_allowed", openrewrite.get("preview_allowed"))
    if preview_allowed is not None:
        metadata["preview_allowed"] = preview_allowed
    apply_allowed = plan.get("apply_allowed", openrewrite.get("apply_allowed"))
    if apply_allowed is None and "apply_goals_forbidden" in plan:
        apply_allowed = not bool(plan.get("apply_goals_forbidden"))
    if apply_allowed is not None:
        metadata["apply_allowed"] = apply_allowed
    sandbox_apply_allowed = plan.get("sandbox_apply_allowed", openrewrite.get("sandbox_apply_allowed"))
    if sandbox_apply_allowed is not None:
        metadata["sandbox_apply_allowed"] = sandbox_apply_allowed
    sandbox_apply_requires_approval = plan.get(
        "sandbox_apply_requires_approval",
        openrewrite.get("sandbox_apply_requires_approval"),
    )
    if sandbox_apply_requires_approval is not None:
        metadata["sandbox_apply_requires_approval"] = sandbox_apply_requires_approval
    sandbox_apply_requires_plan_lock = plan.get(
        "sandbox_apply_requires_plan_lock",
        openrewrite.get("sandbox_apply_requires_plan_lock"),
    )
    if sandbox_apply_requires_plan_lock is not None:
        metadata["sandbox_apply_requires_plan_lock"] = sandbox_apply_requires_plan_lock
    sandbox_apply_requires_workspace_under_run = plan.get(
        "sandbox_apply_requires_workspace_under_run",
        openrewrite.get("sandbox_apply_requires_workspace_under_run"),
    )
    if sandbox_apply_requires_workspace_under_run is not None:
        metadata["sandbox_apply_requires_workspace_under_run"] = sandbox_apply_requires_workspace_under_run
    preview_goals = _string_list(plan.get("preview_goals")) or _string_list(openrewrite.get("allowed_preview_goals"))
    if preview_goals:
        metadata["allowed_preview_goals"] = preview_goals
    sandbox_apply_goals = _string_list(plan.get("allowed_sandbox_apply_goals")) or _string_list(
        openrewrite.get("allowed_sandbox_apply_goals")
    )
    if sandbox_apply_goals:
        metadata["allowed_sandbox_apply_goals"] = sandbox_apply_goals
    forbidden_apply_goals = _string_list(plan.get("forbidden_apply_goals")) or _string_list(openrewrite.get("forbidden_apply_goals"))
    if forbidden_apply_goals:
        metadata["forbidden_apply_goals"] = forbidden_apply_goals
    return openrewrite_policy_from_mapping(metadata)


def _merge_openrewrite_policies(
    canonical_policy: OpenRewritePolicy,
    artifact_policy: OpenRewritePolicy | None,
) -> OpenRewritePolicy:
    if artifact_policy is None:
        return canonical_policy
    canonical_preview = _normalized_goal_map(canonical_policy.allowed_preview_goals)
    artifact_preview = _normalized_goal_map(artifact_policy.allowed_preview_goals)
    merged_preview = [
        goal for normalized, goal in canonical_preview.items() if normalized in artifact_preview
    ] or list(canonical_policy.allowed_preview_goals)
    forbidden_apply_goals = _dedupe_goals(
        [*canonical_policy.forbidden_apply_goals, *artifact_policy.forbidden_apply_goals]
    )
    return OpenRewritePolicy(
        preview_allowed=canonical_policy.preview_allowed and artifact_policy.preview_allowed,
        apply_allowed=canonical_policy.apply_allowed and artifact_policy.apply_allowed,
        sandbox_apply_allowed=canonical_policy.sandbox_apply_allowed,
        sandbox_apply_requires_approval=canonical_policy.sandbox_apply_requires_approval,
        sandbox_apply_requires_plan_lock=canonical_policy.sandbox_apply_requires_plan_lock,
        sandbox_apply_requires_workspace_under_run=canonical_policy.sandbox_apply_requires_workspace_under_run,
        allowed_preview_goals=tuple(merged_preview),
        allowed_sandbox_apply_goals=tuple(canonical_policy.allowed_sandbox_apply_goals),
        forbidden_apply_goals=tuple(forbidden_apply_goals),
    )


def _normalized_goal_map(goals: tuple[str, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for goal in goals:
        normalized = normalize_openrewrite_goal(goal)
        if normalized not in mapping:
            mapping[normalized] = str(goal)
    return mapping


def _dedupe_goals(goals: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for goal in goals:
        normalized = normalize_openrewrite_goal(goal)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(goal))
    return result


def _unit_openrewrite_config(raw_unit: Any, global_openrewrite: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw_unit, dict):
        return None
    config = raw_unit.get("openrewrite")
    if not isinstance(config, dict):
        return None

    active_recipes = _string_list(config.get("active_recipes"))
    if not active_recipes:
        return None

    recipe_artifacts = _string_list(config.get("recipe_artifacts")) or list(global_openrewrite["recipe_artifacts"])
    unit_config: dict[str, Any] = {"active_recipes": active_recipes}
    if recipe_artifacts:
        unit_config["recipe_artifacts"] = recipe_artifacts

    for key in ("apply_goal",):
        value = config.get(key)
        if value is not None:
            unit_config[key] = str(value)
    for key in ("apply_maven_args", "analysis_preview_maven_args"):
        values = _string_list(config.get(key))
        if values:
            unit_config[key] = values
    return unit_config


def _deterministic_source_transformations(
    raw_unit: Any,
    dependency_graph: dict[str, Any] | None,
    tooling_versions: dict[str, str],
    framework_versions: dict[str, str],
    validation_signals: list[str],
    legacy_azure_servicebus_signals: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_unit, dict):
        return []
    unit_id = str(raw_unit.get("id") or "")
    if unit_id == "spring-boot-2-7-stabilization":
        jackson_operation: dict[str, Any] = {
            "op": "align_jackson_dependency_management",
            "version": "2.13.5",
        }
        present_artifacts = _present_optional_jackson_artifacts(dependency_graph)
        if present_artifacts:
            jackson_operation["present_artifacts"] = present_artifacts
        return [
            {"type": "spring_data_sort_by_factory_method"},
            {
                "type": "maven_pom_patch",
                "operations": [
                    jackson_operation,
                    {
                        "op": "remove_dependency_if_version_matches",
                        "group_id": "org.mockito",
                        "artifact_id": "mockito-inline",
                        "version_pattern": r"^[0-9]+(?:\.[0-9]+)*\.x$",
                    },
                ],
            },
        ]
    if unit_id in {"java-17", "java-21"}:
        lombok_version = tooling_versions.get("lombok")
        jacoco_version = tooling_versions.get("jacoco")
        compiler_plugin_version = tooling_versions.get("maven_compiler_plugin")
        azure_servicebus_version = (
            framework_versions.get("azure_messaging_servicebus")
            or DEFAULT_AZURE_MESSAGING_SERVICEBUS_VERSION
        )
        operations: list[dict[str, Any]] = []
        if lombok_version:
            operations.append(
                {
                    "op": "align_lombok_version",
                    "version": lombok_version,
                }
            )
        if jacoco_version:
            operations.append(
                {
                    "op": "align_jacoco_version",
                    "version": jacoco_version,
                }
            )
        if unit_id == "java-21":
            compiler_operation: dict[str, Any] = {"op": "align_maven_compiler_parameters"}
            if compiler_plugin_version:
                compiler_operation["plugin_version"] = compiler_plugin_version
            operations.append(compiler_operation)
            if legacy_azure_servicebus_signals:
                operations.append(
                    {
                        "op": "ensure_dependency",
                        "group_id": "com.azure",
                        "artifact_id": "azure-messaging-servicebus",
                        "version": azure_servicebus_version,
                    }
                )
        transformations: list[dict[str, Any]] = []
        if operations:
            transformations.append(
                {
                    "type": "maven_pom_patch",
                    "operations": operations,
                }
            )
        if unit_id == "java-21":
            transformations.append({"type": "mockito_final_class_inline_mock_maker"})
            if legacy_azure_servicebus_signals:
                transformations.append({"type": "azure_servicebus_legacy_to_modern"})
        return transformations
    if unit_id == "spring-boot-3-5-14":
        jackson_version = framework_versions.get("jackson")
        jackson_annotations_version = framework_versions.get("jackson_annotations")
        jjwt_version = framework_versions.get("jjwt")
        juneau_version = framework_versions.get("juneau")
        thymeleaf_version = framework_versions.get("thymeleaf")
        compiler_plugin_version = tooling_versions.get("maven_compiler_plugin")
        azure_servicebus_version = (
            framework_versions.get("azure_messaging_servicebus")
            or DEFAULT_AZURE_MESSAGING_SERVICEBUS_VERSION
        )
        operations: list[dict[str, Any]] = []
        if jackson_version:
            jackson_operation: dict[str, Any] = {
                "op": "align_jackson_dependency_management",
                "version": jackson_version,
            }
            if jackson_annotations_version:
                jackson_operation["version_overrides"] = {
                    "com.fasterxml.jackson.core:jackson-annotations": jackson_annotations_version,
                }
            present_artifacts = _present_optional_jackson_artifacts(dependency_graph)
            if present_artifacts:
                jackson_operation["present_artifacts"] = present_artifacts
            operations.append(jackson_operation)
        if jjwt_version:
            operations.append(
                {
                    "op": "align_jjwt_version",
                    "version": jjwt_version,
                }
            )
        juneau_operation: dict[str, Any] = {"op": "align_juneau_version"}
        if juneau_version:
            juneau_operation["version"] = juneau_version
        operations.append(juneau_operation)
        thymeleaf_operation: dict[str, Any] = {
            "op": "align_thymeleaf_dependencies",
            "prefer_bom_managed": True,
        }
        if thymeleaf_version:
            thymeleaf_operation["version"] = thymeleaf_version
        operations.append(thymeleaf_operation)
        operations.append(
            {
                "op": "align_validation_dependencies",
                "detected_validation_usage": validation_signals,
                "prefer_boot_starter": True,
                **(
                    {"non_boot_api_version": framework_versions["jakarta_validation_api"]}
                    if framework_versions.get("jakarta_validation_api")
                    else {}
                ),
            }
        )
        slf4j_version = framework_versions.get("slf4j_api")
        spring_security_version = framework_versions.get("spring_security")
        operations.append(
            {
                "op": "align_slf4j_logging",
                **({"slf4j_api_version": slf4j_version} if slf4j_version else {}),
            }
        )
        operations.append(
            {
                "op": "align_spring_security_dependencies",
                "present_artifacts": _present_spring_security_artifacts(dependency_graph),
                **(
                    {"spring_security_version": spring_security_version}
                    if spring_security_version
                    else {}
                ),
            }
        )
        compiler_operation: dict[str, Any] = {"op": "align_maven_compiler_parameters"}
        if compiler_plugin_version:
            compiler_operation["plugin_version"] = compiler_plugin_version
        operations.append(compiler_operation)
        if legacy_azure_servicebus_signals:
            operations.append(
                {
                    "op": "ensure_dependency",
                    "group_id": "com.azure",
                    "artifact_id": "azure-messaging-servicebus",
                    "version": azure_servicebus_version,
                }
            )
        transformations = [
            {
                "type": "maven_pom_patch",
                "operations": operations,
            },
            {"type": "jjwt_api_compatibility_migration"},
            {"type": "spring6_exception_handler_override_alignment"},
            {"type": "spring_boot_test_mockbean_to_mockitobean"},
            {"type": "mockito_initmocks_to_openmocks"},
            {"type": "test_javax_servlet_imports_to_jakarta"},
            {"type": "junit_assertthat_to_hamcrest_matcherassert"},
            {"type": "jakarta_hybrid_strategy_gate"},
            {"type": "powermock_legacy_test_strategy_gate"},
        ]
        if legacy_azure_servicebus_signals:
            transformations.append({"type": "azure_servicebus_legacy_to_modern"})
        transformations.append({"type": "azure_sdk_migration_playbook_gate"})
        return transformations
    return []


def _detected_validation_usage(
    app_path: Path,
    analysis_report: dict[str, Any] | None,
    dependency_graph: dict[str, Any] | None,
) -> list[str]:
    signals: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            signals.append(text)

    report = analysis_report if isinstance(analysis_report, dict) else {}
    for key in ("imports", "java_imports", "detected_imports"):
        value = report.get(key)
        if isinstance(value, list):
            for item in value:
                token = str(item).strip()
                if token.startswith(("jakarta.validation", "javax.validation")):
                    add(token)
                if token.endswith("ConstraintViolationException"):
                    add(token)

    project_metadata = report.get("project_metadata")
    if isinstance(project_metadata, dict):
        imports = project_metadata.get("imports")
        if isinstance(imports, list):
            for item in imports:
                token = str(item).strip()
                if token.startswith(("jakarta.validation", "javax.validation")):
                    add(token)
                if token.endswith("ConstraintViolationException"):
                    add(token)
        import_stats = project_metadata.get("import_stats")
        if isinstance(import_stats, dict):
            javax_count = import_stats.get("javax_count")
            if isinstance(javax_count, int) and javax_count > 0:
                add("javax_count>0")

    dependencies = report.get("dependencies")
    if isinstance(dependencies, list):
        for item in dependencies:
            if not isinstance(item, dict):
                continue
            hay = " ".join(
                str(item.get(key) or "").lower()
                for key in ("groupId", "group_id", "artifactId", "artifact_id")
            )
            if "validation-api" in hay or "jakarta.validation" in hay:
                add(hay)

    if isinstance(dependency_graph, dict):
        for name in sorted(_collect_dependency_names(dependency_graph.get("root"))):
            lower = name.lower()
            if "validation-api" in lower or "jakarta.validation" in lower:
                add(name)

    source_root = app_path / "src" / "main" / "java"
    if source_root.is_dir():
        for java_file in source_root.rglob("*.java"):
            try:
                text = java_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = java_file.read_text(encoding="latin-1")
            if "jakarta.validation" in text:
                add("jakarta.validation")
            if "javax.validation" in text:
                add("javax.validation")
            if "ConstraintViolationException" in text:
                add("ConstraintViolationException")

    return signals


def _present_optional_jackson_artifacts(dependency_graph: dict[str, Any] | None) -> list[str]:
    if not isinstance(dependency_graph, dict):
        return []
    root = dependency_graph.get("root")
    names = _collect_dependency_names(root)
    matches: list[str] = []
    for coordinate in (
        "com.fasterxml.jackson.dataformat:jackson-dataformat-csv",
        "com.fasterxml.jackson.dataformat:jackson-dataformat-xml",
        "com.fasterxml.jackson.module:jackson-module-jaxb-annotations",
    ):
        if coordinate in names:
            matches.append(coordinate)
    return matches


def _present_spring_security_artifacts(dependency_graph: dict[str, Any] | None) -> list[str]:
    if not isinstance(dependency_graph, dict):
        return []
    root = dependency_graph.get("root")
    names = _collect_dependency_names(root)
    return sorted(name for name in names if name.startswith("org.springframework.security:"))


def _detected_legacy_azure_servicebus_usage(
    app_path: Path,
    analysis_report: dict[str, Any] | None,
    dependency_graph: dict[str, Any] | None,
) -> list[str]:
    signals: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            signals.append(text)

    report = analysis_report if isinstance(analysis_report, dict) else {}
    for key in ("imports", "java_imports", "detected_imports"):
        value = report.get(key)
        if isinstance(value, list):
            for item in value:
                token = str(item).strip()
                if token.startswith("com.microsoft.azure.servicebus"):
                    add(token)

    project_metadata = report.get("project_metadata")
    if isinstance(project_metadata, dict):
        imports = project_metadata.get("imports")
        if isinstance(imports, list):
            for item in imports:
                token = str(item).strip()
                if token.startswith("com.microsoft.azure.servicebus"):
                    add(token)

    dependencies = report.get("dependencies")
    if isinstance(dependencies, list):
        for item in dependencies:
            if not isinstance(item, dict):
                continue
            group_id = str(item.get("groupId") or item.get("group_id") or "").strip()
            artifact_id = str(item.get("artifactId") or item.get("artifact_id") or "").strip()
            if group_id == "com.microsoft.azure" and artifact_id == "azure-servicebus":
                add(f"{group_id}:{artifact_id}")

    if isinstance(dependency_graph, dict):
        for name in sorted(_collect_dependency_names(dependency_graph.get("root"))):
            if name == "com.microsoft.azure:azure-servicebus":
                add(name)

    src_root = app_path / "src"
    if src_root.is_dir():
        for java_file in src_root.rglob("*.java"):
            try:
                text = java_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = java_file.read_text(encoding="latin-1")
            if "com.microsoft.azure.servicebus" in text:
                add("com.microsoft.azure.servicebus")
            if "TopicClient" in text:
                add("TopicClient")
            if "ServiceBusException" in text:
                add("ServiceBusException")

    return signals


def _collect_dependency_names(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    names: set[str] = set()
    raw_name = node.get("name")
    if isinstance(raw_name, str):
        parts = raw_name.split(":")
        if len(parts) >= 2:
            names.add(f"{parts[0]}:{parts[1]}")
    for child in node.get("dependencies", []):
        names.update(_collect_dependency_names(child))
    return names


def _mapping_of_strings(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        key_text = str(key).strip()
        value_text = str(item or "").strip()
        if key_text and value_text:
            result[key_text] = value_text
    return result


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return [str(value)]


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _resolve_java_home(java_home_env: str | None) -> str | None:
    if not java_home_env:
        return None
    value = os.environ.get(java_home_env)
    if not value:
        return None
    text = str(value).strip()
    return text or None


def _read_json_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TransformationExecutionPlanError(f"Missing required artifact: {path}")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TransformationExecutionPlanError(f"Invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise TransformationExecutionPlanError(f"Artifact must be a JSON object: {path}")
    return loaded


def _read_optional_json_mapping(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json_mapping(path)


def _read_yaml_file(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise TransformationExecutionPlanError("PyYAML is required to adapt planning artifacts") from exc

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Artifact must be a YAML mapping: {path}")
    return loaded


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TransformationExecutionPlanError(f"Missing required artifact: {path}")
    try:
        return _read_yaml_file(path)
    except ValueError as exc:
        raise TransformationExecutionPlanError(str(exc)) from exc


def _dump_yaml(payload: dict[str, Any]) -> str:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise TransformationExecutionPlanError("PyYAML is required to write Transformer plan") from exc

    return yaml.safe_dump(payload, sort_keys=False)
