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

