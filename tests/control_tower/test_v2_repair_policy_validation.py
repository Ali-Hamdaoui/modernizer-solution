"""F5-T7: Policy Validation Before Gate Presentation — unit tests.

Tests cover:
  - is_unified_diff (patch_gate)
  - extract_touched_paths
  - validate_patch_paths
  - evaluate_patch_proposal
  - _is_unified_diff (repair_review_chain)
  - _check_forbidden_paths_in_diff
  - _check_forbidden_keys
  - evaluate_rule / RuleDecision
  - PatchGateResult statuses
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from migration_factory.repair_loop.patch_gate import (
    BLOCKED_FILE_NAMES,
    BLOCKED_PARTS,
    BLOCKED_PREFIXES,
    PATCH_SOURCE_LLM_REVIEWED,
    POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
    REASON_DELETE_BLOCKED,
    REASON_EXPECTED_EXCEPTION_MASKING,
    REASON_RENAME_BLOCKED,
    REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH,
    REASON_ROUTE_SCOPE_VIOLATION,
    REASON_SECURITY_SENSITIVE_MODIFICATION,
    REASON_SHARED_PATH_VALIDATION_FAILED,
    REASON_TEST_DISABLED_OR_SKIPPED,
    REASON_TRIVIALLY_PASSING_ASSERTION,
    REASON_UNSUPPORTED_FILE_EXTENSION,
    REVIEWED_LLM_DECISION_ALLOWED,
    REVIEWED_LLM_DECISION_BLOCKED,
    PatchGateResult,
    evaluate_patch_proposal,
    evaluate_reviewed_llm_patch,
    extract_touched_paths,
    is_unified_diff,
    reviewed_llm_allowed_route_scope,
    reviewed_llm_policy_payload,
    reviewed_llm_policy_checksum_input,
    validate_patch_paths,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, sha256_hex
from migration_factory.repair_loop.rule_registry import (
    ALLOWED_RULE_IDS,
    RuleDecision,
    evaluate_rule,
)
from migration_factory.orchestrator.repair_review_chain import (
    _check_forbidden_keys,
    _check_forbidden_paths_in_diff,
    _is_unified_diff,
)


# ── Shared helpers ──────────────────────────────────────────────────

VALID_DIFF = """\
diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java
--- a/src/main/java/com/example/App.java
+++ b/src/main/java/com/example/App.java
@@ -10,6 +10,7 @@
 package com.example;
+import jakarta.validation.Valid;
 public class App {
     public static void main(String[] args) {
-        System.out.println("Hello");
+        System.out.println("Hello Jakarta");
     }
 }
"""

DIFF_NO_HEADER = "just some text\n+added line\n-old line\n"

DIFF_NO_PLUS_MINUS = """\
diff --git a/foo.java b/foo.java
--- a/foo.java
+++ b/foo.java
@@ -1,1 +1,1 @@
 unchanged context
"""

BINARY_DIFF = """\
diff --git a/foo.bin b/foo.bin
GIT binary patch
some binary
"""

APPLYABLE_APP_DIFF = """\
diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java
--- a/src/main/java/com/example/App.java
+++ b/src/main/java/com/example/App.java
@@ -1,6 +1,6 @@
 package com.example;
 public class App {
     public static void main(String[] args) {
-        System.out.println("Hello");
+        System.out.println("Hello Jakarta");
     }
 }
