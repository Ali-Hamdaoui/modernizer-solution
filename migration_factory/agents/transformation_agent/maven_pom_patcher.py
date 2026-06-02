from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

JACKSON_MANDATORY_MANAGED_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("com.fasterxml.jackson.core", "jackson-databind"),
    ("com.fasterxml.jackson.core", "jackson-core"),
    ("com.fasterxml.jackson.core", "jackson-annotations"),
    ("com.fasterxml.jackson.datatype", "jackson-datatype-jsr310"),
    ("com.fasterxml.jackson.datatype", "jackson-datatype-jdk8"),
    ("com.fasterxml.jackson.module", "jackson-module-parameter-names"),
)
JACKSON_OPTIONAL_MANAGED_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("com.fasterxml.jackson.dataformat", "jackson-dataformat-csv"),
    ("com.fasterxml.jackson.dataformat", "jackson-dataformat-xml"),
    ("com.fasterxml.jackson.module", "jackson-module-jaxb-annotations"),
)
JACKSON_VERSION_PROPERTY_NAMES: tuple[str, ...] = (
    "fasterxml-jackson.version",
    "jackson.version",
)
LOMBOK_COORDINATE = ("org.projectlombok", "lombok")
LOMBOK_VERSION_PROPERTY_NAMES: tuple[str, ...] = (
    "lombok.version",
)
JACOCO_PLUGIN_COORDINATE = ("org.jacoco", "jacoco-maven-plugin")
JACOCO_AGENT_COORDINATE = ("org.jacoco", "org.jacoco.agent")
JACOCO_VERSION_PROPERTY_NAMES: tuple[str, ...] = (
    "jacoco.version",
    "jacoco-maven-plugin.version",
)
MAVEN_COMPILER_PLUGIN_COORDINATE = ("org.apache.maven.plugins", "maven-compiler-plugin")
MAVEN_COMPILER_PLUGIN_VERSION_PROPERTY_NAMES: tuple[str, ...] = (
    "maven-compiler-plugin.version",
)
THYMELEAF_CORE_COORDINATE = ("org.thymeleaf", "thymeleaf")
THYMELEAF_SPRING_ARTIFACT_IDS: tuple[str, ...] = (
    "thymeleaf-spring4",
    "thymeleaf-spring5",
    "thymeleaf-spring6",
)
THYMELEAF_EXTRAS_PREFIX = "thymeleaf-extras-"
SPRING_BOOT_BOM_COORDINATE = ("org.springframework.boot", "spring-boot-dependencies")
SPRING_BOOT_PARENT_COORDINATE = ("org.springframework.boot", "spring-boot-starter-parent")
SPRING_BOOT_STARTER_VALIDATION_COORDINATE = (
    "org.springframework.boot",
    "spring-boot-starter-validation",
)
JAKARTA_VALIDATION_API_COORDINATE = ("jakarta.validation", "jakarta.validation-api")
VALIDATION_USAGE_MARKERS: tuple[str, ...] = (
    "jakarta.validation",
    "javax.validation",
    "ConstraintViolationException",
    "validation-api",
)
SLF4J_API_COORDINATE = ("org.slf4j", "slf4j-api")
SLF4J_PROPERTY_NAMES: tuple[str, ...] = (
    "org.slf4j.version",
    "slf4j.version",
)
SLF4J_TRACKED_COORDINATES: tuple[tuple[str, str], ...] = (
    ("org.slf4j", "slf4j-api"),
    ("org.slf4j", "slf4j-simple"),
    ("org.slf4j", "slf4j-log4j12"),
    ("org.slf4j", "jcl-over-slf4j"),
    ("org.slf4j", "jul-to-slf4j"),
    ("org.slf4j", "log4j-over-slf4j"),
    ("ch.qos.logback", "logback-classic"),
    ("ch.qos.logback", "logback-core"),
)
SPRING_SECURITY_GROUP_ID = "org.springframework.security"
SPRING_SECURITY_VERSION_PROPERTY_NAMES: tuple[str, ...] = (
    "spring-security.version",
)


@dataclass(frozen=True)
class MavenPomPatchOperationResult:
    op: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MavenPomPatchResult:
    unit_id: str
    pom_file: str
    operation_count: int
    operations_applied: list[dict[str, Any]]
    files_changed: list[str]
    status: str


class MavenPomPatchError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        pom_file: str,
        operation_index: int | None = None,
        operation: Mapping[str, Any] | None = None,
        operations_applied: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.pom_file = pom_file
        self.operation_index = operation_index
        self.operation = dict(operation) if operation is not None else None
        self.operations_applied = [dict(item) for item in operations_applied or []]

    def to_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "pom_file": self.pom_file,
            "operation_index": self.operation_index,
            "operation": self.operation,
            "operations_applied": self.operations_applied,
        }


