"""Worker launcher implementations for controlled diagnostic worker launch."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from migration_factory.control_tower.application.dto import WorkerLaunchResult
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.domain.errors import UnsupportedPlatformError
from migration_factory.control_tower.domain.manifests import CommandManifest, verify_manifest_checksum


class WindowsWorkerLauncher:
    def launch(
        self,
        *,
        working_dir: Path,
        manifest: CommandManifest,
        manifest_bytes: bytes,
        python_executable: str,
    ) -> WorkerLaunchResult:
        verify_manifest_checksum(manifest)

        process_control_id = str(uuid4())
        process_started_at = utc_now_text()

        manifest_path = (
            working_dir / "control" / "commands" / manifest.command_id / "command_manifest.json"
        )

        python_executable_path = Path(python_executable).expanduser()
        if not python_executable_path.is_file():
            python_executable_path = Path(python_executable)
        if not python_executable_path.is_file():
            raise FileNotFoundError(f"Python executable not found: {python_executable}")

        diagnostic_script = str(
            working_dir / "control" / "commands" / manifest.command_id / "diagnostic_worker.py"
        )

        env = {
            "COMMAND_MANIFEST_PATH": str(manifest_path),
            "PROCESS_CONTROL_ID": process_control_id,
            "PATH": os.environ.get("PATH", ""),
        }

        args = [str(python_executable_path), "-c", _DIAGNOSTIC_WORKER_SOURCE]

        creation_flags = subprocess.CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE

        proc = subprocess.Popen(
            args,
            cwd=str(working_dir),
            env=env,
            creationflags=creation_flags,
            startupinfo=startup_info,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

        _assign_to_job_object(proc.pid)

        kernel32 = __import__("ctypes").windll.kernel32
        kernel32.ResumeThread(proc._handle.detach() if hasattr(proc, '_handle') else None)

        handle = kernel32.OpenProcess(0x0040, False, proc.pid)
        if handle:
            kernel32.ResumeThread(handle)
            kernel32.CloseHandle(handle)

        return WorkerLaunchResult(
            command_id=manifest.command_id,
            job_id=manifest.job_id,
            process_control_id=process_control_id,
            worker_pid=proc.pid,
            process_started_at=process_started_at,
            worker_id=manifest.worker_id,
            launch_attempt=1,
        )


def _assign_to_job_object(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_NO_BREAKAWAY = 0x00000100

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("ChildProcessRestrictions", wintypes.DWORD),
            ("MaxLengthOfSavedCommandLine", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", wintypes.ULARGE_INTEGER),
            ("WriteOperationCount", wintypes.ULARGE_INTEGER),
            ("OtherOperationCount", wintypes.ULARGE_INTEGER),
            ("ReadTransferCount", wintypes.ULARGE_INTEGER),
            ("WriteTransferCount", wintypes.ULARGE_INTEGER),
            ("OtherTransferCount", wintypes.ULARGE_INTEGER),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job_object = kernel32.CreateJobObjectW(None, None)
    if not job_object:
        raise ctypes.WinError()

    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_NO_BREAKAWAY
    )

    result = kernel32.SetInformationJobObject(
        job_object,
        9,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    if not result:
        kernel32.CloseHandle(job_object)
        raise ctypes.WinError()

    process_handle = kernel32.OpenProcess(
        0x001F0FFF,
        False,
        pid,
    )
    if not process_handle:
        kernel32.CloseHandle(job_object)
        raise ctypes.WinError()

    result = kernel32.AssignProcessToJobObject(job_object, process_handle)
    kernel32.CloseHandle(process_handle)
    if not result:
        kernel32.CloseHandle(job_object)
        raise ctypes.WinError()


class UnsupportedPlatformWorkerLauncher:
    def launch(
        self,
        *,
        working_dir: Path,
        manifest: CommandManifest,
        manifest_bytes: bytes,
        python_executable: str,
    ) -> WorkerLaunchResult:
        raise UnsupportedPlatformError(sys.platform)


_DIAGNOSTIC_WORKER_SOURCE = r"""import json, os, sys, time
manifest_path = os.environ.get('COMMAND_MANIFEST_PATH', '')
process_control_id = os.environ.get('PROCESS_CONTROL_ID', '')
sys.stdout.write(json.dumps({"status":"started","process_control_id":process_control_id,"manifest_path":manifest_path}))
sys.stdout.flush()
time.sleep(0.5)
sys.stdout.write(json.dumps({"status":"completed","process_control_id":process_control_id}))
"""