"""


def _make_proposal(**overrides):
    base = {
        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
        "risk": "LOW",
        "unified_diff": VALID_DIFF,
        "requires_human_review": False,
        "description": "",
        "expected_validation": [],
        "limitations": [],
    }
    base.update(overrides)
    return base


def _setup_sandbox(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    return sandbox, run_dir, legacy


def _reviewed_policy_kwargs(
    tmp_path,
    diff: str,
    *,
    changed_files: tuple[str, ...] = ("src/main/java/com/example/App.java",),
    allowed_route_scope: tuple[str, ...] | None = None,
    sandbox_files: dict[str, str] | None = None,
):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    files = sandbox_files or {
        "src/main/java/com/example/App.java": (
            "package com.example;\n"
            "public class App {\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(\"Hello\");\n"
            "    }\n"
            "}\n"
        )
    }
    for relative_path, text in files.items():
        path = sandbox / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    patch_path = run_dir / "reviewed.diff"
    patch_path.write_text(diff, encoding="utf-8")
    checksum = "sha256:" + sha256_hex(patch_path.read_bytes())
    return {
        "reviewed_diff_bytes": patch_path.read_bytes(),
        "reviewed_diff_path": patch_path,
        "reviewed_diff_checksum": checksum,
        "sandbox_path": sandbox,
        "run_dir": run_dir,
        "legacy_path": legacy,
        "declared_changed_files": changed_files,
        "allowed_route_scope": allowed_route_scope
        if allowed_route_scope is not None
        else reviewed_llm_allowed_route_scope(route="llm_reviewed_unknown", stage_index=1),
        "job_id": "job-policy",
        "stage_index": 1,
        "command_id": "cmd-policy",
        "route": "llm_reviewed_unknown",
        "failure_evidence_checksum": "sha256:" + "1" * 64,
        "context_checksum": "sha256:" + "2" * 64,
        "base_repo_state_checksum": "sha256:" + "3" * 64,
        "reviewer_output_checksum": "sha256:" + "4" * 64,
        "review_chain_identity_checksum": "sha256:" + "5" * 64,
    }


# ── 1. is_unified_diff — valid diff ─────────────────────────────────

def test_is_unified_diff_returns_true_for_valid_diff():
    assert is_unified_diff(VALID_DIFF) is True


# ── 2. is_unified_diff — invalid diffs ──────────────────────────────

def test_is_unified_diff_returns_false_for_plain_text():
    assert is_unified_diff(DIFF_NO_HEADER) is False


def test_is_unified_diff_returns_false_for_empty():
    assert is_unified_diff("") is False


def test_is_unified_diff_returns_false_for_whitespace_only():
    assert is_unified_diff("   \n  \n ") is False


def test_is_unified_diff_returns_false_for_binary():
    assert is_unified_diff(BINARY_DIFF) is False


def test_is_unified_diff_returns_false_for_missing_at():
    diff = "diff --git a/x.java b/x.java\n--- a/x.java\n+++ b/x.java\nno change\n"
    assert is_unified_diff(diff) is False


# ── 3. extract_touched_paths ────────────────────────────────────────

def test_extract_touched_paths_from_valid_diff():
    paths, errors = extract_touched_paths(VALID_DIFF)
    assert not errors
    assert "src/main/java/com/example/App.java" in paths


def test_extract_touched_paths_strips_ab_prefix():
    diff = """\
diff --git a/src/main/Foo.java b/src/main/Foo.java
--- a/src/main/Foo.java
+++ b/src/main/Foo.java
@@ -1,1 +1,1 @@
"""
    paths, errors = extract_touched_paths(diff)
    assert not errors
    assert paths == ["src/main/Foo.java"]


def test_extract_touched_paths_skips_devnull():
    diff = """\
