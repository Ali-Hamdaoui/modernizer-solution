from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelResult
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    sha256_unified_diff_text,
)
from migration_factory.orchestrator.repair_review_chain import (
    RepairReviewChainProductionError,
    canonical_primary_repair_output,
    canonical_reviewer_repair_output,
    _coerce_primary_repair_output,
    _coerce_reviewer_repair_output,
    _compute_primary_repair_checksum,
    _compute_reviewer_repair_checksum,
    produce_repair_review_chain,
)
from migration_factory.repair_loop.failure_evidence import FailureSource, build_failure_evidence
from migration_factory.repair_loop.repair_context import build_repair_context_pack


VALID_DIFF = "--- a/src/App.java\n+++ b/src/App.java\n@@ -1 +1 @@\n-old\n+new\n"


def _primary(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "root_cause": "old API",
        "fix_strategy": "replace old call",
        "changed_files": ["src/App.java"],
        "proposed_diff": VALID_DIFF,
        "risk": "LOW",
        "confidence": 0.75,
        "rationale": "scoped source update",
    }
    data.update(overrides)
    return data


def _reviewer(*, context: str = "ctx", primary: str = "primary", diff: str = "diff", decision: str = "accept", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "decision": decision,
        "notes": ["bound to exact diff"],
        "risks": [],
        "confidence": 0.8,
        "policy_concerns": [],
        "reviewed_context_checksum": context,
        "reviewed_primary_output_checksum": primary,
        "reviewed_diff_checksum": diff,
    }
    data.update(overrides)
    return data


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"root_cause": "x"}, "Missing required field"),
        ({**_primary(), "extra": "nope"}, "Unexpected property"),
        ([], "root must be a JSON object"),
        ("```json\n{}\n```", "valid JSON"),
        ("prefix " + _json(_primary()), "valid JSON"),
        ({**_primary(), "risk": "CRITICAL"}, "not one of"),
        ({**_primary(), "confidence": -0.1}, "less than minimum"),
        ({**_primary(), "confidence": 1.1}, "greater than maximum"),
        ({**_primary(), "confidence": True}, "Expected number"),
        ({**_primary(), "changed_files": "src/App.java"}, "Expected array"),
        ({**_primary(), "changed_files": ["C:/repo/src/App.java"]}, "absolute path"),
        ({**_primary(), "changed_files": ["C:src\\App.java"]}, "drive-qualified path"),
        ({**_primary(), "changed_files": ["../src/App.java"]}, "path traversal"),
        ({**_primary(), "proposed_diff": "not a diff"}, "unified diff"),
        ({**_primary(), "proposed_diff": ""}, "no_fix_reason"),
        ({**_primary(), "machine_readable_metadata": {"env": {"JAVA_HOME": "x"}}}, "forbidden key"),
    ],
)
def test_primary_contract_rejects_invalid_outputs(payload: Any, error: str) -> None:
    content = payload if isinstance(payload, str) else _json(payload)
    with pytest.raises(RepairReviewChainProductionError, match=error):
        _coerce_primary_repair_output(content)


def test_primary_contract_accepts_empty_diff_only_with_no_fix_reason() -> None:
    parsed = _coerce_primary_repair_output(_json(_primary(proposed_diff="", no_fix_reason="No safe source repair.")))
    assert parsed["proposed_diff"] == ""


def test_primary_contract_preserves_unicode_and_trailing_newline() -> None:
    diff = "--- a/src/App.java\n+++ b/src/App.java\n@@ -1 +1 @@\n-old\n+new café\n"
    parsed = _coerce_primary_repair_output(_json(_primary(proposed_diff=diff, rationale="unicode café")))
    assert parsed["proposed_diff"] == diff
    assert parsed["proposed_diff"].endswith("\n")
    assert "café" in parsed["proposed_diff"]


@pytest.mark.parametrize(
    "payload,error",
    [
        (_reviewer(context="", primary="primary", diff="diff"), "context checksum mismatch"),
        (_reviewer(context="ctx", primary="", diff="diff"), "primary checksum mismatch"),
        (_reviewer(context="ctx", primary="primary", diff=""), "diff checksum mismatch"),
        ({k: v for k, v in _reviewer().items() if k != "reviewed_context_checksum"}, "Missing required field"),
        ({k: v for k, v in _reviewer().items() if k != "reviewed_primary_output_checksum"}, "Missing required field"),
        ({k: v for k, v in _reviewer().items() if k != "reviewed_diff_checksum"}, "Missing required field"),
        ({**_reviewer(), "extra": "nope"}, "Unexpected property"),
        ({**_reviewer(), "decision": "approve"}, "not one of"),
        ("not json", "valid JSON"),
        ("```json\n{}\n```", "valid JSON"),
        ({**_reviewer(), "confidence": True}, "Expected number"),
    ],
)
def test_reviewer_contract_rejects_invalid_outputs(payload: Any, error: str) -> None:
    content = payload if isinstance(payload, str) else _json(payload)
    with pytest.raises(RepairReviewChainProductionError, match=error):
        _coerce_reviewer_repair_output(content, "det", "ctx", "primary", "diff")


def test_reviewer_contract_accepts_explicit_checksum_bindings() -> None:
    parsed = _coerce_reviewer_repair_output(_json(_reviewer()), "det", "ctx", "primary", "diff")
    assert parsed["decision"] == "accept"


