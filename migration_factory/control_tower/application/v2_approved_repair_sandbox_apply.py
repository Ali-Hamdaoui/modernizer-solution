from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_PATCHES = {
    "javax.persistence.version": ("3.0.x", "3.1.0"),
    "javax.servlet.version": ("5.0.x", "6.0.0"),
}


@dataclass(frozen=True)
class ApprovedRepairSandboxApplyResult:
    proposal_id: str
    apply_result: dict[str, Any]
    artifact_path: str
    sandbox_only: bool = True
    validation_started: bool = False
    source_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "apply_result": self.apply_result,
            "artifact_path": self.artifact_path,
            "sandbox_only": self.sandbox_only,
            "validation_started": self.validation_started,
            "source_mutated": self.source_mutated,
        }


class V2ApprovedRepairSandboxApplyService:
    def apply(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
    ) -> ApprovedRepairSandboxApplyResult:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        proposal_payload = self._read_json(proposal_dir / "repair_proposal.json")
        approval_state = self._read_json(proposal_dir / "approval_state.json")
        execution_plan = self._read_json(proposal_dir / "repair_execution_plan.json")
        candidate = self._read_json(proposal_dir / "repair_patch_candidate.json")
        current_checksum = self.compute_proposal_checksum(proposal_payload)
        sandbox_root = self._sandbox_root(trace_root)
        pom_path = self._sandbox_pom_path(sandbox_root)
        apply_result_path = proposal_dir / "sandbox_apply_result.json"
        self._validate_preconditions(
            proposal_id=proposal_id,
            approval_state=approval_state,
            execution_plan=execution_plan,
            candidate=candidate,
            current_checksum=current_checksum,
            apply_result_path=apply_result_path,
            trace_root=trace_root,
            sandbox_root=sandbox_root,
            pom_path=pom_path,
        )
        backup_path, operations_applied = self._apply_operations(
            proposal_dir=proposal_dir,
            pom_path=pom_path,
            patch_operations=list(candidate.get("patch_operations") or []),
        )
        result = {
            "proposal_id": proposal_id,
            "run_id": str(proposal_payload.get("run_id") or candidate.get("run_id") or ""),
            "target_workspace": self._relative_path(sandbox_root, trace_root),
            "modified_files": ["workspaces/sandbox/pom.xml"],
            "operations_applied": operations_applied,
            "backup_refs": [self._relative_path(backup_path, trace_root)],
            "applied": True,
            "validation_required": True,
            "validation_started": False,
            "source_mutated": False,
            "sandbox_only": True,
            "created_at": utc_now_text(),
        }
        apply_result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return ApprovedRepairSandboxApplyResult(
            proposal_id=proposal_id,
            apply_result=result,
            artifact_path=self._relative_path(apply_result_path, trace_root),
        )

    def get_apply_result(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
    ) -> dict[str, Any] | None:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        result_path = proposal_dir / "sandbox_apply_result.json"
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
        current_checksum: str,
        apply_result_path: Path,
        trace_root: Path,
        sandbox_root: Path,
        pom_path: Path,
    ) -> None:
        state = str(approval_state.get("state") or "").strip()
        if state != "approved":
            if state == "pending_approval":
                raise ValueError(f"Repair proposal {proposal_id!r} is still pending approval.")
            if state == "rejected":
                raise ValueError(f"Repair proposal {proposal_id!r} was rejected and cannot be applied to sandbox.")
            raise ValueError(f"Repair proposal {proposal_id!r} is not approved for sandbox apply.")
        stored_checksum = str(approval_state.get("checksum") or "").strip()
        if not stored_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval state is missing checksum.")
        if stored_checksum != current_checksum:
            raise ValueError(f"Repair proposal {proposal_id!r} approval checksum no longer matches current proposal payload.")
        if bool(execution_plan.get("human_approved")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} execution plan is not marked human approved.")
        if bool(execution_plan.get("applied")) is not False:
            raise ValueError(f"Repair proposal {proposal_id!r} execution plan is not eligible because it is already applied.")
        if bool(candidate.get("human_approved")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate is not marked human approved.")
        if bool(candidate.get("applied")) is not False:
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate is already marked applied.")
        if bool(candidate.get("no_source_mutation")) is not True:
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate does not guarantee source immutability.")
        if apply_result_path.exists():
            raise ValueError(f"Repair proposal {proposal_id!r} already has a sandbox apply result; refusing double apply.")
        patch_operations = list(candidate.get("patch_operations") or [])
        if not patch_operations:
            raise ValueError(f"Repair proposal {proposal_id!r} has no bounded patch operations to apply.")
        if not pom_path.is_file():
            raise ValueError(f"Repair proposal {proposal_id!r} sandbox pom.xml is missing.")
        sandbox_root.resolve().relative_to(trace_root.resolve())
        pom_path.resolve().relative_to(sandbox_root.resolve())
        for operation in patch_operations:
            self._validate_patch_operation(proposal_id=proposal_id, operation=operation)

    def _apply_operations(
        self,
        *,
        proposal_dir: Path,
        pom_path: Path,
        patch_operations: list[dict[str, Any]],
    ) -> tuple[Path, list[dict[str, Any]]]:
        backup_dir = proposal_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / "pom.xml.before-repair"
        shutil.copy2(pom_path, backup_path)

        tree = ET.parse(pom_path)
        root = tree.getroot()
        namespace = self._namespace(root.tag)
        if namespace:
            ET.register_namespace("", namespace)
        properties = root.find(self._tag(namespace, "properties"))
        if properties is None:
            raise ValueError("Sandbox pom.xml is missing <properties>; cannot apply bounded Maven property updates.")

        operations_applied: list[dict[str, Any]] = []
        for operation in patch_operations:
            property_name = str(operation.get("property") or "")
            property_node = properties.find(self._tag(namespace, property_name))
            if property_node is None or property_node.text is None:
                raise ValueError(f"Sandbox pom.xml is missing property {property_name!r}.")
            current_value = property_node.text.strip()
            expected_old = str(operation.get("from") or "")
            new_value = str(operation.get("to") or "")
            if current_value != expected_old:
                raise ValueError(
                    f"Sandbox pom.xml property {property_name!r} has value {current_value!r}; expected {expected_old!r}."
                )
            property_node.text = new_value
            operations_applied.append(
                {
                    "target_file": "pom.xml",
                    "operation": "update_maven_property",
                    "property": property_name,
                    "from": expected_old,
                    "to": new_value,
                }
            )

        tree.write(pom_path, encoding="utf-8", xml_declaration=True)
        return backup_path, operations_applied

    def _validate_patch_operation(self, *, proposal_id: str, operation: dict[str, Any]) -> None:
        if str(operation.get("target_file") or "") != "pom.xml":
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate includes unsupported target file.")
        if str(operation.get("operation") or "") != "update_maven_property":
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate includes unsupported patch operation.")
        property_name = str(operation.get("property") or "")
        expected = _ALLOWED_PATCHES.get(property_name)
        if expected is None:
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate includes unsupported Maven property.")
        if (str(operation.get("from") or ""), str(operation.get("to") or "")) != expected:
            raise ValueError(f"Repair proposal {proposal_id!r} patch candidate includes unsupported Maven property transition.")

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
    def _namespace(tag: str) -> str:
        if tag.startswith("{") and "}" in tag:
            return tag[1 : tag.index("}")]
        return ""

    @staticmethod
    def _tag(namespace: str, name: str) -> str:
        return f"{{{namespace}}}{name}" if namespace else name

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
