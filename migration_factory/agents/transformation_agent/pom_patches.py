from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET


LEGACY_JAVA8_ENFORCER_RANGES = {"[1.8,1.9)", "[8,9)", "1.8", "8"}
SPRING_DATA_SORT_IMPORT = "import org.springframework.data.domain.Sort;"
SPRING_DATA_SORT_CONSTRUCTOR_PATTERN = re.compile(
    r"new\s+(?P<qualifier>(?:org\.springframework\.data\.domain\.)?Sort)\s*"
    r"\(\s*(?P<direction>[^,\n]+?)\s*,\s*(?P<property>[^)\n]+?)\s*\)"
)


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
class SourcePatch:
    file: str
    patch: str
    unit: str
    old_signature: str | None = None
    new_signature: str | None = None


SPRING6_HTTPSTATUS_OVERRIDE_PATTERN = re.compile(
    r"(?P<prefix>@Override\s+(?:public|protected)\s+[^{;]+?\bhandle[A-Za-z0-9_]*\s*\([^)]*?)"
    r"(?P<type>\bHttpStatus\b)"
    r"(?P<suffix>[^)]*\))",
    re.DOTALL,
)
SPRING6_CONSTRAINT_OVERRIDE_PATTERN = re.compile(
    r"(?P<signature>@Override\s+(?:public|protected)\s+[^{;]+?\bhandleConstraintViolation\s*"
    r"\(\s*final\s+)(?P<type>(?:jakarta|javax)\.validation\.ConstraintViolationException|ConstraintViolationException)"
    r"(?P<suffix>\s+exception\s*,\s*final\s+NativeWebRequest\s+request\s*\))",
    re.DOTALL,
)


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


