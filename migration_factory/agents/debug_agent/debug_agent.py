from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import re
import shutil
import subprocess

from migration_factory.contracts.migration import (
    BuildValidationStatus,
    LedgerError,
    LedgerStatus,
    load_ledger,
    save_ledger,
)


class DebugAgentError(Exception):
    pass


@dataclass(frozen=True)
class DebugCommandResult:
    command: list[str]
    exit_code: int
    stdout_tail: list[str] = field(default_factory=list)
    stderr_tail: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class DebugRunResult:
    succeeded: bool
    message: str
    commands: list[DebugCommandResult]
    ledger_file: Path | None = None


def run_debug_agent(
    project_path: str | Path | None = None,
    *,
    error_contract_path: str | Path | None = None,
    ledger_file: str | Path | None = None,
    stream_output: bool = True,
    continue_on_failure: bool = False,
) -> DebugRunResult:
    contract_path = _resolve_contract_path(error_contract_path, ledger_file)
    contract = _load_contract(contract_path)
    project_root = _resolve_project_path(project_path, contract)
    commands = build_debug_commands(contract, project_root)

    if not commands:
        result = DebugRunResult(False, f"No automatic debug commands for {contract.get('result_kind')}", [])
        _record_debug_result(ledger_file, contract_path, result, reopen_for_build=False)
        return result

    results: list[DebugCommandResult] = []
    for command in commands:
        result = _run_command(command, project_root, stream_output=stream_output)
        results.append(result)
        if not result.succeeded and not continue_on_failure:
            run_result = DebugRunResult(False, "Debug command failed; ledger remains blocked", results)
            _record_debug_result(ledger_file, contract_path, run_result, reopen_for_build=False)
            return run_result

    succeeded = all(result.succeeded for result in results)
    message = "Debug commands completed; rerun Build Agent" if succeeded else "Debug commands completed with failures"
    run_result = DebugRunResult(succeeded, message, results, Path(ledger_file).resolve() if ledger_file else None)
    _record_debug_result(ledger_file, contract_path, run_result, reopen_for_build=succeeded)
    return run_result


def build_debug_commands(contract: dict[str, Any], project_root: Path) -> list[list[str]]:
    build_tool = contract.get("build_tool")
    result_kind = contract.get("result_kind")
    module = contract.get("module")

    if build_tool == "maven":
        return _maven_debug_commands(project_root, result_kind, module)
    if build_tool == "gradle":
        return _gradle_debug_commands(project_root, result_kind)
    return []


def _maven_debug_commands(project_root: Path, result_kind: str | None, module: str | None) -> list[list[str]]:
    mvn = _maven_executable(project_root)
    base = [mvn]
    if module:
        base.extend(["-f", str(Path(module) / "pom.xml")])

    if result_kind == "dependency_error":
        return [
            [*base, "-U", "dependency:resolve"],
            [*base, "-U", "clean", "install", "-DskipTests"],
        ]
    if result_kind in {
        "compilation_error",
        "main_class_not_found",
        "missing_config",
        "process_exited",
        "timeout",
        "unknown_failure",
    }:
        return [
            [*base, "clean", "compile", "-DskipTests"],
            [*base, "clean", "install", "-DskipTests"],
        ]
    if result_kind == "java_version_mismatch":
        return [
            [mvn, "-version"],
            [_java_executable(), "-version"],
        ]
    return []


def _gradle_debug_commands(project_root: Path, result_kind: str | None) -> list[list[str]]:
    gradle = _gradle_executable(project_root)
    if result_kind == "dependency_error":
        return [[gradle, "--refresh-dependencies", "build", "-x", "test"]]
    if result_kind in {
        "compilation_error",
        "main_class_not_found",
        "missing_config",
        "process_exited",
        "timeout",
        "unknown_failure",
    }:
        return [
            [gradle, "clean", "compileJava", "-x", "test"],
            [gradle, "clean", "build", "-x", "test"],
        ]
    if result_kind == "java_version_mismatch":
        return [
            [gradle, "--version"],
            [_java_executable(), "-version"],
        ]
    return []


def _resolve_contract_path(error_contract_path: str | Path | None, ledger_file: str | Path | None) -> Path:
    if error_contract_path is not None:
        path = Path(error_contract_path).expanduser().resolve()
        if not path.is_file():
            raise DebugAgentError(f"Build error contract does not exist: {path}")
        return path

    if ledger_file is None:
        raise DebugAgentError("Pass --error-contract or --ledger-file")

    ledger = load_ledger(ledger_file)
    contract_path = ledger.get("build_validation", {}).get("error_contract_path")
    if not contract_path:
        raise DebugAgentError("Ledger does not contain build_validation.error_contract_path")

    path = Path(contract_path).expanduser().resolve()
    if not path.is_file():
        raise DebugAgentError(f"Build error contract from ledger does not exist: {path}")
    return path


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DebugAgentError(f"Build error contract is not valid JSON: {path}") from exc


