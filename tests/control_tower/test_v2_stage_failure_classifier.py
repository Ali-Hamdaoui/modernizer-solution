from __future__ import annotations

from typing import Any

from migration_factory.control_tower.application.v2_stage_failure_classifier import classify_stage_failure


def _pack(
    text: str = "",
    *,
    stage_index: int = 2,
    source_boot: str = "2.7",
    target_boot: str = "3.5.16",
    source_java: str = "11",
    target_java: str = "17",
    usable: list[str] | None = None,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    usable_kinds = usable if usable is not None else ["build_error_contract", "pom_xml", "dependency_graph"]
    return {
        "job_id": "job-1",
        "stage_index": stage_index,
        "stage_name": f"Stage {stage_index}",
        "source_boot_version": source_boot,
        "target_boot_version": target_boot,
        "source_java_version": source_java,
        "target_java_version": target_java,
        "failure_summary": text,
        "usable_artifacts": [
            {"kind": kind, "ref": f"{kind}.json", "checksum": "sha256:test", "excerpt": text}
            for kind in usable_kinds
        ],
        "missing_artifacts": missing if missing is not None else [],
        "downstream_stage_state": {"next_stage_index": stage_index + 1, "state": "pending_blocked_by_failed_stage", "auto_started": False},
        "evidence_pack_id": "stage-evidence-test",
        "evidence_pack_checksum": "sha256:evidence",
    }


def assert_candidate(result: dict[str, Any], family: str) -> None:
    assert result["classification_status"] == "known_family_candidate"
    assert result["failure_type"] == family
    assert result["repair_family_candidate"] == family
    assert result["repair_enabled"] is False
    assert result["repair_blocked_reason"] == "R7C_classification_only_no_real_repair_apply"


def test_boot2_jakarta_servlet_compile_error_is_import_candidate() -> None:
    result = classify_stage_failure(_pack("[ERROR] package jakarta.servlet.http does not exist", stage_index=1, source_boot="2.1", target_boot="2.7", target_java="11"))
    assert_candidate(result, "JAKARTA_IMPORT_MECHANICAL_SOURCE")
    assert "compiler:package_jakarta_servlet_missing" in result["matched_signals"]


def test_boot3_javax_servlet_dependency_is_servlet_dependency_candidate() -> None:
    result = classify_stage_failure(_pack("<groupId>javax.servlet</groupId><artifactId>javax.servlet-api</artifactId>"))
    assert_candidate(result, "DEPENDENCY_REPLACE_JAVAX_SERVLET_API_WITH_JAKARTA")


def test_boot3_javax_validation_signal_is_validation_dependency_candidate() -> None:
    result = classify_stage_failure(_pack("javax.validation.Constraint javax.validation:validation-api"))
    assert_candidate(result, "DEPENDENCY_REPLACE_JAVAX_VALIDATION_WITH_JAKARTA")


def test_boot3_tomcat9_override_is_candidate() -> None:
    result = classify_stage_failure(_pack("org.apache.tomcat.embed tomcat-embed-core 9.0.83"))
    assert_candidate(result, "DEPENDENCY_REMOVE_TOMCAT9_OVERRIDE_BOOT3")


def test_java_target_release_mismatch_is_compiler_candidate() -> None:
    result = classify_stage_failure(_pack("Fatal error compiling: invalid target release: 21", stage_index=3, source_java="17", target_java="21"))
    assert_candidate(result, "MAVEN_COMPILER_PLUGIN_SOURCE_TARGET_MISMATCH")


def test_missing_core_artifacts_returns_blocked_pending_evidence() -> None:
    result = classify_stage_failure(_pack("", usable=["dependency_graph", "runtime_contract"], missing=["build_error_contract", "test_agent_log", "test_report"]))
    assert result["classification_status"] == "blocked_pending_evidence"
    assert result["repair_enabled"] is False
    assert "build_error_contract" in result["missing_required_evidence"]


def test_unsupported_known_signal_returns_unsupported_known_failure() -> None:
    result = classify_stage_failure(_pack("springfox documentation plugin incompatible with path matching"))
    assert result["classification_status"] == "unsupported_known_failure"
    assert result["repair_enabled"] is False


def test_no_signal_returns_unknown() -> None:
    result = classify_stage_failure(_pack("Build failed with opaque status", missing=[]))
    assert result["classification_status"] == "unknown"
    assert result["repair_enabled"] is False
