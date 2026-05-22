from __future__ import annotations

import json
from pathlib import Path
import subprocess

import migration_factory.final_report.writer as final_report_writer
import pytest
import migration_factory.agents.copilot_doc_agent.agent as copilot_doc_agent
import migration_factory.final_report.copilot as copilot_module
import migration_factory.orchestrator.summary as summary_module
from migration_factory.final_report.copilot import CopilotAdapterStatus
from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state


@pytest.fixture(autouse=True)
def _clear_copilot_doc_env(monkeypatch) -> None:
    for name in (
        "AI_MIGRATION_COPILOT_DOCS_ENABLED",
        "AI_MIGRATION_COPILOT_CLI_ENABLED",
        "AI_MIGRATION_COPILOT_CLI_PATH",
        "AI_MIGRATION_COPILOT_DOCS_TIMEOUT_SECONDS",
        "AI_MIGRATION_COPILOT_DOCS_FALLBACK_ENABLED",
        "AI_MIGRATION_ENABLE_COPILOT_REPORT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_successful_full_sandbox_writes_final_report_and_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AI_MIGRATION_ENABLE_COPILOT_STATEMENT", raising=False)
    state = _successful_state(tmp_path)

    result = finalize_orchestration_state(state)

    final_report = Path(result["artifact_refs"]["final_migration_report"])
    final_summary = Path(result["artifact_refs"]["final_migration_summary"])
    assert final_report.is_file()
    assert final_summary.is_file()

    payload = json.loads(final_report.read_text(encoding="utf-8"))
    assert payload["test_status"] == "TEST_PASSED"
    assert payload["test_totals"]["tests"] == 3
    assert payload["approval"]["approval_ref"].endswith("approval_decision.json")
    assert payload["lock_status"]["lock_ref"].endswith("approved_plan_lock.json")
    assert payload["limitations"] == [
        "No production promotion performed.",
        "No pull request creation performed.",
        "No deployment performed.",
        "No automatic merge performed.",
    ]
    assert _as_posix(payload["timing"]["timing_report"]).endswith("performance/timing_report.json")
    assert _as_posix(payload["timing"]["timing_summary"]).endswith("performance/timing_summary.md")
    assert "copilot_migration_statement_json" not in result["artifact_refs"]
    assert "copilot_migration_statement_md" not in result["artifact_refs"]
    assert "copilot_report_request" not in result["artifact_refs"]
    assert "copilot_report_response" not in result["artifact_refs"]
    assert "copilot_migration_report" not in result["artifact_refs"]
    assert not (Path(state["run_dir"]) / "final" / "copilot_migration_statement.json").exists()
    assert not (Path(state["run_dir"]) / "final" / "copilot_migration_report.md").exists()
    assert "Copilot Advisory Statement" not in final_summary.read_text(encoding="utf-8")
    assert Path(result["artifact_refs"]["copilot_migration_overview"]).is_file()
    assert Path(result["artifact_refs"]["copilot_technical_changes"]).is_file()
    assert Path(result["artifact_refs"]["copilot_validation_evidence"]).is_file()
    assert Path(result["artifact_refs"]["copilot_risks_and_warnings"]).is_file()
    assert Path(result["artifact_refs"]["copilot_review"]).is_file()
    overview = Path(result["artifact_refs"]["copilot_migration_overview"]).read_text(encoding="utf-8")
    assert "Advisory documentation only" in overview
    assert str(Path(state["artifact_refs"]["analysis_report"])) in overview