diff --git a/old.txt /dev/null
--- a/old.txt
+++ /dev/null
@@ -1,1 +0,0 @@
"""
    paths, errors = extract_touched_paths(diff)
    assert "old.txt" in paths
    assert "/dev/null" not in paths


def test_extract_touched_paths_malformed_header():
    diff = "diff --git a/only\nno other lines\n"
    paths, errors = extract_touched_paths(diff)
    assert "malformed diff --git header" in errors


def test_extract_touched_paths_empty_returns_error():
    paths, errors = extract_touched_paths("")
    assert not paths
    assert any("no touched paths" in err for err in errors)


# ── 4. validate_patch_paths rejects absolute paths ──────────────────

def test_validate_patch_paths_rejects_absolute(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    errors = validate_patch_paths(
        ["/etc/passwd", "C:\\Windows\\System32\\evil.bat"],
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert len(errors) == 2
    assert any("absolute" in err.lower() for err in errors)


# ── 5. validate_patch_paths rejects .. traversal ────────────────────

def test_validate_patch_paths_rejects_dotdot(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    errors = validate_patch_paths(
        ["../etc/conf.txt", "src/../../lib/util.txt"],
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert len(errors) == 2
    assert all("traversal" in err for err in errors)


# ── 6. validate_patch_paths rejects blocked dirs ────────────────────

@pytest.mark.parametrize("blocked", sorted(BLOCKED_PARTS))
def test_validate_patch_paths_rejects_blocked_dirs(tmp_path, blocked):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    errors = validate_patch_paths(
        [f"{blocked}/config.json", f"some/nested/{blocked}/data.txt"],
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert len(errors) == 2
    assert all("blocked generated/internal" in err for err in errors)


# ── 7. validate_patch_paths rejects blocked filenames ───────────────

@pytest.mark.parametrize("blocked_name", sorted(BLOCKED_FILE_NAMES))
def test_validate_patch_paths_rejects_blocked_filenames(tmp_path, blocked_name):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    errors = validate_patch_paths(
        [blocked_name, f"config/{blocked_name}"],
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert len(errors) == 2
    assert all("blocked deployment/env" in err for err in errors)


# ── 8. validate_patch_paths rejects deployment/ prefix ──────────────

@pytest.mark.parametrize("prefix", BLOCKED_PREFIXES)
def test_validate_patch_paths_rejects_blocked_prefixes(tmp_path, prefix):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    errors = validate_patch_paths(
        [f"{prefix}config.yml", f"{prefix}kube/admin.yaml"],
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert len(errors) == 2
    assert all("blocked deployment/release" in err for err in errors)


# ── 9. validate_patch_paths allows safe paths ───────────────────────

def test_validate_patch_paths_allows_safe_paths(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    errors = validate_patch_paths(
        [
            "src/main/java/com/example/App.java",
            "src/main/resources/application.properties",
            "pom.xml",
            "src/test/java/com/example/AppTest.java",
        ],
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert not errors


# ── 10. evaluate_patch_proposal blocks missing rule_id ─────────────

def test_evaluate_patch_proposal_blocks_missing_rule_id(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = _make_proposal(deterministic_rule_id="")
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert "missing deterministic_rule_id" in result.reason.lower()


def test_evaluate_patch_proposal_blocks_none_rule_id(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = _make_proposal()
    del proposal["deterministic_rule_id"]
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"


# ── 11. evaluate_patch_proposal blocks high risk ────────────────────

def test_evaluate_patch_proposal_blocks_high_risk(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = _make_proposal(risk="HIGH")
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "HUMAN_REVIEW_REQUIRED"
    assert result.human_review_required is True
    assert "not low" in result.reason.lower()


def test_evaluate_patch_proposal_blocks_medium_risk(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = _make_proposal(risk="MEDIUM")
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "HUMAN_REVIEW_REQUIRED"


def test_evaluate_patch_proposal_blocks_requires_human_review_flag(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = _make_proposal(risk="LOW", requires_human_review=True)
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "HUMAN_REVIEW_REQUIRED"
    assert "requires human review" in result.reason.lower()


# ── 12. evaluate_patch_proposal blocks non-unified diff ────────────

def test_evaluate_patch_proposal_blocks_non_unified_diff(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    proposal = _make_proposal(unified_diff="just some text without diff headers")
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert "not a unified diff" in result.reason.lower()


# ── 13. evaluate_patch_proposal allows valid proposal ──────────────

def test_evaluate_patch_proposal_allows_valid_proposal(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    pom = sandbox / "pom.xml"
    pom.write_text(
        """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0</version>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.0</version>
  </parent>
  <properties><spring-boot.version>3.2.0</spring-boot.version></properties>
</project>"""
    )

    diff = """\
diff --git a/pom.xml b/pom.xml
--- a/pom.xml
+++ b/pom.xml
@@ -10,6 +10,11 @@
   <version>1.0</version>
+  <dependency>
+    <groupId>com.h2database</groupId>
+    <artifactId>h2</artifactId>
+    <scope>runtime</scope>
+  </dependency>
 </project>
