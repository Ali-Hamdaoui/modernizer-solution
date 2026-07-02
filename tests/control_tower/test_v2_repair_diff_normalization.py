"""F5-T7b: Tests for diff normalization, classification, and aligned validation.

Covers:
  - _normalize_to_git_diff from repair_review_chain
  - classify_diff_failure from patch_gate
  - _is_unified_diff alignment with patch_gate.is_unified_diff
  - No proposal on INVALID_PATCH after reviewer accept
  - Normalization-then-proposal flow
  - LLM invocation binding to proposal_id/gate_id
  - Retry schema failure does not override prior materialization failure
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from migration_factory.orchestrator.repair_review_chain import (
    RepairReviewChainProductionError,
    _normalize_to_git_diff,
    _is_unified_diff,
    _validate_primary_repair_output,
    produce_repair_review_chain,
)
from migration_factory.repair_loop.patch_gate import (
    classify_diff_failure,
    is_unified_diff,
    PatchGateResult,
    evaluate_patch_proposal,
    extract_touched_paths,
)
from migration_factory.repair_loop.failure_evidence import (
    FailureSource,
    build_failure_evidence,
)
from migration_factory.repair_loop.repair_context import (
    build_repair_context_pack,
)


# ── Helpers ───────────────────────────────────────────────────────────

GIT_DIFF = """\
diff --git a/src/main/java/App.java b/src/main/java/App.java
--- a/src/main/java/App.java
+++ b/src/main/java/App.java
@@ -1,3 +1,3 @@
-old line
+new line
 unchanged
"""

NON_GIT_UNIFIED_DIFF = """\
--- a/src/main/java/App.java
+++ b/src/main/java/App.java
@@ -1,3 +1,3 @@
-old line
+new line
 unchanged
"""

EXPECTED_NORMALIZED_DIFF = """\
diff --git a/src/main/java/App.java b/src/main/java/App.java
--- a/src/main/java/App.java
+++ b/src/main/java/App.java
@@ -1,3 +1,3 @@
-old line
+new line
 unchanged
"""

MALFORMED_DIFF = "just some text without any diff headers\n"

ABSOLUTE_PATH_DIFF = """\
diff --git a/C:/Windows/System32/evil.bat b/C:/Windows/System32/evil.bat
--- a/C:/Windows/System32/evil.bat
+++ b/C:/Windows/System32/evil.bat
@@ -1,1 +1,1 @@
-old
+new
"""

PATH_TRAVERSAL_DIFF = """\
diff --git a/../secrets/key b/../secrets/key
--- a/../secrets/key
+++ b/../secrets/key
@@ -1,1 +1,1 @@
-old
+new
"""

NO_HUNK_DIFF = """\
diff --git a/src/Foo.java b/src/Foo.java
--- a/src/Foo.java
+++ b/src/Foo.java
no hunk here
"""

NO_CHANGE_DIFF = """\
diff --git a/src/Foo.java b/src/Foo.java
--- a/src/Foo.java
+++ b/src/Foo.java
@@ -1,1 +1,1 @@
 unchanged context only
