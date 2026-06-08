from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import textwrap
import xml.etree.ElementTree as ET

from migration_factory.agents.build_agent.detection import JavaProjectDetectionError, detect_java_project


LEGACY_JAVA8_ENFORCER_RANGES = {"[1.8,1.9)", "[8,9)", "1.8", "8"}
SPRING_DATA_SORT_IMPORT = "import org.springframework.data.domain.Sort;"
SPRING_DATA_SORT_CONSTRUCTOR_PATTERN = re.compile(
    r"new\s+(?P<qualifier>(?:org\.springframework\.data\.domain\.)?Sort)\s*"
    r"\(\s*(?P<direction>[^,\n]+?)\s*,\s*(?P<property>[^)\n]+?)\s*\)"
)
SPRING_BOOT_TEST_MOCKBEAN_IMPORT = "import org.springframework.boot.test.mock.mockito.MockBean;"
SPRING_BOOT_TEST_MOCKITOBEAN_IMPORT = "import org.springframework.test.context.bean.override.mockito.MockitoBean;"
SPRING_BOOT_TEST_MOCKBEAN_ANNOTATION_PATTERN = re.compile(r"@MockBean\b")
MOCKITO_INITMOCKS_PATTERN = re.compile(
    r"MockitoAnnotations\.initMocks\(\s*(?P<target>[^)]+?)\s*\);"
)
TEST_JAVAX_SERVLET_IMPORT_PATTERN = re.compile(
    r"^import\s+javax\.servlet(?P<suffix>(?:\.[A-Za-z0-9_*]+)+)\s*;\s*$",
    re.MULTILINE,
)
JUNIT_ASSERTTHAT_STATIC_IMPORT = "import static org.junit.Assert.assertThat;"
HAMCREST_ASSERTTHAT_STATIC_IMPORT = "import static org.hamcrest.MatcherAssert.assertThat;"
JUNIT_ASSERTTHAT_FQCN_PATTERN = re.compile(r"\borg\.junit\.Assert\.assertThat\s*\(")
AZURE_MODERN_AMQP_TRANSPORT_IMPORT = "import com.azure.core.amqp.AmqpTransportType;"
AZURE_MODERN_CLIENT_BUILDER_IMPORT = "import com.azure.messaging.servicebus.ServiceBusClientBuilder;"
AZURE_LEGACY_TOPICCLIENT_IMPORT = "import com.microsoft.azure.servicebus.TopicClient;"
AZURE_MODERN_SENDERCLIENT_IMPORT = "import com.azure.messaging.servicebus.ServiceBusSenderClient;"
AZURE_LEGACY_MESSAGE_IMPORT = "import com.microsoft.azure.servicebus.Message;"
AZURE_MODERN_MESSAGE_IMPORT = "import com.azure.messaging.servicebus.ServiceBusMessage;"
AZURE_LEGACY_CONNECTION_STRING_IMPORT = "import com.microsoft.azure.servicebus.primitives.ConnectionStringBuilder;"
AZURE_LEGACY_EXCEPTION_IMPORT = "import com.microsoft.azure.servicebus.primitives.ServiceBusException;"
AZURE_LEGACY_SERVICEBUS_PACKAGE = "com.microsoft.azure.servicebus"
AZURE_FQCN_TOPICCLIENT_PATTERN = re.compile(r"\bcom\.microsoft\.azure\.servicebus\.TopicClient\b")
AZURE_FQCN_MESSAGE_PATTERN = re.compile(r"\bcom\.microsoft\.azure\.servicebus\.Message\b")
AZURE_LEGACY_TOPICCLIENT_PATTERN = re.compile(r"\bTopicClient\b")
AZURE_LEGACY_MESSAGE_PATTERN = re.compile(r"\bMessage\b")
AZURE_SEND_MESSAGE_PATTERN = re.compile(r"(?P<prefix>\.)send\(\s*(?P<argument>(?:Mockito\.)?any\(\s*Message\.class\s*\))\s*\)")
AZURE_LEGACY_QUEUE_MARKERS: tuple[str, ...] = ("IQueueClient", "QueueClient", "ReceiveMode.PEEKLOCK")
AZURE_TOPIC_BUILD_METHOD_PATTERN = re.compile(
    r"private void buildTopicClient\(\)\s*\{\s*try\s*\{\s*this\.setTopicClient\(new TopicClient\(getAmqpConnectionStringBuilder\(\)\)\);\s*\}\s*"
    r"catch\s*\(final ServiceBusException e\)\s*\{\s*topicClient = null;\s*log\.error\(e\.getMessage\(\)\);\s*\}\s*"
    r"catch\s*\(final InterruptedException e\)\s*\{\s*log\.error\(e\.getMessage\(\)\);\s*Thread\.currentThread\(\)\.interrupt\(\);\s*\}\s*"
    r"lastConnectionInstant = Instant\.now\(\);\s*\}",
    re.DOTALL,
)
AZURE_TOPIC_SEND_METHOD_PATTERN = re.compile(
    r"public void sendMessage\(\s*final String jsonMessage,\s*final Map<String,\s*String> properties,\s*String sessionId\s*\)\s*\{\s*"
    r"try\s*\{\s*(?P<body>.*?)\s*\}\s*catch\s*\(final ServiceBusException e\)\s*\{\s*log\.error\(e\.getMessage\(\)\);\s*\}\s*"
    r"catch\s*\(final InterruptedException e\)\s*\{\s*log\.error\(e\.getMessage\(\)\);\s*Thread\.currentThread\(\)\.interrupt\(\);\s*\}\s*\}",
    re.DOTALL,
)
AZURE_BUILDER_ENTITY_PATH_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<indent>\s*)(?P<lhs>[A-Za-z0-9_$.]+)\s*=\s*(?P<target>[A-Za-z0-9_$.()]+\.getAmqp(?:ConnectionStringBuilder|ServiceBusClientBuilder)\(\))\.getEntityPath\(\);"
)
AZURE_DEAD_CHECKED_CATCH_PATTERN = re.compile(
    r"(?P<indent>^[ \t]*)try\s*\{\s*(?P<body>.*?)\s*\}\s*catch\s*\(\s*final\s+"
    r"(?P<exceptions>(?:InterruptedException\s*\|\s*ServiceBusException|ServiceBusException\s*\|\s*InterruptedException))"
    r"\s+e\s*\)\s*\{\s*(?P<catch_body>.*?)\s*\}",
    re.DOTALL | re.MULTILINE,
)
MOCKITO_INLINE_MOCK_MAKER_CONTENT = "mock-maker-inline\n"
MOCKITO_USAGE_MARKERS: tuple[str, ...] = (
    "org.mockito",
    "Mockito.",
    "@Mock",
    "@Spy",
    "@InjectMocks",
    "@Captor",
    "MockitoAnnotations.",
    "@MockBean",
    "@MockitoBean",
)
POWERMOCK_USAGE_MARKERS: tuple[str, ...] = (
    "org.powermock",
    "PowerMockito",
    "PowerMockRunner",
    "@PrepareForTest",
    "PrepareForTest(",
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
    root_path = Path(project_path).expanduser().resolve()
    pom_path = _resolve_project_pom(root_path)
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
                file=str(pom_path.relative_to(root_path).as_posix()),
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
    root_path = Path(project_path).expanduser().resolve()
    pom_path = _resolve_project_pom(root_path)
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
            file=str(pom_path.relative_to(root_path).as_posix()),
            property=property_name,
            old_value=current_value,
            new_value=new_value,
            unit=unit_id,
        )
    ]