"""
    proposal = _make_proposal(unified_diff=diff, deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME")
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
        h2_required=True,
    )
    assert result.status == "ALLOWED"


# ── 14. _check_forbidden_paths_in_diff catches sandbox_path ────────

def test_check_forbidden_paths_in_diff_catches_sandbox_path():
    diff = "sandbox_path: /some/path/in/patch\n+some code\n"
    failures = _check_forbidden_paths_in_diff(diff)
    assert len(failures) >= 1
    assert any("sandbox_path" in f for f in failures)


def test_check_forbidden_paths_in_diff_catches_migration():
    diff = "--- a/.migration/stage.json\n+++ b/.migration/stage.json\n@@ -1,1 +1,1 @@"
    failures = _check_forbidden_paths_in_diff(diff)
    assert len(failures) >= 1
    assert any(".migration" in f for f in failures)


def test_check_forbidden_paths_in_diff_clean_diff():
    diff = VALID_DIFF
    failures = _check_forbidden_paths_in_diff(diff)
    assert not failures


# ── 15. _check_forbidden_paths_in_diff catches .migration ──────────

def test_check_forbidden_paths_in_diff_catches_git():
    diff = "--- a/.git/config\n+++ b/.git/config\n@@ -1,1 +1,1 @@"
    failures = _check_forbidden_paths_in_diff(diff)
    assert any(".git" in f for f in failures)


def test_check_forbidden_paths_in_diff_catches_dockerfile():
    diff = "--- a/Dockerfile\n+++ b/Dockerfile\n@@ -1,1 +1,1 @@"
    failures = _check_forbidden_paths_in_diff(diff)
    assert any("Dockerfile" in f for f in failures)


def test_check_forbidden_paths_in_diff_catches_env():
    diff = "--- a/.env\n+++ b/.env\n@@ -1,1 +1,1 @@"
    failures = _check_forbidden_paths_in_diff(diff)
    assert any(".env" in f for f in failures)


def test_check_forbidden_paths_in_diff_catches_deploy_prefix():
    diff = "--- a/deploy/k8s/config.yml\n+++ b/deploy/k8s/config.yml"
    failures = _check_forbidden_paths_in_diff(diff)
    assert any("deploy/" in f for f in failures)


# ── 16. evaluate_rule with unknown rule_id ──────────────────────────

def test_evaluate_rule_unknown_rule_id(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    decision = evaluate_rule(
        rule_id="NOT_A_REAL_RULE",
        sandbox_path=sandbox,
        touched_paths=["pom.xml"],
        unified_diff="",
    )
    assert decision.allowed is False
    assert decision.human_review_required is True
    assert "not allowlisted" in decision.reason.lower()


# ── 17. evaluate_rule with known rule_id ────────────────────────────

def test_evaluate_rule_h2_missing_pom(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    decision = evaluate_rule(
        rule_id="DEPENDENCY_ADD_H2_RUNTIME",
        sandbox_path=sandbox,
        touched_paths=["pom.xml"],
        unified_diff="+<groupId>com.h2database</groupId>\n+<artifactId>h2</artifactId>\n+<scope>runtime</scope>",
        h2_required=False,
    )
    assert decision.allowed is False
    assert "h2 smoke" in decision.reason.lower()


def test_evaluate_rule_unknown_returns_decision():
    assert ALLOWED_RULE_IDS == {
        "DEPENDENCY_ADD_H2_RUNTIME",
        "DEPENDENCY_ADD_VALIDATION_STARTER",
        "DEPENDENCY_REMOVE_TOMCAT9_OVERRIDE_BOOT3",
        "DEPENDENCY_REPLACE_JAVAX_SERVLET_API_WITH_JAKARTA",
        "DEPENDENCY_REPLACE_JAVAX_VALIDATION_WITH_JAKARTA",
        "DEPENDENCY_UPGRADE_ZALANDO_PROBLEM_SPRING_WEB_0291",
        "H2_SMOKE_CONFIG_ONLY",
        "JAKARTA_IMPORT_MECHANICAL_SOURCE",
    }


def test_reviewed_llm_policy_identity_uses_existing_patch_gate(tmp_path):
    result = evaluate_reviewed_llm_patch(**_reviewed_policy_kwargs(tmp_path, APPLYABLE_APP_DIFF))
    policy_checksum = "sha256:" + sha256_canonical_json(reviewed_llm_policy_checksum_input(result))
    payload = reviewed_llm_policy_payload(
        result,
        policy_checksum=policy_checksum,
        evaluated_at="2026-07-09T00:00:00Z",
    )

    assert POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1 not in ALLOWED_RULE_IDS
    assert result.decision == REVIEWED_LLM_DECISION_ALLOWED
    assert not hasattr(result, "rule_id")
    assert payload["patch_source"] == PATCH_SOURCE_LLM_REVIEWED
    assert payload["policy_id"] == POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1
    assert payload["touched_paths"] == ["src/main/java/com/example/App.java"]
    assert "deterministic_rule_id" not in payload


def test_reviewed_llm_policy_checksum_is_deterministic_without_timestamp(tmp_path):
    kwargs = _reviewed_policy_kwargs(tmp_path, APPLYABLE_APP_DIFF)
    first = evaluate_reviewed_llm_patch(**kwargs)
    second = evaluate_reviewed_llm_patch(**kwargs)

    first_checksum = "sha256:" + sha256_canonical_json(reviewed_llm_policy_checksum_input(first))
    second_checksum = "sha256:" + sha256_canonical_json(reviewed_llm_policy_checksum_input(second))

    assert first.decision == REVIEWED_LLM_DECISION_ALLOWED
    assert first_checksum == second_checksum
    assert "evaluated_at" not in reviewed_llm_policy_checksum_input(first)


def test_reviewed_llm_policy_blocks_exact_byte_checksum_mismatch(tmp_path):
    kwargs = _reviewed_policy_kwargs(tmp_path, APPLYABLE_APP_DIFF)
    kwargs["reviewed_diff_checksum"] = "sha256:" + "0" * 64

    result = evaluate_reviewed_llm_patch(**kwargs)

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert result.reason_codes == (REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH,)


def test_reviewed_llm_policy_blocks_safe_diff_checksum_mismatch(tmp_path, monkeypatch):
    import migration_factory.repair_loop.patch_gate as patch_gate

    original = patch_gate.build_safe_diff_preview

    def mismatch_preview(**kwargs):
        return replace(original(**kwargs), checksum_mismatch=True)

    monkeypatch.setattr(patch_gate, "build_safe_diff_preview", mismatch_preview)

    result = evaluate_reviewed_llm_patch(**_reviewed_policy_kwargs(tmp_path, APPLYABLE_APP_DIFF))

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH in result.reason_codes


def test_reviewed_llm_policy_reuses_shared_path_validation(tmp_path):
    diff = """\