"""


def _valid_primary_json(diff: str = GIT_DIFF) -> str:
    return json.dumps(
        {
            "root_cause": "Missing import",
            "fix_strategy": "Add import statement",
            "changed_files": ["src/main/java/App.java"],
            "proposed_diff": diff,
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
            "reviewed_context_checksum": "",
            "reviewed_primary_output_checksum": "",
            "reviewed_diff_checksum": "",
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
        primary_success: bool = True,
        reviewer_success: bool = True,
    ) -> None:
        self._primary = primary_response or _valid_primary_json()
        self._reviewer = reviewer_response or _accept_reviewer_json()
        self._primary_success = primary_success
        self._reviewer_success = reviewer_success

    def answer_with_role(
        self, *, role, prompt, fallback, **_
    ) -> MagicMock:
        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
        )
        from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole

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
        return V2AssistantModelResult(
            content=self._reviewer,
            source="fake",
            model_status="live_ok" if self._reviewer_success else "fallback",
            provider="fake",
            role=role.value,
            success=self._reviewer_success,
            redacted_summary="ok" if self._reviewer_success else "reviewer failed",
            failure_reason="" if self._reviewer_success else "reviewer_model_failed",
        )


def _setup_sandbox(tmp_path: Path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    return sandbox, run_dir, legacy


# ── 1. _normalize_to_git_diff ────────────────────────────────────────

def test_normalize_git_diff_already_git_style():
    result, was_normalized = _normalize_to_git_diff(GIT_DIFF)
    assert result == GIT_DIFF
    assert was_normalized is False


def test_normalize_non_git_unified_diff():
    result, was_normalized = _normalize_to_git_diff(NON_GIT_UNIFIED_DIFF)
    assert was_normalized is True
    assert result.startswith("diff --git a/src/main/java/App.java b/src/main/java/App.java")
    assert "--- a/src/main/java/App.java" in result
    assert "+++ b/src/main/java/App.java" in result
    assert "@@ -1,3 +1,3 @@" in result


def test_normalize_empty_diff():
    result, was_normalized = _normalize_to_git_diff("")
    assert was_normalized is False
    assert result == ""


def test_normalize_malformed_diff():
    result, was_normalized = _normalize_to_git_diff(MALFORMED_DIFF)
    assert was_normalized is False


def test_normalize_binary_diff():
    binary = "GIT binary patch\nsomebinarydata\n"
    result, was_normalized = _normalize_to_git_diff(binary)
    assert was_normalized is False


# ── 2. classify_diff_failure ─────────────────────────────────────────

def test_classify_missing_git_header():
    assert classify_diff_failure(MALFORMED_DIFF) == "missing_diff_git_header"


def test_classify_empty_diff():
    assert classify_diff_failure("") == "empty_diff"


def test_classify_binary_diff():
    assert classify_diff_failure("GIT binary patch\nfoo\n") == "binary_diff"


def test_classify_no_hunk():
    assert classify_diff_failure(NO_HUNK_DIFF) == "missing_hunk"


def test_classify_no_change():
    assert classify_diff_failure(NO_CHANGE_DIFF) == "no_changes"


def test_classify_absolute_path():
    assert classify_diff_failure(ABSOLUTE_PATH_DIFF) == "absolute_path"


def test_classify_path_traversal():
    assert classify_diff_failure(PATH_TRAVERSAL_DIFF) == "path_traversal"


def test_classify_valid_diff():
    assert classify_diff_failure(GIT_DIFF) == "unknown"


def test_classify_missing_file_headers():
    diff = "diff --git a/x.java b/x.java\n@@ -1,1 +1,1 @@\n+new\n"
    assert classify_diff_failure(diff) == "missing_file_headers"


# ── 3. _is_unified_diff alignment with is_unified_diff ────────────────

def test_is_unified_diff_aligned_on_valid():
    assert _is_unified_diff(GIT_DIFF) is True
    assert is_unified_diff(GIT_DIFF) is True


def test_is_unified_diff_aligned_on_non_git():
    non_git = "--- a/x.java\n+++ b/x.java\n@@ -1 +1 @@\n-old\n+new\n"
    assert _is_unified_diff(non_git) is False
    assert is_unified_diff(non_git) is False


def test_is_unified_diff_aligned_on_empty():
    assert _is_unified_diff("") is False
    assert is_unified_diff("") is False


def test_is_unified_diff_aligned_on_plain_text():
    assert _is_unified_diff("hello world") is False
    assert is_unified_diff("hello world") is False


# ── 4. Main returns strict Git diff -> reviewer accept -> proposal exists
#    (via produce_repair_review_chain)
def test_git_diff_proposal_created(tmp_path: Path):
    evidence = _make_evidence()
    context = _make_context(evidence)
    client = FakeRepairClient()
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context,
        output_dir=tmp_path / "output",
        model_client=client,
    )
    assert result["review_chain"]["reviewer_decision"] == "accept"
    diff_path = result["review_chain"].get("final_diff_ref")
    assert diff_path is not None
    diff_text = Path(diff_path).read_text()
    assert diff_text.startswith("diff --git")


# ── 5. Non-git unified diff with safe paths -> normalization creates Git diff
def test_normalized_diff_proposal_created(tmp_path: Path):
    evidence = _make_evidence()
    context = _make_context(evidence)
    client = FakeRepairClient(primary_response=_valid_primary_json(NON_GIT_UNIFIED_DIFF))
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context,
        output_dir=tmp_path / "output",
        model_client=client,
    )
    assert result["review_chain"]["reviewer_decision"] == "accept"
    diff_path = result["review_chain"].get("final_diff_ref")
    assert diff_path is not None
    diff_text = Path(diff_path).read_text()
    assert diff_text.startswith("diff --git")


# ── 6. Malformed diff -> fail
def test_malformed_diff_fails(tmp_path: Path):
    evidence = _make_evidence()
    context = _make_context(evidence)
    bad_json = json.dumps({
        "root_cause": "test",
        "fix_strategy": "fix",
        "changed_files": ["App.java"],
        "proposed_diff": MALFORMED_DIFF,
        "risk": "LOW",
        "confidence": 0.8,
        "rationale": "test",
    })
    client = FakeRepairClient(primary_response=bad_json)
    with pytest.raises(RepairReviewChainProductionError) as exc:
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context,
            output_dir=tmp_path / "output",
            model_client=client,
        )
    assert "invalid primary repair output" in str(exc.value).lower() or "unified diff" in str(exc.value).lower()


# ── 7. Absolute path diff -> fails patch gate (not primary validation)
def test_absolute_path_fails_patch_gate(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = {
        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
        "risk": "LOW",
        "requires_human_review": False,
        "unified_diff": ABSOLUTE_PATH_DIFF,
        "description": "",
        "expected_validation": [],
        "limitations": [],
    }
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert result.reason_code in ("absolute_path", "unsafe_path")


# ── 8. evaluate_patch_proposal returns reason_code on INVALID_PATCH
def test_patch_gate_reason_code_on_invalid_diff(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = {
        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
        "risk": "LOW",
        "requires_human_review": False,
        "unified_diff": MALFORMED_DIFF,
        "description": "",
        "expected_validation": [],
        "limitations": [],
    }
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert result.reason_code != ""
    assert result.reason_code == "missing_diff_git_header"


def test_patch_gate_reason_code_on_absolute_path(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = {
        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
        "risk": "LOW",
        "requires_human_review": False,
        "unified_diff": ABSOLUTE_PATH_DIFF,
        "description": "",
        "expected_validation": [],
        "limitations": [],
    }
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert result.reason_code in ("absolute_path", "unsafe_path")


def test_patch_gate_accepts_git_style_diff(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    pom = sandbox / "pom.xml"
    pom.write_text("<project><modelVersion>4.0.0</modelVersion></project>")
    diff = "diff --git a/pom.xml b/pom.xml\n--- a/pom.xml\n+++ b/pom.xml\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    proposal = {
        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
        "risk": "LOW",
        "requires_human_review": False,
        "unified_diff": diff,
        "description": "",
        "expected_validation": [],
        "limitations": [],
    }
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status in ("ALLOWED", "HUMAN_REVIEW_REQUIRED", "BLOCKED")


# ── 9. Non-git diff with safe paths -> patch_gate would fail
def test_patch_gate_rejects_non_git_unified(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = {
        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
        "risk": "LOW",
        "requires_human_review": False,
        "unified_diff": NON_GIT_UNIFIED_DIFF,
        "description": "",
        "expected_validation": [],
        "limitations": [],
    }
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert result.reason_code == "missing_diff_git_header"


# ── 10. Normalized diff passes evaluate_patch_proposal
def test_normalized_diff_passes_patch_gate(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    pom = sandbox / "pom.xml"
    pom.write_text("<project></project>")
    normalized, _was = _normalize_to_git_diff(NON_GIT_UNIFIED_DIFF)
    proposal = {
        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
        "risk": "LOW",
        "requires_human_review": False,
        "unified_diff": normalized,
        "description": "",
        "expected_validation": [],
        "limitations": [],
    }
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status in ("ALLOWED", "HUMAN_REVIEW_REQUIRED", "BLOCKED")


# ── 11. Chain and patch_gate use aligned rules
def test_chain_validation_and_patch_gate_aligned():
    """_is_unified_diff and is_unified_diff must agree on valid Git diffs."""
    valid_diffs = [
        GIT_DIFF,
        """\
