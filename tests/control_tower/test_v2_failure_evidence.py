from __future__ import annotations

import json
from pathlib import Path

import pytest

from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
)
from migration_factory.control_tower.application.v2_failure_evidence import (
    FailureEvidenceCollector,
)


def test_failure_evidence_collector_redacts_and_bounds(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    sandbox_dir = tmp_path / "sandbox"
    run_dir.mkdir()
    sandbox_dir.mkdir()

    (run_dir / "phase2_transform.log").write_text(
        "token=abc123\n" + ("PKIX path building failed " * 300),
        encoding="utf-8",
    )
    (run_dir / "test_agent.log").write_text("Bearer secret-token-value", encoding="utf-8")
    (run_dir / "orchestration_summary.json").write_text(
        json.dumps({"message": "build failed at C:/Users/private/app"}),
        encoding="utf-8",
    )
    (run_dir / "build-error-1.json").write_text(
        json.dumps({"stderr": "failure in /home/user/project", "api_key": "topsecret"}),
        encoding="utf-8",
    )
    (sandbox_dir / "pom.xml").write_text("<project><version>1.0.0</version></project>", encoding="utf-8")

    pack = FailureEvidenceCollector(max_total_chars=1200).collect(
        run_id="run-1",
        event_type="build_failed",
        run_dir=run_dir,
        sandbox_path=sandbox_dir,
        artifact_refs={"summary": str(run_dir / "orchestration_summary.json")},
        payload={"stderr": "AZURE_OPENAI_KEY=abc123", "message": "Failed in /home/user/project"},
    )

    joined = "\n".join(snippet.text for snippet in pack.snippets)
    assert pack.total_chars <= 1200
    assert "abc123" not in joined
    assert "topsecret" not in joined
    assert "C:/Users" not in joined
    assert "/home/user" not in joined
    assert pack.redaction_status == "redacted"


def test_failure_evidence_collector_rejects_path_traversal(tmp_path: Path) -> None:
    collector = FailureEvidenceCollector()
    with pytest.raises(ValueError, match="Rejected unsafe path"):
        collector.collect(
            run_id="run-1",
            event_type="build_failed",
            run_dir=tmp_path,
            sandbox_path=tmp_path / ".." / "escape",
            artifact_refs={},
            payload={},
        )


def test_failure_evidence_collector_marks_missing_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pack = FailureEvidenceCollector().collect(
        run_id="run-1",
        event_type="build_failed",
        run_dir=run_dir,
        sandbox_path=None,
        artifact_refs={},
        payload={"message": "plain payload only"},
    )

    assert "phase2_transform.log" in pack.missing_artifacts
    assert "pom.xml" in pack.missing_artifacts


def test_failure_diagnosis_service_handles_missing_artifacts_without_crash(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    service = V2FailureDiagnosisService(
        run_dir_resolver=lambda command_id, event_type: str(run_dir),
    )

    diagnosis = service.diagnose(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        event_type="build_failed",
        payload={
            "build_status": "BUILD_FAILED",
            "message": "compile failed",
            "artifact_refs": {},
        },
    )

    assert diagnosis.failure_type == "unknown_build_failure"


def test_failure_evidence_collector_finds_stage2_nested_v2_run_layout(tmp_path: Path) -> None:
    run_dir = tmp_path / ".migration" / "runs" / "v2-ddbbf317-s2"
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "orchestration").mkdir(parents=True)
    (run_dir / "build").mkdir(parents=True)
    sandbox_dir.mkdir(parents=True)

    (run_dir / "logs" / "phase2_transform.log").write_text(
        "Failed to read artifact descriptor for jakarta.persistence:jakarta.persistence-api:jar:3.0.x\n"
        "PKIX path building failed\n",
        encoding="utf-8",
    )
    (run_dir / "orchestration" / "orchestration_summary.json").write_text(
        json.dumps({"final_status": "BUILD_FAILED_IN_SANDBOX"}),
        encoding="utf-8",
    )
    (run_dir / "build" / "build-error-20260618-004516-dependency_error.json").write_text(
        json.dumps({
            "message": "Failed to read artifact descriptor for jakarta.servlet:jakarta.servlet-api:jar:5.0.x",
        }),
        encoding="utf-8",
    )
    (sandbox_dir / "pom.xml").write_text(
        "<project><dependencies>"
        "<dependency><groupId>jakarta.persistence</groupId><artifactId>jakarta.persistence-api</artifactId><version>3.0.x</version></dependency>"
        "<dependency><groupId>jakarta.servlet</groupId><artifactId>jakarta.servlet-api</artifactId><version>5.0.x</version></dependency>"
        "</dependencies></project>",
        encoding="utf-8",
    )

    pack = FailureEvidenceCollector().collect(
        run_id="v2-ddbbf317-s2",
        event_type="build_failed",
        run_dir=run_dir,
        sandbox_path=sandbox_dir,
        artifact_refs={
            "orchestration_summary": str(run_dir / "orchestration" / "orchestration_summary.json"),
            "build_error": str(run_dir / "build" / "build-error-20260618-004516-dependency_error.json"),
        },
        payload={"build_status": "BUILD_FAILED_IN_SANDBOX"},
    )

    labels = {snippet.label for snippet in pack.snippets}
    joined = "\n".join(snippet.text for snippet in pack.snippets)
    assert "phase2_transform.log" in labels
    assert "orchestration_summary.json" in labels or "orchestration_summary" in labels
    assert "pom.xml" in labels
    assert "jakarta.persistence-api:jar:3.0.x" in joined
    assert "jakarta.servlet-api:jar:5.0.x" in joined
    assert "phase2_transform.log" not in pack.missing_artifacts
    assert "orchestration_summary.json" not in pack.missing_artifacts
    assert "build-error*.json" not in pack.missing_artifacts
    assert "pom.xml" not in pack.missing_artifacts


def test_failure_evidence_collector_infers_stage_specific_run_root_from_artifacts(tmp_path: Path) -> None:
    base_run = tmp_path / ".migration" / "runs" / "v2-ddbbf317"
    stage2_run = tmp_path / ".migration" / "runs" / "v2-ddbbf317-s2"
    (base_run / "logs").mkdir(parents=True)
    (stage2_run / "logs").mkdir(parents=True)
    (stage2_run / "build").mkdir(parents=True)
    (stage2_run / "workspaces" / "sandbox").mkdir(parents=True)

    (base_run / "logs" / "phase2_transform.log").write_text("base run log", encoding="utf-8")
    (stage2_run / "logs" / "phase2_transform.log").write_text("stage2 specific log", encoding="utf-8")
    (stage2_run / "build" / "build-error-1.json").write_text(json.dumps({"error": "3.0.x"}), encoding="utf-8")
    (stage2_run / "workspaces" / "sandbox" / "pom.xml").write_text("<project><version>3.0.x</version></project>", encoding="utf-8")

    pack = FailureEvidenceCollector().collect(
        run_id="v2-ddbbf317",
        event_type="build_failed",
        run_dir=None,
        sandbox_path=stage2_run / "workspaces" / "sandbox",
        artifact_refs={"build_error": str(stage2_run / "build" / "build-error-1.json")},
        payload={},
    )

    joined = "\n".join(snippet.text for snippet in pack.snippets)
    assert "stage2 specific log" in joined
    assert "base run log" not in joined


def test_failure_evidence_collector_extracts_targeted_classification_matches_after_head_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / ".migration" / "runs" / "v2-ddbbf317-s2"
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "build").mkdir(parents=True)
    sandbox_dir.mkdir(parents=True)

    filler = "x" * 900
    (sandbox_dir / "pom.xml").write_text(
        f"<project>{filler}"
        "<javax.persistence.version>3.0.x</javax.persistence.version>\n"
        "<javax.servlet.version>5.0.x</javax.servlet.version>\n"
        "<artifactId>jakarta.persistence-api</artifactId>\n"
        "<artifactId>jakarta.servlet-api</artifactId>\n"
        "</project>",
        encoding="utf-8",
    )
    (run_dir / "build" / "build-error-1.json").write_text(
        json.dumps(
            {
                "message": (
                    f"{filler}\n"
                    "Failed to read artifact descriptor for jakarta.persistence:jakarta.persistence-api:jar:3.0.x\n"
                    "jakarta.servlet:jakarta.servlet-api:pom:5.0.x\n"
                    "PKIX path building failed"
                )
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "logs" / "phase2_transform.log").write_text(
        f"{filler}\n"
        "Failed to download jakarta.persistence:jakarta.persistence-api:3.0.x\n"
        "/home/user/.m2/repository/jakarta/persistence/jakarta.persistence-api/3.0.x/jakarta.persistence-api-3.0.x.pom\n",
        encoding="utf-8",
    )

    pack = FailureEvidenceCollector().collect(
        run_id="v2-ddbbf317-s2",
        event_type="build_failed",
        run_dir=run_dir,
        sandbox_path=sandbox_dir,
        artifact_refs={},
        payload={"build_status": "BUILD_FAILED_IN_SANDBOX"},
    )

    snippets = {snippet.label: snippet for snippet in pack.snippets}
    pom = snippets["pom.xml"]
    build_error = next(snippet for snippet in pack.snippets if snippet.label.startswith("build-error"))
    transform_log = snippets["phase2_transform.log"]

    assert "javax.persistence.version" not in pom.raw_text
    assert "jakarta.persistence-api:jar:3.0.x" not in build_error.raw_text
    assert "jakarta.persistence-api/3.0.x" not in transform_log.raw_text

    assert "javax.persistence.version" in pom.classification_text
    assert "javax.servlet.version" in pom.classification_text
    assert "jakarta.persistence-api:jar:3.0.x" in build_error.classification_text
    assert "jakarta.servlet-api:pom:5.0.x" in build_error.classification_text
    assert "jakarta.persistence-api/3.0.x" in transform_log.classification_text
