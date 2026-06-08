from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import os
import re
import subprocess
import time

from migration_factory.contracts.build import BuildRunResult, write_build_error
from migration_factory.contracts.build.schemas import build_error_contract
from migration_factory.contracts.migration import mark_build_failed, mark_build_passed

from .classifier import BuildClassification, BuildResultKind, command_error_classification
from .failure_classifier import classify_post_transform_test_failures
from .detection import (
    BuildTool,
    BuildValidationMode,
    JavaProjectDetectionError,
    JavaProjectInfo,
    build_run_command,
    detect_java_project,
    discover_maven_run_target,
    full_validation_command,
    is_maven_clean_test_command,
    is_startup_validation_command,
    plan_validation_command,
)
from .runner import ProcessRunResult, run_until_build_result, run_until_exit


STARTUP_TIMEOUT_SECONDS = 120
COMMAND_TIMEOUT_SECONDS = 300
BOOT4_MINIMUM_MAVEN_VERSION = (3, 6, 3)
LEGACY_COMPILER_EXPORTS = "--add-exports=jdk.compiler/com.sun.tools.javac.processing=ALL-UNNAMED"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildEnvironmentGateFailure:
    message: str
    detected_version: str | None = None
    required_minimum: str | None = None
    profile: str | None = None
    target_unit: str | None = None


