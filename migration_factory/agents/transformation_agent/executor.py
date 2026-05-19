from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import shlex
import shutil
import subprocess


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


def run_command(command: str, cwd: Path, stream_output: bool = True) -> CommandResult:
    args = _split_command(command)
    args = _resolve_executable(args)

    try:
        process = subprocess.Popen(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            command=command,
            exit_code=127,
            stdout=[],
            stderr=[
                f"Executable not found: {args[0]}",
                str(exc),
                "Hint: set MAVEN_CMD to the full path of mvn.cmd, for example:",
                r"set MAVEN_CMD=C:\Tools\apache-maven-3.9.15\bin\mvn.cmd",
            ],
        )

    stdout_text, stderr_text = process.communicate()
    stdout = stdout_text.splitlines()
    stderr = stderr_text.splitlines()

    if stream_output:
        for line in stdout:
            print(line)
        for line in stderr:
            print(line)

    return CommandResult(command=command, exit_code=process.returncode, stdout=stdout, stderr=stderr)


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=False)


def _resolve_executable(args: list[str]) -> list[str]:
    if not args:
        return args

    executable = args[0]

    if executable.lower() in {"mvn", "mvn.cmd", "mvn.bat"}:
        maven_cmd = (
            os.environ.get("MAVEN_CMD")
            or os.environ.get("MVN_CMD")
            or shutil.which("mvn.cmd")
            or shutil.which("mvn.bat")
            or shutil.which("mvn")
        )

        if maven_cmd:
            return [maven_cmd, *args[1:]]

    return args