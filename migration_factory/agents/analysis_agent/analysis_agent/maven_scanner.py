from pathlib import Path
import xml.etree.ElementTree as ET

import yaml


DEFAULT_TARGET_STACK = {
    "java": "17",
    "spring_boot": "3.5.14",
}

DEFAULT_INTERNAL_GROUP_PREFIXES = ("com.total.corp",)

SPRING_BOOT_PROPERTY_NAMES = (
    "spring-boot.version",
    "spring.boot.version",
    "springBoot.version",
)


def _default_scan_result(target, warning):
    target_stack_payload = {
        "java": str(target.get("java", "17")),
        "spring_boot": str(target.get("spring_boot", "3.5.14")),
    }
    for optional_key in ("spring_framework", "build"):
        if target.get(optional_key):
            target_stack_payload[optional_key] = str(target[optional_key])

    return {
        "source_stack": {
            "java": "unknown",
            "spring_boot": "unknown",
            "build_tool": "unknown",
        },
        "project_kind": "unknown",
        "has_spring_boot_main": False,
        "has_rest_contracts": False,
        "has_juneau_contracts": False,
        "packaging": "unknown",
        "internal_dependencies_count": 0,
        "internal_dependencies": [],
        "project_structure": {
            "modules": [],
            "module_count": 0,
        },
        "target_stack": target_stack_payload,
        "warnings": [warning],
    }


def load_profile_target_stack(ai_hub_path, profile_id):
    if not ai_hub_path or not profile_id:
        return DEFAULT_TARGET_STACK.copy()

    profile_path = Path(ai_hub_path) / "profiles" / f"{profile_id}.yaml"
    if not profile_path.is_file():
        return DEFAULT_TARGET_STACK.copy()

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    target = profile.get("target") if isinstance(profile, dict) else None
    if not isinstance(target, dict):
        return DEFAULT_TARGET_STACK.copy()

    stack = DEFAULT_TARGET_STACK.copy()
    for key in ("java", "spring_boot", "spring_framework", "build"):
        if target.get(key):
            stack[key] = str(target[key])
    return stack


def scan_root_pom(file_path, target_stack=None):
    return scan_root_pom_with_prefixes(file_path, target_stack=target_stack)


def scan_root_pom_with_prefixes(file_path, target_stack=None, internal_group_prefixes=DEFAULT_INTERNAL_GROUP_PREFIXES):
    ns = {"mvn": "http://maven.apache.org/POM/4.0.0"}
    target = dict(target_stack or DEFAULT_TARGET_STACK)
    pom_path = Path(file_path)

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        parent_group = root.find(".//mvn:parent/mvn:groupId", ns)
        parent_artifact = root.find(".//mvn:parent/mvn:artifactId", ns)
        parent_version = root.find(".//mvn:parent/mvn:version", ns)
        parent_is_boot = (
            parent_group is not None
            and parent_artifact is not None
            and parent_group.text == "org.springframework.boot"
            and parent_artifact.text == "spring-boot-starter-parent"
        )
        spring_boot = _detect_spring_boot_version(root, ns, parent_is_boot, parent_group, parent_artifact, parent_version)

        java_ver_elem = root.find(".//mvn:properties/mvn:java.version", ns)
        compiler_source_elem = root.find(".//mvn:properties/mvn:maven.compiler.source", ns)
        compiler_release_elem = root.find(".//mvn:properties/mvn:maven.compiler.release", ns)
        java_version = "unknown"
        for candidate in (java_ver_elem, compiler_release_elem, compiler_source_elem):
            if candidate is not None and candidate.text:
                java_version = candidate.text
                break

        classification = _scan_project_classification(pom_path, root, ns)
        internal_dependencies = detect_internal_dependencies(root, ns, internal_group_prefixes=internal_group_prefixes)
        modules = [m.text for m in root.findall(".//mvn:modules/mvn:module", ns)]
        target_stack_payload = {
            "java": str(target.get("java", "17")),
            "spring_boot": str(target.get("spring_boot", "3.5.14")),
        }
        for optional_key in ("spring_framework", "build"):
            if target.get(optional_key):
                target_stack_payload[optional_key] = str(target[optional_key])

        return {
            "source_stack": {
                "java": java_version,
                "spring_boot": spring_boot,
                "build_tool": "maven" if pom_path.name == "pom.xml" else "unknown",
            },
            "project_kind": classification["project_kind"],
            "has_spring_boot_main": classification["has_spring_boot_main"],
            "has_rest_contracts": classification["has_rest_contracts"],
            "has_juneau_contracts": classification["has_juneau_contracts"],
            "packaging": classification["packaging"],
            "internal_dependencies_count": len(internal_dependencies),
            "internal_dependencies": internal_dependencies,
            "project_structure": {
                "modules": modules,
                "module_count": len(modules),
            },
            "target_stack": target_stack_payload,
            "warnings": _target_warnings(target, java_version, spring_boot),
        }
    except Exception as e:
        result = _default_scan_result(target, f"Unable to parse root pom.xml: {e}")
        if pom_path.name == "pom.xml" and pom_path.exists():
            result["source_stack"]["build_tool"] = "maven"
        return result


