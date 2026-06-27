"""AMF-269 / F4-T1 source-profile detection artifact tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from migration_factory.agents.analysis_agent.analysis_agent.maven_scanner import (
    build_source_profile_detection_for_root_pom,
    infer_source_profile_from_stack,
)
from migration_factory.control_tower.schemas.profile_model import (
    SOURCE_PROFILE_DETECTION_FIELDS,
    SourceProfileDetectionArtifact,
    SourceProfileEvidenceRef,
    SourceProfileFacts,
    SourceProfileSignal,
)


def test_detection_artifact_from_maven_pom_detects_boot3_java21(tmp_path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.5.4</version>
  </parent>
  <properties>
    <java.version>21</java.version>
  </properties>
  <modules>
    <module>api</module>
    <module>domain</module>
  </modules>
</project>
""",
        encoding="utf-8",
    )

    artifact = build_source_profile_detection_for_root_pom(
        pom,
        job_id="job-269",
        created_at="2026-06-27T00:00:00Z",
        target_profile="springboot-4.0-java21",
        checkpoint_id="checkpoint-analysis",
        artifact_revision_id="revision-analysis",
    )

    assert artifact.artifact_kind == "source_profile_detection"
    assert artifact.job_id == "job-269"
    assert artifact.stage_index == 1
    assert artifact.checkpoint_id == "checkpoint-analysis"
    assert artifact.artifact_revision_id == "revision-analysis"
    assert artifact.detected_source_profile == "springboot-3.5-java21"
    assert artifact.target_profile == "springboot-4.0-java21"
    assert artifact.confidence == 0.9
    assert artifact.profile_facts.java_version == "21"
    assert artifact.profile_facts.spring_boot_version == "3.5.4"
    assert artifact.profile_facts.build_tool == "maven"
    assert artifact.profile_facts.modules == ("api", "domain")
    assert artifact.evidence_checksums == tuple(ref.checksum for ref in artifact.evidence_refs)
    assert artifact.evidence_refs[0].evidence_ref == "analysis:maven-root-pom"
    assert artifact.evidence_refs[0].checksum.startswith("sha256:")
    assert artifact.artifact_checksum.startswith("sha256:")


def test_detection_artifact_public_payload_does_not_expose_runtime_or_paths(tmp_path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(
        """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.7.18</version>
  </parent>
  <properties><java.version>11</java.version></properties>
</project>
""",
        encoding="utf-8",
    )

    artifact = build_source_profile_detection_for_root_pom(
        pom,
        job_id="job-safe",
        created_at="2026-06-27T00:00:00Z",
    )
    payload = json.dumps(artifact.to_dict(), sort_keys=True)

    forbidden = {
        "sandbox_path",
        "argv",
        "env",
        "raw_command",
        "endpoint",
        "deployment",
        "env_ref",
        "filesystem_target",
        "user_supplied_file_path",
        str(pom),
    }
    for value in forbidden:
        assert value not in payload


def test_detection_artifact_rejects_non_selectable_detected_source() -> None:
    with pytest.raises(ValidationError, match="selectable source profile"):
        SourceProfileDetectionArtifact(
            artifact_id="artifact-1",
            artifact_ref="analysis:source-profile-detection",
            artifact_checksum="sha256:artifact",
            job_id="job-1",
            detected_source_profile="springboot-4.0-java21",
            confidence=0.9,
            evidence_refs=(
                SourceProfileEvidenceRef(
                    evidence_ref="analysis:maven-root-pom",
                    evidence_type="maven_root_pom",
                    checksum="sha256:pom",
                ),
            ),
            evidence_checksums=("sha256:pom",),
            profile_signals=(
                SourceProfileSignal(
                    signal_name="spring_boot_version",
                    value="4.0.0",
                    evidence_ref="analysis:maven-root-pom",
                    confidence_weight=0.55,
                ),
            ),
            profile_facts=SourceProfileFacts(
                java_version="21",
                spring_boot_version="4.0.0",
                build_tool="maven",
            ),
            created_at="2026-06-27T00:00:00Z",
        )


def test_detection_artifact_requires_evidence_checksum_binding() -> None:
    with pytest.raises(ValidationError, match="evidence_checksums"):
        SourceProfileDetectionArtifact(
            artifact_id="artifact-1",
            artifact_ref="analysis:source-profile-detection",
            artifact_checksum="sha256:artifact",
            job_id="job-1",
            detected_source_profile="springboot-2.7-java11",
            confidence=0.9,
            evidence_refs=(
                SourceProfileEvidenceRef(
                    evidence_ref="analysis:maven-root-pom",
                    evidence_type="maven_root_pom",
                    checksum="sha256:pom",
                ),
            ),
            evidence_checksums=("sha256:other",),
            profile_signals=(
                SourceProfileSignal(
                    signal_name="spring_boot_version",
                    value="2.7.18",
                    evidence_ref="analysis:maven-root-pom",
                    confidence_weight=0.55,
                ),
            ),
            profile_facts=SourceProfileFacts(
                java_version="11",
                spring_boot_version="2.7.18",
                build_tool="maven",
            ),
            created_at="2026-06-27T00:00:00Z",
        )


def test_infer_source_profile_reports_uncertainty_for_unknown_boot() -> None:
    profile, confidence, notes = infer_source_profile_from_stack(
        java_version="unknown",
        spring_boot_version="unknown",
    )

    assert profile == "springboot-2.7-java11"
    assert confidence == 0.2
    assert notes


def test_source_profile_detection_fields_are_public_safe() -> None:
    dangerous = {
        "sandbox_path",
        "argv",
        "env",
        "raw_command",
        "endpoint",
        "deployment",
        "env_ref",
        "filesystem_target",
        "user_supplied_file_path",
    }

    assert "detected_source_profile" in SOURCE_PROFILE_DETECTION_FIELDS
    assert "confidence" in SOURCE_PROFILE_DETECTION_FIELDS
    assert "evidence_refs" in SOURCE_PROFILE_DETECTION_FIELDS
    assert SOURCE_PROFILE_DETECTION_FIELDS.isdisjoint(dangerous)