def run_build_agent(
    project_path: str | Path,
    *,
    timeout_seconds: int | None = None,
    module: str | None = None,
    main_class: str | None = None,
    auto_discover_maven_target: bool = True,
    output_dir: str | Path | None = None,
    ledger_file: str | Path | None = None,
    stream_output: bool = True,
    stop_after_start: bool = True,
    validation_unit_id: str | None = None,
    source_changing_unit: bool = False,
    validation_command: str | list[str] | tuple[str, ...] | None = None,
    java_home_env: str | None = None,
    source_jdk_home_env: str | None = None,
    target_jdk_home_env: str | None = None,
) -> BuildRunResult:
    project_root = Path(project_path).expanduser().resolve()
    resolved_output_dir = _resolve_output_dir(output_dir)

    try:
        project = detect_java_project(project_root)
    except JavaProjectDetectionError as exc:
        classification = command_error_classification(str(exc))
        contract = build_error_contract(
            project_path=project_root,
            cwd=project_root,
            build_tool=None,
            command=[],
            result_kind=classification.kind.value,
            message=classification.message,
            matched_line=classification.line,
            exit_code=None,
            module=module,
            main_class=main_class,
            stdout=[],
            stderr=[],
            unit_id=validation_unit_id,
        )
        error_path = write_build_error(contract, resolved_output_dir)
        build_result = BuildRunResult(
            succeeded=False,
            result_kind=classification.kind.value,
            message=classification.message,
            error_contract_path=error_path,
            exit_code=None,
            matched_line=classification.line,
            command=[],
            cwd=project_root,
        )
        _update_ledger(ledger_file, build_result)
        return build_result

    explicit_command = (
        plan_validation_command(validation_command, project.base_command)
        if validation_command is not None
        else []
    )
    validation_mode = _validation_mode(project, validation_unit_id, source_changing_unit, explicit_command)
    java_env_name, java_home, java_runtime_error = _java_runtime_for_unit(
        validation_unit_id,
        java_home_env=java_home_env,
        source_jdk_home_env=source_jdk_home_env,
        target_jdk_home_env=target_jdk_home_env,
    )
    fallback_validation_warning = _cross_major_fallback_warning(
        validation_unit_id,
        java_home_env=java_env_name,
        java_home=java_home,
    )
    if java_runtime_error is not None:
        classification = command_error_classification(java_runtime_error)
        contract = build_error_contract(
            project_path=project.path,
            cwd=project.path,
            build_tool=project.build_tool.value,
            command=[],
            result_kind=classification.kind.value,
            message=classification.message,
            matched_line=classification.line,
            exit_code=None,
            module=module,
            main_class=main_class,
            stdout=[],
            stderr=[],
            unit_id=validation_unit_id,
            java_home=java_home,
            java_home_env=java_env_name,
        )
        error_path = write_build_error(contract, resolved_output_dir)
        build_result = BuildRunResult(
            succeeded=False,
            result_kind=classification.kind.value,
            message=classification.message,
            error_contract_path=error_path,
            exit_code=None,
            matched_line=classification.line,
            warnings=[java_runtime_error],
            command=[],
            cwd=project.path,
        )
        _update_ledger(ledger_file, build_result)
        return build_result
    command_env = _build_command_env(
        java_home,
        add_legacy_compiler_exports=fallback_validation_warning is not None,
    )
    gate_failure = _target_environment_gate(project, validation_unit_id, explicit_command, env=command_env)
    if gate_failure is not None:
        classification = command_error_classification(gate_failure.message)
        contract = build_error_contract(
            project_path=project.path,
            cwd=project.path,
            build_tool=project.build_tool.value,
            command=[],
            result_kind=classification.kind.value,
            message=classification.message,
            matched_line=classification.line,
            exit_code=None,
            module=module,
            main_class=main_class,
            stdout=[],
            stderr=[],
            unit_id=validation_unit_id,
            java_home=java_home,
            java_home_env=java_env_name,
            detected_version=gate_failure.detected_version,
            required_minimum=gate_failure.required_minimum,
            profile=gate_failure.profile,
            target_unit=gate_failure.target_unit,
        )
        error_path = write_build_error(contract, resolved_output_dir)
        build_result = BuildRunResult(
            succeeded=False,
            result_kind=classification.kind.value,
            message=classification.message,
            error_contract_path=error_path,
            exit_code=None,
            matched_line=classification.line,
            warnings=[gate_failure.message],
            command=[],
            cwd=project.path,
        )
        _update_ledger(ledger_file, build_result)
        return build_result
    resolved_module = module
    resolved_main_class = main_class
    if validation_mode == BuildValidationMode.REACTOR_TEST:
        command = _reactor_validation_command(project, explicit_command)
        command = _adjust_command_for_cross_major_fallback(
            command,
            project.build_tool,
            warning=fallback_validation_warning,
        )
        command_started = time.monotonic()
        result = run_until_exit(
            command=command,
            cwd=project.path,
            timeout_seconds=_command_timeout(timeout_seconds),
            stream_output=stream_output,
            env=command_env,
        )
        command_duration_seconds = time.monotonic() - command_started
    elif validation_mode == BuildValidationMode.PLAN_COMMAND:
        command = explicit_command
        command = _adjust_command_for_cross_major_fallback(
            command,
            project.build_tool,
            warning=fallback_validation_warning,
        )
        if is_startup_validation_command(command):
            command_started = time.monotonic()
            result = run_until_build_result(
                command=command,
                cwd=project.path,
                timeout_seconds=_startup_timeout(timeout_seconds),
                stream_output=stream_output,
                stop_after_start=stop_after_start,
                env=command_env,
            )
            command_duration_seconds = time.monotonic() - command_started
        else:
            command_started = time.monotonic()
            result = run_until_exit(
                command=command,
                cwd=project.path,
                timeout_seconds=_command_timeout(timeout_seconds),
                stream_output=stream_output,
                env=command_env,
            )
            command_duration_seconds = time.monotonic() - command_started
    else:
        if project.build_tool == BuildTool.MAVEN and auto_discover_maven_target:
            target = discover_maven_run_target(project.path, module=module, main_class=main_class)
            resolved_module = target.module
            resolved_main_class = target.main_class
        command = build_run_command(
            project.base_command,
            project.build_tool,
            resolved_module,
            resolved_main_class,
            use_reactor=False,
        )
        command = _adjust_command_for_cross_major_fallback(
            command,
            project.build_tool,
            warning=fallback_validation_warning,
        )
        command_started = time.monotonic()
        result = run_until_build_result(
            command=command,
            cwd=project.path,
            timeout_seconds=_startup_timeout(timeout_seconds),
            stream_output=stream_output,
            stop_after_start=stop_after_start,
            env=command_env,
        )
        command_duration_seconds = time.monotonic() - command_started

    if result.succeeded:
        build_result = _success_result(
            result,
            command=command,
            cwd=project.path,
            command_duration_seconds=command_duration_seconds,
            extra_warnings=[fallback_validation_warning] if fallback_validation_warning else [],
        )
        _update_ledger(ledger_file, build_result)
        return build_result

    failure_classification = classify_post_transform_test_failures(
        project.path,
        output_dir=resolved_output_dir,
        unit_id=validation_unit_id,
    )
    contract = build_error_contract(
        project_path=project.path,
        cwd=project.path,
        build_tool=project.build_tool.value,
        command=command,
        result_kind=result.classification.kind.value,
        message=result.classification.message,
        matched_line=result.classification.line,
        exit_code=result.exit_code,
        module=resolved_module,
        main_class=resolved_main_class,
        stdout=result.stdout,
        stderr=result.stderr,
        unit_id=validation_unit_id,
        java_home=java_home,
        java_home_env=java_env_name,
        failure_classification_path=(
            str(failure_classification.artifact_path) if failure_classification.artifact_path is not None else None
        ),
        failure_categories=failure_classification.category_counts,
    )
    error_path = write_build_error(contract, resolved_output_dir)

    build_result = BuildRunResult(
        succeeded=False,
        result_kind=result.classification.kind.value,
        message=result.classification.message,
        error_contract_path=error_path,
        exit_code=result.exit_code,
        matched_line=result.classification.line,
        warnings=_merge_warnings(result.warnings, fallback_validation_warning),
        command=command,
        cwd=project.path,
        command_duration_seconds=command_duration_seconds,
    )
    _update_ledger(ledger_file, build_result)
    return build_result