diff --git a/../secrets/keys b/../secrets/keys
--- a/../secrets/keys
+++ b/../secrets/keys
@@ -1,1 +1,1 @@
-old
+new
"""

    result = evaluate_reviewed_llm_patch(**_reviewed_policy_kwargs(tmp_path, diff, changed_files=("../secrets/keys",)))

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert REASON_SHARED_PATH_VALIDATION_FAILED in result.reason_codes


def test_reviewed_llm_policy_reuses_shared_security_validation(tmp_path):
    diff = """\
diff --git a/src/main/java/com/example/SecurityConfig.java b/src/main/java/com/example/SecurityConfig.java
--- a/src/main/java/com/example/SecurityConfig.java
+++ b/src/main/java/com/example/SecurityConfig.java
@@ -1,1 +1,1 @@
-http.authorizeRequests().anyRequest().authenticated();
+http.authorizeRequests().anyRequest().permitAll();
"""

    result = evaluate_reviewed_llm_patch(
        **_reviewed_policy_kwargs(
            tmp_path,
            diff,
            changed_files=("src/main/java/com/example/SecurityConfig.java",),
        )
    )

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert REASON_SECURITY_SENSITIVE_MODIFICATION in result.reason_codes


def test_reviewed_llm_route_scope_allows_safe_root_level_pom(tmp_path):
    diff = """\
diff --git a/pom.xml b/pom.xml
--- a/pom.xml
+++ b/pom.xml
@@ -1,3 +1,3 @@
 <project>
