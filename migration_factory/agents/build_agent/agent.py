from __future__ import annotations

from pathlib import Path
import time

from migration_factory.contracts.build import BuildRunResult, write_build_error
from migration_factory.contracts.build.schemas import build_error_contract
from migration_factory.contracts.migration import mark_build_failed, mark_build_passed

from .classifier import command_error_classification
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
    resolved_module = module
    resolved_main_class = main_class
    if validation_mode == BuildValidationMode.REACTOR_TEST:
        command = _reactor_validation_command(project, explicit_command)
        command_started = time.monotonic()
        result = run_until_exit(
            command=command,
            cwd=project.path,
            timeout_seconds=_command_timeout(timeout_seconds),
            stream_output=stream_output,
        )
        command_duration_seconds = time.monotonic() - command_started
    elif validation_mode == BuildValidationMode.PLAN_COMMAND:
        command = explicit_command
        if is_startup_validation_command(command):
            command_started = time.monotonic()
            result = run_until_build_result(
                command=command,
                cwd=project.path,
                timeout_seconds=_startup_timeout(timeout_seconds),
                stream_output=stream_output,
                stop_after_start=stop_after_start,
            )
            command_duration_seconds = time.monotonic() - command_started
        else:
            command_started = time.monotonic()
            result = run_until_exit(
                command=command,
                cwd=project.path,
                timeout_seconds=_command_timeout(timeout_seconds),
                stream_output=stream_output,
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
        command_started = time.monotonic()
        result = run_until_build_result(
            command=command,
            cwd=project.path,
            timeout_seconds=_startup_timeout(timeout_seconds),
            stream_output=stream_output,
            stop_after_start=stop_after_start,
        )
        command_duration_seconds = time.monotonic() - command_started

    if result.succeeded:
        build_result = _success_result(
            result,
            command=command,
            cwd=project.path,
            command_duration_seconds=command_duration_seconds,
        )
        _update_ledger(ledger_file, build_result)
        return build_result

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
    )
    error_path = write_build_error(contract, resolved_output_dir)

    build_result = BuildRunResult(
        succeeded=False,
        result_kind=result.classification.kind.value,
        message=result.classification.message,
        error_contract_path=error_path,
        exit_code=result.exit_code,
        matched_line=result.classification.line,
        warnings=result.warnings,
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
) -> BuildRunResult:
    return BuildRunResult(
        succeeded=True,
        result_kind=result.classification.kind.value,
        message=result.classification.message,
        error_contract_path=None,
        exit_code=result.exit_code,
        matched_line=result.classification.line,
        warnings=result.warnings,
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
