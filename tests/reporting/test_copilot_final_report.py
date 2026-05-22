from __future__ import annotations

import json
from subprocess import CompletedProcess
from pathlib import Path

import pytest

import migration_factory.final_report.copilot as copilot_module
from migration_factory.final_report.copilot import (
    CopilotAdapterStatus,
    build_copilot_report_request,
    detect_copilot_cli_status,
    generate_copilot_report,
    generate_copilot_report_skeleton,
    load_copilot_report_manifest,
    render_copilot_report_template,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
AI_HUB = REPO_ROOT / "modernizer-solution-ai-hub"


def test_manifest_loads_from_ai_hub_and_resolves_paths() -> None:
    manifest = load_copilot_report_manifest(AI_HUB)

    assert manifest.id == "copilot_final_migration_report_v1"
    assert manifest.version == "1.0.0"
    assert manifest.engine == "github_copilot"
    assert manifest.advisory_only is True
    assert manifest.template_path == AI_HUB / "templates" / "reports" / "copilot_final_migration_report_v1.md"
    assert manifest.output_file == Path("final/copilot_migration_report.md")
    assert manifest.request_file == Path("final/copilot_report_request.json")
    assert manifest.response_file == Path("final/copilot_report_response.json")


def test_missing_required_artifact_fails_report_generation(tmp_path: Path) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)
    (run_dir / "approval" / "approval_decision.json").unlink()
    manifest = load_copilot_report_manifest(AI_HUB)

    request = build_copilot_report_request(run_dir, manifest)

    assert request.missing_required == ["approval/approval_decision.json"]
    with pytest.raises(ValueError, match="approval/approval_decision.json"):
        generate_copilot_report_skeleton(run_dir, AI_HUB)
    assert not (run_dir / "final" / "copilot_migration_report.md").exists()


def test_missing_optional_artifact_is_warning_not_blocker(tmp_path: Path) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)
    manifest = load_copilot_report_manifest(AI_HUB)

    request = build_copilot_report_request(run_dir, manifest)

    assert request.missing_required == []
    assert request.missing_optional == [
        "performance/timing_report.json",
        "workspaces/sandbox/.migration/ledger.json",
        "transformation/transformation_execution_plan.yaml",
    ]
    assert any("missing optional Copilot report artifact" in warning for warning in request.warnings)


def test_deterministic_render_writes_request_response_and_report(tmp_path: Path) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)

    result = generate_copilot_report_skeleton(
        run_dir,
        AI_HUB,
        context={
            "application_name": "payments-service",
            "profile_id": "springboot-3.5-java17",
            "legacy_app_path": "/legacy",
            "final_verdict": "TRANSFORM_APPLIED_IN_SANDBOX",
        },
        status=CopilotAdapterStatus(
            model="configured:gpt-5",
            connectivity="connected",
            report_status="generated",
        ),
    )

    request_path = Path(result["artifact_refs"]["copilot_report_request"])
    response_path = Path(result["artifact_refs"]["copilot_report_response"])
    report_path = Path(result["artifact_refs"]["copilot_migration_report"])
    assert request_path == run_dir / "final" / "copilot_report_request.json"
    assert response_path == run_dir / "final" / "copilot_report_response.json"
    assert report_path == run_dir / "final" / "copilot_migration_report.md"
    assert request_path.is_file()
    assert response_path.is_file()
    assert report_path.is_file()

    report = report_path.read_text(encoding="utf-8")
    assert "{{" not in report
    assert "payments-service" in report
    assert "`github_copilot`" in report
    assert "`gpt-5`" in report

    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["provider"] == "github_copilot"
    assert response["adapter"] == "local_deterministic_template"
    assert response["connectivity"] == "connected"
    assert response["model"] == "gpt-5"
    assert response["auth_status"] == "unknown"
    assert response["cli_status"] == "not_installed"
    assert response["report_status"] == "generated"
    assert response["advisory_only"] is True
    assert response["can_approve"] is False
    assert response["can_transform"] is False
    assert response["can_change_gates"] is False
    assert response["can_mutate_source"] is False
    assert response["can_override_status"] is False