def test_diff_checksum_is_exact_utf8_bytes_not_json_wrapper() -> None:
    diff = "--- a/F.java\n+++ b/F.java\n@@ -1 +1 @@\n-a\n+b café\n"
    assert sha256_unified_diff_text(diff) == hashlib.sha256(diff.encode("utf-8")).hexdigest()
    assert sha256_unified_diff_text(diff) != sha256_canonical_json({"unified_diff": diff})
    assert sha256_unified_diff_text(diff) != sha256_unified_diff_text(diff.replace("+b", "+ b"))
    assert sha256_unified_diff_text(diff) != sha256_unified_diff_text(diff.replace("\n", "\r\n"))
    assert sha256_unified_diff_text(diff) != sha256_unified_diff_text(diff.rstrip("\n"))


class _BoundClient:
    def __init__(self, reviewer_decision: str = "accept") -> None:
        self.calls: list[V2ModelRole] = []
        self.reviewer_prompt_primary_output: dict[str, Any] = {}
        self.reviewer_prompt_primary_checksum = ""
        self.reviewer_decision = reviewer_decision

    def answer_with_role(self, *, role: V2ModelRole, prompt: str, fallback: str, **kwargs: Any) -> V2AssistantModelResult:
        self.calls.append(role)
        if role == V2ModelRole.PROPOSER:
            content = _json(_primary())
        else:
            self.reviewer_prompt_primary_output = json.loads(prompt.split("Primary output:\n", 1)[1])
            checksums = {
                key: re.search(pattern, prompt).group(1)  # type: ignore[union-attr]
                for key, pattern in {
                    "context": r"Context pack checksum: ([0-9a-f]+)",
                    "primary": r"Primary output checksum: ([0-9a-f]+)",
                    "diff": r"Proposed diff checksum: ([0-9a-f]+)",
                }.items()
            }
            self.reviewer_prompt_primary_checksum = checksums["primary"]
            content = _json(_reviewer(
                context=checksums["context"],
                primary=checksums["primary"],
                diff=checksums["diff"],
                decision=self.reviewer_decision,
            ))
        return V2AssistantModelResult(
            content=content,
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role=role.value,
            success=True,
            redacted_summary="ok",
            failure_reason="",
        )


def _evidence_and_context() -> tuple[Any, Any]:
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        job_id="job-i1",
        stage_index=1,
        command_id="cmd-i1",
        failure_summary="build failed",
        changed_files=("src/App.java",),
    )
    return evidence, build_repair_context_pack(failure_evidence=evidence)


@pytest.mark.parametrize("decision", ["revise", "reject"])
def test_reviewer_revise_or_reject_fails_closed(tmp_path: Path, decision: str) -> None:
    evidence, context = _evidence_and_context()
    with pytest.raises(RepairReviewChainProductionError, match=decision):
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context,
            output_dir=tmp_path / "chain",
            model_client=_BoundClient(reviewer_decision=decision),
        )
    assert not (tmp_path / "chain" / "final_reviewed_repair_artifact.json").exists()


def test_review_chain_artifacts_use_same_exact_diff_checksum(tmp_path: Path) -> None:
    evidence, context = _evidence_and_context()
    client = _BoundClient()
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context,
        output_dir=tmp_path / "chain",
        model_client=client,
    )
    refs = result["artifact_refs"]
    diff_bytes = Path(refs["final_reviewed_diff"]).read_bytes()
    exact = hashlib.sha256(diff_bytes).hexdigest()
    primary = json.loads(Path(refs["primary_llm_output"]).read_text(encoding="utf-8"))
    reviewer = json.loads(Path(refs["reviewer_llm_output"]).read_text(encoding="utf-8"))
    artifact = json.loads(Path(refs["final_reviewed_artifact"]).read_text(encoding="utf-8"))
    chain = json.loads(Path(refs["review_chain_metadata"]).read_text(encoding="utf-8"))

    assert client.reviewer_prompt_primary_output == canonical_primary_repair_output(primary)
    assert "output_checksum" not in client.reviewer_prompt_primary_output
    assert "raw_response_checksum" not in client.reviewer_prompt_primary_output
    assert _compute_primary_repair_checksum(client.reviewer_prompt_primary_output) == client.reviewer_prompt_primary_checksum
    assert _compute_primary_repair_checksum(primary) == chain["primary_output_checksum"]
    assert _compute_reviewer_repair_checksum(reviewer) == chain["reviewer_output_checksum"]
    assert canonical_primary_repair_output({**primary, "raw_response_checksum": "changed"}) == canonical_primary_repair_output(primary)
    assert _compute_primary_repair_checksum({**primary, "raw_response_checksum": "changed"}) == chain["primary_output_checksum"]
    assert _compute_reviewer_repair_checksum({**reviewer, "raw_response_checksum": "changed"}) == chain["reviewer_output_checksum"]
    changed_primary = {**primary, "root_cause": "different"}
    changed_reviewer = {**reviewer, "notes": ["different"]}
    assert _compute_primary_repair_checksum(changed_primary) != chain["primary_output_checksum"]
    assert _compute_reviewer_repair_checksum(changed_reviewer) != chain["reviewer_output_checksum"]
    assert canonical_reviewer_repair_output(reviewer)["decision"] == "accept"
    assert exact == sha256_unified_diff_text(primary["proposed_diff"])
    assert reviewer["reviewed_diff_checksum"] == exact
    assert artifact["proposed_diff_checksum"] == exact
    assert chain["proposed_diff_checksum"] == exact
    assert chain["proposed_diff_checksum_algorithm"] == "sha256_utf8_bytes_v1"
    assert chain["checksum_algorithms"]["validated_structured_output_checksum"] == "sha256_canonical_json_v1"