def test_enabled_copilot_final_report_writes_optional_sidecar_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    state = _successful_state(tmp_path)

    result = finalize_orchestration_state(state)

    request_ref = Path(result["artifact_refs"]["copilot_report_request"])
    response_ref = Path(result["artifact_refs"]["copilot_report_response"])
    report_ref = Path(result["artifact_refs"]["copilot_migration_report"])
    assert request_ref.is_file()
    assert response_ref.is_file()
    assert report_ref.is_file()

    response = json.loads(response_ref.read_text(encoding="utf-8"))
    assert response["provider"] == "github_copilot"
    assert response["adapter"] == "local_deterministic_template"
    assert response["connectivity"] == "not_configured"
    assert response["model"] == "gpt-5-mini"
    assert response["report_status"] == "generated"
    assert response["advisory_only"] is True
    assert response["can_approve"] is False
    assert response["can_transform"] is False
    assert response["can_change_gates"] is False
    assert response["can_mutate_source"] is False
    assert response["can_override_status"] is False

    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    assert "copilot_report_request" not in final_report["artifact_refs"]
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    assert summary["artifact_refs"]["copilot_report_request"] == str(request_ref)
    assert summary["artifact_refs"]["copilot_report_response"] == str(response_ref)
    assert summary["artifact_refs"]["copilot_migration_report"] == str(report_ref)
    assert result["orchestration_status"] == "PASS"
    assert result["final_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"


def test_enabled_copilot_final_report_uses_internal_resolved_path_only_in_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resolved_path = r"C:\Users\x\AppData\Roaming\npm\copilot.cmd"
    calls: list[list[str]] = []
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    monkeypatch.setenv("AI_MIGRATION_COPILOT_PROVIDER", "copilot_cli")
    monkeypatch.setenv("AI_MIGRATION_COPILOT_MODEL", "gpt-5-mini")

    def fake_detect(**kwargs) -> CopilotAdapterStatus:
        return CopilotAdapterStatus(
            adapter="copilot_cli",
            model="gpt-5-mini",
            connectivity="connected",
            auth_status="authenticated",
            cli_status="installed",
            resolved_executable_path=resolved_path,
        )

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="# Live report\n", stderr="")

    monkeypatch.setattr(summary_module, "detect_copilot_cli_status", fake_detect)
    monkeypatch.setattr(copilot_module, "detect_copilot_cli_status", fake_detect)
    monkeypatch.setattr(copilot_module.subprocess, "run", fake_run)

    result = finalize_orchestration_state(_successful_state(tmp_path))

    response_ref = Path(result["artifact_refs"]["copilot_report_response"])
    request_ref = Path(result["artifact_refs"]["copilot_report_request"])
    response = json.loads(response_ref.read_text(encoding="utf-8"))
    assert calls[0][:2] == [resolved_path, "-p"]
    assert response["adapter"] == "copilot_cli"
    assert response["report_status"] == "generated"
    assert response["resolved_executable_basename"] == "copilot.cmd"
    assert resolved_path not in response_ref.read_text(encoding="utf-8")
    assert resolved_path not in request_ref.read_text(encoding="utf-8")


def test_copilot_documentation_cli_missing_records_status_and_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_COPILOT_CLI_ENABLED", "true")
    state = _successful_state(tmp_path)

    def missing_run(*args, **kwargs):
        raise FileNotFoundError("copilot not found")

    monkeypatch.setattr(copilot_doc_agent.subprocess, "run", missing_run)

    result = finalize_orchestration_state(state)

    assert Path(result["artifact_refs"]["copilot_migration_overview"]).is_file()
    assert Path(result["artifact_refs"]["copilot_input_manifest"]).is_file()
    status_path = Path(result["artifact_refs"]["copilot_cli_status"])
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["adapter"] == "copilot_cli"
    assert status["fallback_status"] == "used"
    assert status["version_check"]["available"] is False
    assert any("CLI unavailable" in warning for warning in status["warnings"])


def test_copilot_documentation_cli_nonzero_records_bounded_status_and_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_COPILOT_CLI_ENABLED", "true")
    state = _successful_state(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="copilot 1.0\n", stderr="")
        return subprocess.CompletedProcess(args, 2, stdout="x" * 3000, stderr="failed")

    monkeypatch.setattr(copilot_doc_agent.subprocess, "run", fake_run)

    result = finalize_orchestration_state(state)

    status = json.loads(Path(result["artifact_refs"]["copilot_cli_status"]).read_text(encoding="utf-8"))
    assert calls == [["copilot", "--version"], ["copilot"]]
    assert status["exit_code"] == 2
    assert status["fallback_status"] == "used"
    assert len(status["stdout_preview"]) < 2100
    assert any("exited nonzero" in warning for warning in result["warnings"])
    assert Path(result["artifact_refs"]["copilot_review"]).is_file()


def test_copilot_documentation_cli_timeout_records_status_and_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_COPILOT_CLI_ENABLED", "true")
    state = _successful_state(tmp_path)

    def fake_run(args, **kwargs):
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="copilot 1.0\n", stderr="")
        raise subprocess.TimeoutExpired(args, timeout=kwargs["timeout"], output="partial", stderr="late")

    monkeypatch.setattr(copilot_doc_agent.subprocess, "run", fake_run)

    result = finalize_orchestration_state(state)

    status = json.loads(Path(result["artifact_refs"]["copilot_cli_status"]).read_text(encoding="utf-8"))
    assert status["timeout"] is True
    assert status["fallback_status"] == "used"
    assert "partial" in status["stdout_preview"]
    assert any("timed out" in warning for warning in result["warnings"])