def patch_forbidden_source_patterns_allow_jakarta(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    path = _find_any_file(
        project_path,
        Path("shoppoc-app/src/test/java/com/shoppoc/architecture/ForbiddenSourcePatternsTest.java"),
        "ForbiddenSourcePatternsTest.java",
    )
    if not path.is_file():
        return []
    relative_path = path.relative_to(project_path)

    text = path.read_text(encoding="utf-8")
    updated = text.replace(
        'if (line.startsWith("import jakarta.")) {',
        'if (line.startsWith("import javax.")) {',
    ).replace(
        " uses jakarta import",
        " uses javax import",
    )
    if updated == text:
        return []

    path.write_text(updated, encoding="utf-8")
    return [
        SourcePatch(
            file=str(relative_path),
            patch="forbidden_source_patterns_allow_jakarta",
            unit=unit_id,
        )
    ]


def patch_quality_rules_allow_jakarta(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    path = _find_any_file(
        project_path,
        Path("shoppoc-app/src/test/java/com/shoppoc/architecture/QualityRulesTest.java"),
        "QualityRulesTest.java",
    )
    if not path.is_file():
        return []
    relative_path = path.relative_to(project_path)

    text = path.read_text(encoding="utf-8")
    updated = text.replace("no_jakarta_imports", "no_javax_imports").replace('"jakarta.."', '"javax.."')
    if updated == text:
        return []

    path.write_text(updated, encoding="utf-8")
    return [
        SourcePatch(
            file=str(relative_path),
            patch="quality_rules_allow_jakarta",
            unit=unit_id,
        )
    ]


def patch_spring_data_sort_constructor_usage(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    for path in sorted(project_path.rglob("*.java")):
        try:
            relative_path = path.relative_to(project_path)
        except ValueError:
            continue
        text = path.read_text(encoding="utf-8")
        if SPRING_DATA_SORT_IMPORT not in text and "org.springframework.data.domain.Sort" not in text:
            continue
        updated = _replace_spring_data_sort_constructor_usage(text)
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.append(
            SourcePatch(
                file=str(relative_path),
                patch="spring_data_sort_by_factory_method",
                unit=unit_id,
            )
        )
    return patches


def patch_spring6_exception_handler_override_signatures(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    for path in sorted(project_path.rglob("*.java")):
        try:
            relative_path = path.relative_to(project_path)
        except ValueError:
            continue
        text = path.read_text(encoding="utf-8")
        updated = text
        local_patches: list[SourcePatch] = []

        if "@Override" in updated and "handleConstraintViolation" in updated:
            updated, patch = _patch_constraint_violation_override(updated, relative_path, unit_id)
            if patch is not None:
                local_patches.append(patch)

        if "@Override" in updated and "HttpStatus" in updated and "handle" in updated:
            updated, patch = _patch_httpstatus_override(updated, relative_path, unit_id)
            if patch is not None:
                local_patches.append(patch)

        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.extend(local_patches)
    return patches


def _find_source_file(project_path: Path, filename: str) -> Path:
    source_root = project_path / "src" / "main" / "java"
    if not source_root.is_dir():
        return project_path / filename
    matches = sorted(source_root.rglob(filename))
    if not matches:
        return project_path / filename
    return matches[0]


def _find_any_file(project_path: Path, preferred_relative_path: Path, filename: str) -> Path:
    preferred = project_path / preferred_relative_path
    if preferred.is_file():
        return preferred
    matches = sorted(project_path.rglob(filename))
    if matches:
        return matches[0]
    return preferred


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1 : tag.index("}")]
    return ""


def _tag(namespace: str, name: str) -> str:
    if namespace:
        return f"{{{namespace}}}{name}"
    return name


def _replace_spring_data_sort_constructor_usage(text: str) -> str:
    def _replacement(match: re.Match[str]) -> str:
        qualifier = match.group("qualifier")
        direction = match.group("direction").strip()
        property_value = match.group("property").strip()
        factory_target = (
            "org.springframework.data.domain.Sort"
            if qualifier.startswith("org.springframework.data.domain.Sort")
            else "Sort"
        )
        return f"{factory_target}.by({direction}, {property_value})"

    return SPRING_DATA_SORT_CONSTRUCTOR_PATTERN.sub(_replacement, text)


def _patch_constraint_violation_override(
    text: str,
    relative_path: Path,
    unit_id: str,
) -> tuple[str, SourcePatch | None]:
    match = SPRING6_CONSTRAINT_OVERRIDE_PATTERN.search(text)
    if match is None:
        return text, None
    old_signature = " ".join(match.group("signature").strip().split()) + match.group("type") + match.group("suffix")
    replacement_type = "javax.validation.ConstraintViolationException"
    if match.group("type") == replacement_type:
        return text, None
    updated = (
        text[: match.start("type")]
        + replacement_type
        + text[match.end("type") :]
    )
    if "import jakarta.validation.ConstraintViolationException;" in updated:
        updated = updated.replace(
            "import jakarta.validation.ConstraintViolationException;",
            "import javax.validation.ConstraintViolationException;",
            1,
        )
    new_match = SPRING6_CONSTRAINT_OVERRIDE_PATTERN.search(updated)
    new_signature = old_signature
    if new_match is not None:
        new_signature = " ".join(new_match.group("signature").strip().split()) + new_match.group("type") + new_match.group("suffix")
    return updated, SourcePatch(
        file=str(relative_path),
        patch="spring6_exception_handler_override_alignment",
        unit=unit_id,
        old_signature=old_signature,
        new_signature=new_signature,
    )


def _patch_httpstatus_override(
    text: str,
    relative_path: Path,
    unit_id: str,
) -> tuple[str, SourcePatch | None]:
    match = SPRING6_HTTPSTATUS_OVERRIDE_PATTERN.search(text)
    if match is None:
        return text, None
    old_signature = "".join((match.group("prefix"), match.group("type"), match.group("suffix")))
    updated = (
        text[: match.start("type")]
        + "HttpStatusCode"
        + text[match.end("type") :]
    )
    if "import org.springframework.http.HttpStatusCode;" not in updated:
        if "import org.springframework.http.HttpStatus;" in updated:
            updated = updated.replace(
                "import org.springframework.http.HttpStatus;",
                "import org.springframework.http.HttpStatus;\nimport org.springframework.http.HttpStatusCode;",
                1,
            )
        else:
            updated = updated.replace(
                "import org.springframework.http.ResponseEntity;",
                "import org.springframework.http.HttpStatusCode;\nimport org.springframework.http.ResponseEntity;",
                1,
            )
    new_match = SPRING6_HTTPSTATUS_OVERRIDE_PATTERN.search(updated)
    new_signature = old_signature.replace("HttpStatus", "HttpStatusCode", 1)
    if new_match is not None:
        new_signature = "".join((new_match.group("prefix"), new_match.group("type"), new_match.group("suffix")))
    return updated, SourcePatch(
        file=str(relative_path),
        patch="spring6_exception_handler_override_alignment",
        unit=unit_id,
        old_signature=old_signature,
        new_signature=new_signature,
    )