def _resolve_project_pom(project_path: Path) -> Path:
    root_path = Path(project_path).expanduser().resolve()
    direct_pom = root_path / "pom.xml"
    if direct_pom.is_file():
        return direct_pom
    try:
        detected = detect_java_project(root_path)
    except JavaProjectDetectionError:
        return direct_pom
    candidate = detected.path / "pom.xml"
    if candidate.is_file():
        return candidate
    return direct_pom


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
        relative_path = path.relative_to(project_path)
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


def patch_spring_boot_test_mockbean_to_mockitobean(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    for path in _iter_test_java_files(project_path):
        relative_path = path.relative_to(project_path)
        text = path.read_text(encoding="utf-8")
        if SPRING_BOOT_TEST_MOCKBEAN_IMPORT not in text and "@MockBean" not in text:
            continue
        updated = text.replace(
            SPRING_BOOT_TEST_MOCKBEAN_IMPORT,
            SPRING_BOOT_TEST_MOCKITOBEAN_IMPORT,
        )
        updated = SPRING_BOOT_TEST_MOCKBEAN_ANNOTATION_PATTERN.sub("@MockitoBean", updated)
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.append(
            SourcePatch(
                file=str(relative_path),
                patch="spring_boot_test_mockbean_to_mockitobean",
                unit=unit_id,
            )
        )
    return patches


def patch_mockito_initmocks_to_openmocks(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    for path in _iter_test_java_files(project_path):
        relative_path = path.relative_to(project_path)
        text = path.read_text(encoding="utf-8")
        if "MockitoAnnotations.initMocks(" not in text:
            continue
        updated = MOCKITO_INITMOCKS_PATTERN.sub(
            lambda match: f"MockitoAnnotations.openMocks({match.group('target').strip()});",
            text,
        )
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.append(
            SourcePatch(
                file=str(relative_path),
                patch="mockito_initmocks_to_openmocks",
                unit=unit_id,
            )
        )
    return patches


def patch_test_javax_servlet_imports_to_jakarta(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    for path in _iter_test_java_files(project_path):
        relative_path = path.relative_to(project_path)
        text = path.read_text(encoding="utf-8")
        if "import javax.servlet" not in text:
            continue
        updated = TEST_JAVAX_SERVLET_IMPORT_PATTERN.sub(
            lambda match: f"import jakarta.servlet{match.group('suffix')};",
            text,
        )
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.append(
            SourcePatch(
                file=str(relative_path),
                patch="test_javax_servlet_imports_to_jakarta",
                unit=unit_id,
            )
        )
    return patches


def patch_junit_assertthat_to_hamcrest_matcherassert(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    for path in _iter_test_java_files(project_path):
        relative_path = path.relative_to(project_path)
        text = path.read_text(encoding="utf-8")
        if JUNIT_ASSERTTHAT_STATIC_IMPORT not in text and "org.junit.Assert.assertThat(" not in text:
            continue
        updated = text.replace(JUNIT_ASSERTTHAT_STATIC_IMPORT, HAMCREST_ASSERTTHAT_STATIC_IMPORT)
        updated = JUNIT_ASSERTTHAT_FQCN_PATTERN.sub("org.hamcrest.MatcherAssert.assertThat(", updated)
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.append(
            SourcePatch(
                file=str(relative_path),
                patch="junit_assertthat_to_hamcrest_matcherassert",
                unit=unit_id,
            )
        )
    return patches


def patch_azure_servicebus_legacy_to_modern(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    root_path = Path(project_path).expanduser().resolve()
    java_files = []
    for path in sorted(root_path.rglob("*.java")):
        try:
            relative_path = path.relative_to(root_path)
        except ValueError:
            continue
        if "src" not in {part.lower() for part in relative_path.parts[:-1]}:
            continue
        java_files.append(path)
    for path in java_files:
        try:
            relative_path = path.relative_to(project_path)
        except ValueError:
            continue
        text = path.read_text(encoding="utf-8")
        if (
            AZURE_LEGACY_SERVICEBUS_PACKAGE not in text
            and "TopicClient" not in text
            and "Message.class" not in text
            and "getAmqpConnectionStringBuilder()" not in text
            and "getAmqpServiceBusClientBuilder()" not in text
        ):
            continue
        updated = _patch_azure_servicebus_text(text)
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.append(
            SourcePatch(
                file=str(relative_path),
                patch="azure_servicebus_legacy_to_modern",
                unit=unit_id,
            )
        )
    return patches


def patch_mockito_final_class_inline_mock_maker(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    root_path = Path(project_path).expanduser().resolve()
    project_root = _resolve_java_project_root(root_path)
    if _project_uses_powermock(project_root):
        return []
    if not _project_uses_mockito(project_root):
        return []

    resource_path = (
        project_root
        / "src"
        / "test"
        / "resources"
        / "mockito-extensions"
        / "org.mockito.plugins.MockMaker"
    )
    if resource_path.is_file():
        existing = resource_path.read_text(encoding="utf-8")
        if existing.strip() == "mock-maker-inline":
            return []

    resource_path.parent.mkdir(parents=True, exist_ok=True)
    resource_path.write_text(MOCKITO_INLINE_MOCK_MAKER_CONTENT, encoding="utf-8")
    return [
        SourcePatch(
            file=str(resource_path.relative_to(root_path).as_posix()),
            patch="mockito_final_class_inline_mock_maker",
            unit=unit_id,
        )
    ]


def patch_jjwt_api_parser_builder_compatibility(
    project_path: Path,
    *,
    unit_id: str,
) -> list[SourcePatch]:
    patches: list[SourcePatch] = []
    source_root = project_path / "src" / "main" / "java"
    if not source_root.is_dir():
        return patches
    for path in sorted(source_root.rglob("*.java")):
        relative_path = path.relative_to(project_path)
        text = path.read_text(encoding="utf-8")
        if "Jwts.parser()" not in text or "JwtParser" not in text:
            continue
        updated = _patch_jjwt_parser_assignments(text)
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        patches.append(
            SourcePatch(
                file=str(relative_path),
                patch="jjwt_api_parser_builder_compatibility",
                unit=unit_id,
            )
        )
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


def _iter_test_java_files(project_path: Path) -> list[Path]:
    src_root = project_path / "src"
    if not src_root.is_dir():
        return []
    matches: list[Path] = []
    for path in sorted(src_root.rglob("*.java")):
        try:
            relative_path = path.relative_to(project_path)
        except ValueError:
            continue
        parts = [part.lower() for part in relative_path.parts[:-1]]
        if "main" in parts:
            continue
        if not any("test" in part for part in parts):
            continue
        matches.append(path)
    return matches


def _resolve_java_project_root(project_path: Path) -> Path:
    direct_pom = project_path / "pom.xml"
    if direct_pom.is_file():
        return project_path
    try:
        detected = detect_java_project(project_path)
    except JavaProjectDetectionError:
        return project_path
    return detected.path


def _project_uses_mockito(project_root: Path) -> bool:
    pom_path = project_root / "pom.xml"
    if pom_path.is_file():
        pom_text = pom_path.read_text(encoding="utf-8")
        if "mockito" in pom_text.lower():
            return True
    for path in _iter_test_java_files(project_root):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in MOCKITO_USAGE_MARKERS):
            return True
    return False


def _project_uses_powermock(project_root: Path) -> bool:
    pom_path = project_root / "pom.xml"
    if pom_path.is_file():
        pom_text = pom_path.read_text(encoding="utf-8")
        if "powermock" in pom_text.lower():
            return True
    for path in _iter_test_java_files(project_root):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in POWERMOCK_USAGE_MARKERS):
            return True
    return False


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


def _patch_azure_servicebus_text(text: str) -> str:
    if _is_azure_queue_only_text(text):
        return text
    updated = text.replace(AZURE_LEGACY_TOPICCLIENT_IMPORT, AZURE_MODERN_SENDERCLIENT_IMPORT)
    updated = updated.replace(AZURE_LEGACY_MESSAGE_IMPORT, AZURE_MODERN_MESSAGE_IMPORT)
    if _needs_azure_topic_builder_upgrade(text):
        updated = _patch_azure_topic_builder_text(updated)
    updated = _patch_azure_topic_builder_consumers(updated)
    updated = _patch_azure_dead_checked_catches(updated)
    updated = AZURE_FQCN_TOPICCLIENT_PATTERN.sub("com.azure.messaging.servicebus.ServiceBusSenderClient", updated)
    updated = AZURE_FQCN_MESSAGE_PATTERN.sub("com.azure.messaging.servicebus.ServiceBusMessage", updated)
    updated = AZURE_SEND_MESSAGE_PATTERN.sub(
        lambda match: "." + "sendMessage(" + match.group("argument").replace("Message.class", "ServiceBusMessage.class") + ")",
        updated,
    )
    updated = AZURE_LEGACY_TOPICCLIENT_PATTERN.sub("ServiceBusSenderClient", updated)
    updated = AZURE_LEGACY_MESSAGE_PATTERN.sub("ServiceBusMessage", updated)
    return updated


def _is_azure_queue_only_text(text: str) -> bool:
    if "TopicClient" in text or "com.microsoft.azure.servicebus.TopicClient" in text:
        return False
    return any(marker in text for marker in AZURE_LEGACY_QUEUE_MARKERS)


def _needs_azure_topic_builder_upgrade(text: str) -> bool:
    return "TopicClient" in text and "ConnectionStringBuilder" in text


def _patch_azure_topic_builder_text(text: str) -> str:
    updated = text
    updated = updated.replace(AZURE_LEGACY_CONNECTION_STRING_IMPORT, "")
    updated = updated.replace(AZURE_LEGACY_EXCEPTION_IMPORT, "")
    if AZURE_MODERN_SENDERCLIENT_IMPORT in updated and AZURE_MODERN_CLIENT_BUILDER_IMPORT not in updated:
        updated = updated.replace(
            AZURE_MODERN_SENDERCLIENT_IMPORT,
            "\n".join(
                (
                    AZURE_MODERN_AMQP_TRANSPORT_IMPORT,
                    AZURE_MODERN_CLIENT_BUILDER_IMPORT,
                    AZURE_MODERN_SENDERCLIENT_IMPORT,
                )
            ),
        )
    updated = updated.replace(
        "private ConnectionStringBuilder amqpConnectionStringBuilder;",
        "private ServiceBusClientBuilder amqpServiceBusClientBuilder;",
    )
    updated = updated.replace(
        "public ConnectionStringBuilder getAmqpConnectionStringBuilder() {",
        "public ServiceBusClientBuilder getAmqpServiceBusClientBuilder() {",
    )
    updated = updated.replace(
        "public void setAmqpConnectionStringBuilder(final ConnectionStringBuilder amqpConnectionStringBuilder) {",
        "public void setAmqpServiceBusClientBuilder(final ServiceBusClientBuilder amqpServiceBusClientBuilder) {",
    )
    updated = updated.replace("return amqpConnectionStringBuilder;", "return amqpServiceBusClientBuilder;")
    updated = updated.replace("this.amqpConnectionStringBuilder = amqpConnectionStringBuilder;", "this.amqpServiceBusClientBuilder = amqpServiceBusClientBuilder;")
    updated = updated.replace(
        '        connectionString.append(";OperationTimeout=");\n        connectionString.append("PT10S");\n\n'
        "        setAmqpConnectionStringBuilder(new ConnectionStringBuilder(connectionString.toString(), bus.getTopicName()));\n",
        "        ServiceBusClientBuilder serviceBusClientBuilder =\n"
        "                new ServiceBusClientBuilder()\n"
        "                    .connectionString(connectionString.toString())\n"
        "                    .transportType(AmqpTransportType.AMQP_WEB_SOCKETS);\n\n"
        "        setAmqpServiceBusClientBuilder(serviceBusClientBuilder);\n",
    )
    updated = AZURE_TOPIC_BUILD_METHOD_PATTERN.sub(
        "private void buildTopicClient() {\n"
        "        this.setTopicClient(getAmqpServiceBusClientBuilder()\n"
        "                .sender()\n"
        "                .topicName(getBus().getTopicName())\n"
        "                .buildClient());\n"
        "        lastConnectionInstant = Instant.now();\n"
        "    }",
        updated,
    )
    updated = updated.replace(
        "oldClient.closeAsync().get(5, java.util.concurrent.TimeUnit.SECONDS);",
        "java.util.concurrent.CompletableFuture.runAsync(oldClient::close).get(5, java.util.concurrent.TimeUnit.SECONDS);",
    )
    updated = AZURE_TOPIC_SEND_METHOD_PATTERN.sub(_replace_azure_topic_send_method, updated)
    updated = updated.replace("getTopicClient().send(message);", "getTopicClient().sendMessage(message);")
    return updated


def _patch_azure_topic_builder_consumers(text: str) -> str:
    updated = text.replace("getAmqpConnectionStringBuilder()", "getAmqpServiceBusClientBuilder()")
    updated = updated.replace("setAmqpConnectionStringBuilder(", "setAmqpServiceBusClientBuilder(")
    updated = AZURE_BUILDER_ENTITY_PATH_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group('indent')}{match.group('target')}.getClass();",
        updated,
    )
    updated = updated.replace(".getAmqpServiceBusClientBuilder().getEntityPath()", ".getAmqpServiceBusClientBuilder().getClass()")
    return updated


def _replace_azure_topic_send_method(match: re.Match[str]) -> str:
    body = match.group("body")
    body = body.replace("final Message message = new Message(jsonMessage);", "final ServiceBusMessage message = new ServiceBusMessage(jsonMessage);")
    body = body.replace(
        "message.setProperties(properties);",
        "Map<String, Object> applicationProperties = message.getApplicationProperties();\n                applicationProperties.putAll(properties);",
    )
    body = body.replace("getTopicClient().send(message);", "getTopicClient().sendMessage(message);")
    return (
        "public void sendMessage(final String jsonMessage, final Map<String, String> properties, String sessionId) {\n"
        f"            {body.strip()}\n"
        "    }"
    )


def _patch_azure_dead_checked_catches(text: str) -> str:
    def _replacement(match: re.Match[str]) -> str:
        body = match.group("body")
        if not any(
            marker in body
            for marker in (
                "ServiceBusSenderClient",
                "ServiceBusMessage",
                ".sendMessage(",
                ".close()",
                "Mockito.when(",
                "Mockito.doNothing()",
                "PowerMockito.when(",
                "PowerMockito.doNothing()",
            )
        ):
            return match.group(0)
        indent = match.group("indent")
        body_block = textwrap.dedent(body).strip("\n")
        if not body_block:
            return ""
        return textwrap.indent(body_block, indent)

    updated = AZURE_DEAD_CHECKED_CATCH_PATTERN.sub(_replacement, text)
    without_legacy_exception_import = updated.replace(AZURE_LEGACY_EXCEPTION_IMPORT, "")
    if "ServiceBusException" not in without_legacy_exception_import:
        updated = without_legacy_exception_import
    return updated


def _patch_jjwt_parser_assignments(text: str) -> str:
    candidates = collect_jjwt_parser_compatibility_candidates(text)
    if not candidates:
        return text
    updated = text
    for candidate in reversed(candidates):
        expression = candidate["expression"]
        if ".build(" in expression or ".build()" in expression:
            continue
        if not _is_safe_jjwt_parser_builder_expression(expression):
            continue
        updated = (
            updated[: candidate["expression_start"]]
            + expression
            + ".build()"
            + updated[candidate["expression_end"] :]
        )
    return updated


def collect_jjwt_parser_compatibility_candidates(text: str) -> list[dict[str, int | str | bool]]:
    candidates: list[dict[str, int | str | bool]] = []
    search_from = 0
    while True:
        expression_start = text.find("Jwts.parser()", search_from)
        if expression_start == -1:
            break
        expression_end = _find_statement_end(text, expression_start)
        if expression_end == -1:
            break
        statement_start = _find_statement_start(text, expression_start)
        prefix = text[statement_start:expression_start]
        mode = _jjwt_candidate_mode(prefix)
        expression = text[expression_start:expression_end]
        if mode is not None:
            candidates.append(
                {
                    "statement_start": statement_start,
                    "expression_start": expression_start,
                    "expression_end": expression_end,
                    "mode": mode,
                    "expression": expression,
                    "already_built": ".build()" in expression,
                    "safe_to_auto_apply": _is_safe_jjwt_parser_builder_expression(expression),
                }
            )
        search_from = expression_end + 1
    return candidates


def _find_statement_start(text: str, expression_start: int) -> int:
    anchors = [
        text.rfind(";", 0, expression_start),
        text.rfind("{", 0, expression_start),
        text.rfind("\n", 0, expression_start),
    ]
    return max(anchors) + 1


def _find_statement_end(text: str, expression_start: int) -> int:
    paren_depth = 0
    brace_depth = 0
    in_string = False
    string_quote = ""
    escaped = False
    for index in range(expression_start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == string_quote:
                in_string = False
            continue
        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            continue
        if char == "(":
            paren_depth += 1
            continue
        if char == ")":
            paren_depth = max(0, paren_depth - 1)
            continue
        if char == "{":
            brace_depth += 1
            continue
        if char == "}":
            brace_depth = max(0, brace_depth - 1)
            continue
        if char == ";" and paren_depth == 0 and brace_depth == 0:
            return index
    return -1


def _jjwt_candidate_mode(prefix: str) -> str | None:
    if re.search(r"\breturn\s*$", prefix):
        return "return"
    if re.search(r"\bJwtParser\s+\w+\s*=\s*$", prefix):
        return "assignment"
    return None


def _is_safe_jjwt_parser_builder_expression(expression: str) -> bool:
    compact = "".join(expression.split())
    if not compact.startswith("Jwts.parser()"):
        return False
    if ".build()" in compact:
        return False
    tail = compact[len("Jwts.parser()") :]
    if not tail:
        return True
    index = 0
    while index < len(tail):
        if tail[index] != ".":
            return False
        next_paren = tail.find("(", index)
        if next_paren == -1:
            return False
        method_name = tail[index + 1 : next_paren]
        if method_name not in {
            "setSigningKey",
            "setSigningKeyResolver",
            "deserializeJsonWith",
            "base64UrlDecodeWith",
            "clockSkewSeconds",
            "require",
            "requireAudience",
            "requireExpiration",
            "requireId",
            "requireIssuedAt",
            "requireIssuer",
            "requireNotBefore",
            "requireSubject",
            "verifyWith",
        }:
            return False
        depth = 1
        brace_depth = 0
        cursor = next_paren + 1
        while cursor < len(tail) and depth > 0:
            char = tail[cursor]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
            cursor += 1
        if depth != 0 or brace_depth != 0:
            return False
        index = cursor
    return True


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
