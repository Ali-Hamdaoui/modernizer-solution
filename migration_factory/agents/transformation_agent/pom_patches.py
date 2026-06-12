from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET


LEGACY_JAVA8_ENFORCER_RANGES = {"[1.8,1.9)", "[8,9)", "1.8", "8"}


@dataclass(frozen=True)
class MavenEnforcerJavaVersionPatch:
    file: str
    old_range: str
    new_range: str
    unit: str


@dataclass(frozen=True)
class PomPropertyPatch:
    file: str
    property: str
    old_value: str
    new_value: str
    unit: str


@dataclass(frozen=True)
class SpringBootVersionPatch:
    file: str
    location: str
    old_value: str
    new_value: str
    unit: str


@dataclass(frozen=True)
class SourcePatch:
    file: str
    patch: str
    unit: str


def patch_maven_enforcer_java_version(
    project_path: Path,
    *,
    unit_id: str,
    target_range: str = "[21,)",
) -> list[MavenEnforcerJavaVersionPatch]:
    pom_path = project_path / "pom.xml"
    if not pom_path.is_file():
        return []

    tree = ET.parse(pom_path)
    root = tree.getroot()
    namespace = _namespace(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    patches: list[MavenEnforcerJavaVersionPatch] = []
    for rule in root.findall(f".//{_tag(namespace, 'requireJavaVersion')}"):
        version = rule.find(_tag(namespace, "version"))
        if version is None or version.text is None:
            continue
        old_range = version.text.strip()
        if old_range not in LEGACY_JAVA8_ENFORCER_RANGES:
            continue
        version.text = target_range
        patches.append(
            MavenEnforcerJavaVersionPatch(
                file="pom.xml",
                old_range=old_range,
                new_range=target_range,
                unit=unit_id,
            )
        )

    if patches:
        tree.write(pom_path, encoding="utf-8", xml_declaration=True)
    return patches


def patch_pom_property(
    project_path: Path,
    *,
    unit_id: str,
    property_name: str,
    old_value: str,
    new_value: str,
) -> list[PomPropertyPatch]:
    pom_path = project_path / "pom.xml"
    if not pom_path.is_file():
        return []

    tree = ET.parse(pom_path)
    root = tree.getroot()
    namespace = _namespace(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    properties = root.find(_tag(namespace, "properties"))
    if properties is None:
        return []
    property_node = properties.find(_tag(namespace, property_name))
    if property_node is None or property_node.text is None:
        return []

    current_value = property_node.text.strip()
    if current_value != old_value:
        return []

    property_node.text = new_value
    tree.write(pom_path, encoding="utf-8", xml_declaration=True)
    return [
        PomPropertyPatch(
            file="pom.xml",
            property=property_name,
            old_value=current_value,
            new_value=new_value,
            unit=unit_id,
        )
    ]


def patch_spring_boot_version(
    project_path: Path,
    *,
    unit_id: str,
    old_value: str,
    new_value: str,
) -> list[SpringBootVersionPatch]:
    pom_path = project_path / "pom.xml"
    if not pom_path.is_file():
        return []

    tree = ET.parse(pom_path)
    root = tree.getroot()
    namespace = _namespace(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    patches: list[SpringBootVersionPatch] = []

    properties = root.find(_tag(namespace, "properties"))
    if properties is not None:
        for property_name in ("spring-boot.version", "spring.boot.version", "org.springframework.version"):
            property_node = properties.find(_tag(namespace, property_name))
            if property_node is None or property_node.text is None:
                continue
            current_value = property_node.text.strip()
            if current_value != old_value:
                continue
            property_node.text = new_value
            patches.append(
                SpringBootVersionPatch(
                    file="pom.xml",
                    location=f"properties/{property_name}",
                    old_value=current_value,
                    new_value=new_value,
                    unit=unit_id,
                )
            )

    parent = root.find(_tag(namespace, "parent"))
    if parent is not None:
        group_id = parent.find(_tag(namespace, "groupId"))
        artifact_id = parent.find(_tag(namespace, "artifactId"))
        version = parent.find(_tag(namespace, "version"))
        if (
            group_id is not None
            and artifact_id is not None
            and version is not None
            and group_id.text is not None
            and artifact_id.text is not None
            and version.text is not None
            and group_id.text.strip() == "org.springframework.boot"
            and artifact_id.text.strip() == "spring-boot-starter-parent"
            and version.text.strip() == old_value
        ):
            version.text = new_value
            patches.append(
                SpringBootVersionPatch(
                    file="pom.xml",
                    location="parent/version",
                    old_value=old_value,
                    new_value=new_value,
                    unit=unit_id,
                )
            )

    for dependency in root.findall(f".//{_tag(namespace, 'dependency')}"):
        group_id = dependency.find(_tag(namespace, "groupId"))
        artifact_id = dependency.find(_tag(namespace, "artifactId"))
        version = dependency.find(_tag(namespace, "version"))
        if (
            group_id is None
            or artifact_id is None
            or version is None
            or group_id.text is None
            or artifact_id.text is None
            or version.text is None
        ):
            continue
        current_value = version.text.strip()
        if group_id.text.strip() != "org.springframework.boot" or current_value != old_value:
            continue
        version.text = new_value
        patches.append(
            SpringBootVersionPatch(
                file="pom.xml",
                location=f"dependency/{artifact_id.text.strip()}",
                old_value=current_value,
                new_value=new_value,
                unit=unit_id,
            )
        )

    if patches:
        tree.write(pom_path, encoding="utf-8", xml_declaration=True)
    return patches


def patch_security_config_authorize_http_requests(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    path = _find_source_file(project_path, "SecurityConfig.java")
    if not path.is_file():
        return []
    relative_path = path.relative_to(project_path)

    text = path.read_text(encoding="utf-8")
    updated = text.replace(".authorizeRequests(", ".authorizeHttpRequests(")
    updated = updated.replace(
        'return new InMemoryUserDetailsManager(User.builder().username("viewer").build());',
        """PasswordEncoder encoder = passwordEncoder();
        return new InMemoryUserDetailsManager(
            User.builder()
                .username("admin")
                .password(encoder.encode("admin123"))
                .roles("ADMIN")
                .build(),
            User.builder()
                .username("agent")
                .password(encoder.encode("agent123"))
                .roles("AGENT")
                .build(),
            User.builder()
                .username("viewer")
                .password(encoder.encode("viewer123"))
                .roles("VIEWER")
                .build()
        );""",
    )
    if updated == text:
        return []

    path.write_text(updated, encoding="utf-8")
    return [
        SourcePatch(
            file=str(relative_path),
            patch="security_authorize_http_requests",
            unit=unit_id,
        )
    ]


def patch_batch_config_flat_file_item_reader_constructor(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    path = _find_source_file(project_path, "BatchConfig.java")
    if not path.is_file():
        return []
    relative_path = path.relative_to(project_path)

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?P<indent>[ \t]*)FlatFileItemReader<(?P<row_type>[^>]+)> reader = "
        r"new FlatFileItemReader(?:<(?P=row_type)>)?\(\);\n"
        r"(?P=indent)reader\.setResource\((?P<resource>[^;]+)\);\n"
        r"(?P=indent)reader\.setLinesToSkip\((?P<lines>[^;]+)\);\n"
        r"(?P=indent)DefaultLineMapper<(?P=row_type)> lineMapper = "
        r"new DefaultLineMapper(?:<(?P=row_type)>)?\(\);\n"
        r"(?P<body>.*?)"
        r"(?P=indent)reader\.setLineMapper\(lineMapper\);\n"
        r"(?P=indent)return reader;",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return []

    indent = match.group("indent")
    row_type = match.group("row_type")
    replacement = (
        f"{indent}DefaultLineMapper<{row_type}> lineMapper = new DefaultLineMapper<{row_type}>();\n"
        f"{match.group('body')}"
        f"{indent}FlatFileItemReader<{row_type}> reader = new FlatFileItemReader<{row_type}>(lineMapper);\n"
        f"{indent}reader.setResource({match.group('resource')});\n"
        f"{indent}reader.setLinesToSkip({match.group('lines')});\n"
        f"{indent}return reader;"
    )
    path.write_text(text[: match.start()] + replacement + text[match.end() :], encoding="utf-8")
    return [
        SourcePatch(
            file=str(relative_path),
            patch="batch_flat_file_item_reader_line_mapper_constructor",
            unit=unit_id,
        )
    ]


def _find_source_file(project_path: Path, filename: str) -> Path:
    source_root = project_path / "src" / "main" / "java"
    if not source_root.is_dir():
        return project_path / filename
    matches = sorted(source_root.rglob(filename))
    if not matches:
        return project_path / filename
    return matches[0]


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1 : tag.index("}")]
    return ""


def _tag(namespace: str, name: str) -> str:
    if namespace:
        return f"{{{namespace}}}{name}"
    return name
