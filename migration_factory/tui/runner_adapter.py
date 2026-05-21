from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from migration_factory.orchestrator.resume import resume_orchestration
from migration_factory.orchestrator.state import APPROVAL_DECISION_VALUES
from migration_factory.tui.config import TuiConfig


class SubprocessRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True)
class RunnerLaunchResult:
    run_id: str
    returncode: int
    backend_result: dict[str, Any]
    run_dir: Path | None = None
    stdout: str = ""
    stderr: str = ""

    @property
    def human_approval_required(self) -> bool:
        return (
            self.backend_result.get("status") == "human_approval_required"
            or self.backend_result.get("approval_status") == "INTERRUPTED"
        )


@dataclass(frozen=True)
class ApprovalState:
    run_id: str
    run_dir: Path
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    decision_options: tuple[str, ...]
    artifact_refs: dict[str, str]
    mode: str = ""

    @property
    def has_blockers(self) -> bool:
        return bool(self.blockers)


@dataclass(frozen=True)
class RunnerResumeResult:
    run_id: str
    decision: str
    backend_result: dict[str, Any]

    @property
    def stopped(self) -> bool:
        return self.decision != "approved"


class ResumeFunction(Protocol):
    def __call__(
        self,
        *,
        run_id: str,
        run_dir: Path,
        decision: str,
        approved_by: str,
        comments: str = "",
    ) -> dict[str, Any]:
        ...


class RunnerAdapter:
    def __init__(
        self,
        *,
        subprocess_runner: SubprocessRunner = subprocess.run,
        run_id_factory: Callable[[], str] | None = None,
        resume_function: ResumeFunction = resume_orchestration,
    ) -> None:
        self._subprocess_runner = subprocess_runner
        self._run_id_factory = run_id_factory or generate_run_id
        self._resume_function = resume_function

    def next_run_id(self) -> str:
        return self._run_id_factory()

    def launch(self, config: TuiConfig, *, run_id: str | None = None) -> RunnerLaunchResult:
        run_id = run_id or self.next_run_id()
        try:
            completed = self._subprocess_runner(
                [
                    sys.executable,
                    "-m",
                    "migration_factory.orchestrator.runner",
                    "--run-id",
                    run_id,
                    "--legacy",
                    config.legacy_app_path,
                    "--modernized",
                    config.modernized_app_path,
                    "--ai-hub",
                    config.ai_hub_path,
                    "--profile",
                    config.profile_id,
                    "--mode",
                    config.mode,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return RunnerLaunchResult(
                run_id=run_id,
                returncode=1,
                backend_result={
                    "status": "backend_error",
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

        backend_result = _parse_backend_result(completed.stdout, completed.stderr)
        discovered_run_id = _string_value(backend_result.get("run_id")) or run_id

        return RunnerLaunchResult(
            run_id=discovered_run_id,
            returncode=completed.returncode,
            backend_result=backend_result,
            run_dir=_discover_run_dir(config, backend_result, discovered_run_id),
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def load_approval_state(
        self,
        config: TuiConfig,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ApprovalState | None:
        run_id = _string_value((payload or {}).get("run_id")) or config.run_id
        run_dir = _run_dir(config, run_id)
        source = payload if payload else _load_interrupt_state(run_dir)
        if not source:
            return None

        run_id = _string_value(source.get("run_id")) or run_id
        run_dir = _run_dir(config, run_id)
        options = _decision_options(source.get("decision_options"))
        return ApprovalState(
            run_id=run_id,
            run_dir=run_dir,
            blockers=_string_tuple(source.get("blockers")),
            warnings=_string_tuple(source.get("warnings")),
            decision_options=options,
            artifact_refs=_artifact_refs(source.get("artifact_refs")),
            mode=_string_value(source.get("mode")) or config.mode,
        )

    def resume(
        self,
        approval: ApprovalState,
        *,
        decision: str,
        approved_by: str,
        comments: str = "",
    ) -> RunnerResumeResult:
        if decision not in approval.decision_options:
            raise ValueError(f"Unsupported approval decision: {decision}")
        if decision not in APPROVAL_DECISION_VALUES:
            raise ValueError(f"Unsupported backend approval decision: {decision}")
        if decision == "approved" and approval.has_blockers:
            raise ValueError("Cannot approve while blockers exist")
        if not approved_by.strip():
            raise ValueError("approved_by is required")

        result = self._resume_function(
            run_id=approval.run_id,
            run_dir=approval.run_dir,
            decision=decision,
            approved_by=approved_by.strip(),
            comments=comments,
        )
        return RunnerResumeResult(
            run_id=approval.run_id,
            decision=decision,
            backend_result=result,
        )


def generate_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"tui-{stamp}-{uuid4().hex[:8]}"


def format_backend_result(result: RunnerLaunchResult) -> str:
    return json.dumps(result.backend_result, indent=2, sort_keys=True)


def format_resume_result(result: RunnerResumeResult) -> str:
    return json.dumps(result.backend_result, indent=2, sort_keys=True, default=str)


def _parse_backend_result(stdout: str, stderr: str) -> dict[str, Any]:
    if stdout.strip():
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "status": "backend_error",
                "message": "Backend returned invalid JSON",
                "stdout": stdout,
            }
        if isinstance(parsed, dict):
            return parsed
        return {"status": "backend_error", "result": parsed}

    return {
        "status": "backend_error",
        "message": stderr.strip() or "Backend returned no result",
    }


def _run_dir(config: TuiConfig, run_id: str) -> Path:
    return (
        Path(config.modernized_app_path).expanduser()
        / ".migration"
        / "runs"
        / run_id
    )


def _discover_run_dir(
    config: TuiConfig,
    payload: dict[str, Any],
    run_id: str,
) -> Path | None:
    raw_run_dir = _string_value(payload.get("run_dir"))
    if raw_run_dir:
        return Path(raw_run_dir).expanduser()
    if run_id and config.modernized_app_path.strip():
        return _run_dir(config, run_id)
    return None


def _load_interrupt_state(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "orchestration" / "approval_interrupt_state.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _decision_options(value: Any) -> tuple[str, ...]:
    raw = _string_tuple(value)
    options = tuple(option for option in raw if option in APPROVAL_DECISION_VALUES)
    if options:
        return options
    return tuple(sorted(APPROVAL_DECISION_VALUES))


def _artifact_refs(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    refs: dict[str, str] = {}
    for key, raw_ref in value.items():
        ref = _string_value(raw_ref)
        if ref:
            refs[str(key)] = ref
    return refs


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item is not None)
    if value:
        return (str(value),)
    return ()


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