def apply_maven_pom_patch(
    project_path: Path,
    *,
    unit_id: str,
    operations: Sequence[Mapping[str, Any]],
    pom_path: str = "pom.xml",
) -> MavenPomPatchResult:
    root_path = Path(project_path).expanduser().resolve()
    resolved_pom = _resolve_sandbox_path(root_path, pom_path)
    relative_pom = resolved_pom.relative_to(root_path).as_posix()

    if not resolved_pom.is_file():
        raise MavenPomPatchError(
            "POM_FILE_MISSING",
            f"pom.xml not found: {resolved_pom}",
            pom_file=relative_pom,
        )

    try:
        tree = ET.parse(resolved_pom)
    except ET.ParseError as exc:
        raise MavenPomPatchError(
            "POM_XML_INVALID",
            f"Unable to parse pom.xml: {exc}",
            pom_file=relative_pom,
        ) from exc

    root = tree.getroot()
    namespace = _namespace(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    applied: list[dict[str, Any]] = []
    changed = False

    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            raise MavenPomPatchError(
                "INVALID_OPERATION",
                "Each maven_pom_patch operation must be a mapping",
                pom_file=relative_pom,
                operation_index=index,
                operations_applied=applied,
            )
        try:
            result = _apply_operation(root, namespace, operation)
        except MavenPomPatchError as exc:
            raise MavenPomPatchError(
                exc.code,
                exc.message,
                pom_file=relative_pom,
                operation_index=index,
                operation=operation,
                operations_applied=applied,
            ) from exc

        record = {"op": result.op, "status": result.status, **result.details}
        applied.append(record)
        if result.status not in {"no_change", "not_applicable"}:
            changed = True

    if changed:
        tree.write(resolved_pom, encoding="utf-8", xml_declaration=True)

    return MavenPomPatchResult(
        unit_id=unit_id,
        pom_file=relative_pom,
        operation_count=len(operations),
        operations_applied=applied,
        files_changed=[relative_pom] if changed else [],
        status="applied" if changed else "no_change",
    )


def _apply_operation(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    op = str(operation.get("op") or "").strip()
    if not op:
        raise MavenPomPatchError(
            "INVALID_OPERATION",
            "maven_pom_patch operation is missing op",
            pom_file="pom.xml",
        )

    handlers = {
        "update_property": _update_property,
        "add_property_if_missing": _add_property_if_missing,
        "update_dependency_version": _update_dependency_version,
        "replace_dependency": _replace_dependency,
        "remove_duplicate_dependencies": _remove_duplicate_dependencies,
        "add_dependency_management_bom": _add_dependency_management_bom,
        "align_jackson_dependency_management": _align_jackson_dependency_management,
        "align_lombok_version": _align_lombok_version,
        "align_jacoco_version": _align_jacoco_version,
        "align_thymeleaf_dependencies": _align_thymeleaf_dependencies,
        "align_validation_dependencies": _align_validation_dependencies,
        "align_slf4j_logging": _align_slf4j_logging,
        "align_spring_security_dependencies": _align_spring_security_dependencies,
        "align_maven_compiler_parameters": _align_maven_compiler_parameters,
    }
    handler = handlers.get(op)
    if handler is None:
        raise MavenPomPatchError(
            "UNSUPPORTED_OPERATION",
            f"Unsupported maven_pom_patch operation: {op}",
            pom_file="pom.xml",
        )
    return handler(root, namespace, operation)


def _update_property(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    name = _required_text(operation, "name")
    value = _required_text(operation, "value")
    properties = root.find(_tag(namespace, "properties"))
    if properties is None:
        raise MavenPomPatchError(
            "PROPERTY_NOT_FOUND",
            f"Maven properties section not found for property {name}",
            pom_file="pom.xml",
        )
    property_node = properties.find(_tag(namespace, name))
    if property_node is None:
        raise MavenPomPatchError(
            "PROPERTY_NOT_FOUND",
            f"Maven property not found: {name}",
            pom_file="pom.xml",
        )
    current = (property_node.text or "").strip()
    if current == value:
        return MavenPomPatchOperationResult(
            op="update_property",
            status="no_change",
            details={"name": name, "value": value},
        )
    property_node.text = value
    return MavenPomPatchOperationResult(
        op="update_property",
        status="updated",
        details={"name": name, "old_value": current, "new_value": value},
    )


def _add_property_if_missing(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    name = _required_text(operation, "name")
    value = _required_text(operation, "value")
    properties = root.find(_tag(namespace, "properties"))
    if properties is None:
        properties = ET.SubElement(root, _tag(namespace, "properties"))
    property_node = properties.find(_tag(namespace, name))
    if property_node is not None:
        return MavenPomPatchOperationResult(
            op="add_property_if_missing",
            status="no_change",
            details={"name": name, "value": (property_node.text or "").strip()},
        )
    property_node = ET.SubElement(properties, _tag(namespace, name))
    property_node.text = value
    return MavenPomPatchOperationResult(
        op="add_property_if_missing",
        status="added",
        details={"name": name, "value": value},
    )


def _update_dependency_version(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    group_id = _required_text(operation, "group_id")
    artifact_id = _required_text(operation, "artifact_id")
    new_version = _required_text(operation, "new_version")
    matches = _find_dependencies(root, namespace, group_id, artifact_id)
    if not matches:
        raise MavenPomPatchError(
            "DEPENDENCY_NOT_FOUND",
            f"Dependency not found: {group_id}:{artifact_id}",
            pom_file="pom.xml",
        )

    updated = 0
    for dependency in matches:
        version = _ensure_child(dependency, namespace, "version")
        current = (version.text or "").strip()
        if current == new_version:
            continue
        version.text = new_version
        updated += 1

    status = "updated" if updated else "no_change"
    return MavenPomPatchOperationResult(
        op="update_dependency_version",
        status=status,
        details={
            "group_id": group_id,
            "artifact_id": artifact_id,
            "new_version": new_version,
            "matched_dependencies": len(matches),
            "updated_dependencies": updated,
        },
    )


def _replace_dependency(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    old_group_id = _required_text(operation, "old_group_id")
    old_artifact_id = _required_text(operation, "old_artifact_id")
    new_group_id = _required_text(operation, "new_group_id")
    new_artifact_id = _required_text(operation, "new_artifact_id")
    new_version = _required_text(operation, "new_version")

    matches = _find_dependencies(root, namespace, old_group_id, old_artifact_id)
    if not matches:
        replacement_exists = bool(_find_dependencies(root, namespace, new_group_id, new_artifact_id))
        if replacement_exists:
            return MavenPomPatchOperationResult(
                op="replace_dependency",
                status="no_change",
                details={
                    "old_group_id": old_group_id,
                    "old_artifact_id": old_artifact_id,
                    "new_group_id": new_group_id,
                    "new_artifact_id": new_artifact_id,
                    "new_version": new_version,
                },
            )
        raise MavenPomPatchError(
            "DEPENDENCY_NOT_FOUND",
            f"Dependency not found: {old_group_id}:{old_artifact_id}",
            pom_file="pom.xml",
        )

    replaced = 0
    for dependency in matches:
        changed = False
        changed |= _set_child_text(dependency, namespace, "groupId", new_group_id)
        changed |= _set_child_text(dependency, namespace, "artifactId", new_artifact_id)
        changed |= _set_child_text(dependency, namespace, "version", new_version)
        if changed:
            replaced += 1

    return MavenPomPatchOperationResult(
        op="replace_dependency",
        status="replaced" if replaced else "no_change",
        details={
            "old_group_id": old_group_id,
            "old_artifact_id": old_artifact_id,
            "new_group_id": new_group_id,
            "new_artifact_id": new_artifact_id,
            "new_version": new_version,
            "replaced_dependencies": replaced,
        },
    )


def _remove_duplicate_dependencies(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    removed = 0
    for dependencies in _dependency_lists(root, namespace):
        seen: set[tuple[str, str, str, str]] = set()
        duplicates: list[ET.Element] = []
        for dependency in list(dependencies.findall(_tag(namespace, "dependency"))):
            key = (
                _child_text(dependency, namespace, "groupId"),
                _child_text(dependency, namespace, "artifactId"),
                _child_text(dependency, namespace, "classifier"),
                _child_text(dependency, namespace, "type"),
            )
            if key in seen:
                duplicates.append(dependency)
                continue
            seen.add(key)
        for duplicate in duplicates:
            dependencies.remove(duplicate)
            removed += 1

    return MavenPomPatchOperationResult(
        op="remove_duplicate_dependencies",
        status="removed" if removed else "no_change",
        details={"removed_dependencies": removed},
    )


def _add_dependency_management_bom(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    group_id = _required_text(operation, "group_id")
    artifact_id = _required_text(operation, "artifact_id")
    version = _required_text(operation, "version")
    scope = _required_text(operation, "scope")
    dependency_type = _required_text(operation, "type")

    dependency_management = root.find(_tag(namespace, "dependencyManagement"))
    if dependency_management is None:
        dependency_management = ET.SubElement(root, _tag(namespace, "dependencyManagement"))
    dependencies = dependency_management.find(_tag(namespace, "dependencies"))
    if dependencies is None:
        dependencies = ET.SubElement(dependency_management, _tag(namespace, "dependencies"))

    existing = _find_dependency_in_parent(dependencies, namespace, group_id, artifact_id)
    if existing is None:
        existing = ET.SubElement(dependencies, _tag(namespace, "dependency"))
        _set_child_text(existing, namespace, "groupId", group_id)
        _set_child_text(existing, namespace, "artifactId", artifact_id)
        _set_child_text(existing, namespace, "version", version)
        _set_child_text(existing, namespace, "type", dependency_type)
        _set_child_text(existing, namespace, "scope", scope)
        return MavenPomPatchOperationResult(
            op="add_dependency_management_bom",
            status="added",
            details={
                "group_id": group_id,
                "artifact_id": artifact_id,
                "version": version,
                "scope": scope,
                "type": dependency_type,
            },
        )

    changed = False
    changed |= _set_child_text(existing, namespace, "version", version)
    changed |= _set_child_text(existing, namespace, "type", dependency_type)
    changed |= _set_child_text(existing, namespace, "scope", scope)
    return MavenPomPatchOperationResult(
        op="add_dependency_management_bom",
        status="updated" if changed else "no_change",
        details={
            "group_id": group_id,
            "artifact_id": artifact_id,
            "version": version,
            "scope": scope,
            "type": dependency_type,
        },
    )


def _align_jackson_dependency_management(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    target_version = _required_text(operation, "version")
    if not _has_jackson_signal(root, namespace):
        return MavenPomPatchOperationResult(
            op="align_jackson_dependency_management",
            status="not_applicable",
            details={"target_version": target_version},
        )

    dependencies = _dependencies_section(root, namespace)
    dependency_management = _dependency_management_section(root, namespace)

    detected_versions = sorted(_detected_jackson_versions(root, namespace))
    updated_properties: list[str] = []
    updated_direct_dependencies: list[str] = []
    version_overrides = _operation_version_overrides(operation)

    for dependency in dependencies.findall(_tag(namespace, "dependency")):
        group_id = _child_text(dependency, namespace, "groupId")
        artifact_id = _child_text(dependency, namespace, "artifactId")
        if (group_id, artifact_id) not in JACKSON_MANDATORY_MANAGED_ARTIFACTS and (
            group_id,
            artifact_id,
        ) not in JACKSON_OPTIONAL_MANAGED_ARTIFACTS:
            continue
        desired_version = version_overrides.get(f"{group_id}:{artifact_id}", target_version)
        version_node = dependency.find(_tag(namespace, "version"))
        if version_node is None or version_node.text is None:
            continue
        current_version = version_node.text.strip()
        property_name = _property_reference_name(current_version)
        if property_name:
            if _update_property_if_present(root, namespace, property_name, desired_version):
                updated_properties.append(property_name)
            continue
        if current_version and current_version != desired_version:
            version_node.text = desired_version
            updated_direct_dependencies.append(f"{group_id}:{artifact_id}")

    requested_present_artifacts = {
        item.strip()
        for item in _operation_string_list(operation, "present_artifacts")
        if item.strip()
    }
    managed_artifacts = list(JACKSON_MANDATORY_MANAGED_ARTIFACTS)
    for artifact in JACKSON_OPTIONAL_MANAGED_ARTIFACTS:
        coordinate = f"{artifact[0]}:{artifact[1]}"
        if _has_dependency(root, namespace, *artifact) or coordinate in requested_present_artifacts:
            managed_artifacts.append(artifact)

    managed_added = 0
    managed_updated = 0
    for group_id, artifact_id in managed_artifacts:
        desired_version = version_overrides.get(f"{group_id}:{artifact_id}", target_version)
        existing = _find_dependency_in_parent(dependency_management, namespace, group_id, artifact_id)
        if existing is None:
            existing = ET.SubElement(dependency_management, _tag(namespace, "dependency"))
            _set_child_text(existing, namespace, "groupId", group_id)
            _set_child_text(existing, namespace, "artifactId", artifact_id)
            _set_child_text(existing, namespace, "version", desired_version)
            managed_added += 1
            continue
        if _set_child_text(existing, namespace, "version", desired_version):
            managed_updated += 1

    status = "no_change"
    if updated_properties or updated_direct_dependencies or managed_added or managed_updated:
        status = "updated"

    return MavenPomPatchOperationResult(
        op="align_jackson_dependency_management",
        status=status,
        details={
            "target_version": target_version,
            "detected_versions": detected_versions,
            "updated_properties": updated_properties,
            "updated_direct_dependencies": updated_direct_dependencies,
            "managed_artifacts": [f"{group_id}:{artifact_id}" for group_id, artifact_id in managed_artifacts],
            "managed_dependencies_added": managed_added,
            "managed_dependencies_updated": managed_updated,
            "version_overrides": version_overrides,
        },
    )


def _align_lombok_version(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    target_version = _required_text(operation, "version")
    matches = _find_dependencies(root, namespace, *LOMBOK_COORDINATE)
    if not matches:
        return MavenPomPatchOperationResult(
            op="align_lombok_version",
            status="not_applicable",
            details={"target_version": target_version},
        )

    updated_properties: list[str] = []
    updated_dependencies: list[str] = []
    updated_managed_dependencies = 0
    old_versions: list[str] = []

    for dependency in matches:
        version_node = dependency.find(_tag(namespace, "version"))
        current_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
        if current_version:
            property_name = _property_reference_name(current_version)
            if property_name:
                resolved = _property_value(root, namespace, property_name)
                if resolved:
                    old_versions.append(resolved)
                else:
                    old_versions.append(current_version)
                if _should_upgrade_version(resolved or current_version, target_version):
                    if _update_property_if_present(root, namespace, property_name, target_version):
                        updated_properties.append(property_name)
                continue
            old_versions.append(current_version)
            if _should_upgrade_version(current_version, target_version):
                version_node.text = target_version
                updated_dependencies.append("org.projectlombok:lombok")
            continue

        managed_matches = _find_managed_dependencies(root, namespace, *LOMBOK_COORDINATE)
        if not managed_matches:
            continue
        for managed_dependency in managed_matches:
            managed_version_node = _ensure_child(managed_dependency, namespace, "version")
            managed_current = (managed_version_node.text or "").strip()
            if managed_current:
                property_name = _property_reference_name(managed_current)
                if property_name:
                    resolved = _property_value(root, namespace, property_name)
                    if resolved:
                        old_versions.append(resolved)
                    else:
                        old_versions.append(managed_current)
                    if _should_upgrade_version(resolved or managed_current, target_version):
                        if _update_property_if_present(root, namespace, property_name, target_version):
                            updated_properties.append(property_name)
                    continue
                old_versions.append(managed_current)
            if _should_upgrade_version(managed_current, target_version):
                if _set_child_text(managed_dependency, namespace, "version", target_version):
                    updated_managed_dependencies += 1

    unique_old_versions = sorted({value for value in old_versions if value})
    status = "updated" if updated_properties or updated_dependencies or updated_managed_dependencies else "no_change"
    return MavenPomPatchOperationResult(
        op="align_lombok_version",
        status=status,
        details={
            "group_id": LOMBOK_COORDINATE[0],
            "artifact_id": LOMBOK_COORDINATE[1],
            "old_versions": unique_old_versions,
            "new_version": target_version,
            "updated_properties": updated_properties,
            "updated_dependencies": updated_dependencies,
            "updated_managed_dependencies": updated_managed_dependencies,
        },
    )


def _align_jacoco_version(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    target_version = _required_text(operation, "version")
    plugin_matches = _find_plugins(root, namespace, *JACOCO_PLUGIN_COORDINATE)
    dependency_matches = _find_dependencies(root, namespace, *JACOCO_AGENT_COORDINATE)
    property_matches = [
        property_name for property_name in JACOCO_VERSION_PROPERTY_NAMES if _property_value(root, namespace, property_name)
    ]
    if not plugin_matches and not dependency_matches and not property_matches:
        return MavenPomPatchOperationResult(
            op="align_jacoco_version",
            status="not_applicable",
            details={"target_version": target_version},
        )

    updated_properties: list[str] = []
    updated_plugins = 0
    updated_dependencies: list[str] = []
    old_versions: list[str] = []
    referenced_properties: set[str] = set()

    for plugin in plugin_matches:
        version_node = plugin.find(_tag(namespace, "version"))
        current_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
        if not current_version:
            continue
        property_name = _property_reference_name(current_version)
        if property_name:
            referenced_properties.add(property_name)
            resolved = _property_value(root, namespace, property_name)
            if resolved:
                old_versions.append(resolved)
            else:
                old_versions.append(current_version)
            if _should_upgrade_version(resolved or current_version, target_version):
                if _update_property_if_present(root, namespace, property_name, target_version):
                    updated_properties.append(property_name)
            continue
        old_versions.append(current_version)
        if _should_upgrade_version(current_version, target_version):
            version_node.text = target_version
            updated_plugins += 1

    for dependency in dependency_matches:
        version_node = dependency.find(_tag(namespace, "version"))
        current_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
        if not current_version:
            if target_version and not should_use_bom:
                _set_child_text(dependency, namespace, "version", target_version)
                updated_versions.append(
                    {
                        "artifact_id": current_artifact_id,
                        "old_version": "",
                        "new_version": target_version,
                    }
                )
            continue
        property_name = _property_reference_name(current_version)
        if property_name:
            referenced_properties.add(property_name)
            resolved = _property_value(root, namespace, property_name)
            if resolved:
                old_versions.append(resolved)
            else:
                old_versions.append(current_version)
            if _should_upgrade_version(resolved or current_version, target_version):
                if _update_property_if_present(root, namespace, property_name, target_version):
                    updated_properties.append(property_name)
            continue
        old_versions.append(current_version)
        if _should_upgrade_version(current_version, target_version):
            version_node.text = target_version
            updated_dependencies.append("org.jacoco:org.jacoco.agent")

    for property_name in property_matches:
        if property_name in referenced_properties:
            continue
        current_version = _property_value(root, namespace, property_name)
        if not current_version:
            continue
        old_versions.append(current_version)
        if _should_upgrade_version(current_version, target_version):
            if _update_property_if_present(root, namespace, property_name, target_version):
                updated_properties.append(property_name)

    unique_old_versions = sorted({value for value in old_versions if value})
    status = "updated" if updated_properties or updated_plugins or updated_dependencies else "no_change"
    return MavenPomPatchOperationResult(
        op="align_jacoco_version",
        status=status,
        details={
            "group_id": JACOCO_PLUGIN_COORDINATE[0],
            "artifact_id": JACOCO_PLUGIN_COORDINATE[1],
            "old_versions": unique_old_versions,
            "new_version": target_version,
            "updated_properties": sorted(set(updated_properties)),
            "updated_plugins": updated_plugins,
            "updated_dependencies": updated_dependencies,
        },
    )


def _align_thymeleaf_dependencies(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    target_version = str(operation.get("version") or "").strip()
    prefer_bom_managed = bool(operation.get("prefer_bom_managed", False))
    thymeleaf_matches = _find_thymeleaf_dependencies(root, namespace)
    if not thymeleaf_matches:
        return MavenPomPatchOperationResult(
            op="align_thymeleaf_dependencies",
            status="not_applicable",
            details={
                "target_version": target_version or None,
                "prefer_bom_managed": prefer_bom_managed,
            },
        )

    has_boot_bom = _has_dependency(root, namespace, *SPRING_BOOT_BOM_COORDINATE)
    should_use_bom = prefer_bom_managed and has_boot_bom
    replacements: list[dict[str, Any]] = []
    removed_versions: list[dict[str, Any]] = []
    updated_versions: list[dict[str, Any]] = []
    updated_properties: list[str] = []
    old_versions: list[str] = []

    for dependency in thymeleaf_matches:
        artifact_id = _child_text(dependency, namespace, "artifactId")
        current_artifact_id = artifact_id
        if artifact_id in {"thymeleaf-spring4", "thymeleaf-spring5"}:
            replacements.append(
                {
                    "old_artifact_id": artifact_id,
                    "new_artifact_id": "thymeleaf-spring6",
                }
            )
            _set_child_text(dependency, namespace, "artifactId", "thymeleaf-spring6")
            current_artifact_id = "thymeleaf-spring6"

        version_node = dependency.find(_tag(namespace, "version"))
        current_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
        if not current_version:
            continue

        property_name = _property_reference_name(current_version)
        resolved_version = _property_value(root, namespace, property_name) if property_name else current_version
        if resolved_version:
            old_versions.append(resolved_version)

        if should_use_bom:
            if property_name:
                if version_node is not None:
                    dependency.remove(version_node)
                removed_versions.append(
                    {
                        "artifact_id": current_artifact_id,
                        "old_version": resolved_version or current_version,
                        "managed_by_bom": True,
                    }
                )
                continue
            if version_node is not None:
                dependency.remove(version_node)
                removed_versions.append(
                    {
                        "artifact_id": current_artifact_id,
                        "old_version": current_version,
                        "managed_by_bom": True,
                    }
                )
            continue

        if not target_version:
            continue
        if property_name:
            if _should_upgrade_version(resolved_version or current_version, target_version):
                if _update_property_if_present(root, namespace, property_name, target_version):
                    updated_properties.append(property_name)
                    updated_versions.append(
                        {
                            "artifact_id": current_artifact_id,
                            "old_version": resolved_version or current_version,
                            "new_version": target_version,
                        }
                    )
            continue
        if _should_upgrade_version(current_version, target_version):
            version_node.text = target_version
            updated_versions.append(
                {
                    "artifact_id": current_artifact_id,
                    "old_version": current_version,
                    "new_version": target_version,
                }
            )

    status = "updated" if replacements or removed_versions or updated_versions or updated_properties else "no_change"
    return MavenPomPatchOperationResult(
        op="align_thymeleaf_dependencies",
        status=status,
        details={
            "target_version": target_version or None,
            "prefer_bom_managed": prefer_bom_managed,
            "used_bom_management": should_use_bom,
            "old_versions": sorted({value for value in old_versions if value}),
            "replacements": replacements,
            "removed_versions": removed_versions,
            "updated_versions": updated_versions,
            "updated_properties": sorted(set(updated_properties)),
        },
    )


def _align_validation_dependencies(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    detected_usage = _detected_validation_usage_from_operation(operation)
    if not detected_usage:
        return MavenPomPatchOperationResult(
            op="align_validation_dependencies",
            status="not_applicable",
            details={"detected_validation_usage": []},
        )

    if _has_dependency(root, namespace, *SPRING_BOOT_STARTER_VALIDATION_COORDINATE):
        return MavenPomPatchOperationResult(
            op="align_validation_dependencies",
            status="no_change",
            details={
                "detected_validation_usage": detected_usage,
                "dependency_added": None,
                "dependency_already_present": "org.springframework.boot:spring-boot-starter-validation",
            },
        )

    if _has_dependency(root, namespace, *JAKARTA_VALIDATION_API_COORDINATE):
        return MavenPomPatchOperationResult(
            op="align_validation_dependencies",
            status="no_change",
            details={
                "detected_validation_usage": detected_usage,
                "dependency_added": None,
                "dependency_already_present": "jakarta.validation:jakarta.validation-api",
            },
        )

    prefer_boot_starter = bool(operation.get("prefer_boot_starter", False))
    has_boot_bom = _has_dependency(root, namespace, *SPRING_BOOT_BOM_COORDINATE)
    has_boot_parent = _has_parent(root, namespace, *SPRING_BOOT_PARENT_COORDINATE)

    dependencies = _dependencies_section(root, namespace)
    dependency_added: str | None = None

    if prefer_boot_starter and (has_boot_bom or has_boot_parent):
        dependency = ET.SubElement(dependencies, _tag(namespace, "dependency"))
        _set_child_text(dependency, namespace, "groupId", SPRING_BOOT_STARTER_VALIDATION_COORDINATE[0])
        _set_child_text(dependency, namespace, "artifactId", SPRING_BOOT_STARTER_VALIDATION_COORDINATE[1])
        dependency_added = "org.springframework.boot:spring-boot-starter-validation"
        return MavenPomPatchOperationResult(
            op="align_validation_dependencies",
            status="added",
            details={
                "detected_validation_usage": detected_usage,
                "dependency_added": dependency_added,
                "used_boot_starter": True,
                "used_boot_bom_management": has_boot_bom,
                "used_boot_parent_management": has_boot_parent,
            },
        )

    non_boot_api_version = str(operation.get("non_boot_api_version") or "").strip()
    if non_boot_api_version:
        dependency = ET.SubElement(dependencies, _tag(namespace, "dependency"))
        _set_child_text(dependency, namespace, "groupId", JAKARTA_VALIDATION_API_COORDINATE[0])
        _set_child_text(dependency, namespace, "artifactId", JAKARTA_VALIDATION_API_COORDINATE[1])
        _set_child_text(dependency, namespace, "version", non_boot_api_version)
        dependency_added = "jakarta.validation:jakarta.validation-api"
        return MavenPomPatchOperationResult(
            op="align_validation_dependencies",
            status="added",
            details={
                "detected_validation_usage": detected_usage,
                "dependency_added": dependency_added,
                "used_boot_starter": False,
                "used_boot_bom_management": has_boot_bom,
                "used_boot_parent_management": has_boot_parent,
                "api_version": non_boot_api_version,
            },
        )

    return MavenPomPatchOperationResult(
        op="align_validation_dependencies",
        status="no_change",
        details={
            "detected_validation_usage": detected_usage,
            "dependency_added": None,
            "used_boot_starter": False,
            "used_boot_bom_management": has_boot_bom,
            "used_boot_parent_management": has_boot_parent,
        },
    )


def _align_slf4j_logging(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    detected_artifacts = _detected_logging_artifacts(root, namespace)
    if not detected_artifacts:
        return MavenPomPatchOperationResult(
            op="align_slf4j_logging",
            status="not_applicable",
            details={"detected_logging_artifacts": []},
        )

    target_version = str(operation.get("slf4j_api_version") or "").strip()
    has_boot_bom = _has_dependency(root, namespace, *SPRING_BOOT_BOM_COORDINATE)
    has_boot_parent = _has_parent(root, namespace, *SPRING_BOOT_PARENT_COORDINATE)
    bom_managed = has_boot_bom or has_boot_parent
    slf4j_matches = _find_dependencies(root, namespace, *SLF4J_API_COORDINATE)
    if not slf4j_matches:
        return MavenPomPatchOperationResult(
            op="align_slf4j_logging",
            status="no_change",
            details={
                "detected_logging_artifacts": detected_artifacts,
                "old_versions": [],
                "new_versions": [],
                "removed_versions": [],
                "updated_properties": [],
                "managed_by_bom": bom_managed,
            },
        )

    old_versions: list[str] = []
    new_versions: list[str] = []
    removed_versions: list[str] = []
    updated_properties: list[str] = []

    for dependency in slf4j_matches:
        version_node = dependency.find(_tag(namespace, "version"))
        current_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
        if not current_version:
            continue
        property_name = _property_reference_name(current_version)
        resolved_version = _property_value(root, namespace, property_name) if property_name else current_version
        if resolved_version:
            old_versions.append(resolved_version)

        if bom_managed:
            if version_node is not None:
                dependency.remove(version_node)
                removed_versions.append(resolved_version or current_version)
            continue

        if not target_version:
            continue
        if property_name:
            if _should_upgrade_version(resolved_version or current_version, target_version):
                if _update_property_if_present(root, namespace, property_name, target_version):
                    updated_properties.append(property_name)
                    new_versions.append(target_version)
            continue
        if _should_upgrade_version(current_version, target_version):
            version_node.text = target_version
            new_versions.append(target_version)

    status = "updated" if removed_versions or new_versions or updated_properties else "no_change"
    return MavenPomPatchOperationResult(
        op="align_slf4j_logging",
        status=status,
        details={
            "detected_logging_artifacts": detected_artifacts,
            "old_versions": sorted({value for value in old_versions if value}),
            "new_versions": sorted({value for value in new_versions if value}),
            "removed_versions": sorted({value for value in removed_versions if value}),
            "updated_properties": sorted(set(updated_properties)),
            "managed_by_bom": bom_managed,
        },
    )


def _align_spring_security_dependencies(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    target_version = str(operation.get("spring_security_version") or "").strip()
    detected_artifacts = _detected_spring_security_artifacts(root, namespace, operation)
    if not detected_artifacts:
        return MavenPomPatchOperationResult(
            op="align_spring_security_dependencies",
            status="not_applicable",
            details={"detected_spring_security_artifacts": []},
        )

    has_boot_bom = _has_dependency(root, namespace, *SPRING_BOOT_BOM_COORDINATE)
    has_boot_parent = _has_parent(root, namespace, *SPRING_BOOT_PARENT_COORDINATE)
    bom_managed = has_boot_bom or has_boot_parent

    matches: list[ET.Element] = []
    seen: set[int] = set()
    for group_id, artifact_id in detected_artifacts:
        for dependency in _find_dependencies(root, namespace, group_id, artifact_id):
            marker = id(dependency)
            if marker in seen:
                continue
            seen.add(marker)
            matches.append(dependency)
        for dependency in _find_managed_dependencies(root, namespace, group_id, artifact_id):
            marker = id(dependency)
            if marker in seen:
                continue
            seen.add(marker)
            matches.append(dependency)

    old_versions: list[str] = []
    new_versions: list[str] = []
    removed_versions: list[str] = []
    updated_properties: list[str] = []
    updated_dependencies: list[str] = []

    for dependency in matches:
        group_id = _child_text(dependency, namespace, "groupId")
        artifact_id = _child_text(dependency, namespace, "artifactId")
        coordinate = f"{group_id}:{artifact_id}"
        version_node = dependency.find(_tag(namespace, "version"))
        current_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
        if not current_version:
            continue
        property_name = _property_reference_name(current_version)
        resolved_version = _property_value(root, namespace, property_name) if property_name else current_version
        if resolved_version:
            old_versions.append(resolved_version)

        if bom_managed:
            if version_node is not None:
                dependency.remove(version_node)
                removed_versions.append(resolved_version or current_version)
                updated_dependencies.append(coordinate)
            continue

        if not target_version:
            continue
        if property_name:
            if _should_upgrade_version(resolved_version or current_version, target_version):
                if _update_property_if_present(root, namespace, property_name, target_version):
                    updated_properties.append(property_name)
                    new_versions.append(target_version)
                    updated_dependencies.append(coordinate)
            continue
        if _should_upgrade_version(current_version, target_version):
            version_node.text = target_version
            new_versions.append(target_version)
            updated_dependencies.append(coordinate)

    status = "updated" if removed_versions or new_versions or updated_properties else "no_change"
    return MavenPomPatchOperationResult(
        op="align_spring_security_dependencies",
        status=status,
        details={
            "detected_spring_security_artifacts": [
                f"{group_id}:{artifact_id}" for group_id, artifact_id in detected_artifacts
            ],
            "old_versions": sorted({value for value in old_versions if value}),
            "new_versions": sorted({value for value in new_versions if value}),
            "removed_versions": sorted({value for value in removed_versions if value}),
            "updated_properties": sorted(set(updated_properties)),
            "updated_dependencies": sorted(set(updated_dependencies)),
            "managed_by_bom": bom_managed,
        },
    )


def _align_maven_compiler_parameters(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> MavenPomPatchOperationResult:
    target_version = str(operation.get("plugin_version") or "").strip()
    plugin_matches = _find_plugins(root, namespace, *MAVEN_COMPILER_PLUGIN_COORDINATE)
    has_plugin = bool(plugin_matches)

    if not has_plugin and not target_version:
        return MavenPomPatchOperationResult(
            op="align_maven_compiler_parameters",
            status="not_applicable",
            details={
                "old_compiler_configuration_summary": {},
                "new_compiler_configuration_summary": {},
                "plugin_added": False,
            },
        )

    old_summary = _compiler_configuration_summary(plugin_matches[0], namespace) if plugin_matches else {}

    if not plugin_matches:
        plugin = _ensure_plugin(root, namespace, *MAVEN_COMPILER_PLUGIN_COORDINATE)
        if target_version:
            _set_child_text(plugin, namespace, "version", target_version)
        plugin_matches = [plugin]
    plugin_added = not has_plugin
    if old_summary.get("parameters_enabled"):
        return MavenPomPatchOperationResult(
            op="align_maven_compiler_parameters",
            status="no_change",
            details={
                "old_compiler_configuration_summary": old_summary,
                "new_compiler_configuration_summary": old_summary,
                "plugin_added": False,
            },
        )

    updated_properties: list[str] = []
    updated_plugins = 0
    old_versions: list[str] = []

    for plugin in plugin_matches:
        version_node = plugin.find(_tag(namespace, "version"))
        current_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
        if current_version:
            property_name = _property_reference_name(current_version)
            resolved_version = _property_value(root, namespace, property_name) if property_name else current_version
            if resolved_version:
                old_versions.append(resolved_version)
            if target_version and property_name and _should_upgrade_version(resolved_version or current_version, target_version):
                if _update_property_if_present(root, namespace, property_name, target_version):
                    updated_properties.append(property_name)
            elif target_version and not property_name and _should_upgrade_version(current_version, target_version):
                version_node.text = target_version
                updated_plugins += 1
        elif target_version:
            _set_child_text(plugin, namespace, "version", target_version)
            updated_plugins += 1

        configuration = _ensure_child(plugin, namespace, "configuration")
        changed = _set_child_text(configuration, namespace, "parameters", "true")
        if not changed:
            compiler_args = configuration.find(_tag(namespace, "compilerArgs"))
            if compiler_args is None:
                continue
            args = [(_child.text or "").strip() for _child in compiler_args.findall(_tag(namespace, "arg"))]
            if "-parameters" in args:
                continue
            arg = ET.SubElement(compiler_args, _tag(namespace, "arg"))
            arg.text = "-parameters"
            changed = True
        if changed:
            updated_plugins += 1

    new_summary = _compiler_configuration_summary(plugin_matches[0], namespace)
    status = "updated" if plugin_added or updated_plugins or updated_properties else "no_change"
    return MavenPomPatchOperationResult(
        op="align_maven_compiler_parameters",
        status=status,
        details={
            "old_compiler_configuration_summary": old_summary,
            "new_compiler_configuration_summary": new_summary,
            "plugin_added": plugin_added,
            "old_versions": sorted({value for value in old_versions if value}),
            "new_version": target_version or None,
            "updated_properties": sorted(set(updated_properties)),
        },
    )


def _resolve_sandbox_path(project_path: Path, pom_path: str) -> Path:
    candidate = (project_path / pom_path).resolve()
    try:
        candidate.relative_to(project_path)
    except ValueError as exc:
        raise MavenPomPatchError(
            "POM_PATH_OUTSIDE_SANDBOX",
            f"POM patch path escapes sandbox: {pom_path}",
            pom_file=str(Path(pom_path).as_posix()),
        ) from exc
    return candidate


def _dependencies_section(root: ET.Element, namespace: str) -> ET.Element:
    dependencies = root.find(_tag(namespace, "dependencies"))
    if dependencies is None:
        dependencies = ET.SubElement(root, _tag(namespace, "dependencies"))
    return dependencies


def _dependency_management_section(root: ET.Element, namespace: str) -> ET.Element:
    dependency_management = root.find(_tag(namespace, "dependencyManagement"))
    if dependency_management is None:
        dependency_management = ET.SubElement(root, _tag(namespace, "dependencyManagement"))
    dependencies = dependency_management.find(_tag(namespace, "dependencies"))
    if dependencies is None:
        dependencies = ET.SubElement(dependency_management, _tag(namespace, "dependencies"))
    return dependencies


def _dependency_lists(root: ET.Element, namespace: str) -> list[ET.Element]:
    lists: list[ET.Element] = []
    dependencies = root.find(_tag(namespace, "dependencies"))
    if dependencies is not None:
        lists.append(dependencies)
    dependency_management = root.find(_tag(namespace, "dependencyManagement"))
    if dependency_management is not None:
        managed = dependency_management.find(_tag(namespace, "dependencies"))
        if managed is not None:
            lists.append(managed)
    return lists


def _has_dependency(root: ET.Element, namespace: str, group_id: str, artifact_id: str) -> bool:
    return bool(_find_dependencies(root, namespace, group_id, artifact_id))


def _find_dependencies(
    root: ET.Element,
    namespace: str,
    group_id: str,
    artifact_id: str,
) -> list[ET.Element]:
    matches: list[ET.Element] = []
    for dependencies in _dependency_lists(root, namespace):
        for dependency in dependencies.findall(_tag(namespace, "dependency")):
            if (
                _child_text(dependency, namespace, "groupId") == group_id
                and _child_text(dependency, namespace, "artifactId") == artifact_id
            ):
                matches.append(dependency)
    return matches


def _find_thymeleaf_dependencies(root: ET.Element, namespace: str) -> list[ET.Element]:
    matches: list[ET.Element] = []
    seen: set[int] = set()
    for dependencies in _dependency_lists(root, namespace):
        for dependency in dependencies.findall(_tag(namespace, "dependency")):
            group_id = _child_text(dependency, namespace, "groupId")
            artifact_id = _child_text(dependency, namespace, "artifactId")
            if group_id != "org.thymeleaf":
                continue
            if artifact_id == THYMELEAF_CORE_COORDINATE[1]:
                pass
            elif artifact_id in THYMELEAF_SPRING_ARTIFACT_IDS:
                pass
            elif artifact_id.startswith(THYMELEAF_EXTRAS_PREFIX):
                pass
            else:
                continue
            marker = id(dependency)
            if marker in seen:
                continue
            seen.add(marker)
            matches.append(dependency)
    return matches


def _detected_validation_usage_from_operation(operation: Mapping[str, Any]) -> list[str]:
    signals: list[str] = []
    seen: set[str] = set()
    for item in _operation_string_list(operation, "detected_validation_usage"):
        text = str(item).strip()
        if not text:
            continue
        if any(marker.lower() in text.lower() for marker in VALIDATION_USAGE_MARKERS):
            if text not in seen:
                seen.add(text)
                signals.append(text)
    return signals


def _detected_logging_artifacts(root: ET.Element, namespace: str) -> list[str]:
    detected: list[str] = []
    seen: set[str] = set()
    for group_id, artifact_id in SLF4J_TRACKED_COORDINATES:
        if _has_dependency(root, namespace, group_id, artifact_id):
            coordinate = f"{group_id}:{artifact_id}"
            if coordinate not in seen:
                seen.add(coordinate)
                detected.append(coordinate)
    return detected


def _detected_spring_security_artifacts(
    root: ET.Element,
    namespace: str,
    operation: Mapping[str, Any],
) -> list[tuple[str, str]]:
    detected: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for dependencies in _dependency_lists(root, namespace):
        for dependency in dependencies.findall(_tag(namespace, "dependency")):
            group_id = _child_text(dependency, namespace, "groupId")
            artifact_id = _child_text(dependency, namespace, "artifactId")
            if group_id != SPRING_SECURITY_GROUP_ID or not artifact_id:
                continue
            coordinate = (group_id, artifact_id)
            if coordinate in seen:
                continue
            seen.add(coordinate)
            detected.append(coordinate)

    for value in _operation_string_list(operation, "present_artifacts"):
        parts = [part.strip() for part in str(value).split(":", 1)]
        if len(parts) != 2:
            continue
        coordinate = (parts[0], parts[1])
        if coordinate[0] != SPRING_SECURITY_GROUP_ID or not coordinate[1]:
            continue
        if coordinate in seen:
            continue
        seen.add(coordinate)
        detected.append(coordinate)

    if detected:
        return detected

    for property_name in SPRING_SECURITY_VERSION_PROPERTY_NAMES:
        if _property_value(root, namespace, property_name):
            return [(SPRING_SECURITY_GROUP_ID, "spring-security-core")]
    return []


def _find_managed_dependencies(
    root: ET.Element,
    namespace: str,
    group_id: str,
    artifact_id: str,
) -> list[ET.Element]:
    dependency_management = root.find(_tag(namespace, "dependencyManagement"))
    if dependency_management is None:
        return []
    managed = dependency_management.find(_tag(namespace, "dependencies"))
    if managed is None:
        return []
    match = _find_dependency_in_parent(managed, namespace, group_id, artifact_id)
    return [match] if match is not None else []


def _has_parent(root: ET.Element, namespace: str, group_id: str, artifact_id: str) -> bool:
    parent = root.find(_tag(namespace, "parent"))
    if parent is None:
        return False
    return (
        _child_text(parent, namespace, "groupId") == group_id
        and _child_text(parent, namespace, "artifactId") == artifact_id
    )


def _plugin_lists(root: ET.Element, namespace: str) -> list[ET.Element]:
    lists: list[ET.Element] = []
    for path in (
        "./build/plugins",
        "./build/pluginManagement/plugins",
        "./profiles/profile/build/plugins",
        "./profiles/profile/build/pluginManagement/plugins",
    ):
        plugins = root.find(_qualify_path(namespace, path))
        if plugins is not None:
            lists.append(plugins)
    return lists


def _ensure_plugin(root: ET.Element, namespace: str, group_id: str, artifact_id: str) -> ET.Element:
    plugins = root.find(_qualify_path(namespace, "./build/plugins"))
    if plugins is None:
        build = root.find(_tag(namespace, "build"))
        if build is None:
            build = ET.SubElement(root, _tag(namespace, "build"))
        plugins = build.find(_tag(namespace, "plugins"))
        if plugins is None:
            plugins = ET.SubElement(build, _tag(namespace, "plugins"))
    plugin = _find_plugin_in_parent(plugins, namespace, group_id, artifact_id)
    if plugin is not None:
        return plugin
    plugin = ET.SubElement(plugins, _tag(namespace, "plugin"))
    _set_child_text(plugin, namespace, "groupId", group_id)
    _set_child_text(plugin, namespace, "artifactId", artifact_id)
    return plugin


def _find_plugins(
    root: ET.Element,
    namespace: str,
    group_id: str,
    artifact_id: str,
) -> list[ET.Element]:
    matches: list[ET.Element] = []
    for plugin in root.findall(f".//{_tag(namespace, 'plugin')}"):
        if (
            _child_text(plugin, namespace, "groupId") == group_id
            and _child_text(plugin, namespace, "artifactId") == artifact_id
        ):
            matches.append(plugin)
    return matches


def _find_plugin_in_parent(
    plugins: ET.Element,
    namespace: str,
    group_id: str,
    artifact_id: str,
) -> ET.Element | None:
    for plugin in plugins.findall(_tag(namespace, "plugin")):
        if (
            _child_text(plugin, namespace, "groupId") == group_id
            and _child_text(plugin, namespace, "artifactId") == artifact_id
        ):
            return plugin
    return None


def _find_dependency_in_parent(
    dependencies: ET.Element,
    namespace: str,
    group_id: str,
    artifact_id: str,
) -> ET.Element | None:
    for dependency in dependencies.findall(_tag(namespace, "dependency")):
        if (
            _child_text(dependency, namespace, "groupId") == group_id
            and _child_text(dependency, namespace, "artifactId") == artifact_id
        ):
            return dependency
    return None


def _required_text(operation: Mapping[str, Any], key: str) -> str:
    value = operation.get(key)
    text = "" if value is None else str(value).strip()
    if not text:
        raise MavenPomPatchError(
            "INVALID_OPERATION",
            f"maven_pom_patch operation missing {key}",
            pom_file="pom.xml",
        )
    return text


def _operation_string_list(operation: Mapping[str, Any], key: str) -> list[str]:
    value = operation.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    text = str(value).strip()
    return [text] if text else []


def _operation_version_overrides(operation: Mapping[str, Any]) -> dict[str, str]:
    raw = operation.get("version_overrides")
    if not isinstance(raw, Mapping):
        return {}
    overrides: dict[str, str] = {}
    for key, value in raw.items():
        coordinate = str(key or "").strip()
        version = str(value or "").strip()
        if coordinate and version:
            overrides[coordinate] = version
    return overrides


def _update_property_if_present(
    root: ET.Element,
    namespace: str,
    property_name: str,
    target_version: str,
) -> bool:
    properties = root.find(_tag(namespace, "properties"))
    if properties is None:
        return False
    property_node = properties.find(_tag(namespace, property_name))
    if property_node is None:
        return False
    current = (property_node.text or "").strip()
    if current == target_version:
        return False
    property_node.text = target_version
    return True


def _ensure_child(parent: ET.Element, namespace: str, name: str) -> ET.Element:
    child = parent.find(_tag(namespace, name))
    if child is not None:
        return child
    return ET.SubElement(parent, _tag(namespace, name))


def _set_child_text(parent: ET.Element, namespace: str, name: str, value: str) -> bool:
    child = _ensure_child(parent, namespace, name)
    current = (child.text or "").strip()
    if current == value:
        return False
    child.text = value
    return True


def _child_text(parent: ET.Element, namespace: str, name: str) -> str:
    child = parent.find(_tag(namespace, name))
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _detected_jackson_versions(root: ET.Element, namespace: str) -> set[str]:
    versions: set[str] = set()
    for group_id, artifact_id in JACKSON_MANDATORY_MANAGED_ARTIFACTS + JACKSON_OPTIONAL_MANAGED_ARTIFACTS:
        for dependency in _find_dependencies(root, namespace, group_id, artifact_id):
            version = _child_text(dependency, namespace, "version")
            if not version:
                continue
            property_name = _property_reference_name(version)
            if property_name:
                resolved = _property_value(root, namespace, property_name)
                if resolved:
                    versions.add(resolved)
                else:
                    versions.add(version)
                continue
            versions.add(version)
    for property_name in JACKSON_VERSION_PROPERTY_NAMES:
        value = _property_value(root, namespace, property_name)
        if value:
            versions.add(value)
    return versions


def _has_jackson_signal(root: ET.Element, namespace: str) -> bool:
    for dependencies in _dependency_lists(root, namespace):
        for dependency in dependencies.findall(_tag(namespace, "dependency")):
            group_id = _child_text(dependency, namespace, "groupId")
            artifact_id = _child_text(dependency, namespace, "artifactId")
            if group_id.startswith("com.fasterxml.jackson."):
                return True
            if artifact_id.startswith("jackson-") or artifact_id.endswith("-jackson") or "-jackson-" in artifact_id:
                return True
    for property_name in JACKSON_VERSION_PROPERTY_NAMES:
        if _property_value(root, namespace, property_name):
            return True
    return False


def _property_value(root: ET.Element, namespace: str, property_name: str) -> str:
    properties = root.find(_tag(namespace, "properties"))
    if properties is None:
        return ""
    property_node = properties.find(_tag(namespace, property_name))
    if property_node is None or property_node.text is None:
        return ""
    return property_node.text.strip()


def _property_reference_name(value: str) -> str | None:
    stripped = value.strip()
    if not (stripped.startswith("${") and stripped.endswith("}")):
        return None
    property_name = stripped[2:-1].strip()
    return property_name or None


def _compiler_configuration_summary(plugin: ET.Element, namespace: str) -> dict[str, Any]:
    version_node = plugin.find(_tag(namespace, "version"))
    raw_version = (version_node.text or "").strip() if version_node is not None and version_node.text else ""
    configuration = plugin.find(_tag(namespace, "configuration"))
    parameters_enabled = False
    compiler_args_contains_parameters = False
    source = ""
    target = ""
    release = ""
    if configuration is not None:
        parameters_enabled = _child_text(configuration, namespace, "parameters").lower() == "true"
        source = _child_text(configuration, namespace, "source")
        target = _child_text(configuration, namespace, "target")
        release = _child_text(configuration, namespace, "release")
        compiler_args = configuration.find(_tag(namespace, "compilerArgs"))
        if compiler_args is not None:
            args = [(_child.text or "").strip() for _child in compiler_args.findall(_tag(namespace, "arg"))]
            compiler_args_contains_parameters = "-parameters" in args
            parameters_enabled = parameters_enabled or compiler_args_contains_parameters
    return {
        "group_id": MAVEN_COMPILER_PLUGIN_COORDINATE[0],
        "artifact_id": MAVEN_COMPILER_PLUGIN_COORDINATE[1],
        "version": raw_version,
        "parameters_enabled": parameters_enabled,
        "compiler_args_contains_parameters": compiler_args_contains_parameters,
        "source": source,
        "target": target,
        "release": release,
    }


def _should_upgrade_version(current_version: str, target_version: str) -> bool:
    if not current_version:
        return False
    current_key = _version_key(current_version)
    target_key = _version_key(target_version)
    if current_key is None or target_key is None:
        return current_version != target_version
    return current_key < target_key


def _version_key(version: str) -> tuple[int, ...] | None:
    parts = [part for part in version.replace("-", ".").split(".") if part]
    values: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        values.append(int(part))
    return tuple(values)


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1 : tag.index("}")]
    return ""


def _tag(namespace: str, name: str) -> str:
    if namespace:
        return f"{{{namespace}}}{name}"
    return name


def _qualify_path(namespace: str, path: str) -> str:
    if not namespace:
        return path
    parts = [part for part in path.split("/") if part]
    return "./" + "/".join(_tag(namespace, part) for part in parts)