def test_renderer_uses_deterministic_placeholder_substitution(tmp_path: Path) -> None:
    template = tmp_path / "template.md"
    template.write_text("A={{a}}\nB={{b}}\nMissing={{missing}}\n", encoding="utf-8")

    assert render_copilot_report_template(template, {"a": "one", "b": 2}) == "A=one\nB=2\nMissing=\n"


def test_copilot_cli_detector_reports_not_installed(monkeypatch) -> None:
    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", lambda name: None)

    status = detect_copilot_cli_status(env={})

    assert status.to_dict() == {
        "provider": "github_copilot",
        "adapter": "local_deterministic_template",
        "model": "gpt-5-mini",
        "connectivity": "not_configured",
        "report_status": "skipped",
        "auth_status": "unknown",
        "cli_status": "not_installed",
        "resolved_executable_basename": "",
    }


def test_copilot_cli_detector_reports_installed_with_gh_auth(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return f"/tools/{name}" if name in {"copilot", "gh"} else None

    def fake_run(*args, **kwargs) -> CompletedProcess[str]:
        return CompletedProcess(args=args[0], returncode=0, stdout="Logged in to github.com account ada\n", stderr="")

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    status = detect_copilot_cli_status(env={"AI_MIGRATION_COPILOT_MODEL": "gpt-5"})

    assert status.connectivity == "connected"
    assert status.adapter == "copilot_cli"
    assert status.model == "gpt-5"
    assert status.auth_status == "authenticated"
    assert status.cli_status == "installed"


def test_copilot_cli_detector_treats_version_update_error_as_installed(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "copilot":
            return r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd"
        if name == "gh":
            return r"C:\Program Files\GitHub CLI\gh.exe"
        if name == "where.exe":
            return r"C:\Windows\System32\where.exe"
        return None

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        calls.append(list(args))
        if args[1:] == ["version"]:
            return CompletedProcess(
                args=args,
                returncode=1,
                stdout="GitHub Copilot CLI 1.0.51\n",
                stderr="rate limit exceeded while checking for updates\n",
            )
        if args[1:] == ["auth", "status"]:
            return CompletedProcess(args=args, returncode=0, stdout="Logged in to github.com account ada\n", stderr="")
        if args[1:] == ["copilot"]:
            return CompletedProcess(args=args, returncode=0, stdout=r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd\n", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    status = detect_copilot_cli_status(
        env={
            "AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli",
            "AI_MIGRATION_COPILOT_MODEL": "gpt-5-mini",
        }
    )

    assert status.provider == "github_copilot"
    assert status.adapter == "copilot_cli"
    assert status.model == "gpt-5-mini"
    assert status.connectivity == "connected"
    assert status.auth_status == "authenticated"
    assert status.cli_status == "installed"
    assert calls == [
        [r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd", "version"],
        [r"C:\Program Files\GitHub CLI\gh.exe", "auth", "status"],
    ]


def test_copilot_cli_detector_uses_where_when_which_misses_copilot(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "where.exe":
            return r"C:\Windows\System32\where.exe"
        return None

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        calls.append(list(args))
        if args[1:] == ["copilot"]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout="C:\\Users\\ada\\AppData\\Roaming\\npm\\copilot\nC:\\Users\\ada\\AppData\\Roaming\\npm\\copilot.cmd\n",
                stderr="",
            )
        if args[1:] == ["version"]:
            return CompletedProcess(args=args, returncode=1, stdout="GitHub Copilot CLI 1.0.51\n", stderr="update check failed")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    status = detect_copilot_cli_status(env={"AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli"})

    assert status.adapter == "copilot_cli"
    assert status.connectivity == "unavailable"
    assert status.auth_status == "unknown"
    assert status.cli_status == "installed"
    assert status.resolved_executable == r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd"
    assert status.to_dict()["resolved_executable_basename"] == "copilot.cmd"
    assert calls[:2] == [
        [r"C:\Windows\System32\where.exe", "copilot"],
        [r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd", "version"],
    ]


def test_copilot_cli_detector_prefers_cmd_on_windows(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "copilot.cmd":
            return r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd"
        if name == "copilot":
            return r"C:\Users\ada\AppData\Roaming\npm\copilot"
        return None

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        calls.append(list(args))
        if args[1:] == ["version"]:
            return CompletedProcess(args=args, returncode=0, stdout="GitHub Copilot CLI 1.0.51\n", stderr="")
        return CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    monkeypatch.setattr(copilot_module.os, "name", "nt")
    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    status = detect_copilot_cli_status(env={"AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli"})

    assert status.cli_status == "installed"
    assert status.resolved_executable == r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd"
    assert calls[0] == [r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd", "version"]


def test_copilot_cli_detector_normalizes_configured_model(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return f"/tools/{name}" if name in {"copilot", "gh"} else None

    def fake_run(*args, **kwargs) -> CompletedProcess[str]:
        return CompletedProcess(args=args[0], returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    status = detect_copilot_cli_status(env={"AI_MIGRATION_COPILOT_MODEL": "configured:gpt-5-mini"})

    assert status.model == "gpt-5-mini"


def test_copilot_cli_detector_reports_auth_unknown_without_gh(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/tools/copilot" if name == "copilot" else None

    def fake_run(*args, **kwargs) -> CompletedProcess[str]:
        return CompletedProcess(args=args[0], returncode=0, stdout="GitHub Copilot CLI 1.0.51\n", stderr="")

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    status = detect_copilot_cli_status(env={})

    assert status.connectivity == "unavailable"
    assert status.adapter == "copilot_cli"
    assert status.auth_status == "unknown"
    assert status.cli_status == "installed"


def test_request_response_and_report_do_not_persist_secrets(tmp_path: Path) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)
    token = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    final_report = run_dir / "final" / "migration_report.json"
    payload = json.loads(final_report.read_text(encoding="utf-8"))
    payload["github_token"] = token
    payload["nested"] = {"password": "do-not-store"}
    final_report.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    result = generate_copilot_report_skeleton(
        run_dir,
        AI_HUB,
        context={"application_name": token, "profile_id": "secret-profile"},
    )

    for ref in result["artifact_refs"].values():
        content = Path(ref).read_text(encoding="utf-8")
        assert token not in content
        assert "do-not-store" not in content
    request_payload = json.loads(Path(result["artifact_refs"]["copilot_report_request"]).read_text(encoding="utf-8"))
    assert request_payload["artifacts"]["required"]["final/migration_report.json"]["github_token"] == "[REDACTED]"
    assert request_payload["artifacts"]["required"]["final/migration_report.json"]["nested"]["password"] == "[REDACTED]"


def test_copilot_cli_provider_writes_live_markdown_and_response(tmp_path: Path, monkeypatch) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return f"/tools/{name}" if name in {"copilot", "gh"} else None

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        calls.append(list(args))
        if args[1:] == ["version"]:
            return CompletedProcess(args=args, returncode=0, stdout="GitHub Copilot CLI 1.0.51\n", stderr="")
        if args[1:] == ["auth", "status"]:
            return CompletedProcess(args=args, returncode=0, stdout="logged in\n", stderr="")
        return CompletedProcess(args=args, returncode=0, stdout="# Live Copilot Report\n\nGenerated.\n", stderr="")

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    result = generate_copilot_report(
        run_dir,
        AI_HUB,
        env={
            "AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli",
            "AI_MIGRATION_COPILOT_MODEL": "configured:gpt-5-mini",
        },
    )

    response = json.loads(Path(result["artifact_refs"]["copilot_report_response"]).read_text(encoding="utf-8"))
    report = Path(result["artifact_refs"]["copilot_migration_report"]).read_text(encoding="utf-8")
    assert response["adapter"] == "copilot_cli"
    assert response["report_status"] == "generated"
    assert response["model"] == "gpt-5-mini"
    assert "# Live Copilot Report" in report
    assert any(call[:2] == ["/tools/copilot", "-p"] for call in calls)
    prompt_call = next(call for call in calls if call[:2] == ["/tools/copilot", "-p"])
    assert "--no-ask-user" in prompt_call
    assert "--model" in prompt_call


def test_copilot_cli_provider_uses_resolved_cmd_path_on_windows(tmp_path: Path, monkeypatch) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "copilot.cmd":
            return r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd"
        if name == "copilot":
            return r"C:\Users\ada\AppData\Roaming\npm\copilot"
        if name == "gh":
            return r"C:\Program Files\GitHub CLI\gh.exe"
        return None

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        calls.append(list(args))
        if args[1:] == ["version"]:
            return CompletedProcess(args=args, returncode=0, stdout="GitHub Copilot CLI 1.0.51\n", stderr="")
        if args[1:] == ["auth", "status"]:
            return CompletedProcess(args=args, returncode=0, stdout="logged in\n", stderr="")
        if args[0].endswith("copilot.cmd") and args[1] == "-p":
            return CompletedProcess(args=args, returncode=0, stdout="# Live Windows Copilot Report\n", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(copilot_module.os, "name", "nt")
    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    result = generate_copilot_report(
        run_dir,
        AI_HUB,
        env={
            "AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli",
            "AI_MIGRATION_COPILOT_MODEL": "gpt-5-mini",
        },
    )

    response = json.loads(Path(result["artifact_refs"]["copilot_report_response"]).read_text(encoding="utf-8"))
    assert response["adapter"] == "copilot_cli"
    assert response["report_status"] == "generated"
    assert response["resolved_executable_basename"] == "copilot.cmd"
    assert any(call[:2] == [r"C:\Users\ada\AppData\Roaming\npm\copilot.cmd", "-p"] for call in calls)


def test_copilot_cli_provider_uses_internal_resolved_path_without_publishing_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)
    resolved_path = r"C:\Users\x\AppData\Roaming\npm\copilot.cmd"
    calls: list[list[str]] = []

    def fake_detect(**kwargs) -> CopilotAdapterStatus:
        return CopilotAdapterStatus(
            adapter="copilot_cli",
            model="gpt-5-mini",
            connectivity="connected",
            auth_status="authenticated",
            cli_status="installed",
            resolved_executable_path=resolved_path,
        )

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        calls.append(list(args))
        return CompletedProcess(args=args, returncode=0, stdout="# Live Copilot Report\n", stderr="")

    monkeypatch.setattr(copilot_module, "detect_copilot_cli_status", fake_detect)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    result = generate_copilot_report(
        run_dir,
        AI_HUB,
        env={
            "AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli",
            "AI_MIGRATION_COPILOT_MODEL": "gpt-5-mini",
        },
    )

    response_path = Path(result["artifact_refs"]["copilot_report_response"])
    request_path = Path(result["artifact_refs"]["copilot_report_request"])
    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["adapter"] == "copilot_cli"
    assert response["report_status"] == "generated"
    assert response["resolved_executable_basename"] == "copilot.cmd"
    assert calls[0][:2] == [resolved_path, "-p"]
    assert resolved_path not in response_path.read_text(encoding="utf-8")
    assert resolved_path not in request_path.read_text(encoding="utf-8")


def test_copilot_cli_provider_falls_back_when_installed_status_lacks_internal_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)

    def fake_detect(**kwargs) -> CopilotAdapterStatus:
        return CopilotAdapterStatus(
            adapter="copilot_cli",
            model="gpt-5-mini",
            connectivity="connected",
            auth_status="authenticated",
            cli_status="installed",
        )

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr(copilot_module, "detect_copilot_cli_status", fake_detect)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    result = generate_copilot_report(
        run_dir,
        AI_HUB,
        env={
            "AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli",
            "AI_MIGRATION_COPILOT_MODEL": "gpt-5-mini",
        },
    )

    response = json.loads(Path(result["artifact_refs"]["copilot_report_response"]).read_text(encoding="utf-8"))
    warning = "\n".join(response["warnings"])
    assert response["adapter"] == "local_deterministic_template"
    assert response["cli_status"] == "installed"
    assert response["report_status"] == "generated_with_fallback"
    assert "Copilot executable path was not resolved for live call" in warning
    assert "internal_resolved_executable_path_present=false" in warning
    assert "AppData" not in warning


def test_copilot_cli_provider_falls_back_on_empty_output(tmp_path: Path, monkeypatch) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)

    def fake_which(name: str) -> str | None:
        return f"/tools/{name}" if name in {"copilot", "gh"} else None

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        if args[1:] == ["version"]:
            return CompletedProcess(args=args, returncode=0, stdout="GitHub Copilot CLI 1.0.51\n", stderr="")
        if args[1:] == ["auth", "status"]:
            return CompletedProcess(args=args, returncode=0, stdout="logged in\n", stderr="")
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", fake_which)
    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    result = generate_copilot_report(
        run_dir,
        AI_HUB,
        env={
            "AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli",
            "AI_MIGRATION_COPILOT_MODEL": "gpt-5-mini",
        },
    )

    response = json.loads(Path(result["artifact_refs"]["copilot_report_response"]).read_text(encoding="utf-8"))
    report = Path(result["artifact_refs"]["copilot_migration_report"]).read_text(encoding="utf-8")
    assert response["adapter"] == "local_deterministic_template"
    assert response["report_status"] == "generated_with_fallback"
    assert any(
        "RuntimeError: copilot CLI returned empty output" in warning
        for warning in response["warnings"]
    )
    assert "Copilot Final Migration Report" in report


def test_copilot_cli_provider_fallback_warning_is_debug_safe_when_path_unresolved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _run_dir_with_required_artifacts(tmp_path)

    monkeypatch.setattr("migration_factory.final_report.copilot.shutil.which", lambda name: None)

    def fake_run(args, **kwargs) -> CompletedProcess[str]:
        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("migration_factory.final_report.copilot.subprocess.run", fake_run)

    result = generate_copilot_report(
        run_dir,
        AI_HUB,
        env={
            "AI_MIGRATION_COPILOT_PROVIDER": "copilot_cli",
            "AI_MIGRATION_COPILOT_MODEL": "gpt-5-mini",
        },
    )

    response = json.loads(Path(result["artifact_refs"]["copilot_report_response"]).read_text(encoding="utf-8"))
    warning = "\n".join(response["warnings"])
    assert response["adapter"] == "local_deterministic_template"
    assert response["report_status"] == "generated_with_fallback"
    assert "FileNotFoundError: Copilot executable path was not resolved for live call" in warning
    assert "ghp_" not in warning


def _run_dir_with_required_artifacts(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run-001"
    for directory in (
        run_dir / "final",
        run_dir / "orchestration",
        run_dir / "approval",
        run_dir / "test" / "post_transform",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    (run_dir / "final" / "migration_report.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "source_stack": {"java": "11", "spring_boot": "2.7.18", "build_tool": "maven"},
                "target_stack": {"java": "17", "spring_boot": "3.5.0", "build_tool": "maven"},
                "risk_level": "medium",
                "requires_human_approval": True,
                "production_allowed": False,
                "approval": {"status": "COMPLETED", "decision": "approved", "approved_by": "ada"},
                "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "build_status": "BUILD_PASSED_IN_SANDBOX",
                "test_status": "TEST_PASSED",
                "test_totals": {"tests": 4, "passed": 4, "failures": 0, "errors": 0, "skipped": 0},
                "sandbox_path": "/sandbox",
                "warnings": ["review javax leftovers"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "orchestration" / "orchestration_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "orchestration_status": "PASS",
                "orchestration_artifacts_valid": True,
                "blockers": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "approval" / "approval_decision.json").write_text(
        json.dumps({"decision": "approved", "approved_by": "ada", "source": "cli"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "approval" / "approved_plan_lock.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "test" / "post_transform" / "test_report.json").write_text(
        json.dumps(
            {
                "test_status": "TEST_PASSED",
                "totals": {"tests": 4, "passed": 4, "failures": 0, "errors": 0, "skipped": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir
