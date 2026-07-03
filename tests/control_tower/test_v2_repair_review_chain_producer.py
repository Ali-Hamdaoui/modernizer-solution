"""F5-T3/T4/T5/T6: Tests for repair review chain producer.

Covers:
  _is_unified_diff, _check_forbidden_paths_in_diff, _check_forbidden_keys,
  _validate_primary_repair_output, _compute_*_repair_checksum,
  produce_repair_review_chain (with fake model client).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelResult,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.orchestrator.repair_review_chain import (
    RepairReviewChainProductionError,
    _check_forbidden_keys,
    _check_forbidden_paths_in_diff,
    _compute_final_repair_artifact_checksum,
    _compute_primary_repair_checksum,
    _compute_reviewer_repair_checksum,
    _coerce_primary_repair_output,
    _coerce_reviewer_repair_output,
    _is_unified_diff,
    _primary_repair_prompt,
    _reviewer_repair_prompt,
    _validate_primary_repair_output,
    produce_repair_review_chain,
)
from migration_factory.repair_loop.failure_evidence import (
    FailureSource,
    build_failure_evidence,
)
from migration_factory.repair_loop.repair_context import (
    build_repair_context_pack,
)


# ── Helpers ───────────────────────────────────────────────────────────

VALID_UNIFIED_DIFF = """\
diff --git a/src/main/java/App.java b/src/main/java/App.java
--- a/src/main/java/App.java
+++ b/src/main/java/App.java
@@ -1,3 +1,3 @@
-old line
+new line
 unchanged
