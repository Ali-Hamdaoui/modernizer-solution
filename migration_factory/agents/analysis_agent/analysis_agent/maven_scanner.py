from pathlib import Path
import re
import xml.etree.ElementTree as ET

import yaml


DEFAULT_TARGET_STACK = {
    "java": "17",
    "spring_boot": "3.5.14",
}


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
    ns = {"mvn": "http://maven.apache.org/POM/4.0.0"}
    target = dict(target_stack or DEFAULT_TARGET_STACK)
    pom_path = Path(file_path)

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        properties = _maven_properties(root, ns)
        spring_boot = _detect_spring_boot_version(root, ns, properties)

        java_ver_elem = root.find(".//mvn:properties/mvn:java.version", ns)
        compiler_source_elem = root.find(".//mvn:properties/mvn:maven.compiler.source", ns)
        compiler_release_elem = root.find(".//mvn:properties/mvn:maven.compiler.release", ns)
        java_version = "unknown"
        for candidate in (java_ver_elem, compiler_release_elem, compiler_source_elem):
            if candidate is not None and candidate.text:
                java_version = candidate.text
                break

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


def _maven_properties(root, ns):
    properties = {}
    properties_elem = root.find("./mvn:properties", ns)
    if properties_elem is None:
        return properties

    for child in list(properties_elem):
        key = _strip_namespace(child.tag)
        value = _text(child)
        if key and value:
            properties[key] = value
    return properties


def _detect_spring_boot_version(root, ns, properties):
    for property_name in ("spring-boot.version", "spring.boot.version"):
        version = _resolve_property_placeholders(properties.get(property_name, ""), properties)
        if version:
            return version

    parent_group = root.find("./mvn:parent/mvn:groupId", ns)
    parent_artifact = root.find("./mvn:parent/mvn:artifactId", ns)
    parent_version = root.find("./mvn:parent/mvn:version", ns)
    if (
        _text(parent_group) == "org.springframework.boot"
        and _text(parent_artifact) == "spring-boot-starter-parent"
    ):
        version = _resolve_property_placeholders(_text(parent_version), properties)
        if version:
            return version

    for dependency in root.findall("./mvn:dependencyManagement/mvn:dependencies/mvn:dependency", ns):
        if (
            _text(dependency.find("./mvn:groupId", ns)) == "org.springframework.boot"
            and _text(dependency.find("./mvn:artifactId", ns)) == "spring-boot-dependencies"
        ):
            version = _resolve_property_placeholders(
                _text(dependency.find("./mvn:version", ns)),
                properties,
            )
            if version:
                return version

    if parent_group is None and parent_artifact is None:
        version = _resolve_property_placeholders(_text(parent_version), properties)
        if version:
            return version

    return "unknown"


def _resolve_property_placeholders(value, properties):
    value = str(value or "").strip()
    if not value:
        return ""

    def replace(match):
        property_name = match.group(1)
        return str(properties.get(property_name, match.group(0))).strip()

    resolved = re.sub(r"\$\{([^}]+)\}", replace, value)
    return resolved.strip()


def _text(element):
    return element.text.strip() if element is not None and element.text else ""


def _strip_namespace(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag
