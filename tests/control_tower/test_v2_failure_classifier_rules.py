from __future__ import annotations

from migration_factory.control_tower.application.v2_failure_classifier_rules import (
    classify_failure,
)
from migration_factory.control_tower.application.v2_failure_evidence import (
    EvidenceSnippet,
    FailureEvidencePack,
)


def _pack(*snippets: EvidenceSnippet, missing_artifacts: tuple[str, ...] = ()) -> FailureEvidencePack:
    return FailureEvidencePack(
        run_id="run-1",
        event_type="build_failed",
        snippets=snippets,
        missing_artifacts=missing_artifacts,
        affected_paths=("pom.xml",) if snippets else (),
        redaction_status="redacted",
        total_chars=sum(len(s.text) for s in snippets),
    )


def test_pkix_classification() -> None:
    result = classify_failure(
        evidence_pack=_pack(EvidenceSnippet("phase2_transform.log", "stderr", "PKIX path building failed during dependency download")),
        payload={},
        stage_index=1,
        event_type="build_failed",
    )
    assert result["failure_type"] == "maven_truststore_pkix"


def test_invalid_maven_wildcard_version_classification() -> None:
    result = classify_failure(
        evidence_pack=_pack(EvidenceSnippet("pom.xml", "pom.xml", "<version>3.0.x</version>")),
        payload={},
        stage_index=1,
        event_type="build_failed",
    )
    assert result["failure_type"] == "invalid_maven_wildcard_version"


def test_stage1_lombok_jdk_mismatch_classification() -> None:
    result = classify_failure(
        evidence_pack=_pack(EvidenceSnippet("phase2_transform.log", "stderr", "IllegalAccessError lombok access denied on Java 17")),
        payload={},
        stage_index=1,
        event_type="build_failed",
    )
    assert result["failure_type"] == "stage1_wrong_jdk_lombok"


def test_jakarta_dependency_issue_classification() -> None:
    result = classify_failure(
        evidence_pack=_pack(EvidenceSnippet("pom.xml", "pom.xml", "spring-boot 3.2 javax.servlet javax.persistence still present")),
        payload={},
        stage_index=2,
        event_type="build_failed",
    )
    assert result["failure_type"] == "jakarta_migration_dependency_issue"


def test_jakarta_namespace_issue_classification() -> None:
    result = classify_failure(
        evidence_pack=_pack(EvidenceSnippet("phase2_transform.log", "stderr", "package javax.servlet does not exist")),
        payload={},
        stage_index=2,
        event_type="build_failed",
    )
    assert result["failure_type"] == "jakarta_namespace_issue"


def test_missing_artifacts_are_explicit() -> None:
    result = classify_failure(
        evidence_pack=_pack(
            EvidenceSnippet("event_payload", "message", "build failed"),
            missing_artifacts=("phase2_transform.log", "pom.xml"),
        ),
        payload={},
        stage_index=1,
        event_type="build_failed",
    )
    assert result["failure_type"] == "unknown_build_failure"
    assert "phase2_transform.log" in result["likely_root_cause"]