def _validation_mode(
    project: JavaProjectInfo,
    validation_unit_id: str | None,
    source_changing_unit: bool,
    explicit_command: list[str],
) -> BuildValidationMode:
    if (
        project.build_tool == BuildTool.MAVEN
        and project.maven_modules
        and source_changing_unit
        and validation_unit_id != "baseline"
    ):
        return BuildValidationMode.REACTOR_TEST
    if explicit_command:
        return BuildValidationMode.PLAN_COMMAND
    return BuildValidationMode.STARTUP


def _reactor_validation_command(project: JavaProjectInfo, explicit_command: list[str]) -> list[str]:
    if (
        explicit_command
        and not is_startup_validation_command(explicit_command)
        and "-f" not in explicit_command
        and is_maven_clean_test_command(explicit_command)
    ):
        return explicit_command
    return full_validation_command(project.base_command, project.build_tool)


def _startup_timeout(timeout_seconds: int | None) -> int:
    return timeout_seconds if timeout_seconds is not None else STARTUP_TIMEOUT_SECONDS


def _command_timeout(timeout_seconds: int | None) -> int:
    return timeout_seconds if timeout_seconds is not None else COMMAND_TIMEOUT_SECONDS


def _success_result(
    result: ProcessRunResult,
    *,
    command: list[str],
    cwd: Path,
    command_duration_seconds: float,
    extra_warnings: list[str] | None = None,
) -> BuildRunResult:
    return BuildRunResult(
        succeeded=True,
        result_kind=result.classification.kind.value,
        message=result.classification.message,
        error_contract_path=None,
        exit_code=result.exit_code,
        matched_line=result.classification.line,
        warnings=[*result.warnings, *(extra_warnings or [])],
        command=command,
        cwd=cwd,
        command_duration_seconds=command_duration_seconds,
    )


