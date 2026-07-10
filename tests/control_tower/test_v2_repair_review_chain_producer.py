"""F5-T3/T4/T5/T6: Tests for repair review chain producer.

Covers:
  _is_unified_diff, _check_forbidden_paths_in_diff, _check_forbidden_keys,
  _validate_primary_repair_output, _compute_*_repair_checksum,
  produce_repair_review_chain (with fake model client).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelResult,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.domain.checksums import sha256_hex
from migration_factory.orchestrator.repair_review_chain import (
    RepairReviewChainProductionError,
    _check_forbidden_keys,
    _check_forbidden_paths_in_diff,
    _compute_final_repair_artifact_checksum,
    _compute_primary_repair_checksum,
    _compute_reviewer_repair_checksum,
    _is_unified_diff,
    _validate_primary_repair_output,
    produce_repair_review_chain,
)
from migration_factory.repair_loop.failure_evidence import (
    FailureSource,
    NormalizedCompilerError,
    NormalizedTestFailure,
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
    return _primary_json_with_diff(VALID_UNIFIED_DIFF, ["src/main/java/App.java"])


def _primary_json_with_diff(diff: str, changed_files: list[str]) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "proposal_kind": "llm_repair_primary",
            "root_cause": "Missing import",
            "fix_strategy": "Add import statement",
            "changed_files": changed_files,
            "proposed_diff": diff,
            "risk": "LOW",
            "confidence": 0.9,
            "rationale": "Simple fix",
            "deterministic_rule_id": "rule-1",
        },
        sort_keys=True,
    )


def _checksums_from_prompt(prompt: str) -> dict[str, str]:
    patterns = {
        "context": r"Context pack checksum: ([0-9a-f]+)",
        "primary": r"Primary output checksum: ([0-9a-f]+)",
        "diff": r"Proposed diff checksum: ([0-9a-f]+)",
    }
    return {
        key: re.search(pattern, prompt).group(1)  # type: ignore[union-attr]
        for key, pattern in patterns.items()
    }


def _accept_reviewer_json(prompt: str, *, decision: str = "accept", context_checksum: str | None = None) -> str:
    checksums = _checksums_from_prompt(prompt)
    return json.dumps(
        {
            "schema_version": "1.0",
            "proposal_kind": "llm_repair_review",
            "decision": decision,
            "notes": ["Looks correct"],
            "confidence": 0.95,
            "risks": [],
            "policy_concerns": [],
            "reviewed_context_checksum": context_checksum if context_checksum is not None else checksums["context"],
            "reviewed_primary_output_checksum": checksums["primary"],
            "reviewed_diff_checksum": checksums["diff"],
        },
        sort_keys=True,
    )


def _large_valid_primary_json() -> str:
    diff_lines = [
        "diff --git a/src/main/java/App.java b/src/main/java/App.java",
        "--- a/src/main/java/App.java",
        "+++ b/src/main/java/App.java",
        "@@ -1,6 +1,6 @@",
    ]
    for index in range(80):
        diff_lines.append(f"-old line {index}")
        diff_lines.append(f"+new line {index}")
    diff = "\n".join(diff_lines) + "\n"
    assert len(diff) > 700
    return json.dumps(
        {
            **json.loads(_valid_primary_json()),
            "proposed_diff": diff,
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
        reviewer_response: str = "",
        reviewer_decision: str = "accept",
        primary_success: bool = True,
        reviewer_success: bool = True,
    ) -> None:
        self._primary = primary_response or _valid_primary_json()
        self._reviewer = reviewer_response
        self._reviewer_decision = reviewer_decision
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
            reviewer_content = self._reviewer
            if not reviewer_content:
                reviewer_content = _accept_reviewer_json(prompt, decision=self._reviewer_decision)
            if reviewer_content == "__MISMATCH_CONTEXT__":
                reviewer_content = _accept_reviewer_json(prompt, context_checksum="mismatched-checksum")
            return V2AssistantModelResult(
                content=reviewer_content,
                source="fake",
                model_status="live_ok" if self._reviewer_success else "fallback",
                provider="fake",
                role=role.value,
                success=self._reviewer_success,
                redacted_summary="ok" if self._reviewer_success else "reviewer failed",
                failure_reason="" if self._reviewer_success else "reviewer_model_failed",
            )


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


class _Ledger:
    def __init__(self) -> None:
        self.count = 0

    def start_invocation(self, **_: Any) -> str:
        self.count += 1
        return f"inv-{self.count}"

    def complete_invocation(self, *_: Any, **__: Any) -> None:
        return None

    def fail_invocation(self, *_: Any, **__: Any) -> None:
        return None


class RecordingLedger:
    def __init__(self) -> None:
        self.count = 0
        self.rows: dict[str, dict[str, Any]] = {}

    def start_invocation(self, **kwargs: Any) -> str:
        self.count += 1
        invocation_id = f"inv-{self.count}"
        self.rows[invocation_id] = {"invocation_id": invocation_id, "status": "started", **kwargs}
        return invocation_id

    def complete_invocation(self, invocation_id: str, **kwargs: Any) -> None:
        row = self.rows[invocation_id]
        assert row["status"] == "started"
        row.update(kwargs)
        row["status"] = "fallback" if kwargs.get("fallback_used") else "completed"

    def fail_invocation(self, invocation_id: str, **kwargs: Any) -> None:
        row = self.rows[invocation_id]
        assert row["status"] == "started"
        row.update(kwargs)
        row["status"] = "fallback" if kwargs.get("fallback_used") else "failed"


class SequenceRepairClient:
    def __init__(self, results: list[V2AssistantModelResult]) -> None:
        self.results = list(results)
        self.calls: list[V2ModelRole] = []
        self.prompts: list[str] = []

    def answer_with_role(
        self, *, role: V2ModelRole, prompt: str, fallback: str, **_: Any
    ) -> V2AssistantModelResult:
        self.calls.append(role)
        self.prompts.append(prompt)
        if not self.results:
            raise AssertionError("No queued model result")
        result = self.results.pop(0)
        if role == V2ModelRole.REVIEWER and result.content in {"__ACCEPT__", "__MISMATCH_CONTEXT__", "__REVISE__", "__REJECT__"}:
            decision = {
                "__ACCEPT__": "accept",
                "__MISMATCH_CONTEXT__": "accept",
                "__REVISE__": "revise",
                "__REJECT__": "reject",
            }[result.content]
            return V2AssistantModelResult(
                content=_accept_reviewer_json(
                    prompt,
                    decision=decision,
                    context_checksum="mismatched-checksum" if result.content == "__MISMATCH_CONTEXT__" else None,
                ),
                source=result.source,
                model_status=result.model_status,
                provider=result.provider,
                role=role.value,
                success=result.success,
                redacted_summary=result.redacted_summary,
                failure_reason=result.failure_reason,
                fallback_used=result.fallback_used,
            )
        return result


def _model_result(
    content: str,
    *,
    role: str,
    success: bool = True,
    source: str = "fake",
    provider: str = "fake",
    model_status: str = "live_ok",
    failure_reason: str = "",
    fallback_used: bool = False,
) -> V2AssistantModelResult:
    return V2AssistantModelResult(
        content=content,
        source=source,
        model_status=model_status,
        provider=provider,
        role=role,
        success=success,
        redacted_summary="safe summary",
        failure_reason=failure_reason,
        fallback_used=fallback_used,
    )


def _run_chain(
    tmp_path: Path,
    client: Any,
    ledger: RecordingLedger,
    *,
    output_name: str = "chain",
    proposal_id: str | None = "proposal-123",
    gate_id: str | None = "gate-123",
    attempt_number: int | None = 7,
) -> dict[str, Any]:
    evidence = _make_evidence(job_id="job-corr", stage_index=3)
    context = _make_context(evidence, cycle_number=5)
    return produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context,
        output_dir=tmp_path / output_name,
        model_client=client,
        invocation_ledger=ledger,
        proposal_id=proposal_id,
        gate_id=gate_id,
        attempt_number=attempt_number,
    )


def _assert_fail_closed(output_dir: Path, ledger: RecordingLedger) -> None:
    assert ledger.rows
    assert all(row["status"] != "started" for row in ledger.rows.values())
    assert not (output_dir / "final_reviewed_repair_artifact.json").exists()
    assert not (output_dir / "final_reviewed_repair.diff").exists()
    assert not list(output_dir.glob("*candidate*"))
    assert not list(output_dir.glob("*approval*"))
    assert not list(output_dir.glob("*apply*"))


# ── F5-T3: _is_unified_diff ──────────────────────────────────────────


def test_is_unified_diff_valid() -> None:
    assert _is_unified_diff(VALID_UNIFIED_DIFF) is True


def test_is_unified_diff_plain_text() -> None:
    assert _is_unified_diff("hello world") is False


def test_is_unified_diff_empty() -> None:
    assert _is_unified_diff("") is False


def test_is_unified_diff_rejects_apply_patch_wrapper() -> None:
    diff = (
        "*** Begin Patch\n"
        "*** Update File: src/main/java/App.java\n"
        "@@\n"
        "-old\n"
        "+new\n"
        "*** End Patch\n"
    )
    assert _is_unified_diff(diff) is False


def test_is_unified_diff_rejects_markdown_fence() -> None:
    assert _is_unified_diff(f"```diff\n{VALID_UNIFIED_DIFF}```\n") is False


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
        "changed_files": ["src/main/java/App.java"],
        "risk": "LOW",
        "confidence": 0.8,
        "rationale": "safe fix",
    })
    assert any("root_cause" in f for f in failures)


def test_validate_primary_rejects_missing_fix_strategy() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["src/main/java/App.java"],
        "risk": "LOW",
        "confidence": 0.8,
        "rationale": "safe fix",
    })
    assert any("fix_strategy" in f for f in failures)


def test_validate_primary_rejects_invalid_risk() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["src/main/java/App.java"],
        "risk": "CRITICAL",
        "confidence": 0.8,
    })
    assert any("risk" in f for f in failures)


def test_validate_primary_rejects_confidence_out_of_range() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["src/main/java/App.java"],
        "risk": "LOW",
        "confidence": 1.5,
    })
    assert any("confidence" in f for f in failures)


def test_validate_primary_rejects_non_unified_diff() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": "just some plain text",
        "changed_files": ["src/main/java/App.java"],
        "risk": "LOW",
        "confidence": 0.8,
    })
    assert any("unified diff" in f for f in failures)


def test_validate_primary_rejects_declared_changed_files_mismatch() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["src/main/java/Other.java"],
        "risk": "LOW",
        "confidence": 0.8,
        "rationale": "safe fix",
    })
    assert any("declared_changed_files_mismatch" in f for f in failures)


def test_validate_primary_accepts_valid_output() -> None:
    failures = _validate_primary_repair_output({
        "root_cause": "valid cause",
        "fix_strategy": "valid strategy",
        "proposed_diff": VALID_UNIFIED_DIFF,
        "changed_files": ["src/main/java/App.java"],
        "risk": "LOW",
        "confidence": 0.8,
        "rationale": "safe fix",
    })
    assert failures == []


def test_context_pack_derives_live_shaped_source_evidence_from_bounded_log(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    test_file = sandbox / "src/test/java/com/example/m1/MigrationBehaviorTest.java"
    prod_file = sandbox / "src/main/java/com/example/m1/MigrationBehavior.java"
    pom_file = sandbox / "pom.xml"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    prod_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "package com.example.m1;\n"
        "class MigrationBehaviorTest {\n"
        "  void migratedRuntimeBehaviorMustCompleteSuccessfully() {\n"
        "    org.junit.jupiter.api.Assertions.assertEquals(\"READY\", new MigrationBehavior().run());\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    prod_file.write_text(
        "package com.example.m1;\n"
        "class MigrationBehavior { String run() { throw new RuntimeException(\"M1_UNKNOWN_RUNTIME_SENTINEL\"); } }\n",
        encoding="utf-8",
    )
    pom_file.write_text("<project><modelVersion>4.0.0</modelVersion></project>\n", encoding="utf-8")
    outside_test = tmp_path / "outside/src/test/java/com/example/m1/MigrationBehaviorTest.java"
    outside_test.parent.mkdir(parents=True, exist_ok=True)
    outside_test.write_text("outside sandbox sentinel\n", encoding="utf-8")
    for blocked in (
        sandbox / ".migration/MigrationBehaviorTest.java",
        sandbox / ".github/MigrationBehaviorTest.java",
        sandbox / "target/MigrationBehaviorTest.java",
    ):
        blocked.parent.mkdir(parents=True, exist_ok=True)
        blocked.write_text(f"blocked sentinel: {blocked.parent.name}\n", encoding="utf-8")
    stack_trace = (
        "[ERROR] Errors:\n"
        "[ERROR] MigrationBehaviorTest.unknownBehaviorMustBeReviewedAfterBootUpgrade\n"
        "java.lang.IllegalStateException: M1_UNKNOWN_RUNTIME_SENTINEL\n"
        "    at com.example.m1.MigrationBehaviorTest.unknownBehaviorMustBeReviewedAfterBootUpgrade"
        "(MigrationBehaviorTest.java:13)\n"
    )
    evidence = build_failure_evidence(
        failure_source=FailureSource.TEST,
        job_id="job-source",
        stage_index=1,
        command_id="cmd-source",
        failure_summary="Build failed after migration",
        test_failures=(),
        compiler_errors=(),
        changed_files=(),
        safe_log_preview=stack_trace,
    )

    context = build_repair_context_pack(
        failure_evidence=evidence,
        sandbox_path=sandbox,
    )

    evidence_paths = [entry["path"] for entry in context.source_evidence]
    assert evidence_paths == [
        "src/test/java/com/example/m1/MigrationBehaviorTest.java",
        "src/main/java/com/example/m1/MigrationBehavior.java",
        "pom.xml",
    ]
    assert len(context.source_evidence) <= 8
    assert sum(entry["byte_length"] for entry in context.source_evidence) <= 12_000
    for entry in context.source_evidence:
        relative = Path(entry["path"])
        assert not relative.is_absolute()
        raw = (sandbox / relative).read_bytes()
        assert entry["checksum"] == "sha256:" + sha256_hex(raw)
        assert entry["byte_length"] == len(raw) <= 12_000
    projected = json.dumps(context.source_evidence)
    assert str(tmp_path) not in projected
    assert "outside sandbox sentinel" not in projected
    assert "blocked sentinel" not in projected


def test_source_evidence_priority_preserves_failure_related_files(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    contents = {
        "src/main/java/com/example/CompileFailure.java": "class CompileFailure {}\n",
        "src/test/java/com/example/StructuredBehaviorTest.java": "class StructuredBehaviorTest {}\n",
        "src/test/java/com/example/LogBehaviorIT.java": "class LogBehaviorIT {}\n",
        "src/main/java/com/example/StructuredBehavior.java": "class StructuredBehavior {}\n",
        "src/main/java/com/example/LogBehavior.java": "class LogBehavior {}\n",
        "pom.xml": "<project/>\n",
        **{f"src/main/java/com/example/Changed{index}.java": f"class Changed{index} {{}}\n" for index in range(8)},
    }
    for relative, content in contents.items():
        path = sandbox / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    changed_files = tuple(f"src/main/java/com/example/Changed{index}.java" for index in range(8))
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        compiler_errors=(NormalizedCompilerError(file_path="src/main/java/com/example/CompileFailure.java"),),
        test_failures=(
            NormalizedTestFailure(file_path="src/test/java/com/example/StructuredBehaviorTest.java"),
        ),
        changed_files=changed_files,
        stderr_tail="in com.example.LogBehaviorIT\n",
    )

    context = build_repair_context_pack(failure_evidence=evidence, sandbox_path=sandbox)

    assert [entry["path"] for entry in context.source_evidence] == [
        "src/main/java/com/example/CompileFailure.java",
        "src/test/java/com/example/StructuredBehaviorTest.java",
        "src/test/java/com/example/LogBehaviorIT.java",
        "src/main/java/com/example/StructuredBehavior.java",
        "src/main/java/com/example/LogBehavior.java",
        "pom.xml",
        "src/main/java/com/example/Changed0.java",
        "src/main/java/com/example/Changed1.java",
    ]


def test_source_evidence_preserves_dot_paths_and_blocks_case_insensitively(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    files = {
        "pom.xml": "<project/>\n",
        "src/main/java/App.java": "class App {}\n",
        ".migration/secret.xml": "blocked\n",
        "migration/secret.xml": "must not be selected by normalization\n",
        ".GitHub/workflow.yml": "blocked\n",
        "TARGET/Generated.java": "blocked\n",
    }
    for relative, content in files.items():
        path = sandbox / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        changed_files=(
            "././src/main/java/App.java",
            ".migration/secret.xml",
            ".GitHub/workflow.yml",
            "TARGET/Generated.java",
        ),
    )

    context = build_repair_context_pack(failure_evidence=evidence, sandbox_path=sandbox)

    assert [entry["path"] for entry in context.source_evidence] == [
        "pom.xml",
        "src/main/java/App.java",
    ]


def test_source_evidence_excludes_symlink_escape(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "pom.xml").write_text("<project/>\n", encoding="utf-8")
    outside = tmp_path / "outside/Escape.java"
    outside.parent.mkdir(parents=True)
    outside.write_text("class Escape {}\n", encoding="utf-8")
    escaped_link = sandbox / "src/main/java/Escape.java"
    escaped_link.parent.mkdir(parents=True)
    blocked_target = sandbox / ".migration/Secret.java"
    blocked_target.parent.mkdir(parents=True)
    blocked_target.write_text("class Secret {}\n", encoding="utf-8")
    blocked_link = sandbox / "src/main/java/Internal.java"
    try:
        escaped_link.symlink_to(outside)
        blocked_link.symlink_to(blocked_target)
    except OSError as exc:
        pytest.skip(f"Symlink creation privilege unavailable: {exc}")
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        changed_files=("src/main/java/Escape.java", "src/main/java/Internal.java"),
    )

    context = build_repair_context_pack(failure_evidence=evidence, sandbox_path=sandbox)

    assert [entry["path"] for entry in context.source_evidence] == ["pom.xml"]


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
            invocation_ledger=_Ledger(),
        )
    assert "schema invalid" in str(exc_info.value)


def test_produce_raises_on_reviewer_reject_decision(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(reviewer_decision="reject")
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
            invocation_ledger=_Ledger(),
        )
    assert "reject" in str(exc_info.value)


def test_produce_raises_on_reviewer_checksum_mismatch(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(reviewer_response="__MISMATCH_CONTEXT__")
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
            invocation_ledger=_Ledger(),
        )
    assert "checksum mismatch" in str(exc_info.value)


def test_produce_success_with_accept_decision(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient()
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context_pack,
        output_dir=tmp_path / "output",
        model_client=client,
        invocation_ledger=_Ledger(),
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
    proposer_prompt = client.call_kwargs[0]["prompt"]
    reviewer_prompt = client.call_kwargs[1]["prompt"]
    assert "diff string must start with 'diff --git'" in proposer_prompt
    assert "Do NOT use '*** Begin Patch'" in proposer_prompt
    assert "Do NOT wrap the diff in markdown fences" in proposer_prompt
    assert "value for proposed_diff inside the JSON response" in proposer_prompt
    assert (
        "diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java\n"
        "--- a/src/main/java/com/example/App.java\n"
        "+++ b/src/main/java/com/example/App.java\n"
        "@@ -1,3 +1,3 @@\n"
        "-old\n"
        "+new\n"
    ) in proposer_prompt
    assert "Do not change a test merely to expect the current production exception" in proposer_prompt
    assert "Prefer fixing src/main/** production code" in proposer_prompt
    assert "Independently verify the diff is a canonical Git unified diff" in reviewer_prompt
    assert "Reject apply_patch wrapper syntax" in reviewer_prompt
    assert "assertThrows(CurrentProductionFailure.class" in reviewer_prompt
    chain = result["review_chain"]
    primary_path = tmp_path / "output" / "primary_repair_llm_output.json"
    final_path = tmp_path / "output" / "final_reviewed_repair_artifact.json"
    primary_artifact = json.loads(primary_path.read_text(encoding="utf-8"))
    final_artifact = json.loads(final_path.read_text(encoding="utf-8"))
    assert chain["primary_output_checksum"] == _compute_primary_repair_checksum(primary_artifact)
    assert chain["primary_validated_output_checksum"] == _compute_primary_repair_checksum(primary_artifact)
    assert chain["final_artifact_checksum"] == _compute_final_repair_artifact_checksum(final_artifact)
    assert chain["primary_output_artifact_checksum"] == sha256_hex(primary_path.read_bytes())
    assert chain["final_artifact_persisted_checksum"] == sha256_hex(final_path.read_bytes())
    assert chain["checksum_algorithms"]["primary_output_checksum"] == "sha256_canonical_json_v1"
    assert chain["checksum_algorithms"]["primary_validated_output_checksum"] == "sha256_canonical_json_v1"
    assert chain["checksum_algorithms"]["final_artifact_checksum"] == "sha256_canonical_json_v1"
    assert chain["checksum_algorithms"]["primary_output_artifact_checksum"] == "sha256_exact_bytes_v1"
    assert chain["checksum_algorithms"]["final_artifact_persisted_checksum"] == "sha256_exact_bytes_v1"


@pytest.mark.parametrize(
    ("name", "diff"),
    [
        (
            "apply_patch_wrapper",
            "*** Begin Patch\n*** Update File: src/main/java/App.java\n@@\n-old\n+new\n*** End Patch\n",
        ),
        (
            "markdown_fence",
            f"```diff\n{VALID_UNIFIED_DIFF}```\n",
        ),
        (
            "plain_instructions",
            "Replace App.java so it returns READY.\n",
        ),
    ],
)
def test_proposer_rejects_non_git_diff_before_reviewer_acceptance(tmp_path: Path, name: str, diff: str) -> None:
    ledger = RecordingLedger()
    output_dir = tmp_path / name
    client = SequenceRepairClient([
        _model_result(_primary_json_with_diff(diff, ["src/main/java/App.java"]), role="proposer"),
        _model_result("__ACCEPT__", role="reviewer"),
    ])

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _run_chain(tmp_path, client, ledger, output_name=name)

    assert exc_info.value.failure_code == "proposer_diff_not_git_unified"
    assert client.calls == [V2ModelRole.PROPOSER]
    assert [row["status"] for row in ledger.rows.values()] == ["failed"]
    _assert_fail_closed(output_dir, ledger)


def test_reviewer_cannot_accept_test_patch_that_masks_current_exception(tmp_path: Path) -> None:
    masking_diff = (
        "diff --git a/src/test/java/com/example/m1/MigrationBehaviorTest.java b/src/test/java/com/example/m1/MigrationBehaviorTest.java\n"
        "--- a/src/test/java/com/example/m1/MigrationBehaviorTest.java\n"
        "+++ b/src/test/java/com/example/m1/MigrationBehaviorTest.java\n"
        "@@ -1,6 +1,7 @@\n"
        " package com.example.m1;\n"
        " class MigrationBehaviorTest {\n"
        "   void migratedRuntimeBehaviorMustCompleteSuccessfully() {\n"
        "-    org.junit.jupiter.api.Assertions.assertEquals(\"READY\", new MigrationBehavior().run());\n"
        "+    org.junit.jupiter.api.Assertions.assertThrows(IllegalStateException.class, () -> new MigrationBehavior().run());\n"
        "   }\n"
        " }\n"
    )
    ledger = RecordingLedger()
    output_dir = tmp_path / "masking"
    client = SequenceRepairClient([
        _model_result(
            _primary_json_with_diff(
                masking_diff,
                ["src/test/java/com/example/m1/MigrationBehaviorTest.java"],
            ),
            role="proposer",
        ),
        _model_result("__ACCEPT__", role="reviewer"),
    ])

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _run_chain(tmp_path, client, ledger, output_name="masking")

    assert exc_info.value.failure_code == "reviewer_rejected"
    assert "expected_exception_masking" in str(exc_info.value)
    assert client.calls == [V2ModelRole.PROPOSER, V2ModelRole.REVIEWER]
    assert [row["status"] for row in ledger.rows.values()] == ["completed", "failed"]
    _assert_fail_closed(output_dir, ledger)


def test_invocation_correlation_and_provider_fallback_statuses(tmp_path: Path) -> None:
    ledger = RecordingLedger()
    client = SequenceRepairClient(
        [
            _model_result(
                _valid_primary_json(),
                role="proposer",
                provider="azure_secondary",
                source="azure_secondary",
                fallback_used=True,
            ),
            _model_result(
                "__ACCEPT__",
                role="reviewer",
                provider="azure_secondary",
                source="azure_secondary",
                fallback_used=True,
            ),
        ]
    )

    result = _run_chain(tmp_path, client, ledger)

    proposer_id = result["review_chain"]["proposer_invocation_id"]
    reviewer_id = result["review_chain"]["reviewer_invocation_id"]
    assert proposer_id != reviewer_id
    proposer = ledger.rows[proposer_id]
    reviewer = ledger.rows[reviewer_id]
    for row in (proposer, reviewer):
        assert row["job_id"] == "job-corr"
        assert row["stage_index"] == 3
        assert row["attempt_number"] == 7
        assert row["proposal_id"] == "proposal-123"
        assert row["gate_id"] == "gate-123"
        assert row["status"] == "fallback"
        assert row["accepted_provider_source"] == "azure_secondary"
        assert row["deterministic_fallback_used"] is False
    assert proposer["responsibility"] == "repair_proposal"
    assert reviewer["responsibility"] == "repair_review"
    assert (tmp_path / "chain" / "final_reviewed_repair_artifact.json").exists()
    assert not list((tmp_path / "chain").glob("*candidate*"))
    assert not list((tmp_path / "chain").glob("*approval*"))
    assert not list((tmp_path / "chain").glob("*apply*"))


@pytest.mark.parametrize(
    ("name", "results", "expected_status", "expected_reason"),
    [
        (
            "primary_invalid_json",
            [_model_result("not json", role="proposer")],
            ["failed"],
            "valid JSON",
        ),
        (
            "primary_schema_invalid",
            [_model_result(json.dumps({"schema_version": "1.0"}), role="proposer")],
            ["failed"],
            "schema invalid",
        ),
        (
            "primary_invalid_diff_path",
            [
                _model_result(
                    json.dumps(
                        {
                            **json.loads(_valid_primary_json()),
                            "changed_files": ["../escape.java"],
                            "proposed_diff": "plain text",
                        },
                        sort_keys=True,
                    ),
                    role="proposer",
                )
            ],
            ["failed"],
            "invalid primary repair output",
        ),
        (
            "reviewer_invalid_json",
            [_model_result(_valid_primary_json(), role="proposer"), _model_result("not json", role="reviewer")],
            ["completed", "failed"],
            "valid JSON",
        ),
        (
            "reviewer_checksum_mismatch",
            [_model_result(_valid_primary_json(), role="proposer"), _model_result("__MISMATCH_CONTEXT__", role="reviewer")],
            ["completed", "failed"],
            "checksum mismatch",
        ),
        (
            "reviewer_revise",
            [
                _model_result(_valid_primary_json(), role="proposer"),
                _model_result("__REVISE__", role="reviewer"),
            ],
            ["completed", "failed"],
            "reviewer decision failed closed: revise",
        ),
        (
            "reviewer_reject",
            [
                _model_result(_valid_primary_json(), role="proposer"),
                _model_result("__REJECT__", role="reviewer"),
            ],
            ["completed", "failed"],
            "reviewer decision failed closed: reject",
        ),
        (
            "deterministic_proposer_fallback",
            [
                _model_result(
                    "fallback",
                    role="proposer",
                    success=False,
                    source="deterministic",
                    provider="deterministic",
                    model_status="fallback",
                    failure_reason="missing_deployment",
                    fallback_used=True,
                )
            ],
            ["fallback"],
            "primary repair model failed closed",
        ),
        (
            "deterministic_reviewer_fallback",
            [
                _model_result(_valid_primary_json(), role="proposer"),
                _model_result(
                    "fallback",
                    role="reviewer",
                    success=False,
                    source="deterministic",
                    provider="deterministic",
                    model_status="fallback",
                    failure_reason="missing_deployment",
                    fallback_used=True,
                ),
            ],
            ["completed", "fallback"],
            "reviewer repair model failed closed",
        ),
    ],
)
def test_terminal_ledger_failure_states(
    tmp_path: Path,
    name: str,
    results: list[V2AssistantModelResult],
    expected_status: list[str],
    expected_reason: str,
) -> None:
    ledger = RecordingLedger()
    output_dir = tmp_path / name
    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _run_chain(tmp_path, SequenceRepairClient(results), ledger, output_name=name)

    assert expected_reason in str(exc_info.value)
    assert [row["status"] for row in ledger.rows.values()] == expected_status
    _assert_fail_closed(output_dir, ledger)
    if "deterministic" in name:
        terminal = list(ledger.rows.values())[-1]
        assert terminal["deterministic_fallback_used"] is True
        assert terminal["accepted_provider_source"] == "deterministic"


def test_proposer_output_truncated_fails_before_json_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import migration_factory.orchestrator.repair_review_chain as module

    ledger = RecordingLedger()
    output_dir = tmp_path / "truncated"
    client = SequenceRepairClient(
        [
            _model_result(
                '{"schema_version":"1.0","root_cause":"partial',
                role="proposer",
                success=False,
                model_status="fallback",
                failure_reason="output_truncated",
                source="deterministic",
                provider="deterministic",
                fallback_used=True,
            )
        ]
    )

    def fail_if_parsed(*_: Any, **__: Any) -> dict[str, Any]:
        raise AssertionError("truncated provider output must not be parsed")

    monkeypatch.setattr(module, "_parse_strict_json_object", fail_if_parsed)

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _run_chain(tmp_path, client, ledger, output_name="truncated")

    assert exc_info.value.failure_code == "proposer_output_truncated"
    assert [row["status"] for row in ledger.rows.values()] == ["fallback"]
    _assert_fail_closed(output_dir, ledger)


def test_malformed_completed_primary_json_is_proposer_schema_invalid(tmp_path: Path) -> None:
    ledger = RecordingLedger()
    output_dir = tmp_path / "malformed"

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        _run_chain(
            tmp_path,
            SequenceRepairClient([_model_result("{\"schema_version\":\"1.0\"", role="proposer")]),
            ledger,
            output_name="malformed",
        )

    assert exc_info.value.failure_code == "proposer_schema_invalid"
    assert [row["status"] for row in ledger.rows.values()] == ["failed"]
    _assert_fail_closed(output_dir, ledger)


def test_large_valid_primary_diff_proceeds_to_reviewer_without_apply_or_approval(tmp_path: Path) -> None:
    ledger = RecordingLedger()
    output_dir = tmp_path / "large_valid"
    client = SequenceRepairClient(
        [
            _model_result(_large_valid_primary_json(), role="proposer"),
            _model_result("__ACCEPT__", role="reviewer"),
        ]
    )

    result = _run_chain(tmp_path, client, ledger, output_name="large_valid")

    assert client.calls == [V2ModelRole.PROPOSER, V2ModelRole.REVIEWER]
    assert result["review_chain"]["reviewer_decision"] == "accept"
    assert len((output_dir / "final_reviewed_repair.diff").read_text(encoding="utf-8")) > 700
    assert not list(output_dir.glob("*candidate*"))
    assert not list(output_dir.glob("*approval*"))
    assert not list(output_dir.glob("*apply*"))


def test_primary_artifact_write_failure_gets_terminal_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import migration_factory.orchestrator.repair_review_chain as module

    ledger = RecordingLedger()
    real_write_json = module._write_json

    def fail_primary_artifact(path: Path, payload: Any) -> None:
        if path.name == "primary_repair_llm_output.json":
            raise OSError("artifact write blocked")
        real_write_json(path, payload)

    monkeypatch.setattr(module, "_write_json", fail_primary_artifact)
    output_dir = tmp_path / "primary_artifact_write"
    with pytest.raises(RepairReviewChainProductionError):
        _run_chain(tmp_path, SequenceRepairClient([_model_result(_valid_primary_json(), role="proposer")]), ledger, output_name="primary_artifact_write")

    assert [row["status"] for row in ledger.rows.values()] == ["failed"]
    _assert_fail_closed(output_dir, ledger)


def test_reviewer_final_artifact_write_failure_gets_terminal_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import migration_factory.orchestrator.repair_review_chain as module

    ledger = RecordingLedger()
    real_write_json = module._write_json

    def fail_final_artifact(path: Path, payload: Any) -> None:
        if path.name == "final_reviewed_repair_artifact.json":
            raise OSError("final artifact write blocked")
        real_write_json(path, payload)

    monkeypatch.setattr(module, "_write_json", fail_final_artifact)
    output_dir = tmp_path / "reviewer_final_artifact_write"
    with pytest.raises(RepairReviewChainProductionError):
        _run_chain(
            tmp_path,
            SequenceRepairClient([
                _model_result(_valid_primary_json(), role="proposer"),
                _model_result("__ACCEPT__", role="reviewer"),
            ]),
            ledger,
            output_name="reviewer_final_artifact_write",
        )

    assert [row["status"] for row in ledger.rows.values()] == ["completed", "failed"]
    _assert_fail_closed(output_dir, ledger)


def test_produce_accepts_real_provider_fallback(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient()

    original_answer = client.answer_with_role

    def answer_with_fallback_marker(**kwargs: Any) -> V2AssistantModelResult:
        result = original_answer(**kwargs)
        return V2AssistantModelResult(
            content=result.content,
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role=result.role,
            success=True,
            redacted_summary=result.redacted_summary,
            failure_reason="",
            fallback_used=True,
            exact_provider_content=result.content,
        )

    client.answer_with_role = answer_with_fallback_marker  # type: ignore[method-assign]
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context_pack,
        output_dir=tmp_path / "output",
        model_client=client,
        invocation_ledger=_Ledger(),
    )

    assert result["review_chain"]["primary_fallback_used"] is True
    assert result["review_chain"]["reviewer_fallback_used"] is True
    assert result["review_chain"]["primary_provider_source"] == "azure_openai"


def test_produce_requires_mandatory_invocation_ledger(tmp_path: Path) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient()

    with pytest.raises(RepairReviewChainProductionError, match="mandatory invocation ledger"):
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "output",
            model_client=client,
        )
    assert client.calls == []


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
            invocation_ledger=_Ledger(),
        )
    assert "failed closed" in str(exc_info.value)


@pytest.mark.parametrize("decision", ["reject", "revise"])
def test_reviewer_non_accept_decision_has_stable_governed_classification(
    tmp_path: Path,
    decision: str,
) -> None:
    evidence = _make_evidence()
    context_pack = _make_context(evidence)
    client = FakeRepairClient(reviewer_decision=decision)
    ledger = RecordingLedger()

    with pytest.raises(RepairReviewChainProductionError) as exc_info:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / decision,
            model_client=client,
            invocation_ledger=ledger,
        )

    assert exc_info.value.failure_code == "reviewer_rejected"
    assert [row["status"] for row in ledger.rows.values()] == ["completed", "failed"]
    assert not (tmp_path / decision / "final_reviewed_repair_artifact.json").exists()
    assert not (tmp_path / decision / "final_reviewed_repair.diff").exists()