def _detect_spring_boot_version(root, ns, parent_is_boot, parent_group, parent_artifact, parent_version):
    parent_version_text = _text(parent_version)
    if parent_version_text and (parent_is_boot or parent_group is None or parent_artifact is None):
        return parent_version_text

    properties = _pom_properties(root, ns)
    for property_name in SPRING_BOOT_PROPERTY_NAMES:
        property_value = _resolve_property_reference(properties.get(property_name), properties)
        if property_value:
            return property_value

    for dependency in root.findall("./mvn:dependencyManagement/mvn:dependencies/mvn:dependency", ns):
        group_id = _resolve_property_reference(_find_text(dependency, "mvn:groupId", ns), properties)
        artifact_id = _resolve_property_reference(_find_text(dependency, "mvn:artifactId", ns), properties)
        if group_id != "org.springframework.boot" or artifact_id != "spring-boot-dependencies":
            continue

        version = _resolve_property_reference(_find_text(dependency, "mvn:version", ns), properties)
        if version:
            return version

    for dependency in _project_dependencies(root, ns):
        group_id = _resolve_property_reference(_find_text(dependency, "mvn:groupId", ns), properties)
        artifact_id = _resolve_property_reference(_find_text(dependency, "mvn:artifactId", ns), properties)
        version = _resolve_property_reference(_find_text(dependency, "mvn:version", ns), properties)
        if group_id == "org.springframework.boot" and artifact_id and version:
            return version

    return "unknown"


def _pom_properties(root, ns):
    properties = {}
    properties_elem = root.find(".//mvn:properties", ns)
    if properties_elem is None:
        return properties

    for child in list(properties_elem):
        tag_name = child.tag.rsplit("}", 1)[-1]
        if child.text:
            properties[tag_name] = child.text.strip()
    return properties


def _find_text(element, path, ns):
    child = element.find(path, ns)
    return _text(child)


def _text(element):
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _resolve_property_reference(value, properties):
    if not value:
        return None
    value = value.strip()
    if value.startswith("${") and value.endswith("}"):
        return properties.get(value[2:-1], value)
    return value


def _project_dependencies(root, ns):
    return root.findall("./mvn:dependencies/mvn:dependency", ns)


def detect_internal_dependencies(root, ns, internal_group_prefixes=DEFAULT_INTERNAL_GROUP_PREFIXES):
    dependencies = []
    for dependency in _project_dependencies(root, ns):
        group_id = _find_text(dependency, "mvn:groupId", ns)
        artifact_id = _find_text(dependency, "mvn:artifactId", ns)
        if not group_id or not artifact_id:
            continue
        if not _matches_internal_group_prefix(group_id, internal_group_prefixes):
            continue

        dependencies.append(
            {
                "groupId": group_id,
                "artifactId": artifact_id,
                "version": _find_text(dependency, "mvn:version", ns),
                "scope": _find_text(dependency, "mvn:scope", ns) or "compile",
                "optional": (_find_text(dependency, "mvn:optional", ns) or "").lower() == "true",
                "source": "pom",
                "classification": "internal_candidate",
            }
        )
    return dependencies


def _matches_internal_group_prefix(group_id, internal_group_prefixes):
    for prefix in internal_group_prefixes or ():
        normalized = str(prefix).strip()
        if not normalized:
            continue
        if group_id == normalized or group_id.startswith(f"{normalized}."):
            return True
    return False


def _scan_project_classification(pom_path, root, ns):
    packaging = _find_text(root, ".//mvn:packaging", ns) or "jar"
    source_root = pom_path.parent / "src" / "main" / "java"
    java_files = list(source_root.rglob("*.java")) if source_root.is_dir() else []
    has_any_java_source = bool(java_files)
    has_spring_boot_main = False
    has_rest_contracts = False
    has_juneau_contracts = False

    for java_file in java_files:
        try:
            content = java_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = java_file.read_text(encoding="latin-1")
        except OSError:
            continue

        if "@SpringBootApplication" in content or "SpringApplication.run(" in content:
            has_spring_boot_main = True
        if any(
            marker in content
            for marker in (
                "@RequestMapping",
                "@GetMapping",
                "@PostMapping",
                "@PutMapping",
                "@DeleteMapping",
                "@PatchMapping",
                "@RestController",
                "@Controller",
            )
        ):
            has_rest_contracts = True
        if "@RemoteResource" in content or "@RestResource" in content:
            has_juneau_contracts = True

        if has_spring_boot_main and has_rest_contracts and has_juneau_contracts:
            break

    if has_spring_boot_main:
        project_kind = "spring_boot_application"
    elif packaging == "jar" and (has_rest_contracts or has_juneau_contracts):
        project_kind = "contract_library"
    elif packaging == "jar" and has_any_java_source:
        project_kind = "shared_library"
    else:
        project_kind = "unknown"

    return {
        "project_kind": project_kind,
        "has_spring_boot_main": has_spring_boot_main,
        "has_rest_contracts": has_rest_contracts,
        "has_juneau_contracts": has_juneau_contracts,
        "packaging": packaging,
    }


def _target_warnings(target, source_java, source_boot):
    warnings = []
    target_boot = str(target.get("spring_boot", ""))
    target_java = str(target.get("java", ""))
    if target_boot.startswith("4."):
        warnings.extend(
            [
                "Spring Boot 4 requires Spring Framework 7.x.",
                "Spring Boot 4 uses Jakarta EE 11 / Servlet 6.1 baseline.",
                "Boot 3 deprecated APIs removed in Boot 4 must be reviewed.",
                "Spring Cloud compatibility must be reviewed.",
                "Spring Security, Spring Data, Hibernate, and custom starter risk requires human review.",
                "javax.* leftovers must be eliminated before Boot 4 readiness.",
                "Maven version and Java runtime must match Boot 4 target validation gates.",
                "Official Boot guidance prefers latest 3.5.x before Boot 4; direct migration should fall back if unstable.",
            ]
        )
    if target_java.startswith("21") and not str(source_java).startswith("21"):
        warnings.append("Target Java 21 requires a Java 21-capable runtime during target validation.")
    if str(source_boot).startswith("2.") and target_boot.startswith("4."):
        warnings.append("Direct Spring Boot 2.x to 4.x migration is sandbox-only and high risk.")
    return warnings