-  <name>old</name>
+  <name>new</name>
 </project>
"""

    result = evaluate_reviewed_llm_patch(
        **_reviewed_policy_kwargs(
            tmp_path,
            diff,
            changed_files=("pom.xml",),
            sandbox_files={"pom.xml": "<project>\n  <name>old</name>\n</project>\n"},
        )
    )

    assert reviewed_llm_allowed_route_scope(route="llm_reviewed_unknown", stage_index=1) == ("sandbox_relative:**",)
    assert result.decision == REVIEWED_LLM_DECISION_ALLOWED
    assert result.allowed_route_scope == ("sandbox_relative:**",)


def test_reviewed_llm_route_scope_allows_safe_nested_java(tmp_path):
    result = evaluate_reviewed_llm_patch(**_reviewed_policy_kwargs(tmp_path, APPLYABLE_APP_DIFF))

    assert result.decision == REVIEWED_LLM_DECISION_ALLOWED
    assert result.allowed_route_scope == ("sandbox_relative:**",)


def test_reviewed_llm_unsupported_root_extension_is_extension_policy_not_route_scope(tmp_path):
    diff = """\
diff --git a/local.lock b/local.lock
--- a/local.lock
+++ b/local.lock
@@ -1,1 +1,1 @@
-old
+new
"""

    result = evaluate_reviewed_llm_patch(
        **_reviewed_policy_kwargs(
            tmp_path,
            diff,
            changed_files=("local.lock",),
            sandbox_files={"local.lock": "old\n"},
        )
    )

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert REASON_UNSUPPORTED_FILE_EXTENSION in result.reason_codes
    assert REASON_ROUTE_SCOPE_VIOLATION not in result.reason_codes


def test_reviewed_llm_traversal_path_remains_shared_path_validation(tmp_path):
    diff = """\
diff --git a/../secrets/keys.txt b/../secrets/keys.txt
--- a/../secrets/keys.txt
+++ b/../secrets/keys.txt
@@ -1,1 +1,1 @@
-old
+new
"""

    result = evaluate_reviewed_llm_patch(
        **_reviewed_policy_kwargs(
            tmp_path,
            diff,
            changed_files=("../secrets/keys.txt",),
        )
    )

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert REASON_SHARED_PATH_VALIDATION_FAILED in result.reason_codes


def test_reviewed_llm_route_scope_is_backend_owned_not_evidence_or_model_output(tmp_path):
    kwargs = _reviewed_policy_kwargs(
        tmp_path,
        APPLYABLE_APP_DIFF,
        changed_files=("src/main/java/com/example/App.java",),
    )
    kwargs["evidence_changed_files"] = ("diagnostics/evidence-only.txt",)

    result = evaluate_reviewed_llm_patch(**kwargs)

    assert result.decision == REVIEWED_LLM_DECISION_ALLOWED
    assert result.evidence_changed_files == ("diagnostics/evidence-only.txt",)
    assert result.declared_changed_files == ("src/main/java/com/example/App.java",)
    assert result.allowed_route_scope == ("sandbox_relative:**",)
    assert result.allowed_route_scope != result.evidence_changed_files
    assert result.allowed_route_scope != result.declared_changed_files


def test_reviewed_llm_unsupported_route_fails_closed_with_route_scope_reason(tmp_path):
    kwargs = _reviewed_policy_kwargs(tmp_path, APPLYABLE_APP_DIFF)
    kwargs["route"] = "unsupported_route"
    kwargs["allowed_route_scope"] = reviewed_llm_allowed_route_scope(route="unsupported_route", stage_index=1)

    result = evaluate_reviewed_llm_patch(**kwargs)

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert result.reason_codes == (REASON_ROUTE_SCOPE_VIOLATION,)


def test_reviewed_llm_invalid_stage_fails_closed_with_route_scope_reason(tmp_path):
    kwargs = _reviewed_policy_kwargs(tmp_path, APPLYABLE_APP_DIFF)
    kwargs["stage_index"] = 0
    kwargs["allowed_route_scope"] = reviewed_llm_allowed_route_scope(route="llm_reviewed_unknown", stage_index=0)

    result = evaluate_reviewed_llm_patch(**kwargs)

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert result.reason_codes == (REASON_ROUTE_SCOPE_VIOLATION,)


def test_reviewed_llm_policy_blocks_route_scope_violation(tmp_path):
    result = evaluate_reviewed_llm_patch(
        **_reviewed_policy_kwargs(
            tmp_path,
            APPLYABLE_APP_DIFF,
            allowed_route_scope=("sandbox_relative:src/main/resources/*.properties",),
        )
    )

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert REASON_ROUTE_SCOPE_VIOLATION in result.reason_codes


@pytest.mark.parametrize(
    ("diff", "changed_files", "reason_code"),
    [
        (
            """\
