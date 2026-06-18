from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text
from migration_factory.repair_loop.validation_runner import (
    ValidationResult,
    run_validation_after_patch,
)


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ApprovedRepairSandboxValidationOutcome:
    proposal_id: str
    validation_result: dict[str, Any]
    artifact_path: str
    sandbox_only: bool = True
    source_mutated: bool = False
    stage_resumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "validation_result": self.validation_result,
            "artifact_path": self.artifact_path,
            "sandbox_only": self.sandbox_only,
            "source_mutated": self.source_mutated,
            "stage_resumed": self.stage_resumed,
        }


class V2ApprovedRepairSandboxValidationService:
    def validate(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
        validation_runner: Callable[..., ValidationResult] = run_validation_after_patch,
        backup_restorer: Callable[[Path, Path], None] = shutil.copy2,
    ) -> ApprovedRepairSandboxValidationOutcome:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        proposal_payload = self._read_json(proposal_dir / "repair_proposal.json")
        approval_state = self._read_json(proposal_dir / "approval_state.json")
        execution_plan = self._read_json(proposal_dir / "repair_execution_plan.json")
        candidate = self._read_json(proposal_dir / "repair_patch_candidate.json")
        apply_result_path = proposal_dir / "sandbox_apply_result.json"
        if not apply_result_path.is_file():
            raise ValueError(f"Repair proposal {proposal_id!r} must be applied to sandbox before validation.")
        apply_result = self._read_json(apply_result_path)
        current_checksum = self.compute_proposal_checksum(proposal_payload)
        sandbox_root = self._sandbox_root(trace_root)
        pom_path = self._sandbox_pom_path(sandbox_root)
        backup_path = proposal_dir / "backups" / "pom.xml.before-repair"
        validation_result_path = proposal_dir / "sandbox_validation_result.json"
        self._validate_preconditions(
            proposal_id=proposal_id,
            approval_state=approval_state,
            execution_plan=execution_plan,
            candidate=candidate,
            apply_result=apply_result,
            current_checksum=current_checksum,
            trace_root=trace_root,
            sandbox_root=sandbox_root,
            pom_path=pom_path,
            backup_path=backup_path,
            validation_result_path=validation_result_path,
        )

        started_at = utc_now_text()
        validation = validation_runner(
            run_id=str(proposal_payload.get("run_id") or apply_result.get("run_id") or proposal_id),
            run_dir=trace_root,
            sandbox_path=sandbox_root,
            attempt=1,
        )
        finished_at = utc_now_text()
        commands_run = [list(command) for command in list(getattr(validation, "validation_commands", []) or [])]
        exit_code = 0 if bool(getattr(validation, "passed", False)) else 1
        stdout_excerpt = self._excerpt(getattr(validation, "warnings", []) or [])
        stderr_excerpt = self._excerpt(getattr(validation, "errors", []) or [])
        rollback_performed = False
        rollback_reason = ""
        status = "passed"
        rollback_error = ""

        if not bool(getattr(validation, "passed", False)):
            rollback_reason = "; ".join(str(item) for item in (getattr(validation, "errors", []) or [])) or "sandbox validation failed"
            try:
                backup_restorer(backup_path, pom_path)
                rollback_performed = True
                status = "rolled_back"
            except Exception as exc:  # pragma: no cover - exercised in focused test via injected stub
                status = "failed"
                rollback_error = str(exc)

        result = {
            "proposal_id": proposal_id,
            "run_id": str(proposal_payload.get("run_id") or apply_result.get("run_id") or ""),
            "target_workspace": self._relative_path(sandbox_root, trace_root),
            "commands_run": commands_run,
            "exit_code": exit_code,
            "status": status,
            "stdout_excerpt": stdout_excerpt,
            "stderr_excerpt": stderr_excerpt,
            "validation_started_at": started_at,
            "validation_finished_at": finished_at,
            "rollback_performed": rollback_performed,
            "rollback_reason": rollback_reason,
            "source_mutated": False,
            "sandbox_only": True,
        }
        if rollback_error:
            result["rollback_error"] = rollback_error
        validation_result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return ApprovedRepairSandboxValidationOutcome(
            proposal_id=proposal_id,
            validation_result=result,
            artifact_path=self._relative_path(validation_result_path, trace_root),
        )

    def get_validation_result(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
    ) -> dict[str, Any] | None:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        result_path = proposal_dir / "sandbox_validation_result.json"
        if not result_path.is_file():
            return None
        return self._read_json(result_path)

    def compute_proposal_checksum(self, proposal_payload: dict[str, Any]) -> str:
        canonical_payload = {
            key: value
            for key, value in proposal_payload.items()
            if key not in {"proposal_checksum", "approval_state"}
        }
        return sha256_canonical_json(canonical_payload)

    def _validate_preconditions(
        self,
        *,
        proposal_id: str,
        approval_state: dict[str, Any],
        execution_plan: dict[str, Any],
        candidate: dict[str, Any],
        apply_result: dict[str, Any],
        current_checksum: str,
        trace_root: Path,
        sandbox_root: Path,
        pom_path: Path,
        backup_path: Path,
        validation_result_path: Path,
    ) -> None:
        state = str(approval_state.get("state") or "").strip()
        if state != "approved":
            if state == "pending_approval":
                raise ValueError(f"Repair proposal {proposal_id!r} is still pending approval.")
            if state == "rejected":
                raise ValueError(f"Repair proposal {proposal_id!r} was rejected and cannot be validated in sandbox.")
            raise ValueError(f"Repair proposal {proposal_id!r} is not approved for sandbox validation.")
        stored_checksum = str(approval_state.get("checksum") or "").strip()
        if not stored_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval state is missing checksum.")
        if stored_checksum != current_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval checksum no longer matches current proposal payload.")
        if bool(execution_plan.get("human_approved")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} execution plan is not marked human approved.")
        if bool(candidate.get("human_approved")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate is not marked human approved.")
        if bool(apply_result.get("applied")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} must be applied to sandbox before validation.")
        if bool(apply_result.get("sandbox_only")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} apply result is not sandbox-only.")
        if bool(apply_result.get("source_mutated")) is not False:
            raise ValueError(f"Repair proposal {proposal_id!r} apply result indicates source mutation.")
        if not backup_path.is_file():
            raise ValueError(f"Repair proposal {proposal_id!r} backup pom.xml is missing before validation.")
        if not pom_path.is_file():
            raise ValueError(f"Repair proposal {proposal_id!r} sandbox pom.xml is missing.")
        sandbox_root.resolve().relative_to(trace_root.resolve())
        pom_path.resolve().relative_to(sandbox_root.resolve())
        if validation_result_path.exists():
            raise ValueError(f"Repair proposal {proposal_id!r} already has a sandbox validation result.")

    def _proposal_dir(self, *, trace_root: Path, proposal_id: str) -> Path:
        if not _ID_RE.match(proposal_id):
            raise ValueError(f"Invalid repair proposal id {proposal_id!r}")
        proposal_dir = (trace_root / "ai_supervision" / "repair_proposals" / proposal_id).resolve()
        proposal_dir.relative_to((trace_root / "ai_supervision" / "repair_proposals").resolve())
        return proposal_dir

    def _sandbox_root(self, trace_root: Path) -> Path:
        sandbox_root = (trace_root / "workspaces" / "sandbox").resolve()
        sandbox_root.relative_to(trace_root.resolve())
        return sandbox_root

    def _sandbox_pom_path(self, sandbox_root: Path) -> Path:
        pom_path = (sandbox_root / "pom.xml").resolve()
        pom_path.relative_to(sandbox_root.resolve())
        return pom_path

    @staticmethod
    def _excerpt(values: list[str], *, limit: int = 800) -> str:
        text = "\n".join(str(value) for value in values if str(value).strip())
        return text[:limit]

    @staticmethod
    def _relative_path(path: Path, trace_root: Path) -> str:
        try:
            return str(path.resolve().relative_to(trace_root.resolve())).replace("\\", "/")
        except ValueError:
            return path.name

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object at {path}")
        return payload