def test_copilot_documentation_cli_success_uses_generated_docs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_COPILOT_CLI_ENABLED", "true")
    state = _successful_state(tmp_path)

    def fake_run(args, **kwargs):
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="copilot 1.0\n", stderr="")
        docs_dir = Path(kwargs["cwd"]) / "final" / "copilot_docs"
        for artifact in copilot_doc_agent.DOC_ARTIFACTS:
            (docs_dir / artifact).write_text(f"# CLI {artifact}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(copilot_doc_agent.subprocess, "run", fake_run)

    result = finalize_orchestration_state(state)

    overview = Path(result["artifact_refs"]["copilot_migration_overview"]).read_text(encoding="utf-8")
    manifest = json.loads(Path(result["artifact_refs"]["copilot_input_manifest"]).read_text(encoding="utf-8"))
    status = json.loads(Path(result["artifact_refs"]["copilot_cli_status"]).read_text(encoding="utf-8"))
    assert overview.startswith("# CLI migration_overview.md")
    assert manifest["required_outputs"] == list(copilot_doc_agent.DOC_ARTIFACTS)
    assert "analysis_report" in manifest["read_only_artifacts"]
    assert status["fallback_status"] == "not_used"
    assert status["generated_refs"]["copilot_cli_status"] == result["artifact_refs"]["copilot_cli_status"]


def test_copilot_documentation_cli_outside_write_is_rejected_and_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_COPILOT_CLI_ENABLED", "true")
    state = _successful_state(tmp_path)
    protected = Path(state["artifact_refs"]["approval_decision"])
    before = protected.read_bytes()

    def fake_run(args, **kwargs):
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="copilot 1.0\n", stderr="")
        protected.write_text(json.dumps({"decision": "changed"}) + "\n", encoding="utf-8")
        docs_dir = Path(kwargs["cwd"]) / "final" / "copilot_docs"
        for artifact in copilot_doc_agent.DOC_ARTIFACTS:
            (docs_dir / artifact).write_text(f"# CLI {artifact}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(copilot_doc_agent.subprocess, "run", fake_run)

    result = finalize_orchestration_state(state)

    status = json.loads(Path(result["artifact_refs"]["copilot_cli_status"]).read_text(encoding="utf-8"))
    assert status["fallback_status"] == "used"
    assert any("outside docs boundary" in warning for warning in result["warnings"])
    assert protected.read_bytes() == before


def test_enabled_copilot_advisory_writes_artifacts_and_summary_reference(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_STATEMENT", "true")
    state = _successful_state(tmp_path)

    result = finalize_orchestration_state(state)

    json_ref = Path(result["artifact_refs"]["copilot_migration_statement_json"])
    md_ref = Path(result["artifact_refs"]["copilot_migration_statement_md"])
    assert json_ref.is_file()
    assert md_ref.is_file()

    statement = json.loads(json_ref.read_text(encoding="utf-8"))
    assert statement["advisory_only"] is True
    assert statement["can_approve"] is False
    assert statement["can_transform"] is False
    assert statement["can_change_gates"] is False
    assert statement["can_mutate_source"] is False
    assert statement["can_override_status"] is False
    assert "sandbox migration candidate only" in statement["disclaimer"]
    assert "no production promotion, no PR, no deployment" in statement["disclaimer"]
    assert statement["facts"]["approval_decision"] == "approved"
    assert statement["facts"]["test_totals"]["tests"] == 3
    assert statement["facts"]["target_versions"] == {"java": "17"}

    advisory_md = md_ref.read_text(encoding="utf-8")
    assert "Copilot Advisory Statement" in advisory_md
    assert "sandbox migration candidate only" in advisory_md

    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")
    assert "## Copilot Advisory Statement" in final_summary
    assert "copilot_migration_statement.json" in final_summary
    assert "copilot_migration_statement.md" in final_summary

    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    assert final_report["artifact_refs"]["copilot_migration_statement_json"] == str(json_ref)
    assert final_report["artifact_refs"]["copilot_migration_statement_md"] == str(md_ref)


def test_copilot_advisory_failure_records_warning_without_failing_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_STATEMENT", "true")

    def fail_generation(payload, final_dir):
        raise RuntimeError("template unavailable")

    monkeypatch.setattr(final_report_writer, "_generate_copilot_advisory_statement", fail_generation)
    state = _successful_state(tmp_path)

    result = finalize_orchestration_state(state)

    assert result["orchestration_status"] == "PASS"
    assert result["final_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"
    assert result["orchestration_artifacts_valid"] is True
    assert Path(result["artifact_refs"]["final_migration_report"]).is_file()
    assert "copilot_migration_statement_json" not in result["artifact_refs"]
    assert "copilot_migration_statement_md" not in result["artifact_refs"]
    assert any("copilot advisory statement generation failed" in warning for warning in result["warnings"])


def test_missing_test_report_blocks_final_report_generation(tmp_path: Path) -> None:
    state = _successful_state(tmp_path)
    Path(state["artifact_refs"]["post_transform_test_report"]).unlink()

    result = finalize_orchestration_state(state)

    assert result["orchestration_artifacts_valid"] is False
    assert result["orchestration_status"] == "FAIL"
    assert result["final_status"] == "FAILED"
    assert "final_migration_report" not in result["artifact_refs"]
    assert any("post_transform_test_report" in blocker for blocker in result["blockers"])
    assert "copilot_migration_overview" not in result["artifact_refs"]


def test_copilot_documentation_warns_when_required_source_artifact_ref_is_missing(tmp_path: Path) -> None:
    state = _successful_state(tmp_path)
    del state["artifact_refs"]["analysis_report"]

    result = finalize_orchestration_state(state)

    assert result["orchestration_status"] == "PASS"
    assert result["final_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"
    assert "copilot_migration_overview" not in result["artifact_refs"]
    assert any("copilot documentation generation skipped" in warning for warning in result["warnings"])


def test_copilot_documentation_does_not_mutate_source_or_approval_artifacts(tmp_path: Path) -> None:
    state = _successful_state(tmp_path)
    legacy_file = Path(state["legacy_app_path"]) / "src" / "main" / "java" / "Legacy.java"
    sandbox_file = Path(state["sandbox_path"]) / "src" / "main" / "java" / "Migrated.java"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("class Legacy {}\n", encoding="utf-8")
    sandbox_file.write_text("class Migrated {}\n", encoding="utf-8")
    watched = [
        legacy_file,
        sandbox_file,
        Path(state["artifact_refs"]["approval_decision"]),
        Path(state["artifact_refs"]["approved_plan_lock"]),
        Path(state["artifact_refs"]["migration_plan"]),
    ]
    before = {path: path.read_bytes() for path in watched}

    result = finalize_orchestration_state(state)

    assert Path(result["artifact_refs"]["copilot_review"]).is_file()
    assert {path: path.read_bytes() for path in watched} == before


def test_copilot_documentation_runs_only_after_successful_sandbox_validation(tmp_path: Path) -> None:
    state = _successful_state(tmp_path)
    state["test_status"] = "TEST_FAILED"
    state["final_status"] = "TEST_FAILED"

    result = finalize_orchestration_state(state)

    assert result["orchestration_artifacts_valid"] is False
    assert "copilot_migration_overview" not in result["artifact_refs"]


def test_final_report_extracts_transform_unit_recipes_and_boot4_target(tmp_path: Path) -> None:
    state = _successful_state(tmp_path)
    run_dir = Path(state["run_dir"])
    planning_dir = Path(state["planning_dir"])
    assessment_dir = Path(state["assessment_dir"])
    transform_plan = Path(state["artifact_refs"]["transformation_execution_plan"])
    (planning_dir / "migration_plan.yaml").write_text(
        """
profile: springboot-2-java8-to-boot4-java21
risk: HIGH
requires_human_approval: true
target_stack:
  java: "21"
  spring_boot: "4.0.0"
  spring_framework: "7.x"
profile_governance:
  strategy: direct_openrewrite_sandbox
  risk_level: high
  production_allowed: false
  fallback_profile: springboot-2-to-3-5-to-4-java21
warnings:
  - Spring Framework 7 required
""".lstrip(),
        encoding="utf-8",
    )
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps(
            {
                "source_stack": {"java": "8", "spring_boot": "2.7.18"},
                "target_stack": {"java": "21", "spring_boot": "4.0.0"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    transform_plan.write_text(
        """
migration_units:
  - id: java-21
    transformations:
      - type: openrewrite
        active_recipes:
          - org.openrewrite.java.migrate.UpgradeToJava21
          - org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0
""".lstrip(),
        encoding="utf-8",
    )

    result = finalize_orchestration_state(state)

    payload = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    assert payload["target_stack"]["java"] == "21"
    assert payload["target_stack"]["spring_boot"] == "4.0.0"
    assert payload["target_stack"]["spring_framework"] == "7.x"
    assert payload["risk_level"] == "high"
    assert payload["strategy"] == "direct_openrewrite_sandbox"
    assert payload["fallback_profile"] == "springboot-2-to-3-5-to-4-java21"
    assert payload["production_allowed"] is False
    assert payload["recipes"] == [
        "org.openrewrite.java.migrate.UpgradeToJava21",
        "org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0",
    ]
    assert any("Servlet 6.1" in warning for warning in payload["boot4_warnings"])
    assert "No deployment performed." in payload["limitations"]
    assert "No automatic merge performed." in payload["limitations"]


def _successful_state(tmp_path: Path) -> dict:
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    ai_hub = tmp_path / "ai-hub"
    legacy.mkdir()
    modernized.mkdir()
    (ai_hub / "profiles").mkdir(parents=True)
    (ai_hub / "profiles" / "java17.yaml").write_text("id: java17\n", encoding="utf-8")

    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(legacy),
        modernized_app_path=str(modernized),
        ai_hub_path=str(ai_hub),
        profile_id="java17",
        mode=FULL_SANDBOX_MIGRATION_MODE,
    )
    run_dir = Path(state["run_dir"])
    analysis_dir = Path(state["analysis_dir"])
    planning_dir = Path(state["planning_dir"])
    assessment_dir = Path(state["assessment_dir"])
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    approval_dir = run_dir / "approval"
    transform_dir = run_dir / "transformation"
    logs_dir = run_dir / "logs"
    test_dir = run_dir / "test" / "post_transform"

    for directory in (analysis_dir, planning_dir, assessment_dir, sandbox_dir, approval_dir, transform_dir, logs_dir, test_dir):
        directory.mkdir(parents=True, exist_ok=True)

    (analysis_dir / "analysis_report.json").write_text("{}\n", encoding="utf-8")
    (planning_dir / "migration_plan.yaml").write_text("status: PASS\n", encoding="utf-8")
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps({"source_stack": {"java": "11"}, "target_stack": {"java": "17"}}) + "\n",
        encoding="utf-8",
    )

    decision_path = approval_dir / "approval_decision.json"
    lock_path = approval_dir / "approved_plan_lock.json"
    exec_plan_path = transform_dir / "transformation_execution_plan.yaml"
    ledger_path = sandbox_dir / ".migration" / "ledger.json"
    phase2_log_path = logs_dir / "phase2_transform.log"
    test_report_path = test_dir / "test_report.json"
    test_summary_path = test_dir / "test_summary.md"
    test_log_path = test_dir / "test_agent.log"
    timing_report_path = run_dir / "performance" / "timing_report.json"
    timing_summary_path = run_dir / "performance" / "timing_summary.md"
    (sandbox_dir / ".migration").mkdir(parents=True, exist_ok=True)

    decision_path.write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
    lock_path.write_text("{}\n", encoding="utf-8")
    exec_plan_path.write_text("recipes:\n  - org.openrewrite.java.migrate.UpgradeToJava17\n", encoding="utf-8")
    ledger_path.write_text("{}\n", encoding="utf-8")
    phase2_log_path.write_text("ok\n", encoding="utf-8")
    test_summary_path.write_text("# Test\n", encoding="utf-8")
    test_log_path.write_text("ok\n", encoding="utf-8")
    test_report_path.write_text(
        json.dumps(
            {
                "test_status": "TEST_PASSED",
                "totals": {"tests": 3, "passed": 3, "failures": 0, "errors": 0, "skipped": 0},
                "test_log_path": str(test_log_path),
                "source_log_path": str(phase2_log_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    timing_report_path.parent.mkdir(parents=True, exist_ok=True)
    timing_report_path.write_text("{}\n", encoding="utf-8")
    timing_summary_path.write_text("# timing\n", encoding="utf-8")

    state.update(
        {
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "approved_by": "reviewer",
            "orchestration_status": "PASS",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "test_totals": {"tests": 3, "passed": 3, "failures": 0, "errors": 0, "skipped": 0},
            "sandbox_path": str(sandbox_dir),
            "transform_log_path": str(phase2_log_path),
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "artifact_refs": {
                "analysis_report": str(analysis_dir / "analysis_report.json"),
                "approval_decision": str(decision_path),
                "approved_plan_lock": str(lock_path),
                "assessment_report": str(assessment_dir / "assessment_report.json"),
                "migration_plan": str(planning_dir / "migration_plan.yaml"),
                "transformation_execution_plan": str(exec_plan_path),
                "migration_ledger": str(ledger_path),
                "phase2_log": str(phase2_log_path),
                "post_transform_test_report": str(test_report_path),
                "post_transform_test_summary": str(test_summary_path),
                "post_transform_test_log": str(test_log_path),
                "timing_report": str(timing_report_path),
                "timing_summary": str(timing_summary_path),
                "orchestration_summary": str(Path(state["orchestration_dir"]) / "orchestration_summary.json"),
            },
        }
    )
    return state


def _as_posix(path: str) -> str:
    return path.replace("\\", "/")
