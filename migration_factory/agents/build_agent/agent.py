from __future__ import annotations

from pathlib import Path
import subprocess

from migration_factory.contracts.build import BuildRunResult, write_build_error
from migration_factory.contracts.build.schemas import build_error_contract
from migration_factory.contracts.migration import mark_build_failed, mark_build_passed

from .classifier import command_error_classification
from .detection import BuildTool, JavaProjectDetectionError, build_run_command, detect_java_project, discover_maven_run_target
from .runner import ProcessRunResult, run_until_build_result


def run_build_agent(
    project_path: str | Path,
    *,
    timeout_seconds: int = 120,
    module: str | None = None,
    main_class: str | None = None,
    auto_discover_maven_target: bool = True,
    output_dir: str | Path | None = None,
    ledger_file: str | Path | None = None,
    stream_output: bool = True,
    stop_after_start: bool = True,
) -> BuildRunResult:
    project_root = Path(project_path).expanduser().resolve()
    resolved_output_dir = _resolve_output_dir(output_dir)

    try:
        project = detect_java_project(project_root)
    except JavaProjectDetectionError as exc:
        classification = command_error_classification(str(exc))
        contract = build_error_contract(
            project_path=project_root,
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
        )
        _update_ledger(ledger_file, build_result)
        return build_result

    resolved_module = module
    resolved_main_class = main_class
    if project.build_tool == BuildTool.MAVEN and auto_discover_maven_target:
        target = discover_maven_run_target(project.path, module=module, main_class=main_class)
        resolved_module = target.module
        resolved_main_class = target.main_class

    command = build_run_command(project.base_command, project.build_tool, resolved_module, resolved_main_class)
    result = run_until_build_result(
        command=command,
        cwd=project.path,
        timeout_seconds=timeout_seconds,
        stream_output=stream_output,
        stop_after_start=stop_after_start,
    )

    if _should_retry_with_maven_rebuild(project.build_tool, result):
        rebuild_succeeded = _run_maven_rebuild(project.base_command[0], project.path)
        if rebuild_succeeded:
            result = run_until_build_result(
                command=command,
                cwd=project.path,
                timeout_seconds=timeout_seconds,
                stream_output=stream_output,
                stop_after_start=stop_after_start,
            )

    if result.succeeded:
        build_result = _success_result(result)
        _update_ledger(ledger_file, build_result)
        return build_result

    contract = build_error_contract(
        project_path=project.path,
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
    )
    _update_ledger(ledger_file, build_result)
    return build_result


def _success_result(result: ProcessRunResult) -> BuildRunResult:
    return BuildRunResult(
        succeeded=True,
        result_kind=result.classification.kind.value,
        message=result.classification.message,
        error_contract_path=None,
        exit_code=result.exit_code,
        matched_line=result.classification.line,
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
        )
        return

    mark_build_failed(
        ledger_file,
        result_kind=result.result_kind,
        message=result.message,
        error_contract_path=result.error_contract_path,
        matched_line=result.matched_line,
        exit_code=result.exit_code,
    )


def _should_retry_with_maven_rebuild(build_tool: BuildTool, result: ProcessRunResult) -> bool:
    if build_tool != BuildTool.MAVEN:
        return False
    if result.classification.kind.value != "missing_config":
        return False

    merged_output = "\n".join([*result.stdout, *result.stderr]).lower()
    indicators = (
        "not a managed type",
        "beancreationexception",
        "enablejparepositories",
    )
    return any(indicator in merged_output for indicator in indicators)


def _run_maven_rebuild(maven_executable: str, cwd: Path) -> bool:
    completed = subprocess.run(
        [maven_executable, "clean", "install", "-DskipTests"],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return completed.returncode == 0