"""


def _valid_primary_json() -> str:
    return json.dumps(
        {
            "root_cause": "Missing import",
            "fix_strategy": "Add import statement",
            "changed_files": ["src/main/java/App.java"],
            "proposed_diff": VALID_UNIFIED_DIFF,
            "risk": "LOW",
            "confidence": 0.9,
            "rationale": "Simple fix",
            "deterministic_rule_id": "rule-1",
        },
        sort_keys=True,
    )


def _accept_reviewer_json() -> str:
    return json.dumps(
        {
            "decision": "accept",
            "notes": ["Looks correct"],
            "confidence": 0.95,
            "risks": [],
            "policy_concerns": [],
            "changed_files_verified": True,
            "diff_parseable": True,
            "reviewed_context_checksum": "context-cs",
            "reviewed_primary_output_checksum": "primary-cs",
            "reviewed_diff_checksum": "diff-cs",
        },
        sort_keys=True,
    )


def _prompt_value(prompt: str, label: str) -> str:
    prefix = f"{label}: "
    for line in prompt.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    raise AssertionError(f"missing prompt value {label!r}")


def _accept_reviewer_json_for_prompt(
    prompt: str,
    *,
    diff_parseable: bool = True,
    changed_files_verified: bool = True,
) -> str:
    return json.dumps(
        {
            "decision": "accept",
            "notes": ["Looks correct"],
            "confidence": 0.95,
            "risks": [],
            "policy_concerns": [],
            "changed_files_verified": changed_files_verified,
            "diff_parseable": diff_parseable,
            "reviewed_context_checksum": _prompt_value(prompt, "Context pack checksum"),
            "reviewed_primary_output_checksum": _prompt_value(prompt, "Primary output checksum"),
            "reviewed_diff_checksum": _prompt_value(prompt, "Normalized proposed diff checksum"),
        },
        sort_keys=True,
    )


def _make_evidence(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "failure_source": FailureSource.BUILD,
        "job_id": "job-test",
        "stage_index": 1,
        "command_id": "cmd-1",
        "failure_summary": "Compilation error",
        "source_profile": "java11",
        "target_profile": "java17",
        "changed_files": ("src/main/java/App.java",),
    }
    kwargs.update(overrides)
    return build_failure_evidence(**kwargs)


def _make_context(evidence: Any, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "failure_evidence": evidence,
        "job_id": evidence.job_id,
        "stage_index": evidence.stage_index,
        "command_id": evidence.command_id,
        "source_profile": evidence.source_profile,
        "target_profile": evidence.target_profile,
        "changed_files": evidence.changed_files,
    }
    kwargs.update(overrides)
    return build_repair_context_pack(**kwargs)


class FakeRepairClient:
    def __init__(
        self,
        primary_response: str = "",
        reviewer_response: str | None = None,
        primary_success: bool = True,
        reviewer_success: bool = True,
    ) -> None:
        self._primary = primary_response or _valid_primary_json()
        self._reviewer = reviewer_response
        self._primary_success = primary_success
        self._reviewer_success = reviewer_success
        self.calls: list[V2ModelRole] = []
        self.call_kwargs: list[dict[str, Any]] = []

    def answer_with_role(
        self, *, role: V2ModelRole, prompt: str, fallback: str, **_: Any
    ) -> V2AssistantModelResult:
        self.calls.append(role)
        self.call_kwargs.append({"role": role, "prompt": prompt, "fallback": fallback, **_})
        if role == V2ModelRole.PROPOSER:
            return V2AssistantModelResult(
                content=self._primary,
                source="fake",
                model_status="live_ok" if self._primary_success else "fallback",
                provider="fake",
                role=role.value,
                success=self._primary_success,
                redacted_summary="ok" if self._primary_success else "primary failed",
                failure_reason="" if self._primary_success else "primary_model_failed",
            )
        else:
            content = self._reviewer
            if content is None:
                content = _accept_reviewer_json_for_prompt(prompt)
            else:
                content = (
                    content
                    .replace("{context_checksum}", _prompt_value(prompt, "Context pack checksum"))
                    .replace("{primary_checksum}", _prompt_value(prompt, "Primary output checksum"))
                    .replace("{diff_checksum}", _prompt_value(prompt, "Normalized proposed diff checksum"))
                )
            return V2AssistantModelResult(
                content=content,
                source="fake",
                model_status="live_ok" if self._reviewer_success else "fallback",
                provider="fake",
                role=role.value,
                success=self._reviewer_success,
                redacted_summary="ok" if self._reviewer_success else "reviewer failed",
                failure_reason="" if self._reviewer_success else "reviewer_model_failed",
            )


class ReviewerSchemaInvalidClient(FakeRepairClient):
    def answer_with_role(
        self, *, role: V2ModelRole, prompt: str, fallback: str, **_: Any
    ) -> V2AssistantModelResult:
        if role == V2ModelRole.REVIEWER:
            return V2AssistantModelResult(
                content='{"decision":"accept"}',
                source="fake",
                model_status="fallback",
                provider="fake",
                role=role.value,
                success=False,
                redacted_summary="Reviewer model output failed schema validation.",
                failure_reason="reviewer_schema_invalid",
                schema_diagnostics={
                    "schema_validated": False,
                    "schema_name": "RepairReviewerOutput",
                    "role": "reviewer",
                    "stage": "reviewer",
                    "reason_code": "reviewer_schema_invalid",
                    "missing_fields": ["notes"],
                },
            )
        return super().answer_with_role(role=role, prompt=prompt, fallback=fallback, **_)


class FailingRepairClient:
    def answer_with_role(
        self, *, role: V2ModelRole, prompt: str, fallback: str, **_: Any
    ) -> V2AssistantModelResult:
        return V2AssistantModelResult(
            content=fallback,
            source="deterministic",
            model_status="fallback",
            provider="deterministic",
            role=role.value,
            success=False,
            redacted_summary="model unavailable",
            failure_reason="missing_deployment",
        )


# ── F5-T3: _is_unified_diff ──────────────────────────────────────────


def test_is_unified_diff_valid() -> None:
    assert _is_unified_diff(VALID_UNIFIED_DIFF) is True


def test_is_unified_diff_plain_text() -> None:
    assert _is_unified_diff("hello world") is False


def test_is_unified_diff_empty() -> None:
    assert _is_unified_diff("") is False


# ── F5-T3: _check_forbidden_paths_in_diff ────────────────────────────


def test_forbidden_paths_catches_dot_git() -> None:
    diff = "--- a/.git/config\n+++ b/.git/config\n@@ -1 +1 @@\n-old\n+new\n"
    failures = _check_forbidden_paths_in_diff(diff)
    assert any(".git" in f for f in failures)


def test_forbidden_paths_catches_dockerfile() -> None:
    diff = "--- a/Dockerfile\n+++ b/Dockerfile\n@@ -1 +1 @@\n-old\n+new\n"
    failures = _check_forbidden_paths_in_diff(diff)
    assert any("Dockerfile" in f for f in failures)


def test_forbidden_paths_catches_deployment_pattern() -> None:
    diff = "--- a/deployment/config.yml\n+++ b/deployment/config.yml\n@@ -1 +1 @@\n-old\n+new\n"
    failures = _check_forbidden_paths_in_diff(diff)
    assert any("deployment/" in f for f in failures)


def test_forbidden_paths_passes_safe_diff() -> None:
    diff = "--- a/src/main/java/App.java\n+++ b/src/main/java/App.java\n@@ -1,3 +1,3 @@\n-old\n+new\n unchanged\n"
    failures = _check_forbidden_paths_in_diff(diff)
    assert failures == []


# ── F5-T3: _check_forbidden_keys ─────────────────────────────────────


def test_forbidden_keys_finds_sandbox_path() -> None:
    failures = _check_forbidden_keys({"sandbox_path": "/tmp/sandbox"})
    assert any("sandbox_path" in f for f in failures)


def test_forbidden_keys_finds_env() -> None:
    failures = _check_forbidden_keys({"env": {"HOME": "/root"}})
    assert any("env" in f for f in failures)


def test_forbidden_keys_passes_clean_dict() -> None:
    failures = _check_forbidden_keys({"root_cause": "test", "risk": "LOW"})
    assert failures == []


# ── F5-T4: _validate_primary_repair_output ────────────────────────────


def test_validate_primary_rejects_empty_root_cause() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["App.java"],
        "risk": "LOW",
        "confidence": 0.8,
    })
    assert any("root_cause" in f for f in failures)


def test_validate_primary_rejects_missing_fix_strategy() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["App.java"],
        "risk": "LOW",
        "confidence": 0.8,
    })
    assert any("fix_strategy" in f for f in failures)


def test_validate_primary_rejects_invalid_risk() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["App.java"],
        "risk": "CRITICAL",
        "confidence": 0.8,
    })
    assert any("risk" in f for f in failures)


def test_validate_primary_rejects_confidence_out_of_range() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["App.java"],
        "risk": "LOW",
        "confidence": 1.5,
    })
    assert any("confidence" in f for f in failures)


def test_validate_primary_rejects_non_unified_diff() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": "just some plain text",
        "changed_files": ["App.java"],
        "risk": "LOW",
        "confidence": 0.8,
    })
    assert any("unified diff" in f for f in failures)


def test_validate_primary_accepts_valid_output() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["App.java"],
        "risk": "LOW",
        "confidence": 0.8,
    })
    assert failures == []


# ── F5-T3/T4: Checksum determinism ───────────────────────────────────


def test_compute_primary_repair_checksum_deterministic() -> None:
    output = {"root_cause": "X", "fix_strategy": "Y", "risk": "LOW", "confidence": 0.9}
    assert _compute_primary_repair_checksum(output) == _compute_primary_repair_checksum(output)


def test_compute_primary_repair_checksum_changes_on_diff_change() -> None:
    a = _compute_primary_repair_checksum({"root_cause": "X", "proposed_diff": "diff-a"})
    b = _compute_primary_repair_checksum({"root_cause": "X", "proposed_diff": "diff-b"})
    assert a != b


def test_compute_reviewer_repair_checksum_deterministic() -> None:
    output = {"decision": "accept", "notes": ["ok"], "confidence": 0.9}
    assert _compute_reviewer_repair_checksum(output) == _compute_reviewer_repair_checksum(output)


def test_compute_reviewer_repair_checksum_changes_on_decision_change() -> None:
    a = _compute_reviewer_repair_checksum({"decision": "accept"})
    b = _compute_reviewer_repair_checksum({"decision": "reject"})
    assert a != b


def test_compute_final_repair_artifact_checksum_deterministic() -> None:
    payload = {"key": "value"}
    assert _compute_final_repair_artifact_checksum(payload) == _compute_final_repair_artifact_checksum(payload)


def test_compute_final_repair_artifact_checksum_excludes_volatile_fields() -> None:
    base = {"key": "value"}
    a = _compute_final_repair_artifact_checksum({**base, "artifact_checksum": "aaa", "created_at": "2020-01-01T00:00:00Z"})
    b = _compute_final_repair_artifact_checksum({**base, "artifact_checksum": "bbb", "created_at": "2025-12-31T23:59:59Z"})
    c = _compute_final_repair_artifact_checksum({**base, "policy_validation_checksum": "ccc"})
    assert a == b
    assert a == c


# ── F5-T4/T5/T6: produce_repair_review_chain with fake client ──────────


def _reviewer_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decision": "accept",
        "notes": ["Looks correct"],
        "confidence": 0.95,
        "risks": [],
        "policy_concerns": [],
        "changed_files_verified": True,
        "diff_parseable": True,
        "reviewed_context_checksum": "context-cs",
        "reviewed_primary_output_checksum": "primary-cs",
        "reviewed_diff_checksum": "diff-cs",
    }
    payload.update(overrides)
    return payload


def test_coerce_reviewer_accepts_top_level_checksum_bindings() -> None:
    output = _coerce_reviewer_repair_output(
        json.dumps(_reviewer_payload()),
        "deterministic-cs",
        "context-cs",
        "primary-cs",
        "diff-cs",
    )
    assert output["decision"] == "accept"
    assert output["reviewed_context_checksum"] == "context-cs"
    assert output["reviewed_primary_output_checksum"] == "primary-cs"
    assert output["reviewed_diff_checksum"] == "diff-cs"


def test_coerce_reviewer_rejects_nested_only_checksum_bindings() -> None:
    payload = _reviewer_payload(
        checksum_bindings={
            "reviewed_context_checksum": "context-cs",
            "reviewed_primary_output_checksum": "primary-cs",
            "reviewed_diff_checksum": "diff-cs",
        }
    )
    del payload["reviewed_context_checksum"]
    del payload["reviewed_primary_output_checksum"]
    del payload["reviewed_diff_checksum"]

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _coerce_reviewer_repair_output(
            json.dumps(payload),
            "deterministic-cs",
            "context-cs",
            "primary-cs",
            "diff-cs",
        )

    assert exc_info.value.reason_code == "reviewer_schema_invalid"


@pytest.mark.parametrize(
    "missing_field",
    [
        "reviewed_context_checksum",
        "reviewed_primary_output_checksum",
        "reviewed_diff_checksum",
    ],
)
def test_coerce_reviewer_rejects_missing_top_level_checksum(missing_field: str) -> None:
    payload = _reviewer_payload()
    del payload[missing_field]

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _coerce_reviewer_repair_output(
            json.dumps(payload),
            "deterministic-cs",
            "context-cs",
            "primary-cs",
            "diff-cs",
        )

    assert exc_info.value.reason_code == "reviewer_schema_invalid"
    assert missing_field in str(exc_info.value)


@pytest.mark.parametrize(
    "field",
    [
        "reviewed_context_checksum",
        "reviewed_primary_output_checksum",
        "reviewed_diff_checksum",
    ],
)
def test_coerce_reviewer_rejects_each_checksum_mismatch(field: str) -> None:
    payload = _reviewer_payload(**{field: "mismatched-checksum"})

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _coerce_reviewer_repair_output(
            json.dumps(payload),
            "deterministic-cs",
            "context-cs",
            "primary-cs",
            "diff-cs",
        )

    assert exc_info.value.reason_code == "reviewer_checksum_mismatch"


def test_produce_raises_on_invalid_primary_json(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(
        primary_response=json.dumps({"not_root_cause": "oops", "confidence": 0.5}),
    )
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
        )
    assert "missing required fields" in str(exc_info.value)


def test_produce_raises_on_reviewer_reject_decision(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(
        reviewer_response=json.dumps({
            "decision": "reject",
            "changed_files_verified": True,
            "diff_parseable": True,
            "reviewed_context_checksum": "{context_checksum}",
            "reviewed_primary_output_checksum": "{primary_checksum}",
            "reviewed_diff_checksum": "{diff_checksum}",
        }),
    )
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
        )
    assert "reject" in str(exc_info.value)


def test_produce_raises_on_reviewer_checksum_mismatch(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(
        reviewer_response=json.dumps({
            "decision": "accept",
            "reviewed_context_checksum": "mismatched-checksum",
            "reviewed_primary_output_checksum": "{primary_checksum}",
            "reviewed_diff_checksum": "{diff_checksum}",
            "changed_files_verified": True,
            "diff_parseable": True,
        }),
    )
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
        )
    assert "checksum binding did not match" in str(exc_info.value)
    assert exc_info.value.reason_code == "reviewer_checksum_mismatch"
    assert exc_info.value.schema_diagnostics is not None
    assert exc_info.value.schema_diagnostics["schema_name"] == "RepairReviewerOutput"
    assert exc_info.value.schema_diagnostics["stage"] == "reviewer"
    assert exc_info.value.schema_diagnostics["mismatched_fields"] == ["reviewed_context_checksum"]


def test_produce_rejects_accept_with_diff_parseable_false_without_materializing(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    output_dir = tmp_path / "output"
    client = FakeRepairClient(
        reviewer_response=json.dumps({
            "decision": "accept",
            "notes": ["Diff is not parseable"],
            "confidence": 0.95,
            "risks": [],
            "policy_concerns": [],
            "changed_files_verified": True,
            "diff_parseable": False,
            "reviewed_context_checksum": "{context_checksum}",
            "reviewed_primary_output_checksum": "{primary_checksum}",
            "reviewed_diff_checksum": "{diff_checksum}",
        }),
    )

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=output_dir,
            model_client=client,
        )

    assert exc_info.value.reason_code == "reviewer_rejected_diff"
    assert not (output_dir / "final_reviewed_repair_artifact.json").exists()
    assert not (output_dir / "final_reviewed_repair.diff").exists()


def test_produce_rejects_accept_with_changed_files_verified_false_without_materializing(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    output_dir = tmp_path / "output"
    client = FakeRepairClient(
        reviewer_response=json.dumps({
            "decision": "accept",
            "notes": ["Changed files were not verified"],
            "confidence": 0.95,
            "risks": [],
            "policy_concerns": [],
            "changed_files_verified": False,
            "diff_parseable": True,
            "reviewed_context_checksum": "{context_checksum}",
            "reviewed_primary_output_checksum": "{primary_checksum}",
            "reviewed_diff_checksum": "{diff_checksum}",
        }),
    )

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=output_dir,
            model_client=client,
        )

    assert exc_info.value.reason_code == "reviewer_policy_reject"
    assert not (output_dir / "final_reviewed_repair_artifact.json").exists()
    assert not (output_dir / "final_reviewed_repair.diff").exists()


def test_produce_preserves_reviewer_schema_invalid_diagnostics(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = ReviewerSchemaInvalidClient()
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
        )
    assert exc_info.value.reason_code == "reviewer_schema_invalid"
    assert exc_info.value.schema_diagnostics is not None
    assert exc_info.value.schema_diagnostics["schema_name"] == "RepairReviewerOutput"
    assert exc_info.value.schema_diagnostics["stage"] == "reviewer"


def test_produce_success_with_accept_decision(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient()
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context_pack,
        output_dir=tmp_path / "output",
        model_client=client,
    )
    assert "artifact_refs" in result
    assert "review_chain" in result
    assert result["review_chain"]["reviewer_decision"] == "accept"
    assert (tmp_path / "output" / "deterministic_repair_artifact.json").exists()
    assert (tmp_path / "output" / "primary_repair_llm_output.json").exists()
    assert (tmp_path / "output" / "reviewer_repair_llm_output.json").exists()
    assert (tmp_path / "output" / "final_reviewed_repair_artifact.json").exists()
    assert (tmp_path / "output" / "final_reviewed_repair.diff").exists()
    assert (tmp_path / "output" / "review_chain.json").exists()
    assert client.call_kwargs[0]["output_schema_name"] == "RepairPrimaryOutput"
    assert client.call_kwargs[0]["require_schema"] is True
    assert client.call_kwargs[1]["output_schema_name"] == "RepairReviewerOutput"
    assert client.call_kwargs[1]["require_schema"] is True
    assert result["review_chain"]["model_roles"]["proposer"]["available"] is True
    assert result["review_chain"]["model_roles"]["reviewer"]["available"] is True
    assert "deployment" not in json.dumps(result["review_chain"]["model_roles"]).lower()
    assert "endpoint" not in json.dumps(result["review_chain"]["model_roles"]).lower()


def test_produce_raises_on_primary_model_failure(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FailingRepairClient()
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
        )
    assert "failed closed" in str(exc_info.value)


# ── F5-T4: Prompt content tests ──────────────────────────────────────


def test_main_prompt_requires_json_only() -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    prompt = _primary_repair_prompt(context_pack, "test-checksum")
    assert "Output only valid JSON" in prompt
    assert "No markdown" in prompt
    assert "No code fences" in prompt
    assert "No commentary" in prompt


def test_main_prompt_includes_repair_primary_schema() -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    prompt = _primary_repair_prompt(context_pack, "test-checksum")
    assert "root_cause (string)" in prompt
    assert "fix_strategy (string)" in prompt
    assert "changed_files (list of strings)" in prompt
    assert "proposed_diff (string)" in prompt
    assert "risk (string)" in prompt
    assert "LOW, MEDIUM, or HIGH" in prompt
    assert "confidence (number)" in prompt
    assert "0.0 to 1.0" in prompt
    assert "rationale (string)" in prompt


def test_main_prompt_requires_unified_diff_hunk_ranges() -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    prompt = _primary_repair_prompt(context_pack, "test-checksum")
    assert "hunk header MUST include line-range" in prompt
    assert "diff --git" in prompt


# ── F5-T4: Coerce primary output failure semantics ────────────────────


def test_empty_primary_raises_with_reason_code() -> None:
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _coerce_primary_repair_output("")
    assert exc_info.value.reason_code == "main_empty_response"


def test_whitespace_primary_raises_with_reason_code() -> None:
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _coerce_primary_repair_output("   \n\n  ")
    assert exc_info.value.reason_code == "main_empty_response"


def test_invalid_main_json_marks_reviewed_repair_unavailable(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(
        primary_response="not valid json at all",
    )
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "out1",
            model_client=client,
        )
    assert exc_info.value.reason_code == "main_schema_invalid"


def test_main_empty_response_marks_reviewed_repair_unavailable(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(
        primary_response="   \n\n  ",
    )
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "out2",
            model_client=client,
        )
    assert exc_info.value.reason_code == "main_empty_response"


def test_invalid_main_json_does_not_call_reviewer(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(
        primary_response="not valid json at all",
    )
    with pytest.raises(RepairReviewChainProductionError):
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "out3",
            model_client=client,
        )
    assert V2ModelRole.REVIEWER not in client.calls


def test_valid_main_output_continues_to_reviewer(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient()
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context_pack,
        output_dir=tmp_path / "output",
        model_client=client,
    )
    assert "artifact_refs" in result
    assert "review_chain" in result
    assert result["review_chain"]["reviewer_decision"] == "accept"
    assert V2ModelRole.REVIEWER in client.calls
    assert V2ModelRole.PROPOSER in client.calls


def test_reviewed_repair_unavailable_projection_has_clear_next_action(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(
        primary_response="corrupt: not json",
    )
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "out4",
            model_client=client,
        )
    msg = str(exc_info.value)
    assert exc_info.value.reason_code == "main_schema_invalid"
    assert "valid JSON" in msg or "unparseable" in msg or "schema" in msg


def _sample_reviewer_prompt() -> str:
    return _reviewer_repair_prompt(
        {
            "root_cause": "test",
            "fix_strategy": "fix",
            "changed_files": [],
            "proposed_diff": "",
            "risk": "LOW",
            "confidence": 0.9,
            "rationale": "ok",
        },
        "deterministic-cs",
        "context-cs",
        "primary-cs",
        "diff-cs",
    )


def test_reviewer_prompt_requires_json_only() -> None:
    prompt = _sample_reviewer_prompt()
    assert "Output only valid JSON" in prompt
    assert "No markdown" in prompt
    assert "No code fences" in prompt
    assert "No commentary" in prompt


def test_reviewer_prompt_uses_top_level_checksum_fields() -> None:
    prompt = _sample_reviewer_prompt()
    assert 'reviewed_context_checksum: "context-cs"' in prompt
    assert 'reviewed_primary_output_checksum: "primary-cs"' in prompt
    assert 'reviewed_diff_checksum: "diff-cs"' in prompt


def test_reviewer_prompt_does_not_include_checksum_bindings() -> None:
    prompt = _sample_reviewer_prompt()
    assert "checksum_bindings" not in prompt


def test_reviewer_prompt_includes_expected_checksum_values() -> None:
    prompt = _sample_reviewer_prompt()
    assert "Context pack checksum: context-cs" in prompt
    assert "Primary output checksum: primary-cs" in prompt
    assert "Normalized proposed diff checksum: diff-cs" in prompt
    assert '"reviewed_context_checksum": "context-cs"' in prompt
    assert '"reviewed_primary_output_checksum": "primary-cs"' in prompt
    assert '"reviewed_diff_checksum": "diff-cs"' in prompt


def test_reviewer_prompt_includes_valid_json_example() -> None:
    prompt = _sample_reviewer_prompt()
    assert "Valid JSON example:" in prompt
    example_text = prompt.split("Valid JSON example:\n", 1)[1].split("\n\nCONSTRAINTS:", 1)[0]
    example = json.loads(example_text)
    assert example == {
        "decision": "accept",
        "notes": [],
        "risks": [],
        "policy_concerns": [],
        "changed_files_verified": True,
        "diff_parseable": True,
        "reviewed_context_checksum": "context-cs",
        "reviewed_primary_output_checksum": "primary-cs",
        "reviewed_diff_checksum": "diff-cs",
    }


def test_reviewer_prompt_says_normalized_diff_is_reviewed() -> None:
    prompt = _reviewer_repair_prompt(
        {"root_cause": "test", "fix_strategy": "fix", "changed_files": [], "proposed_diff": "", "risk": "LOW", "confidence": 0.9, "rationale": "ok"},
        "deterministic-cs", "context-cs", "primary-cs", "diff-cs",
    )
    assert "Normalized proposed diff checksum" in prompt