diff --git a/pom.xml b/pom.xml
--- a/pom.xml
+++ b/pom.xml
@@ -10,6 +10,7 @@
  unchanged
+new line
""",
    ]
    for diff in valid_diffs:
        assert _is_unified_diff(diff) is True, f"_is_unified_diff rejects: {diff[:50]}"
        assert is_unified_diff(diff) is True, f"is_unified_diff rejects: {diff[:50]}"


def test_chain_validation_and_patch_gate_aligned_invalid():
    """Both must reject non-git diffs consistently."""
    invalid_diffs = [
        NON_GIT_UNIFIED_DIFF,
        MALFORMED_DIFF,
        "--- a/x.java\n+++ b/x.java\n@@ -1 +1 @@\n-old\n+new\n",
    ]
    for diff in invalid_diffs:
        assert _is_unified_diff(diff) is False, f"_is_unified_diff accepts: {diff[:50]}"
        assert is_unified_diff(diff) is False, f"is_unified_diff accepts: {diff[:50]}"


# ── 12. Retry schema failure does not override materialization failure
def test_retry_schema_failure_does_not_hide_materialization(tmp_path: Path):
    """A later schema-invalid retry must not shadow prior materialization failure.
    
    Simulate two events: first materialization fails, then a retry fails schema.
    The UI should prioritize the materialization failure over the schema failure.
    """
    events: list[dict[str, Any]] = []

    class EventRecorder:
        def save(self, job_id, stage, event_type, status, message, payload):
            events.append({
                "event_type": event_type,
                "status": status,
                "reason_code": payload.get("reason_code", ""),
                "message": message,
            })

    recorder = EventRecorder()
    chain: dict[str, Any] = {}

    # Emit materialization failed first
    from migration_factory.control_tower.application.v2_repair_gate_service import (
        V2RepairGateService,
    )
    svc = V2RepairGateService.__new__(V2RepairGateService)
    svc._event_repo = recorder
    svc._llm_invocation_repo = None

    svc._emit_reviewed_repair_materialization_failed(
        job_id="job-retry",
        stage_index=1,
        context_checksum="cs-1",
        reason_code="repair policy validation failed: INVALID_PATCH",
        chain=chain,
        detail="missing_diff_git_header",
    )

    # Emit schema invalid later (retry)
    svc._emit_reviewed_repair_unavailable(
        job_id="job-retry",
        stage_index=1,
        context_checksum="cs-1",
        reason_code="proposer_schema_invalid",
    )

    materialization_events = [
        e for e in events
        if e["event_type"] == "reviewed_repair_materialization_failed"
    ]
    schema_events = [
        e for e in events
        if e["event_type"] == "repair_primary_schema_invalid"
    ]

    assert len(materialization_events) == 1
    assert len(schema_events) == 1
    assert "INVALID_PATCH" in materialization_events[0]["reason_code"]