diff --git a/scripts/run.sh b/scripts/run.sh
--- a/scripts/run.sh
+++ b/scripts/run.sh
@@ -1,1 +1,1 @@
-echo old
+echo new
""",
            ("scripts/run.sh",),
            REASON_UNSUPPORTED_FILE_EXTENSION,
        ),
        (
            """\
diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/Application.java
similarity index 92%
rename from src/main/java/com/example/App.java
rename to src/main/java/com/example/Application.java
--- a/src/main/java/com/example/App.java
+++ b/src/main/java/com/example/Application.java
@@ -1,1 +1,1 @@
-old
+new
""",
            ("src/main/java/com/example/App.java", "src/main/java/com/example/Application.java"),
            REASON_RENAME_BLOCKED,
        ),
        (
            """\
diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java
deleted file mode 100644
--- a/src/main/java/com/example/App.java
+++ /dev/null
@@ -1,1 +0,0 @@
-old
""",
            ("src/main/java/com/example/App.java",),
            REASON_DELETE_BLOCKED,
        ),
        (
            """\
diff --git a/src/test/java/com/example/AppTest.java b/src/test/java/com/example/AppTest.java
--- a/src/test/java/com/example/AppTest.java
+++ b/src/test/java/com/example/AppTest.java
@@ -1,1 +1,2 @@
 assertThrows(RuntimeException.class, () -> run());
+assertTrue(true);
""",
            ("src/test/java/com/example/AppTest.java",),
            REASON_TRIVIALLY_PASSING_ASSERTION,
        ),
        (
            """\
diff --git a/src/test/java/com/example/AppTest.java b/src/test/java/com/example/AppTest.java
--- a/src/test/java/com/example/AppTest.java
+++ b/src/test/java/com/example/AppTest.java
@@ -1,1 +1,2 @@
 assertThrows(RuntimeException.class, () -> run());
+@Disabled
""",
            ("src/test/java/com/example/AppTest.java",),
            REASON_TEST_DISABLED_OR_SKIPPED,
        ),
        (
            """\
