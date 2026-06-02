from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import migration_factory.orchestrator.preflight as preflight_module
from migration_factory.agents.failure_classifier import classify_failure
from migration_factory.agents.h2_runtime_startup_agent import build_h2_startup_report, write_h2_config
from migration_factory.agents.openrewrite_diff_safety_agent import scan_openrewrite_diff
from migration_factory.copilot_repair.evidence_session import create_evidence_session, finalize_evidence_session
from migration_factory.copilot_repair.feature_probe import probe_copilot_availability
from migration_factory.copilot_repair.response_validator import (
    parse_copilot_stdout,
    validate_copilot_repair_response,
)
from migration_factory.copilot_repair.skill_validator import validate_agent_file, validate_skill_file
from migration_factory.orchestrator.preflight import PreflightError, build_langgraph_config, validate_preflight
from migration_factory.orchestrator.state import build_initial_state


HELP_ALL_FLAGS = """
--prompt --agent --model --available-tools --deny-tool --no-ask-user --silent
--no-custom-instructions --no-remote --disable-builtin-mcps
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_copilot_feature_probe_requires_required_flags(tmp_path: Path) -> None:
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="--prompt --agent", stderr="")

    result = probe_copilot_availability(
        repo_root=_repo_root(),
        run_dir=tmp_path,
        provider="copilot_cli",
        run=fake_run,
    )

    assert result["status"] == "UNAVAILABLE"
    assert "--no-ask-user" in result["missing_required_flags"]
    assert "--deny-tool" in result["missing_required_flags"]


def test_copilot_availability_required_blocks_preflight(tmp_path: Path, monkeypatch) -> None:
    state = _valid_state(tmp_path)
    state["copilot_required"] = True

    monkeypatch.setattr(
        preflight_module,
        "probe_copilot_availability",
        lambda **kwargs: {"status": "UNAVAILABLE", "reason": "missing flags"},
    )

    with pytest.raises(PreflightError, match="Copilot repair proposal preflight failed"):
        validate_preflight(state, build_langgraph_config(state["run_id"]))


def test_evidence_session_does_not_use_repo_or_sandbox_cwd(tmp_path: Path) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-1"
    sandbox = run_dir / "workspaces" / "sandbox"
    sandbox.mkdir(parents=True)

    session = create_evidence_session(
        repo_root=_repo_root(),
        run_dir=run_dir,
        run_id="run-1",
        evidence={"message": "no secrets"},
    )

    assert session.session_dir.is_relative_to(run_dir.resolve())
    assert session.session_dir != _repo_root().resolve()
    assert session.session_dir != sandbox.resolve()


def test_evidence_session_snapshot_detects_mutation(tmp_path: Path) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-1"
    session = create_evidence_session(
        repo_root=_repo_root(),
        run_dir=run_dir,
        run_id="run-1",
        evidence={"message": "x"},
    )
    (session.session_dir / "unexpected.txt").write_text("changed\n", encoding="utf-8")

    manifest = finalize_evidence_session(session.session_dir, strict=True)

    assert {"path": "unexpected.txt", "status": "created"} in manifest["unexpected_mutations"]
    assert manifest["errors"]


def test_skill_frontmatter_required(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: bad\n---\nbody\n", encoding="utf-8")

    valid, errors = validate_skill_file(skill)

    assert not valid
    assert any("description" in error for error in errors)


def test_skill_forbids_broad_tools(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\nname: bad\ndescription: Bad skill\nallowed-tools: write,shell\n---\nbody\n",
        encoding="utf-8",
    )

    valid, errors = validate_skill_file(skill)

    assert not valid
    assert any("broad tools" in error for error in errors)


def test_agent_validator_rejects_unsafe_agent(tmp_path: Path) -> None:
    agent = tmp_path / "unsafe.agent.md"
    agent.write_text(
        "---\nname: unsafe\ndescription: Unsafe\n---\nYou may deploy and create a PR.\n",
        encoding="utf-8",
    )

    valid, errors = validate_agent_file(agent)

    assert not valid
    assert any("unsafe instruction" in error for error in errors)


def test_openrewrite_deleted_source_file_high_risk() -> None:
    report = scan_openrewrite_diff(
        run_id="run-1",
        diff_text="diff --git a/src/main/java/A.java b/src/main/java/A.java\ndeleted file mode 100644\n",
    )

    assert report["risk_level"] == "HIGH"
    assert report["requires_human_review"] is True


def test_openrewrite_security_change_blocked() -> None:
    report = scan_openrewrite_diff(
        run_id="run-1",
        diff_text=(
            "diff --git a/src/main/java/SecurityConfig.java b/src/main/java/SecurityConfig.java\n"
            "+++ b/src/main/java/SecurityConfig.java\n"
            "+@Bean SecurityFilterChain chain(HttpSecurity http) { return http.authorizeHttpRequests(a -> a.anyRequest().permitAll()).build(); }\n"
        ),
    )

    assert report["status"] == "BLOCKED"
    assert any("permitAll" in item for item in report["high_risk_changes"])


def test_openrewrite_pom_only_aligned_change_low_risk() -> None:
    report = scan_openrewrite_diff(
        run_id="run-1",
        diff_text="diff --git a/pom.xml b/pom.xml\n+++ b/pom.xml\n-<version>2.7.18</version>\n+<version>3.5.0</version>\n",
        planned_pom_changes=["pom.xml"],
    )

    assert report["status"] == "LOW_RISK"
    assert report["requires_human_review"] is False


def test_h2_startup_optional_failure_does_not_break_old_success(tmp_path: Path) -> None:
    class Result:
        succeeded = False
        stdout = ["APPLICATION FAILED TO START"]
        stderr = []

    report = build_h2_startup_report(
        run_id="run-1",
        run_dir=tmp_path,
        sandbox_path=tmp_path,
        required=False,
        runner=lambda **kwargs: Result(),
    )

    assert report["h2_status"] == "H2_STARTUP_WARNING"
    assert report["required"] is False


def test_h2_startup_required_failure_blocks_proof(tmp_path: Path) -> None:
    class Result:
        succeeded = False
        stdout = ["APPLICATION FAILED TO START"]
        stderr = []

    report = build_h2_startup_report(
        run_id="run-1",
        run_dir=tmp_path,
        sandbox_path=tmp_path,
        required=True,
        runner=lambda **kwargs: Result(),
    )

    assert report["h2_status"] == "H2_STARTUP_FAILED"
    assert report["proof_level"] == "not_verified"


def test_h2_config_written_under_run_dir(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    config = write_h2_config(tmp_path / "run")

    assert config.is_relative_to((tmp_path / "run").resolve())
    assert not (sandbox / "src/main/resources/application-migration-smoke.properties").exists()


def test_h2_command_uses_argv_no_shell(tmp_path: Path) -> None:
    calls: list[dict] = []

    class Result:
        succeeded = True
        stdout = ["Started DemoApplication in 1.0 seconds"]
        stderr = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return Result()

    build_h2_startup_report(
        run_id="run-1",
        run_dir=tmp_path,
        sandbox_path=tmp_path,
        runner=fake_runner,
    )

    assert isinstance(calls[0]["command"], list)
    assert calls[0]["command"][0] == "mvn"


def test_failure_classifier_class_not_found_missing_runtime_dependency() -> None:
    report = classify_failure(run_id="run-1", evidence_text="NoClassDefFoundError: org/example/Missing")

    assert report["failure_type"] == "MISSING_RUNTIME_DEPENDENCY"
    assert report["send_to_copilot"] is True


def test_failure_classifier_jakarta_class_not_found() -> None:
    report = classify_failure(run_id="run-1", evidence_text="ClassNotFoundException: jakarta.servlet.Servlet")

    assert report["failure_type"] == "JAKARTA_CLASS_NOT_FOUND"


def test_failure_classifier_keystore_jwt_security_env_warning() -> None:
    report = classify_failure(run_id="run-1", evidence_text="Missing JWT keystore secret")

    assert report["failure_type"] == "SECURITY_ENV_WARNING"
    assert report["migration_blocker"] is False
    assert report["security_env_warning"] is True


def test_copilot_response_rejects_free_form_output() -> None:
    payload, errors = parse_copilot_stdout("Here is the plan")

    assert payload is None
    assert errors


def test_copilot_response_schema_validates() -> None:
    valid, errors = validate_copilot_repair_response(_valid_response())

    assert valid
    assert errors == []


def test_final_report_never_claims_sqlserver_or_endpoint_validation(tmp_path: Path) -> None:
    from tests.test_final_report import _successful_state
    from migration_factory.orchestrator.summary import finalize_orchestration_state

    result = finalize_orchestration_state(_successful_state(tmp_path))
    payload = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))

    assert "SQL Server production behavior" in payload["not_validated"]
    assert "endpoint/business behavior" in payload["not_validated"]
    assert "SQL Server production behavior not validated." in payload["limitations"]


def _valid_response() -> dict:
    return {
        "schema_version": "1.0.0",
        "repair_summary": "Add missing runtime dependency.",
        "failure_classification": "MISSING_RUNTIME_DEPENDENCY",
        "skills_claimed": ["dependency-repair"],
        "wrapper_checklist": {
            "legacy_source_not_modified": True,
            "sandbox_only": True,
            "no_deployment": True,
            "no_pr_creation": True,
            "no_security_weakening": True,
            "h2_only_runtime_scope": True,
            "sql_server_out_of_scope": True,
            "endpoint_smoke_out_of_scope": True,
        },
        "patch_proposals": [],
        "security_review_required": False,
        "confidence": "MEDIUM",
        "refusals": [],
        "limitations": [],
    }


def _valid_state(tmp_path: Path) -> dict:
    legacy_app_path = tmp_path / "legacy"
    modernized_app_path = tmp_path / "modernized"
    ai_hub_path = tmp_path / "ai-hub"
    legacy_app_path.mkdir()
    (ai_hub_path / "profiles").mkdir(parents=True)
    (ai_hub_path / "profiles" / "java17.yaml").write_text("id: java17\n", encoding="utf-8")
    return build_initial_state(
        run_id="run-001",
        legacy_app_path=str(legacy_app_path),
        modernized_app_path=str(modernized_app_path),
        ai_hub_path=str(ai_hub_path),
        profile_id="java17",
    )