def _resolve_project_path(project_path: str | Path | None, contract: dict[str, Any]) -> Path:
    raw_path = project_path or contract.get("project_path")
    if not raw_path:
        raise DebugAgentError("Project path was not provided and is missing from the build contract")

    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir():
        raise DebugAgentError(f"Project path does not exist or is not a directory: {path}")
    return path


def _run_command(command: list[str], cwd: Path, *, stream_output: bool) -> DebugCommandResult:
    resolved = _resolve_executable(command, cwd)
    try:
        process = subprocess.Popen(
            resolved,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        return DebugCommandResult(command, 127, [], [f"Executable not found: {resolved[0]}", str(exc)])

    stdout_text, stderr_text = process.communicate()
    stdout = stdout_text.splitlines()
    stderr = stderr_text.splitlines()

    if stream_output:
        for line in stdout:
            print(line)
        for line in stderr:
            print(line)

    return DebugCommandResult(command, process.returncode, stdout[-40:], stderr[-40:])


def _record_debug_result(
    ledger_file: str | Path | None,
    contract_path: Path,
    result: DebugRunResult,
    *,
    reopen_for_build: bool,
) -> None:
    if ledger_file is None:
        return

    ledger = load_ledger(ledger_file)
    unit_id = ledger.get("current_unit") or ledger.get("blocked_unit")
    if not unit_id:
        raise LedgerError("Cannot record debug result because ledger has no current or blocked unit")

    unit = ledger.setdefault("units", {}).setdefault(unit_id, {})
    attempts = unit.setdefault("debug_attempts", [])
    attempts.append(
        {
            "agent": "debug-agent",
            "created_at": _now(),
            "succeeded": result.succeeded,
            "message": result.message,
            "error_contract_path": str(contract_path),
            "commands": [
                {
                    "command": item.command,
                    "exit_code": item.exit_code,
                    "stdout_tail": item.stdout_tail,
                    "stderr_tail": item.stderr_tail,
                }
                for item in result.commands
            ],
        }
    )

    if reopen_for_build:
        unit["status"] = LedgerStatus.AWAITING_BUILD_AGENT
        ledger["status"] = LedgerStatus.AWAITING_BUILD_AGENT
        ledger["blocked_unit"] = None
        ledger["build_validation"] = {
            "required": True,
            "status": BuildValidationStatus.PENDING,
            "unit_id": unit_id,
            "debugged_at": _now(),
            "previous_error_contract_path": str(contract_path),
            "message": "Debug Agent completed automatic repair commands; rerun Build Agent",
        }
    else:
        unit["status"] = LedgerStatus.BLOCKED
        ledger["status"] = LedgerStatus.BLOCKED
        ledger["blocked_unit"] = unit_id
        ledger.setdefault("build_validation", {})["debug_status"] = "failed"
        ledger["build_validation"]["debugged_at"] = _now()

    save_ledger(ledger_file, ledger)


def _maven_executable(project_root: Path) -> str:
    wrapper = _project_wrapper(project_root, "mvnw")
    if wrapper:
        return wrapper
    return os.environ.get("MAVEN_CMD") or os.environ.get("MVN_CMD") or _which_windows("mvn") or "mvn"


def _gradle_executable(project_root: Path) -> str:
    wrapper = _project_wrapper(project_root, "gradlew")
    if wrapper:
        return wrapper
    return os.environ.get("GRADLE_CMD") or _which_windows("gradle") or "gradle"


def _java_executable() -> str:
    return _which_windows("java") or "java"


def _project_wrapper(project_root: Path, base_name: str) -> str | None:
    candidates = [base_name]
    if os.name == "nt":
        candidates = [f"{base_name}.cmd", f"{base_name}.bat", base_name]

    for candidate in candidates:
        wrapper = project_root / candidate
        if wrapper.is_file():
            return str(wrapper)
    return None


def _resolve_executable(command: list[str], cwd: Path) -> list[str]:
    if not command:
        return command

    executable = command[0]
    base = Path(executable).name.lower()
    if re.fullmatch(r"mvn(\.cmd|\.bat|\.exe)?", base):
        return [_maven_executable(cwd), *command[1:]]
    if re.fullmatch(r"gradle(w)?(\.cmd|\.bat|\.exe)?", base):
        return [_gradle_executable(cwd), *command[1:]]
    return command


def _which_windows(base_name: str) -> str | None:
    candidates = [base_name]
    if os.name == "nt":
        candidates = [f"{base_name}.cmd", f"{base_name}.bat", f"{base_name}.exe", base_name]

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