diff --git a/src/test/java/com/example/AppTest.java b/src/test/java/com/example/AppTest.java
--- a/src/test/java/com/example/AppTest.java
+++ b/src/test/java/com/example/AppTest.java
@@ -1,3 +1,3 @@
-assertThrows(RuntimeException.class, () -> run());
+assertDoesNotThrow(() -> run());
""",
            ("src/test/java/com/example/AppTest.java",),
            REASON_EXPECTED_EXCEPTION_MASKING,
        ),
    ],
)
def test_reviewed_llm_policy_blocks_generic_review_controls(tmp_path, diff, changed_files, reason_code):
    result = evaluate_reviewed_llm_patch(**_reviewed_policy_kwargs(tmp_path, diff, changed_files=changed_files))

    assert result.decision == REVIEWED_LLM_DECISION_BLOCKED
    assert reason_code in result.reason_codes


# ── 18. Gate result statuses ────────────────────────────────────────

def test_patch_gate_result_allowed():
    result = PatchGateResult("ALLOWED", "valid patch", "RULE_X", "LOW", ())
    assert result.status == "ALLOWED"
    assert not result.human_review_required


def test_patch_gate_result_blocked():
    result = PatchGateResult("BLOCKED", "security risk", "RULE_X", "LOW", ())
    assert result.status == "BLOCKED"


def test_patch_gate_result_invalid_patch():
    result = PatchGateResult("INVALID_PATCH", "bad diff", "RULE_X", "LOW", ())
    assert result.status == "INVALID_PATCH"


def test_patch_gate_result_human_review():
    result = PatchGateResult("HUMAN_REVIEW_REQUIRED", "needs review", "RULE_X", "HIGH", (), True)
    assert result.status == "HUMAN_REVIEW_REQUIRED"
    assert result.human_review_required is True


def test_patch_gate_result_defaults():
    result = PatchGateResult("ALLOWED", "ok")
    assert result.rule_id == ""
    assert result.risk == "BLOCKED"
    assert result.touched_paths == ()
    assert result.human_review_required is False


# ── _is_unified_diff (repair_review_chain variant) ───────────────────

def test_repair_review_is_unified_diff_valid():
    assert _is_unified_diff(VALID_DIFF) is True


def test_repair_review_is_unified_diff_plain_text():
    assert _is_unified_diff(DIFF_NO_HEADER) is False  # no ---/+++/@@ headers


def test_repair_review_is_unified_diff_only_headers():
    assert _is_unified_diff(DIFF_NO_PLUS_MINUS) is True  # headers + +/- in the +++/--- lines


def test_repair_review_is_unified_diff_empty():
    assert _is_unified_diff("") is False


# ── _check_forbidden_keys ───────────────────────────────────────────

def test_check_forbidden_keys_sandbox_path():
    data = {"sandbox_path": "/tmp/some", "key": "value"}
    failures = _check_forbidden_keys(data)
    assert len(failures) >= 1
    assert any("sandbox_path" in f for f in failures)


def test_check_forbidden_keys_deployment():
    data = {"deployment": "staging", "key": "value"}
    failures = _check_forbidden_keys(data)
    assert len(failures) >= 1
    assert any("deployment" in f for f in failures)


def test_check_forbidden_keys_provider():
    data = {"provider": "aws", "key": "value"}
    failures = _check_forbidden_keys(data)
    assert len(failures) >= 1
    assert any("provider" in f for f in failures)


def test_check_forbidden_keys_multiple():
    data = {"sandbox_path": "/x", "argv": ["/bin/sh"], "env": {"SECRET": "1"}, "endpoint": "http://evil"}
    failures = _check_forbidden_keys(data)
    assert len(failures) >= 4


def test_check_forbidden_keys_clean():
    data = {"key": "value", "nested": {"inner": "ok"}}
    failures = _check_forbidden_keys(data)
    assert not failures


def test_check_forbidden_keys_empty_value_ignored():
    data = {"sandbox_path": "", "key": "value"}
    failures = _check_forbidden_keys(data)
    assert not failures


# ── RuleDecision dataclass ──────────────────────────────────────────

def test_rule_decision_allowed():
    d = RuleDecision(allowed=True, reason="ok")
    assert d.allowed is True
    assert d.human_review_required is False


def test_rule_decision_not_allowed():
    d = RuleDecision(allowed=False, reason="blocked!", human_review_required=True)
    assert d.allowed is False
    assert d.human_review_required is True


# ── Additional evaluate_patch_proposal edge cases ───────────────────

def test_evaluate_patch_proposal_rejects_absolute_paths_in_diff(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    diff = """\
diff --git a/src/main/App.java b//etc/passwd
--- a/src/main/App.java
+++ b//etc/passwd
@@ -1,1 +1,1 @@
"""
    proposal = _make_proposal(unified_diff=diff)
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert "absolute" in result.reason.lower()


def test_evaluate_patch_proposal_rejects_dotdot_in_diff(tmp_path):
    sandbox, run_dir, legacy = _setup_sandbox(tmp_path)
    diff = """\
diff --git a/../secrets/keys b/../secrets/keys
--- a/../secrets/keys
+++ b/../secrets/keys
@@ -1,1 +1,1 @@
"""
    proposal = _make_proposal(unified_diff=diff)
    result = evaluate_patch_proposal(
        proposal=proposal,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    assert result.status == "INVALID_PATCH"
    assert "traversal" in result.reason.lower()
