from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ApprovedRepairExecutionPlanResult:
    proposal_id: str
    execution_plan: dict[str, Any]
    artifact_path: str
    applied: bool = False
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "execution_plan": self.execution_plan,
            "artifact_path": self.artifact_path,
            "applied": self.applied,
            "read_only": self.read_only,
        }


class V2ApprovedRepairExecutionPlanService:
    def materialize(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
    ) -> ApprovedRepairExecutionPlanResult:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        proposal_payload = self._read_json(proposal_dir / "repair_proposal.json")
        approval_state = self._read_json(proposal_dir / "approval_state.json")
        current_checksum = self.compute_proposal_checksum(proposal_payload)
        self._validate_approval_state(
            proposal_id=proposal_id,
            approval_state=approval_state,
            current_checksum=current_checksum,
        )
        plan = self._build_plan(
            proposal_id=proposal_id,
            proposal_payload=proposal_payload,
            approval_state=approval_state,
            trace_root=trace_root,
            proposal_dir=proposal_dir,
        )
        plan_path = proposal_dir / "repair_execution_plan.json"
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
        return ApprovedRepairExecutionPlanResult(
            proposal_id=proposal_id,
            execution_plan=plan,
            artifact_path=self._relative_path(plan_path, trace_root),
        )

    def get_plan(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
    ) -> dict[str, Any] | None:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        plan_path = proposal_dir / "repair_execution_plan.json"
        if not plan_path.is_file():
            return None
        return self._read_json(plan_path)

    def compute_proposal_checksum(self, proposal_payload: dict[str, Any]) -> str:
        canonical_payload = {
            key: value
            for key, value in proposal_payload.items()
            if key not in {"proposal_checksum", "approval_state"}
        }
        return sha256_canonical_json(canonical_payload)

    def _validate_approval_state(
        self,
        *,
        proposal_id: str,
        approval_state: dict[str, Any],
        current_checksum: str,
    ) -> None:
        state = str(approval_state.get("state") or "").strip()
        if state != "approved":
            if state == "pending_approval":
                raise ValueError(f"Repair proposal {proposal_id!r} is still pending approval.")
            if state == "rejected":
                raise ValueError(f"Repair proposal {proposal_id!r} was rejected and cannot be materialized.")
            raise ValueError(f"Repair proposal {proposal_id!r} is not approved for execution-plan materialization.")
        stored_checksum = str(approval_state.get("checksum") or "").strip()
        if not stored_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval state is missing checksum.")
        if stored_checksum != current_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval checksum no longer matches current proposal payload.")

    def _build_plan(
        self,
        *,
        proposal_id: str,
        proposal_payload: dict[str, Any],
        approval_state: dict[str, Any],
        trace_root: Path,
        proposal_dir: Path,
    ) -> dict[str, Any]:
        proposal = dict(proposal_payload.get("model1_result") or {})
        failure_type = str(proposal_payload.get("failure_type") or proposal.get("failure_type") or "")
        planned_operations = self._planned_operations(proposal=proposal, failure_type=failure_type)
        artifact_refs = self._artifact_refs_for_dir(trace_root=trace_root, proposal_dir=proposal_dir)
        plan = {
            "proposal_id": proposal_id,
            "run_id": str(proposal_payload.get("run_id") or ""),
            "approval_checksum": str(approval_state.get("checksum") or ""),
            "failure_type": failure_type,
            "root_cause": str(proposal_payload.get("root_cause") or proposal.get("root_cause") or ""),
            "affected_paths": list(proposal_payload.get("affected_paths") or proposal.get("affected_paths") or []),
            "planned_operations": planned_operations,
            "validation_commands": list(proposal_payload.get("validation_commands") or proposal.get("validation_commands") or []),
            "rollback_plan": str(proposal_payload.get("rollback_plan") or proposal.get("rollback_plan") or ""),
            "source_artifact_refs": artifact_refs,
            "requires_sandbox_apply": True,
            "requires_validation": True,
            "human_approved": True,
            "applied": False,
            "read_only": True,
            "created_at": utc_now_text(),
        }
        if not planned_operations:
            plan["requires_human_review"] = True
            plan["unsupported_reason"] = (
                "Automatic execution-plan materialization is unsupported for this failure class; "
                "no file patch operations were created."
            )
        return plan

    def _planned_operations(self, *, proposal: dict[str, Any], failure_type: str) -> list[dict[str, Any]]:
        if failure_type != "invalid_maven_wildcard_version":
            return []
        joined = " ".join(str(item) for item in proposal.get("proposed_file_changes", []))
        operations: list[dict[str, Any]] = []
        if "javax.persistence.version" in joined and "3.1.0" in joined:
            operations.append(
                {
                    "kind": "update_maven_property",
                    "path": "pom.xml",
                    "property": "javax.persistence.version",
                    "from": "3.0.x",
                    "to": "3.1.0",
                }
            )
        if "javax.servlet.version" in joined and "6.0.0" in joined:
            operations.append(
                {
                    "kind": "update_maven_property",
                    "path": "pom.xml",
                    "property": "javax.servlet.version",
                    "from": "5.0.x",
                    "to": "6.0.0",
                }
            )
        return operations

    def _proposal_dir(self, *, trace_root: Path, proposal_id: str) -> Path:
        if not _ID_RE.match(proposal_id):
            raise ValueError(f"Invalid repair proposal id {proposal_id!r}")
        proposal_dir = (trace_root / "ai_supervision" / "repair_proposals" / proposal_id).resolve()
        proposal_dir.relative_to((trace_root / "ai_supervision" / "repair_proposals").resolve())
        return proposal_dir

    def _artifact_refs_for_dir(self, *, trace_root: Path, proposal_dir: Path) -> dict[str, str]:
        refs: dict[str, str] = {}
        for name in ("repair_proposal.json", "repair_verification.json", "repair_proposal.md", "approval_state.json"):
            path = proposal_dir / name
            if path.is_file():
                refs[name.replace(".", "_")] = self._relative_path(path, trace_root)
        return refs

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