def _resolve_output_dir(output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        return Path(output_dir).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "contracts" / "build"


def _update_ledger(ledger_file: str | Path | None, result: BuildRunResult) -> None:
    if ledger_file is None:
        return

    if result.succeeded:
        mark_build_passed(
            ledger_file,
            result_kind=result.result_kind,
            message=result.message,
            matched_line=result.matched_line,
            exit_code=result.exit_code,
            warnings=result.warnings,
            command=result.command,
            cwd=result.cwd,
            command_duration_seconds=result.command_duration_seconds,
        )
        return

    mark_build_failed(
        ledger_file,
        result_kind=result.result_kind,
        message=result.message,
        error_contract_path=result.error_contract_path,
        matched_line=result.matched_line,
        exit_code=result.exit_code,
        warnings=result.warnings,
        command=result.command,
        cwd=result.cwd,
        command_duration_seconds=result.command_duration_seconds,
    )


def _java_runtime_for_unit(
    validation_unit_id: str | None,
    *,
    java_home_env: str | None,
    source_jdk_home_env: str | None,
    target_jdk_home_env: str | None,
) -> tuple[str | None, str | None, str | None]:
    env_name = None
    allow_fallback = False
    if java_home_env:
        env_name = java_home_env
        allow_fallback = env_name in {source_jdk_home_env, target_jdk_home_env}
    elif validation_unit_id == "baseline":
        env_name = source_jdk_home_env
        allow_fallback = True
    elif validation_unit_id:
        env_name = target_jdk_home_env
        allow_fallback = True
    if not env_name:
        return None, None, None
    java_home = os.environ.get(env_name)
    if not java_home:
        fallback_home, _fallback_reason = _compatible_java_home_fallback(validation_unit_id) if allow_fallback else (None, None)
        if fallback_home:
            return env_name, fallback_home, None
        return env_name, None, f"Configured Java home env '{env_name}' is not set."
    java_home_path = Path(java_home)
    java_bin = java_home_path / "bin" / ("java.exe" if os.name == "nt" else "java")
    if not java_home_path.is_dir() or not java_bin.is_file():
        fallback_home, _fallback_reason = _compatible_java_home_fallback(validation_unit_id) if allow_fallback else (None, None)
        if fallback_home:
            return env_name, fallback_home, None
        return env_name, str(java_home), (
            f"Configured Java home env '{env_name}' points to invalid JAVA_HOME: {java_home}"
        )
    return env_name, str(java_home), None


def _compatible_java_home_fallback(validation_unit_id: str | None) -> tuple[str | None, str | None]:
    fallback_home = os.environ.get("JAVA_HOME")
    if not fallback_home:
        return None, None
    java_home_path = Path(fallback_home)
    java_bin = java_home_path / "bin" / ("java.exe" if os.name == "nt" else "java")
    if not java_home_path.is_dir() or not java_bin.is_file():
        return None, None
    required_major = _target_java_for_unit(validation_unit_id) or 11
    version_result = _run_version_command([str(java_bin), "-version"], env=_build_command_env(str(java_home_path)))
    version_text = "\n".join([*version_result.stderr, *version_result.stdout])
    major = _parse_java_major(version_text)
    if version_result.exit_code != 0 or major is None or major < required_major:
        return None, None
    return (
        str(java_home_path),
        f"Configured Java home env unavailable; falling back to compatible JAVA_HOME ({major}) for unit {validation_unit_id or 'unknown'}.",
    )


def _build_command_env(
    java_home: str | None,
    *,
    add_legacy_compiler_exports: bool = False,
) -> dict[str, str] | None:
    if not java_home:
        return None
    env = os.environ.copy()
    env["JAVA_HOME"] = java_home
    env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")
    if add_legacy_compiler_exports:
        existing = str(env.get("MAVEN_OPTS") or "").strip()
        if LEGACY_COMPILER_EXPORTS not in existing:
            env["MAVEN_OPTS"] = f"{existing} {LEGACY_COMPILER_EXPORTS}".strip()
    return env


def _cross_major_fallback_warning(
    validation_unit_id: str | None,
    *,
    java_home_env: str | None,
    java_home: str | None,
) -> str | None:
    if not validation_unit_id or not java_home_env or not java_home:
        return None
    configured_home = str(os.environ.get(java_home_env) or "").strip()
    if configured_home:
        return None
    current_home = str(os.environ.get("JAVA_HOME") or "").strip()
    if not current_home:
        return None
    current_path = Path(current_home).expanduser()
    java_home_path = Path(java_home).expanduser()
    if current_path != java_home_path:
        return None
    required_major = _target_java_for_unit(validation_unit_id) or 11
    version_result = _run_version_command(
        _java_version_command(_build_command_env(java_home)),
        env=_build_command_env(java_home),
    )
    version_text = "\n".join([*version_result.stderr, *version_result.stdout])
    current_major = _parse_java_major(version_text)
    if current_major is None or current_major <= required_major:
        return None
    return (
        f"Requested source JDK env '{java_home_env}' is unavailable; "
        f"using JAVA_HOME {current_major} for unit {validation_unit_id} with Maven test execution skipped."
    )


def _adjust_command_for_cross_major_fallback(
    command: list[str],
    build_tool: BuildTool,
    *,
    warning: str | None,
) -> list[str]:
    if warning is None or build_tool != BuildTool.MAVEN:
        return command
    if not is_maven_clean_test_command(command):
        return command
    if any(arg == "-DskipTests" for arg in command):
        return command
    executable = command[0]
    args = [arg for arg in command[1:] if arg != "test"]
    return [executable, "-DskipTests", *args, "test"]


def _merge_warnings(existing: list[str], extra: str | None) -> list[str]:
    if not extra:
        return existing
    return [*existing, extra]


def _target_environment_gate(
    project: JavaProjectInfo,
    validation_unit_id: str | None,
    validation_command: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> BuildEnvironmentGateFailure | None:
    if not validation_unit_id:
        return None
    target_java = _target_java_for_unit(validation_unit_id)
    boot4 = "spring-boot-4-0" in validation_unit_id
    if target_java is not None and target_java >= 21:
        java_result = _run_version_command(_java_version_command(env), env=env)
        java_major = _parse_java_major("\n".join([*java_result.stderr, *java_result.stdout]))
        if java_result.exit_code != 0 or java_major is None:
            return BuildEnvironmentGateFailure(f"Java runtime version check failed for target Java {target_java}.")
        if java_major < target_java:
            return BuildEnvironmentGateFailure(
                f"Java runtime {java_major} is incompatible with target Java {target_java}."
            )
    if boot4 and project.build_tool == BuildTool.MAVEN:
        maven_command = _maven_version_executable(project, validation_command)
        mvn_result = _run_version_command([maven_command, "-version"], env=env)
        maven_output = "\n".join([*mvn_result.stdout, *mvn_result.stderr])
        maven_version = _parse_maven_version(maven_output)
        required_minimum = _format_version(BOOT4_MINIMUM_MAVEN_VERSION)
        detected_version = _format_version(maven_version) if maven_version is not None else None
        LOGGER.info(
            "Maven version gate for %s: detected=%s required_minimum=%s",
            validation_unit_id,
            detected_version or "unparseable",
            required_minimum,
        )
        if mvn_result.exit_code != 0 or maven_version is None:
            return BuildEnvironmentGateFailure(
                "Maven version check failed for Spring Boot 4 target; mvn -version output was unparseable.",
                detected_version=detected_version,
                required_minimum=required_minimum,
                profile="spring-boot-4",
                target_unit=validation_unit_id,
            )
        if maven_version < BOOT4_MINIMUM_MAVEN_VERSION:
            return BuildEnvironmentGateFailure(
                f"Maven version {detected_version} is incompatible with Spring Boot 4 target; "
                f"Maven >= {required_minimum} is required.",
                detected_version=detected_version,
                required_minimum=required_minimum,
                profile="spring-boot-4",
                target_unit=validation_unit_id,
            )
    return None


def _maven_version_executable(project: JavaProjectInfo, validation_command: list[str] | None = None) -> str:
    candidates: list[str] = []
    if validation_command:
        candidates.append(validation_command[0])
    if project.base_command:
        candidates.append(project.base_command[0])
    candidates.append("mvn")

    for candidate in candidates:
        if _is_non_executable_local_file(candidate):
            LOGGER.info("Skipping non-executable Maven wrapper for version gate: %s", candidate)
            continue
        return candidate
    return "mvn"


def _is_non_executable_local_file(command: str) -> bool:
    if os.name == "nt":
        return False
    path = Path(command)
    if not path.is_absolute() and os.sep not in command:
        return False
    return path.is_file() and not os.access(path, os.X_OK)


def _target_java_for_unit(unit_id: str) -> int | None:
    if "spring-boot-4-0" in unit_id:
        return 21
    match = re.search(r"java-(\d+)", unit_id)
    return int(match.group(1)) if match else None


def _run_version_command(command: list[str], env: dict[str, str] | None = None) -> ProcessRunResult:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProcessRunResult(command_error_classification(str(exc)), None, [], [str(exc)])
    return ProcessRunResult(
        BuildClassification(BuildResultKind.SUCCESS, "version checked")
        if completed.returncode == 0
        else command_error_classification("version check failed"),
        completed.returncode,
        completed.stdout.splitlines(),
        completed.stderr.splitlines(),
    )


def _java_version_command(env: dict[str, str] | None = None) -> list[str]:
    java_home = str((env or {}).get("JAVA_HOME") or "").strip()
    if java_home:
        java_bin = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if java_bin.is_file():
            return [str(java_bin), "-version"]
    return ["java", "-version"]


def _parse_java_major(output: str) -> int | None:
    match = re.search(r'version "([^"]+)"', output)
    if not match:
        match = re.search(r"\b(?:openjdk|java)\s+(\d+(?:\.\d+)*)", output, re.IGNORECASE)
    if not match:
        return None
    version = match.group(1)
    if version.startswith("1."):
        parts = version.split(".")
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    major = version.split(".", 1)[0]
    return int(major) if major.isdigit() else None


def _parse_maven_version(output: str) -> tuple[int, int, int] | None:
    match = re.search(r"Apache Maven\s+(\d+)\.(\d+)(?:\.(\d+))?", output)
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def _format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)
