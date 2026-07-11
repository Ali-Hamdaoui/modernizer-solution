from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import re


SCHEMA_VERSION = "1.0"
DEFAULT_AGENT_NAME = "build-agent"


@dataclass(frozen=True)
class BuildErrorContract:
    schema_version: str
    agent: str
    created_at: str
    project_path: str
    cwd: str | None
    build_tool: str | None
    command: list[str]
    status: str
    result_kind: str
    message: str
    matched_line: str | None
    exit_code: int | None
    requested_command: list[str] = field(default_factory=list)
    resolved_command: list[str] = field(default_factory=list)
    module: str | None = None
    main_class: str | None = None
    stdout_tail: list[str] = field(default_factory=list)
    stderr_tail: list[str] = field(default_factory=list)
    unit_id: str | None = None
    java_home: str | None = None
    java_home_env: str | None = None
    detected_version: str | None = None
    required_minimum: str | None = None
    profile: str | None = None
    target_unit: str | None = None
    maven_cmd: str | None = None
    maven_home: str | None = None
    effective_java_home: str | None = None
    PATH_excerpt: str | None = None
    platform: str | None = None


@dataclass(frozen=True)
class BuildRunResult:
    succeeded: bool
    result_kind: str
    message: str
    error_contract_path: Path | None = None
    exit_code: int | None = None
    matched_line: str | None = None
    warnings: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    cwd: Path | None = None
    command_duration_seconds: float | None = None


def write_build_error(contract: BuildErrorContract, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    kind = _safe_filename_part(contract.result_kind)
    output_path = output_dir / f"build-error-{timestamp}-{kind}.json"
    output_path.write_text(
        json.dumps(asdict(contract), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def build_error_contract(
    *,
    project_path: Path,
    cwd: Path | None = None,
    build_tool: str | None,
    command: list[str],
    result_kind: str,
    message: str,
    matched_line: str | None,
    exit_code: int | None,
    module: str | None,
    main_class: str | None,
    stdout: list[str],
    stderr: list[str],
    unit_id: str | None = None,
    java_home: str | None = None,
    java_home_env: str | None = None,
    detected_version: str | None = None,
    required_minimum: str | None = None,
    profile: str | None = None,
    target_unit: str | None = None,
    requested_command: list[str] | None = None,
    resolved_command: list[str] | None = None,
    diagnostics: dict[str, str | None] | None = None,
    tail_size: int = 40,
) -> BuildErrorContract:
    diagnostics = diagnostics or {}
    return BuildErrorContract(
        schema_version=SCHEMA_VERSION,
        agent=DEFAULT_AGENT_NAME,
        created_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        project_path=str(project_path),
        cwd=str(cwd) if cwd is not None else None,
        build_tool=build_tool,
        command=command,
        status="failed",
        result_kind=result_kind,
        message=message,
        matched_line=matched_line,
        exit_code=exit_code,
        requested_command=requested_command if requested_command is not None else command,
        resolved_command=resolved_command if resolved_command is not None else command,
        module=module,
        main_class=main_class,
        stdout_tail=stdout[-tail_size:],
        stderr_tail=stderr[-tail_size:],
        unit_id=unit_id,
        java_home=java_home,
        java_home_env=java_home_env,
        detected_version=detected_version,
        required_minimum=required_minimum,
        profile=profile,
        target_unit=target_unit,
        maven_cmd=diagnostics.get("maven_cmd"),
        maven_home=diagnostics.get("maven_home"),
        effective_java_home=diagnostics.get("effective_java_home"),
        PATH_excerpt=diagnostics.get("PATH_excerpt"),
        platform=diagnostics.get("platform"),
    )


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned or "unknown"
