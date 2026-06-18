from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ApprovedRepairPatchCandidateResult:
    proposal_id: str
    patch_candidate: dict[str, Any]
    artifact_path: str
    applied: bool = False
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "patch_candidate": self.patch_candidate,
            "artifact_path": self.artifact_path,
            "applied": self.applied,
            "read_only": self.read_only,
        }


class V2ApprovedRepairPatchCandidateService:
    def materialize(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
    ) -> ApprovedRepairPatchCandidateResult:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        proposal_payload = self._read_json(proposal_dir / "repair_proposal.json")
        approval_state = self._read_json(proposal_dir / "approval_state.json")
        execution_plan = self._read_json(proposal_dir / "repair_execution_plan.json")
        current_checksum = self.compute_proposal_checksum(proposal_payload)
        self._validate_preconditions(
            proposal_id=proposal_id,
            approval_state=approval_state,
            execution_plan=execution_plan,
            current_checksum=current_checksum,
        )
        candidate = self._build_candidate(
            proposal_id=proposal_id,
            proposal_payload=proposal_payload,
            approval_state=approval_state,
            execution_plan=execution_plan,
            trace_root=trace_root,
            proposal_dir=proposal_dir,
        )
        candidate_path = proposal_dir / "repair_patch_candidate.json"
        candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True), encoding="utf-8")
        return ApprovedRepairPatchCandidateResult(
            proposal_id=proposal_id,
            patch_candidate=candidate,
            artifact_path=self._relative_path(candidate_path, trace_root),
        )

    def get_candidate(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
    ) -> dict[str, Any] | None:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        candidate_path = proposal_dir / "repair_patch_candidate.json"
        if not candidate_path.is_file():
            return None
        return self._read_json(candidate_path)

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
        current_checksum: str,
    ) -> None:
        state = str(approval_state.get("state") or "").strip()
        if state != "approved":
            if state == "pending_approval":
                raise ValueError(f"Repair proposal {proposal_id!r} is still pending approval.")
            if state == "rejected":
                raise ValueError(f"Repair proposal {proposal_id!r} was rejected and cannot produce a patch candidate.")
            raise ValueError(f"Repair proposal {proposal_id!r} is not approved for patch-candidate materialization.")
        stored_checksum = str(approval_state.get("checksum") or "").strip()
        if not stored_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval state is missing checksum.")
        if stored_checksum != current_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval checksum no longer matches current proposal payload.")
        if bool(execution_plan.get("human_approved")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} execution plan is not marked human approved.")
        if bool(execution_plan.get("applied")) is not False:
            raise ValueError(f"Repair proposal {proposal_id!r} execution plan is not eligible because it is already applied.")

    def _build_candidate(
        self,
        *,
        proposal_id: str,
        proposal_payload: dict[str, Any],
        approval_state: dict[str, Any],
        execution_plan: dict[str, Any],
        trace_root: Path,
        proposal_dir: Path,
    ) -> dict[str, Any]:
        failure_type = str(execution_plan.get("failure_type") or proposal_payload.get("failure_type") or "")
        patch_operations = self._patch_operations(
            failure_type=failure_type,
            planned_operations=list(execution_plan.get("planned_operations") or []),
        )
        candidate = {
            "proposal_id": proposal_id,
            "run_id": str(proposal_payload.get("run_id") or execution_plan.get("run_id") or ""),
            "approval_checksum": str(approval_state.get("checksum") or ""),
            "execution_plan_ref": self._relative_path(proposal_dir / "repair_execution_plan.json", trace_root),
            "failure_type": failure_type,
            "root_cause": str(execution_plan.get("root_cause") or proposal_payload.get("root_cause") or ""),
            "affected_paths": list(execution_plan.get("affected_paths") or []),
            "planned_operations": list(execution_plan.get("planned_operations") or []),
            "patch_strategy": "bounded_structured_operations" if patch_operations else "conservative_no_auto_patch",
            "patch_operations": patch_operations,
            "validation_commands": list(execution_plan.get("validation_commands") or []),
            "rollback_plan": str(execution_plan.get("rollback_plan") or ""),
            "requires_sandbox_apply": True,
            "requires_validation": True,
            "human_approved": True,
            "applied": False,
            "read_only": True,
            "no_source_mutation": True,
            "created_at": utc_now_text(),
        }
        if not patch_operations:
            candidate["requires_human_review"] = True
            candidate["unsupported_reason"] = (
                "Automatic bounded patch-candidate materialization is unsupported for this failure class; "
                "no patch operations were created."
            )
        return candidate

    def _patch_operations(self, *, failure_type: str, planned_operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if failure_type != "invalid_maven_wildcard_version":
            return []
        allowed: list[dict[str, Any]] = []
        for operation in planned_operations:
            if (
                str(operation.get("kind") or "") == "update_maven_property"
                and str(operation.get("path") or "") == "pom.xml"
                and str(operation.get("property") or "") in {"javax.persistence.version", "javax.servlet.version"}
            ):
                allowed.append(
                    {
                        "target_file": "pom.xml",
                        "operation": "update_maven_property",
                        "property": str(operation.get("property") or ""),
                        "from": str(operation.get("from") or ""),
                        "to": str(operation.get("to") or ""),
                    }
                )
        return allowed

    def _proposal_dir(self, *, trace_root: Path, proposal_id: str) -> Path:
        if not _ID_RE.match(proposal_id):
            raise ValueError(f"Invalid repair proposal id {proposal_id!r}")
        proposal_dir = (trace_root / "ai_supervision" / "repair_proposals" / proposal_id).resolve()
        proposal_dir.relative_to((trace_root / "ai_supervision" / "repair_proposals").resolve())
        return proposal_dir

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
