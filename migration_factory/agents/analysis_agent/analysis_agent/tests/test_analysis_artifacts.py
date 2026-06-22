import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as analysis_main
from analysis_artifacts import discover_reference_project_path
from context_manager import MigrationContext
from main import run_analysis_agent


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _seed_project(root: Path) -> None:
    (root / "src/main/java/com/example").mkdir(parents=True)
    (root / "src/test/java/com/example").mkdir(parents=True)
    (root / "pom.xml").write_text(
        """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>fixture</artifactId>
  <version>1.0.0</version>
</project>
""",
        encoding="utf-8",
    )
    (root / "src/main/java/com/example/App.java").write_text("package com.example;\nclass App {}\n", encoding="utf-8")
    (root / "src/test/java/com/example/AppTest.java").write_text("class AppTest {}\n", encoding="utf-8")


def _stub_analysis_deps(monkeypatch):
    monkeypatch.setattr(analysis_main, "run_dependency_tree", lambda context: None)
    monkeypatch.setattr(analysis_main, "run_openrewrite_dryrun", lambda context, analysis_facts=None: {"status": "SKIPPED", "warnings": []})
    monkeypatch.setattr(
        analysis_main,
        "enrich_with_ai",
        lambda context, report_data: report_data,
    )


def test_analysis_artifacts_generate_runtime_and_reference_delta(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    reference = tmp_path / "reference"
    legacy.mkdir()
    modernized.mkdir()
    reference.mkdir()
    _seed_project(legacy)
    _seed_project(modernized)
    _seed_project(reference)

    before_hash = _hash_tree(legacy)
    (modernized / ".migration").mkdir(parents=True)
    profile = {"analysis": {"reference_project_path": str(reference)}}
    (modernized / ".migration" / "ai_hub_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    _stub_analysis_deps(monkeypatch)

    ctx = MigrationContext("run-artifacts", str(legacy), str(modernized))
    result = run_analysis_agent(ctx)

    assert discover_reference_project_path(ctx) == reference.resolve()
    assert result.status == "COMPLETED"
    assert Path(result.artifact_paths["runtime_contract"]).is_file()
    assert Path(result.artifact_paths["reference_delta"]).is_file()

    report = json.loads(Path(result.artifact_paths["analysis_report"]).read_text(encoding="utf-8"))
    assert report["analysis_artifacts"]["runtime_contract"]["status"] == "generated"
    assert report["analysis_artifacts"]["reference_delta"]["status"] == "generated"
    assert report["analysis_artifacts"]["reference_project_path"] == str(reference.resolve())

    after_hash = _hash_tree(legacy)
    assert after_hash == before_hash


def test_analysis_artifacts_skip_reference_delta_without_config(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    legacy.mkdir()
    modernized.mkdir()
    _seed_project(legacy)
    _seed_project(modernized)

    _stub_analysis_deps(monkeypatch)

    ctx = MigrationContext("run-skip", str(legacy), str(modernized))
    result = run_analysis_agent(ctx)

    assert result.status == "COMPLETED"
    assert Path(result.artifact_paths["runtime_contract"]).is_file()
    assert not Path(result.artifact_paths["reference_delta"]).exists()

    report = json.loads(Path(result.artifact_paths["analysis_report"]).read_text(encoding="utf-8"))
    assert report["analysis_artifacts"]["reference_delta"]["status"] == "skipped_not_configured"
    assert report["analysis_artifacts"]["runtime_contract"]["status"] == "generated"


def test_analysis_artifacts_best_effort_reference_failure(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    reference = tmp_path / "reference"
    legacy.mkdir()
    modernized.mkdir()
    reference.mkdir()
    _seed_project(legacy)
    _seed_project(modernized)
    _seed_project(reference)
    (modernized / ".migration").mkdir(parents=True)
    profile = {"analysis": {"reference_project_path": str(reference)}}
    (modernized / ".migration" / "ai_hub_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    _stub_analysis_deps(monkeypatch)
    monkeypatch.setattr("analysis_artifacts.analyze_reference_delta", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("delta boom")))

    ctx = MigrationContext("run-fail", str(legacy), str(modernized))
    result = run_analysis_agent(ctx)

    assert result.status == "COMPLETED"
    report = json.loads(Path(result.artifact_paths["analysis_report"]).read_text(encoding="utf-8"))
    assert report["analysis_artifacts"]["reference_delta"]["status"] == "failed_best_effort"
    assert report["analysis_artifacts"]["runtime_contract"]["status"] == "generated"
    assert any("delta boom" in warning for warning in result.warnings)
