from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import os
import shutil
import xml.etree.ElementTree as ET


class BuildTool(str, Enum):
    MAVEN = "maven"
    GRADLE = "gradle"


@dataclass(frozen=True)
class JavaProjectInfo:
    path: Path
    build_tool: BuildTool
    base_command: list[str]
    uses_wrapper: bool


class JavaProjectDetectionError(Exception):
    pass


@dataclass(frozen=True)
class MavenRunTarget:
    module: str | None
    main_class: str | None


def detect_java_project(project_path: str | Path) -> JavaProjectInfo:
    path = Path(project_path).expanduser().resolve()

    if not path.exists():
        raise JavaProjectDetectionError(f"Project path does not exist: {path}")
    if not path.is_dir():
        raise JavaProjectDetectionError(f"Project path is not a directory: {path}")

    if (path / "pom.xml").is_file():
        return _maven_project(path)

    if any((path / filename).is_file() for filename in _gradle_markers()):
        return _gradle_project(path)

    raise JavaProjectDetectionError(
        "Could not detect Maven or Gradle project. Expected pom.xml, build.gradle, "
        "build.gradle.kts, settings.gradle, or settings.gradle.kts."
    )


def build_run_command(
    base_command: list[str],
    build_tool: BuildTool,
    module: str | None = None,
    main_class: str | None = None,
) -> list[str]:
    command = list(base_command)
    if build_tool != BuildTool.MAVEN:
        return command

    executable = command[0]
    goal = command[1] if len(command) > 1 else "spring-boot:run"
    maven_args: list[str] = []

    if module:
        maven_args.extend(["-f", str(Path(module) / "pom.xml")])
    if main_class:
        maven_args.append(f"-Dspring-boot.run.mainClass={main_class}")

    return [executable, *maven_args, goal]


def discover_maven_run_target(
    project_path: Path,
    module: str | None = None,
    main_class: str | None = None,
) -> MavenRunTarget:
    if module and main_class:
        return MavenRunTarget(module, main_class)

    candidates = _candidate_source_roots(project_path, module)
    discovered_module = module
    discovered_main_class = main_class

    for candidate_module, source_root in candidates:
        found_main_class = _find_spring_boot_main_class(source_root)
        if found_main_class is None:
            continue
        if discovered_module is None:
            discovered_module = candidate_module
        if discovered_main_class is None:
            discovered_main_class = found_main_class
        break

    return MavenRunTarget(discovered_module, discovered_main_class)


def _maven_project(path: Path) -> JavaProjectInfo:
    wrapper = _wrapper_command(path, "mvnw")
    if wrapper:
        return JavaProjectInfo(path, BuildTool.MAVEN, [wrapper, "spring-boot:run"], True)
    return JavaProjectInfo(path, BuildTool.MAVEN, [_resolve_system_command("mvn"), "spring-boot:run"], False)


def _gradle_project(path: Path) -> JavaProjectInfo:
    wrapper = _wrapper_command(path, "gradlew")
    if wrapper:
        return JavaProjectInfo(path, BuildTool.GRADLE, [wrapper, "bootRun"], True)
    return JavaProjectInfo(path, BuildTool.GRADLE, [_resolve_system_command("gradle"), "bootRun"], False)


def _wrapper_command(path: Path, base_name: str) -> str | None:
    candidates = [base_name]
    if os.name == "nt":
        candidates = [f"{base_name}.cmd", f"{base_name}.bat", base_name]

    for candidate in candidates:
        wrapper = path / candidate
        if wrapper.is_file():
            return str(wrapper)

    return None


def _resolve_system_command(base_name: str) -> str:
    candidates = [base_name]
    if os.name == "nt":
        candidates = [f"{base_name}.cmd", f"{base_name}.bat", f"{base_name}.exe", base_name]

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    return base_name


def _gradle_markers() -> tuple[str, ...]:
    return ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")


def _candidate_source_roots(project_path: Path, module: str | None) -> list[tuple[str | None, Path]]:
    if module:
        return [(module, project_path / module / "src" / "main" / "java")]

    modules = _read_maven_modules(project_path / "pom.xml")
    if modules:
        return [(module_name, project_path / module_name / "src" / "main" / "java") for module_name in modules]

    return [(None, project_path / "src" / "main" / "java")]


def _read_maven_modules(pom_path: Path) -> list[str]:
    if not pom_path.is_file():
        return []

    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return []

    modules_node = _find_child(root, "modules")
    if modules_node is None:
        return []

    modules: list[str] = []
    for child in modules_node:
        if _local_name(child.tag) == "module" and child.text and child.text.strip():
            modules.append(child.text.strip().replace("\\", "/"))
    return modules


def _find_spring_boot_main_class(source_root: Path) -> str | None:
    if not source_root.is_dir():
        return None

    for java_file in source_root.rglob("*.java"):
        text = java_file.read_text(encoding="utf-8", errors="ignore")
        if "@SpringBootApplication" not in text and "SpringApplication.run" not in text:
            continue

        package_name = _extract_package_name(text)
        class_name = java_file.stem
        if package_name:
            return f"{package_name}.{class_name}"
        return class_name

    return None


def _extract_package_name(source_text: str) -> str | None:
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if line.startswith("package ") and line.endswith(";"):
            return line.removeprefix("package ").removesuffix(";").strip()
    return None


def _find_child(parent: ET.Element, local_name: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == local_name:
            return child
    return None


def _local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag
