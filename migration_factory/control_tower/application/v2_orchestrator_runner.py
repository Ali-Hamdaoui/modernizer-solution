"""Run V2 backend-owned orchestrator manifests and persist live events."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from migration_factory.control_tower.application.redaction import (
    redact_model_summary,
    redact_public_value,
)
from migration_factory.control_tower.application.v2_approval_mapping import V2ApprovalMappingService
from migration_factory.control_tower.domain.checksums import sha256_canonical_json


UnitOfWorkFactory = Callable[[], Any]

_EVENT_PREFIX = "CONTROL_TOWER_EVENT "
_FINAL_JSON_PREFIX = "CONTROL_TOWER_FINAL_JSON "
_MAX_TEXT = 4096

_SAFE_ENV_KEYS = (
    "COMSPEC",
    "HOME",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
)

_MANIFEST_ENV_KEYS = (
    "JAVA_HOME",
    "JAVA11_HOME",
    "JAVA17_HOME",
    "JAVA21_HOME",
    "MAVEN_CMD",
)

_COPILOT_ENV_KEYS = (
    "AI_MIGRATION_COPILOT_PROVIDER",
    "AI_MIGRATION_COPILOT_MODEL",
    "AI_MIGRATION_COPILOT_ASSIST",
    "AI_MIGRATION_ENABLE_COPILOT_REPORT",
    "AI_MIGRATION_COPILOT_REQUIRED",
    "AI_MIGRATION_COPILOT_FAILURE_AGENT_ENABLED",
    "AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS",
    "AI_MIGRATION_SKIP_ENDPOINT_SMOKE",
    "AI_MIGRATION_PROOF_LEVEL",
    "AI_MIGRATION_H2_STARTUP_REQUIRED",
    "AI_MIGRATION_COPILOT_TIMEOUT_SECONDS",
    "AI_MIGRATION_COPILOT_REPAIR_MAX_ATTEMPTS",
    "AI_MIGRATION_COPILOT_REPAIR_STRICT_CONTAINMENT",
    "AI_MIGRATION_COPILOT_LOG_LEVEL",
)

_SECRET_ENV_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTHORIZATION")

_TERMINAL_FAILURES = {
    "BUILD_FAILED_IN_SANDBOX",
    "TEST_FAILED",
    "TEST_FAILED_IN_SANDBOX",
    "FALLBACK_REPAIR_PLAN",
    "TRANSFORM_FAILED",
    "FAILED",
    "FAIL",
}

_SUCCESS_ORCHESTRATION_STATUS = "PASS"
_SUCCESS_FINAL_STATUS = "TRANSFORM_APPLIED_IN_SANDBOX"
_SUCCESS_TRANSFORM_STATUS = "TRANSFORM_APPLIED_IN_SANDBOX"
_SUCCESS_BUILD_STATUS = "BUILD_PASSED_IN_SANDBOX"
_SUCCESS_TEST_STATUSES = {"PASS", "TEST_PASSED", "TESTS_NOT_FOUND", "PASS_WITH_WARNINGS"}

_NON_ACTIVE_REPAIR_STATUSES = {
    "",
    "SKIPPED",
    "PENDING",
    "NOT_IMPLEMENTED",
    "NONE",
    "NO_REPAIR",
}


@dataclass(frozen=True)
class V2OrchestratorStart:
    command_id: str
    job_id: str
    stage_index: int
    pid: int | None
    status: str


class V2OrchestratorRunner:
    """Launches the persisted runner manifest in a background subprocess."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        notifier: Any | None = None,
        popen_factory: Any = subprocess.Popen,
        cwd: Path | None = None,
        diagnosis_callback: Callable[[str, int, str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._notifier = notifier
        self._popen_factory = popen_factory
        self._cwd = cwd or Path(__file__).resolve().parents[3]
        self._event_lock = threading.Lock()
        self._last_stdout_lines: list[str] = []
        self._diagnosis_callback = diagnosis_callback

    def start(self, *, job_id: str, command_id: str) -> V2OrchestratorStart:
        with self._unit_of_work_factory() as uow:
            command = uow.v2_commands.get(command_id)
            if command is None:
                raise ValueError(f"V2 command {command_id!r} not found")
            argv = _load_json_list(command.argv_json)
            env_manifest = _load_json_dict(command.env_json)
            stage_index = command.stage_index

        thread = threading.Thread(
            target=self._run_process,
            kwargs={
                "job_id": job_id,
                "command_id": command_id,
                "stage_index": stage_index,
                "argv": argv,
                "env_manifest": env_manifest,
            },
            name=f"v2-orchestrator-{command_id[:8]}",
            daemon=True,
        )
        thread.start()

        return V2OrchestratorStart(
            command_id=command_id,
            job_id=job_id,
            stage_index=stage_index,
            pid=None,
            status="started",
        )

    def start_resume(self, *, job_id: str, resume_id: str) -> V2OrchestratorStart:
        with self._unit_of_work_factory() as uow:
            resume = uow.v2_approvals.get_resume(resume_id)
            if resume is None:
                raise ValueError(f"V2 resume command {resume_id!r} not found")
            if resume.job_id != job_id:
                raise ValueError(f"V2 resume command {resume_id!r} does not belong to job {job_id!r}")

            argv = _load_json_list(resume.command_json)
            stage_index = resume.stage_index
            env_manifest = _load_env_manifest_for_stage(uow, job_id, stage_index)

        thread = threading.Thread(
            target=self._run_process,
            kwargs={
                "job_id": job_id,
                "command_id": resume_id,
                "stage_index": stage_index,
                "argv": argv,
                "env_manifest": env_manifest,
                "resume": True,
            },
            name=f"v2-orchestrator-resume-{resume_id[:8]}",
            daemon=True,
        )
        thread.start()

        return V2OrchestratorStart(
            command_id=resume_id,
            job_id=job_id,
            stage_index=stage_index,
            pid=None,
            status="started",
        )

    def _run_process(
        self,
        *,
        job_id: str,
        command_id: str,
        stage_index: int,
        argv: list[str],
        env_manifest: dict[str, Any],
        resume: bool = False,
    ) -> None:
        if resume:
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="approval_started",
                status="running",
                message="Approval accepted; orchestrator resume process starting.",
                payload={"command_id": command_id},
            )

        self._event(
            job_id=job_id,
            stage=stage_index,
            event_type="resume_started" if resume else "stage_started",
            status="running",
            message=f"Stage {stage_index} real orchestrator {'resume ' if resume else ''}started.",
            payload={"command_id": command_id},
        )
        self._event(
            job_id=job_id,
            stage=stage_index,
            event_type="command_started",
            status="running",
            message=(
                "Backend-owned approval resume command launched."
                if resume
                else "Backend-owned orchestrator manifest launched."
            ),
            payload={"command_id": command_id, "shell": False, "cwd": str(self._cwd)},
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        try:
            process_env = _build_env(env_manifest)
            copilot_enabled = bool(
                process_env.get("AI_MIGRATION_COPILOT_PROVIDER")
                or process_env.get("AI_MIGRATION_COPILOT_MODEL")
            )

            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="copilot_status_checked",
                status="completed",
                message="Copilot/model runtime configuration checked for orchestrator subprocess.",
                payload={
                    "command_id": command_id,
                    "copilot_config_present": copilot_enabled,
                    "provider_configured": bool(process_env.get("AI_MIGRATION_COPILOT_PROVIDER")),
                    "model_configured": bool(process_env.get("AI_MIGRATION_COPILOT_MODEL")),
                },
            )

            process = self._popen_factory(
                _normalized_argv(argv),
                cwd=str(self._cwd),
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )

            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="process_started",
                status="running",
                message="Orchestrator subprocess is running.",
                payload={"command_id": command_id, "pid": getattr(process, "pid", None)},
            )

            out_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stdout, stdout_lines),
                kwargs={
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "stream": "stdout",
                },
                daemon=True,
            )
            err_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stderr, stderr_lines),
                kwargs={
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "stream": "stderr",
                },
                daemon=True,
            )

            out_thread.start()
            err_thread.start()

            exit_code = process.wait()

            out_thread.join(timeout=5)
            err_thread.join(timeout=5)

            self._last_stdout_lines = list(stdout_lines)
            final_json = _extract_final_json("\n".join(stdout_lines))

            self._handle_exit(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                exit_code=exit_code,
                result=final_json,
                stderr="\n".join(stderr_lines),
                resume=resume,
            )
        except Exception as exc:
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="stage_failed",
                status="failed",
                message=f"Orchestrator launch failed: {exc}",
                payload={"command_id": command_id},
            )

    def _read_stream(
        self,
        stream_handle: Any,
        captured: list[str],
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        stream: str,
    ) -> None:
        if stream_handle is None:
            return

        for raw_line in stream_handle:
            line = raw_line.rstrip("\r\n")
            captured.append(line)

            if not line:
                continue

            if stream == "stdout" and line.startswith(_EVENT_PREFIX):
                self._event_from_orchestrator(
                    job_id=job_id,
                    stage_index=stage_index,
                    command_id=command_id,
                    line=line[len(_EVENT_PREFIX):],
                )
                continue

            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type=stream,
                status="running",
                message=line,
                payload={"command_id": command_id},
            )

    def _event_from_orchestrator(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        line: str,
    ) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return

        phase = str(payload.get("phase") or "orchestrator")
        status = str(payload.get("status") or "running").lower()
        suffix = _status_suffix(status)

        if phase.startswith("model") or phase == "assistant_model":
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type=f"model_invocation_{suffix}",
                status=status,
                message=str(payload.get("message") or f"{phase} {status}"),
                payload={"command_id": command_id, "source_phase": phase},
            )
            return

        canonical_type = _canonical_event_type(phase, suffix, stage_index=stage_index)

        if phase in ("sandbox_transform", "transform") and suffix == "started":
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="approval_completed",
                status="completed",
                message="Human approval phase complete; sandbox transform has started.",
                payload={"command_id": command_id},
            )

        self._event(
            job_id=job_id,
            stage=stage_index,
            event_type=canonical_type,
            status=status,
            message=str(payload.get("message") or f"{phase} {status}"),
            payload={"command_id": command_id, **payload},
        )

    def _handle_exit(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        exit_code: int,
        result: dict[str, Any] | None,
        stderr: str,
        resume: bool = False,
    ) -> None:
        stdout_tail = _bounded("\n".join(self._last_stdout_lines) if hasattr(self, "_last_stdout_lines") else "")
        stderr_tail = _bounded(stderr)
        parse_strategy = "sentinel" if result is not None and "CONTROL_TOWER_FINAL_JSON" in ("".join(getattr(self, "_last_stdout_lines", []))) else "generic_scan"

        if exit_code != 0:
            if result is not None:
                self._emit_diagnostic_failure_events(
                    job_id=job_id,
                    stage_index=stage_index,
                    command_id=command_id,
                    result=result,
                )
            payload: dict[str, Any] = {
                "command_id": command_id,
                "exit_code": exit_code,
                "stderr": stderr_tail,
                "stdout_tail": stdout_tail,
                "final_json_found": result is not None,
                "parse_strategy": parse_strategy,
            }
            if result is None:
                payload["result_parse_status"] = "missing_final_json"
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="stage_failed",
                status="failed",
                message=f"Orchestrator exited with code {exit_code}.",
                payload=payload,
            )
            return

        if result is None:
            payload: dict[str, Any] = {
                "command_id": command_id,
                "exit_code": exit_code,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "final_json_found": False,
                "parse_strategy": parse_strategy,
            }
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="result_contract_failed",
                status="failed",
                message="Orchestrator result contract could not be parsed.",
                payload=payload,
            )
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="stage_failed",
                status="failed",
                message="Orchestrator completed without a parseable final JSON result. Inspect orchestrator stdout/stderr and orchestration_summary.json. The subprocess exited but Control Tower could not parse its final result contract.",
                payload={
                    "command_id": command_id,
                    "exit_code": exit_code,
                    "stderr": stderr_tail,
                    "stdout_tail": stdout_tail,
                    "final_json_found": False,
                    "parse_strategy": parse_strategy,
                    "result_contract_failed": True,
                },
            )
            return

        result = dict(result)
        sandbox_path = _result_sandbox_path(result)

        if sandbox_path:
            result["sandbox_path"] = sandbox_path

        self._emit_artifacts(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            result=result,
        )
        self._emit_phase_outcome_events(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            result=result,
        )
        self._emit_failure_repair_events(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            result=result,
        )

        if result.get("status") == "human_approval_required":
            checksum = sha256_canonical_json(result)
            with self._unit_of_work_factory() as uow:
                card = V2ApprovalMappingService(uow.v2_approvals).create_decision_card(
                    job_id=job_id,
                    interrupt_id=str(result.get("run_id") or command_id),
                    request_checksum=checksum,
                    stage_index=stage_index,
                    summary="Human approval required before sandbox transform.",
                )

            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="approval_required",
                status="blocked",
                message="Orchestrator paused for human approval.",
                payload={"command_id": command_id, "card_id": card.card_id, "request_checksum": checksum},
            )
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="stage_blocked_for_approval",
                status="blocked",
                message="Stage is blocked until exact checksum approval.",
                payload={"command_id": command_id, "card_id": card.card_id},
            )
            return

        final_status = str(result.get("final_status", ""))
        build_status = str(result.get("build_status", ""))
        test_status = str(result.get("test_status", ""))
        transform_status = str(result.get("transform_status", ""))
        repair_status = str(result.get("repair_loop_status", ""))
        orchestration_status = str(result.get("orchestration_status", ""))

        if _is_terminal_failure_result(result):
            self._emit_diagnostic_failure_events(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                result=result,
            )
            terminal_value = (
                final_status
                or build_status
                or test_status
                or transform_status
                or repair_status
                or orchestration_status
                or "FAILED"
            )
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="stage_failed",
                status="failed",
                message=f"Stage {stage_index} real orchestrator completed with terminal failure: {terminal_value}.",
                payload={
                    "command_id": command_id,
                    "final_status": final_status,
                    "build_status": build_status,
                    "test_status": test_status,
                    "transform_status": transform_status,
                    "repair_loop_status": repair_status,
                    "orchestration_status": orchestration_status,
                },
            )
            return

        success_proof = _has_success_proof(result)
        if not success_proof[0]:
            failure = success_proof[1]
            expected_text = (
                failure["expected"]
                if failure["detected"] != "missing" and failure["expected"] not in {"present", "empty"}
                else f"{failure['field']}={failure['expected']}"
            )
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="stage_failed",
                status="failed",
                message=(
                    f"Stage {stage_index} did not produce strict success proof: "
                    f"expected {expected_text}, detected={failure['detected']}."
                ),
                payload={
                    "command_id": command_id,
                    "missing_success_proof": True,
                    "reason": failure["reason"],
                    "proof_failure_field": failure["field"],
                    "proof_expected": failure["expected"],
                    "proof_detected": failure["detected"],
                    "proof_expected_values": failure["expected_values"],
                    "proof_detected_values": failure["detected_values"],
                    "orchestration_status": orchestration_status,
                    "transform_status": transform_status,
                    "build_status": build_status,
                    "test_status": test_status,
                    "final_status": final_status,
                    "sandbox_path": sandbox_path,
                    "errors": result.get("errors", {}),
                    "blockers": result.get("blockers", {}),
                },
            )
            return

        if stage_index in (1, 2):
            with self._unit_of_work_factory() as uow:
                cards = uow.v2_approvals.list_cards_by_job(job_id)

            unapproved = [
                c
                for c in cards
                if c.stage_index == stage_index and c.status != "approved"
            ]

            if unapproved:
                card = unapproved[0]
                self._event(
                    job_id=job_id,
                    stage=stage_index,
                    event_type="stage_blocked_for_approval",
                    status="blocked",
                    message=(
                        f"Stage {stage_index} cannot progress: "
                        f"approval card {card.card_id!r} has status {card.status!r}."
                    ),
                    payload={"command_id": command_id, "card_id": card.card_id},
                )
                return

        self._event(
            job_id=job_id,
            stage=stage_index,
            event_type="proof_updated",
            status="completed",
            message="Orchestrator result parsed into deterministic evidence.",
            payload={"command_id": command_id, "final_status": final_status},
        )
        self._event(
            job_id=job_id,
            stage=stage_index,
            event_type="stage_completed",
            status="completed",
            message=f"Stage {stage_index} real orchestrator completed.",
            payload={
                "command_id": command_id,
                "sandbox_path": sandbox_path,
                "exit_code": exit_code,
            },
        )

        # Emit report completion events based on stage index
        if stage_index == 3:
            report_type = "final_report"
            report_label = "Final migration proof report"
        else:
            report_type = "stage_report"
            report_label = f"Stage {stage_index} report"

        self._event(
            job_id=job_id,
            stage=stage_index,
            event_type=f"{report_type}_started",
            status="running",
            message=f"{report_label} generation started.",
            payload={"command_id": command_id, "sandbox_path": sandbox_path},
        )
        self._event(
            job_id=job_id,
            stage=stage_index,
            event_type=f"{report_type}_completed",
            status="completed",
            message=f"{report_label} completed.",
            payload={"command_id": command_id, "final_status": final_status},
        )

        self._auto_queue_next_stage(
            job_id=job_id,
            stage_index=stage_index,
            sandbox_path=sandbox_path,
        )

    def _emit_phase_outcome_events(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        result: dict[str, Any],
    ) -> None:
        transform_status = str(result.get("transform_status", ""))
        build_status = str(result.get("build_status", ""))
        test_status = str(result.get("test_status", ""))

        if transform_status == "TRANSFORM_APPLIED_IN_SANDBOX":
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="sandbox_transform_completed",
                status="completed",
                message="Sandbox transform completed.",
                payload={"command_id": command_id, "transform_status": transform_status},
            )
        elif _is_failure_status(transform_status):
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="sandbox_transform_failed",
                status="failed",
                message=f"Sandbox transform failed: {transform_status}",
                payload={"command_id": command_id, "transform_status": transform_status},
            )

        if build_status == "BUILD_PASSED_IN_SANDBOX":
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="build_completed",
                status="completed",
                message="Sandbox build completed.",
                payload={"command_id": command_id, "build_status": build_status},
            )
        elif _is_failure_status(build_status):
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="build_failed",
                status="failed",
                message=f"Sandbox build failed: {build_status}",
                payload={"command_id": command_id, "build_status": build_status},
            )

        if test_status in _SUCCESS_TEST_STATUSES:
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="test_completed",
                status="completed",
                message=(
                    "Sandbox tests passed."
                    if test_status in {"PASS", "TEST_PASSED"}
                    else f"Sandbox tests accepted with status: {test_status}."
                ),
                payload={"command_id": command_id, "test_status": test_status},
            )
        elif _is_failure_status(test_status):
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="test_failed",
                status="failed",
                message=f"Sandbox test validation failed: {test_status}",
                payload={"command_id": command_id, "test_status": test_status},
            )

    def _emit_failure_repair_events(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        result: dict[str, Any],
    ) -> None:
        repair_status = str(result.get("repair_loop_status", ""))
        copilot_status = str(result.get("copilot_invocation_status", ""))
        fallback = result.get("repair_fallback_generated")

        if repair_status.upper() not in _NON_ACTIVE_REPAIR_STATUSES:
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="repair_started",
                status="running" if not _is_failure_status(repair_status) else "failed",
                message=f"Repair loop status: {repair_status}",
                payload={"command_id": command_id, "repair_loop_status": repair_status},
            )

        if fallback in (True, "true", "True", 1, "yes"):
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="repair_fallback_generated",
                status="completed",
                message="Fallback repair plan generated.",
                payload={"command_id": command_id},
            )

        if copilot_status == "INVALID_RESPONSE":
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="copilot_repair_invalid_response",
                status="failed",
                message="Copilot repair response was invalid.",
                payload={"command_id": command_id, "copilot_invocation_status": copilot_status},
            )

    def _emit_diagnostic_failure_events(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        result: dict[str, Any],
    ) -> None:
        build_status = str(result.get("build_status", ""))
        test_status = str(result.get("test_status", ""))
        final_status = str(result.get("final_status", ""))
        final_proof = str(result.get("final_proof_level", ""))
        transform_status = str(result.get("transform_status", ""))
        copilot_status = str(result.get("copilot_invocation_status", ""))
        fallback = result.get("repair_fallback_generated")

        build_validation = result.get("build_validation") or {}
        build_contract = {
            "matched_line": _str_or_none(build_validation.get("matched_line") or result.get("matched_line")),
            "command": _list_or_none(build_validation.get("command") or result.get("command")),
            "requested_command": _list_or_none(build_validation.get("requested_command") or result.get("requested_command")),
            "resolved_command": _list_or_none(build_validation.get("resolved_command") or result.get("resolved_command")),
            "build_tool": _str_or_none(build_validation.get("build_tool") or result.get("build_tool")),
            "module": _str_or_none(build_validation.get("module") or result.get("module")),
            "main_class": _str_or_none(build_validation.get("main_class") or result.get("main_class")),
            "unit_id": _str_or_none(build_validation.get("unit_id") or result.get("unit_id")),
            "result_kind": _str_or_none(build_validation.get("result_kind") or result.get("result_kind")),
            "message": _str_or_none(build_validation.get("message") or result.get("message")),
            "java_home": _str_or_none(build_validation.get("java_home") or result.get("java_home")),
            "detected_version": _str_or_none(build_validation.get("detected_version") or result.get("detected_version")),
            "required_minimum": _str_or_none(build_validation.get("required_minimum") or result.get("required_minimum")),
        }
        public_contract = {k: v for k, v in build_contract.items() if v is not None}

        if _is_failure_status(build_status):
            build_payload = {
                "command_id": command_id,
                "build_status": build_status,
                "test_status": test_status,
                **public_contract,
            }
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="build_failed",
                status="failed",
                message=f"Build result: {build_status}",
                payload=build_payload,
            )
            self._maybe_diagnose(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                event_type="build_failed",
                payload=build_payload,
            )

        if _is_failure_status(test_status):
            test_payload = {
                "command_id": command_id,
                "test_status": test_status,
                **public_contract,
            }
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="test_failed",
                status="failed",
                message=f"Test result: {test_status}",
                payload=test_payload,
            )
            self._maybe_diagnose(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                event_type="test_failed",
                payload=test_payload,
            )

        if _is_failure_status(final_status) or _is_failure_status(transform_status):
            transform_payload = {
                "command_id": command_id,
                "final_status": final_status,
                "transform_status": transform_status,
                "final_proof_level": final_proof,
                "build_status": build_status,
                "copilot_invocation_status": copilot_status,
                "repair_fallback_generated": bool(fallback),
                **public_contract,
            }
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="transform_failed",
                status="failed",
                message=f"Transform/build failed: {final_status or transform_status}",
                payload=transform_payload,
            )
            self._maybe_diagnose(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                event_type="transform_failed",
                payload=transform_payload,
            )

    def _maybe_diagnose(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Route failure events to the optional diagnosis callback (F02).

        Only called when a diagnosis_callback was injected at construction.
        The callback is expected to have signature:
            (job_id, stage_index, command_id, event_type, payload) -> None
        """
        if self._diagnosis_callback is not None:
            try:
                self._diagnosis_callback(
                    job_id, stage_index, command_id, event_type, payload
                )
            except Exception:
                # Diagnosis is advisory — never let a diagnosis failure
                # block the orchestrator event loop.
                pass

    def _auto_queue_next_stage(
        self,
        *,
        job_id: str,
        stage_index: int,
        sandbox_path: str,
    ) -> None:
        from migration_factory.control_tower.application.v2_stage_progression import (
            V2StageProgressionService,
        )
        from migration_factory.control_tower.application.v2_phase_gate_service import (
            CreateGateRequest,
            V2PhaseGateService,
        )
        from migration_factory.control_tower.schemas.run_configuration import (
            RunPolicy,
            StageContinuationPolicy,
        )

        next_stage = stage_index + 1
        next_command_id: str | None = None

        try:
            with self._unit_of_work_factory() as uow:
                job = uow.v2_jobs.get(job_id)
                if job is None:
                    return

                # Load stage continuation policy from run configuration
                stage_continuation_policy = StageContinuationPolicy.AUTO_ON_GREEN
                run_config = uow.run_configurations.get_for_job(job_id)
                if run_config is not None and run_config.policy_json:
                    try:
                        import json
                        policy_dict = json.loads(run_config.policy_json)
                        policy = RunPolicy(**policy_dict)
                        stage_continuation_policy = policy.stage_continuation_policy
                    except (json.JSONDecodeError, Exception):
                        pass

                service = V2StageProgressionService(
                    setup_repo=uow.v2_setups,
                    command_repo=uow.v2_commands,
                )
                queued = service.queue_next_stage(
                    job_id=job_id,
                    setup_id=job.setup_id,
                    current_stage=stage_index,
                    sandbox_path=sandbox_path,
                    stage_continuation_policy=stage_continuation_policy,
                )

                # Handle manual policy: create stage_completion_review gate
                if queued.status == "blocked":
                    import json
                    uow.v2_events.save(
                        job_id=job_id,
                        stage=stage_index,
                        event_type="stage_completion_review_required",
                        status="blocked",
                        message=(
                            f"Stage {stage_index} completed under manual policy. "
                            f"Gate review required before stage {next_stage} can start."
                        ),
                        payload={
                            "from_stage": stage_index,
                            "to_stage": next_stage,
                            "reason": queued.reason,
                        },
                    )
                    return

                uow.v2_events.save(
                    job_id=job_id,
                    stage=next_stage,
                    event_type="next_stage_queued",
                    status="queued",
                    message=f"Stage {next_stage} command manifest queued for real orchestrator execution.",
                    payload={
                        "from_stage": stage_index,
                        "to_stage": next_stage,
                        "sandbox_path": sandbox_path,
                    },
                )

                next_command_id = _queued_command_id(queued)

                if not next_command_id:
                    commands = uow.v2_commands.list_by_job(job_id)
                    stage_commands = [
                        cmd
                        for cmd in commands
                        if int(getattr(cmd, "stage_index", 0)) == next_stage
                    ]
                    if stage_commands:
                        next_command_id = str(getattr(stage_commands[-1], "command_id", ""))

        except ValueError:
            return

        if next_command_id:
            self.start(job_id=job_id, command_id=next_command_id)

    def _emit_artifacts(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        result: dict[str, Any],
    ) -> None:
        refs = result.get("artifact_refs") if isinstance(result.get("artifact_refs"), dict) else {}
        for kind, path in refs.items():
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="artifact_written",
                status="completed",
                message=f"Artifact written: {kind}",
                payload={
                    "command_id": command_id,
                    "artifact_kind": str(kind),
                    "relative_path": _safe_artifact_ref(path),
                },
            )

        sandbox_path = _result_sandbox_path(result)
        if sandbox_path:
            self._event(
                job_id=job_id,
                stage=stage_index,
                event_type="artifact_written",
                status="completed",
                message="Stage sandbox output registered.",
                payload={
                    "command_id": command_id,
                    "artifact_kind": "sandbox",
                    "relative_path": _safe_artifact_ref(sandbox_path),
                },
            )

    def _event(
        self,
        *,
        job_id: str,
        stage: int | None,
        event_type: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._event_lock:
            with self._unit_of_work_factory() as uow:
                redacted_payload = redact_public_value(payload or {})
                uow.v2_events.save(
                    job_id=job_id,
                    stage=stage,
                    event_type=event_type,
                    status=status,
                    message=_bounded(str(redact_public_value(message))),
                    payload=redacted_payload if isinstance(redacted_payload, dict) else {},
                )

        if self._notifier is not None:
            asyncio.run(self._notifier.notify())


def _normalized_argv(argv: list[str]) -> list[str]:
    if argv and argv[0] == "python":
        return [sys.executable, *argv[1:]]
    return argv


def _build_env(manifest: dict[str, Any]) -> dict[str, str]:
    env = {
        key: value
        for key in _SAFE_ENV_KEYS
        if (value := os.environ.get(key)) is not None
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])

    for key in _MANIFEST_ENV_KEYS:
        value = manifest.get(key)
        if isinstance(value, str) and value:
            env[key] = value

    for key in _COPILOT_ENV_KEYS:
        if _is_secret_env_key(key):
            continue
        value = os.environ.get(key)
        if value:
            env[key] = value

    path_prepend = manifest.get("PATH_PREPEND")
    if isinstance(path_prepend, str) and path_prepend:
        current_path = env.get("PATH", "")
        env["PATH"] = path_prepend + (os.pathsep + current_path if current_path else "")

    env["AI_MIGRATION_CONTROL_TOWER_EVENTS"] = "jsonl"
    return env


def _is_secret_env_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in _SECRET_ENV_MARKERS)


def _load_json_list(text: str) -> list[str]:
    value = json.loads(text)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Persisted argv_json must be a string array")
    return value


def _load_json_dict(text: str) -> dict[str, Any]:
    value = json.loads(text or "{}")
    if not isinstance(value, dict):
        raise ValueError("Persisted env_json must be an object")
    return value


def _load_env_manifest_for_stage(uow: Any, job_id: str, stage_index: int) -> dict[str, Any]:
    commands = uow.v2_commands.list_by_job(job_id)
    for cmd in commands:
        if int(getattr(cmd, "stage_index", -1)) == stage_index:
            try:
                return _load_json_dict(getattr(cmd, "env_json", "{}"))
            except json.JSONDecodeError:
                return {}
    return {}


def _extract_final_json(stdout: str) -> dict[str, Any] | None:
    """Extract the orchestrator result JSON from stdout.

    Strategy (in order of priority):
    1. Look for a line starting with CONTROL_TOWER_FINAL_JSON prefix.
    2. Fall back to scanning for the last JSON object that looks like an
       orchestrator result (backward-compatible).
    """
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(_FINAL_JSON_PREFIX):
            payload = line[len(_FINAL_JSON_PREFIX):]
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and _looks_like_orchestrator_result(value):
                return value

    # Fallback: generic scan over non-event lines
    lines = [line for line in stdout.splitlines() if not line.startswith(_EVENT_PREFIX)]
    text = "\n".join(lines).strip()
    if not text:
        return None

    decoder = json.JSONDecoder()
    index = 0
    last_result: dict[str, Any] | None = None

    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break

        try:
            value, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue

        if isinstance(value, dict) and _looks_like_orchestrator_result(value):
            last_result = value

        index = start + max(consumed, 1)

    return last_result


def _looks_like_orchestrator_result(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "run_id",
            "final_status",
            "approval_status",
            "transform_status",
            "build_status",
            "test_status",
            "artifact_refs",
            "sandbox_path",
            "modernized_app_path",
        )
    )


def _result_sandbox_path(result: dict[str, Any]) -> str:
    artifact_refs = result.get("artifact_refs") if isinstance(result.get("artifact_refs"), dict) else {}

    direct = _first_text(
        result.get("sandbox_path"),
        result.get("modernized_app_path"),
        result.get("output_app_path"),
        artifact_refs.get("sandbox"),
        artifact_refs.get("sandbox_path"),
        artifact_refs.get("modernized_app"),
        artifact_refs.get("modernized_app_path"),
    )
    if direct:
        return direct

    summary_ref = _first_text(
        artifact_refs.get("orchestration_summary"),
        result.get("orchestration_summary"),
    )
    if summary_ref:
        try:
            summary_path = Path(summary_ref)
            if summary_path.is_file():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                return _first_text(
                    summary.get("sandbox_path"),
                    summary.get("modernized_app_path"),
                    (summary.get("artifact_refs") or {}).get("sandbox")
                    if isinstance(summary.get("artifact_refs"), dict)
                    else "",
                )
        except Exception:
            return ""

    return ""


def _safe_artifact_ref(value: Any) -> str:
    text = str(value)
    marker = ".migration"
    if marker in text:
        return text[text.index(marker):]
    return _bounded(str(redact_public_value(text)))


def _canonical_event_type(phase: str, suffix: str, *, stage_index: int) -> str:
    mapping = {
        "transform": f"sandbox_transform_{suffix}",
        "sandbox_transform": f"sandbox_transform_{suffix}",
        "build": f"build_{suffix}",
        "test": f"test_{suffix}",
        "repair": f"repair_{suffix}",
        "copilot_repair": f"copilot_repair_{suffix}",
    }

    if phase == "final_report":
        # Only Stage 3 gets final_report events; earlier stages get stage_report events
        if stage_index == 3:
            return f"final_report_{suffix}"
        return f"stage_report_{suffix}"

    if phase in mapping:
        return mapping[phase]

    return f"{phase}_{suffix}"


def _status_suffix(status: str) -> str:
    normalized = str(status or "").lower()
    if normalized == "running":
        return "started"
    if normalized == "completed":
        return "completed"
    return normalized or "running"


def _is_terminal_failure_result(result: dict[str, Any]) -> bool:
    statuses = [
        str(result.get("final_status", "")),
        str(result.get("build_status", "")),
        str(result.get("test_status", "")),
        str(result.get("transform_status", "")),
        str(result.get("repair_loop_status", "")),
    ]
    if any(_is_failure_status(value) for value in statuses):
        return True
    if result.get("errors") or result.get("blockers"):
        return True
    return False


def _has_success_proof(result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    expected_values = {
        "orchestration_status": _SUCCESS_ORCHESTRATION_STATUS,
        "final_status": _SUCCESS_FINAL_STATUS,
        "transform_status": _SUCCESS_TRANSFORM_STATUS,
        "build_status": _SUCCESS_BUILD_STATUS,
        "test_status": sorted(_SUCCESS_TEST_STATUSES),
    }
    detected_values = {
        "orchestration_status": _normalize_detected(result.get("orchestration_status")),
        "final_status": _normalize_detected(result.get("final_status")),
        "transform_status": _normalize_detected(result.get("transform_status")),
        "build_status": _normalize_detected(result.get("build_status")),
        "test_status": _normalize_detected(result.get("test_status")),
        "sandbox_path": _result_sandbox_path(result),
    }

    if not detected_values["sandbox_path"]:
        return False, _proof_failure_details(
            field="sandbox_path",
            expected="present",
            detected="missing",
            reason="missing sandbox_path",
            expected_values=expected_values,
            detected_values=detected_values,
        )
    if result.get("errors"):
        return False, _proof_failure_details(
            field="errors",
            expected="empty",
            detected=_normalize_detected(result.get("errors")),
            reason="errors present",
            expected_values=expected_values,
            detected_values=detected_values,
        )
    if result.get("blockers"):
        return False, _proof_failure_details(
            field="blockers",
            expected="empty",
            detected=_normalize_detected(result.get("blockers")),
            reason="blockers present",
            expected_values=expected_values,
            detected_values=detected_values,
        )

    checks = (
        ("orchestration_status", {_SUCCESS_ORCHESTRATION_STATUS}, "PASS"),
        ("final_status", {_SUCCESS_FINAL_STATUS}, _SUCCESS_FINAL_STATUS),
        ("transform_status", {_SUCCESS_TRANSFORM_STATUS}, _SUCCESS_TRANSFORM_STATUS),
        ("build_status", {_SUCCESS_BUILD_STATUS}, _SUCCESS_BUILD_STATUS),
        ("test_status", _SUCCESS_TEST_STATUSES, "{" + ", ".join(sorted(_SUCCESS_TEST_STATUSES)) + "}"),
    )
    for field, accepted, expected_text in checks:
        detected = detected_values[field]
        if not detected:
            return False, _proof_failure_details(
                field=field,
                expected=expected_text,
                detected="missing",
                reason=f"missing {field}",
                expected_values=expected_values,
                detected_values=detected_values,
            )
        if detected not in accepted:
            return False, _proof_failure_details(
                field=field,
                expected=expected_text,
                detected=detected,
                reason=f"expected {field}={expected_text}, detected={detected}",
                expected_values=expected_values,
                detected_values=detected_values,
            )
    return True, {
        "field": "",
        "expected": "",
        "detected": "",
        "reason": "",
        "expected_values": expected_values,
        "detected_values": detected_values,
    }


def _is_failure_status(value: Any) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return False
    if text in _TERMINAL_FAILURES:
        return True
    if "FAILED" in text or text.endswith("_FAIL") or text == "FAIL":
        return True
    if "FALLBACK_REPAIR_PLAN" in text:
        return True
    return False


def _normalize_detected(value: Any) -> str:
    return str(value or "").strip()


def _proof_failure_details(
    *,
    field: str,
    expected: str,
    detected: Any,
    reason: str,
    expected_values: dict[str, Any],
    detected_values: dict[str, Any],
) -> dict[str, Any]:
    return {
        "field": field,
        "expected": expected,
        "detected": detected,
        "reason": reason,
        "expected_values": expected_values,
        "detected_values": detected_values,
    }


def _queued_command_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("command_id") or "")
    return str(getattr(value, "command_id", "") or "")


def _bounded(value: str) -> str:
    redacted = redact_model_summary(value)
    if len(redacted) <= _MAX_TEXT:
        return redacted
    return redacted[:_MAX_TEXT] + "...[truncated]"


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _list_or_none(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
        return items if items else None
    return None
