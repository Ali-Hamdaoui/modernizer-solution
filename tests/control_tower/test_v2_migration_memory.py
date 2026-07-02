from __future__ import annotations

from pathlib import Path

from migration_factory.control_tower.application.v2_migration_memory import (
    MigrationMemoryCase,
    load_memory_seed_cases,
    retrieve_migration_memory,
)
from migration_factory.control_tower.adapters.fastapi.app import _safe_migration_memory


def _context(
    failure_type: str,
    *,
    stage_index: int = 2,
    target_boot: str = "3.5.16",
    target_java: str = "17",
    status: str = "unsupported_known_failure",
    repair_family: str = "",
    governance_gate: str = "human_review_gate",
    signals: list[str] | None = None,
) -> dict[str, object]:
    return {
        "stage_index": stage_index,
        "source_boot_version": "2.7" if stage_index > 1 else "2.1",
        "target_boot_version": target_boot,
        "source_java_version": "11",
        "target_java_version": target_java,
        "classification_status": status,
        "failure_type": failure_type,
        "repair_family_candidate": repair_family,
        "governance_gate_type": governance_gate,
        "matched_signals": signals or [],
        "usable_artifacts": ["pom_xml", "dependency_graph"],
        "missing_required_evidence": ["test_report"],
    }


def test_memory_seed_loader_loads_checked_in_cases() -> None:
    cases = load_memory_seed_cases()
    ids = {case.memory_case_id for case in cases}
    assert "msa-utils-powermock-legacy-test-strategy" in ids
    assert "msa-utils-initmocks-to-openmocks" in ids


def test_memory_schema_normalizes_non_advisory_authority() -> None:
    case = MigrationMemoryCase.from_dict({
        "memory_case_id": "bad-authority",
        "title": "Bad authority",
        "trust_level": "not-real",
        "authority_level": "apply_authority",
    })
    assert case.trust_level == "untrusted_import"
    assert case.authority_level == "advisory_only"


def test_powermock_retrieves_legacy_test_memory() -> None:
    result = retrieve_migration_memory(_context(
        "POWERMOCK_LEGACY_TEST_STRATEGY",
        signals=["review_gate:powermock_legacy_test_strategy"],
    ))
    assert result["retrieval_status"] == "available"
    assert result["top_match"]["memory_case_id"] == "msa-utils-powermock-legacy-test-strategy"
    assert "POWERMOCK" in " ".join(result["retrieved_case_ids"]).upper()


def test_legacy_api_dependency_alignment_retrieves_memory() -> None:
    result = retrieve_migration_memory(_context(
        "LEGACY_API_DEPENDENCY_ALIGNMENT_REVIEW",
        stage_index=1,
        target_boot="2.7",
        target_java="11",
        signals=["review_gate:legacy_api_dependency_alignment"],
    ))
    assert result["retrieval_status"] == "available"
    assert result["top_match"]["memory_case_id"] == "msa-utils-legacy-api-dependency-alignment"


def test_initmocks_retrieves_openmocks_memory() -> None:
    result = retrieve_migration_memory(_context(
        "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        status="known_family_candidate",
        repair_family="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        governance_gate="future_deterministic_candidate",
        signals=["candidate:initmocks_to_openmocks"],
    ))
    assert result["retrieval_status"] == "available"
    assert result["top_match"]["memory_case_id"] == "msa-utils-initmocks-to-openmocks"


def test_mockbean_retrieves_but_boot27_match_is_weak_advisory() -> None:
    result = retrieve_migration_memory(_context(
        "MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        stage_index=1,
        target_boot="2.7",
        target_java="11",
        status="known_family_candidate",
        repair_family="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        governance_gate="future_deterministic_candidate",
        signals=["candidate:mockbean_to_mockitobean"],
    ))
    assert result["retrieval_status"] == "available"
    assert result["top_match"]["memory_case_id"] == "msa-utils-mockbean-to-mockitobean"
    assert result["top_match"]["weak_stage_match"] is True
    assert result["authority_level"] == "advisory_only"


def test_boot27_classification_does_not_retrieve_boot34_memory_as_authoritative() -> None:
    result = retrieve_migration_memory(_context(
        "LEGACY_TEST_FRAMEWORK_MIGRATION",
        stage_index=1,
        target_boot="2.7",
        target_java="11",
        governance_gate="human_review_gate",
        signals=["review_gate:legacy_test_framework_migration"],
    ))
    top = result["top_match"]
    assert top is not None
    assert top["authority_level"] == "advisory_only"


def test_memory_result_has_no_repair_or_apply_authority() -> None:
    result = retrieve_migration_memory(_context("POWERMOCK_LEGACY_TEST_STRATEGY"))
    assert result["repair_enabled"] is False
    assert result["memory_can_apply"] is False
    assert result["memory_can_approve"] is False
    assert result["memory_can_start_downstream"] is False
    assert result["authority_level"] == "advisory_only"


def test_no_matches_and_unavailable_are_safe(tmp_path: Path) -> None:
    no_match = retrieve_migration_memory(_context("UNKNOWN_FAILURE", governance_gate="unknown"))
    assert no_match["retrieval_status"] == "no_matches"
    assert no_match["repair_enabled"] is False

    unavailable = retrieve_migration_memory(_context("POWERMOCK_LEGACY_TEST_STRATEGY"), seed_path=tmp_path / "missing.json")
    assert unavailable["retrieval_status"] == "unavailable"
    assert unavailable["memory_can_apply"] is False


def test_retrieval_uses_no_live_llm_or_api_calls(monkeypatch) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("network call attempted")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    result = retrieve_migration_memory(_context("POWERMOCK_LEGACY_TEST_STRATEGY"))
    assert result["retrieval_status"] == "available"


def test_browser_cannot_inject_memory_authority_fields() -> None:
    sanitized = _safe_migration_memory({
        "retrieval_status": "available",
        "authority_level": "apply_authority",
        "repair_enabled": True,
        "memory_can_apply": True,
        "memory_can_approve": True,
        "memory_can_start_downstream": True,
        "memory_matches": [{
            "memory_case_id": "case-1",
            "title": "Injected",
            "authority_level": "command_authority",
        }],
    })
    assert sanitized is not None
    assert sanitized["authority_level"] == "advisory_only"
    assert sanitized["repair_enabled"] is False
    assert sanitized["memory_can_apply"] is False
    assert sanitized["memory_can_approve"] is False
    assert sanitized["memory_can_start_downstream"] is False
    assert sanitized["memory_matches"][0]["authority_level"] == "advisory_only"
