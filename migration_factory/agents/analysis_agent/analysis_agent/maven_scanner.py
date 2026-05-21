from pathlib import Path
import xml.etree.ElementTree as ET

import yaml


DEFAULT_TARGET_STACK = {
    "java": "17",
    "spring_boot": "3.5.14",
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

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        parent_version = root.find(".//mvn:parent/mvn:version", ns)
        spring_boot = parent_version.text if parent_version is not None else "unknown"

        java_ver_elem = root.find(".//mvn:properties/mvn:java.version", ns)
        java_version = java_ver_elem.text if java_ver_elem is not None else "unknown"

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
            },
            "project_structure": {
                "modules": modules,
                "module_count": len(modules),
            },
            "target_stack": target_stack_payload,
            "warnings": _target_warnings(target, java_version, spring_boot),
        }
    except Exception as e:
        return {"error": str(e)}


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
