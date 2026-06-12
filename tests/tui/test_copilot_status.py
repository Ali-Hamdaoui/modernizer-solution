from __future__ import annotations

import json
from pathlib import Path

import pytest

from migration_factory.final_report.copilot import CopilotAdapterStatus
from migration_factory.tui.app import RunViewModel, _view_launch_state
import migration_factory.tui.copilot_status as copilot_status
from migration_factory.tui.copilot_status import get_copilot_status_lines


def test_copilot_status_maps_live_cli_generated_response(tmp_path: Path) -> None:
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "detected:gpt-5-mini",
                "connectivity": "connected",
                "adapter": "copilot_cli",
                "auth_status": "authenticated",
                "cli_status": "installed",
                "status": "generated",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert get_copilot_status_lines(tmp_path) == [
        "Advisory report status: Advisory report generated",
        "Report generation: Enabled",
        "Copilot Assist: Connected",
        "Provider: github_copilot",
        "Adapter: copilot_cli",
        "Model: gpt-5-mini",
        "Auth: Authenticated",
        "CLI: Installed",
        "Copilot Assist is advisory and does not affect migration result.",
    ]


@pytest.mark.parametrize(
    ("report_status", "expected_status"),
    [
        ("generated", "Advisory report status: Advisory report generated"),
        ("generated_with_fallback", "Advisory report status: Advisory report generated via fallback"),
    ],
)
def test_copilot_status_shows_generated_report_path_only_when_markdown_exists(
    tmp_path: Path,
    report_status: str,
    expected_status: str,
) -> None:
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    report_path = final_dir / "copilot_migration_report.md"
    report_path.write_text("# report\n", encoding="utf-8")
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "gpt-5-mini",
                "connectivity": "connected",
                "adapter": "copilot_cli",
                "auth_status": "authenticated",
                "cli_status": "installed",
                "report_status": report_status,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lines = get_copilot_status_lines(tmp_path)

    assert expected_status in lines
    assert f"Copilot Assist report: {report_path}" in lines


@pytest.mark.parametrize("report_status", ["failed", "disabled", "not_generated", "pending"])
def test_copilot_status_hides_stale_report_path_for_non_generated_statuses(
    tmp_path: Path,
    report_status: str,
) -> None:
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_migration_report.md").write_text("# stale\n", encoding="utf-8")
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "gpt-5-mini",
                "connectivity": "connected",
                "adapter": "copilot_cli",
                "auth_status": "authenticated",
                "cli_status": "installed",
                "report_status": report_status,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lines = get_copilot_status_lines(tmp_path)

    assert not any(line.startswith("Copilot Assist report:") for line in lines)


def test_copilot_status_shows_disabled_when_response_missing_and_report_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="not_configured",
            adapter="local_deterministic_template",
            model="unknown",
            auth_status="unknown",
            cli_status="not_installed",
        ),
    )

    assert get_copilot_status_lines(Path("missing-run")) == [
        "Advisory report status: Copilot Assist disabled",
        "Report generation: Disabled",
        "Copilot Assist: Not configured",
        "Provider: github_copilot",
        "Adapter: local_deterministic_template",
        "Model: unknown",
        "Auth: Unknown",
        "CLI: Not installed",
        "Copilot Assist is advisory and does not affect migration result.",
    ]


def test_copilot_status_shows_not_generated_when_response_missing_after_completion(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="connected",
            adapter="copilot_cli",
            model="configured:gpt-5-mini",
            auth_status="authenticated",
            cli_status="installed",
        ),
    )

    assert get_copilot_status_lines(None, prefer_response=False, active_run=False) == [
        "Advisory report status: Advisory report not generated for this run",
        "Report generation: Enabled",
        "Copilot Assist: Connected",
        "Provider: github_copilot",
        "Adapter: copilot_cli",
        "Model: gpt-5-mini",
        "Auth: Authenticated",
        "CLI: Installed",
        "Copilot Assist is advisory and does not affect migration result.",
    ]


def test_copilot_status_ignores_old_response_when_live_source_requested(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "old-model",
                "connectivity": "connected",
                "adapter": "local_deterministic_template",
                "auth_status": "unknown",
                "cli_status": "not_installed",
                "report_status": "generated",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="connected",
            adapter="copilot_cli",
            model="gpt-5-mini",
            auth_status="authenticated",
            cli_status="installed",
        ),
    )

    lines = get_copilot_status_lines(tmp_path, prefer_response=False, active_run=False)

    assert "Adapter: copilot_cli" in lines
    assert "Model: gpt-5-mini" in lines
    assert "Advisory report status: Advisory report not generated for this run" in lines


def test_copilot_status_shows_pending_for_active_run_without_response(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="connected",
            adapter="copilot_cli",
            model="gpt-5-mini",
            auth_status="authenticated",
            cli_status="installed",
        ),
    )

    lines = get_copilot_status_lines(tmp_path, active_run=True)

    assert "Advisory report status: Advisory report pending while run is active" in lines
    assert "Report generation: Enabled" in lines


def test_copilot_status_maps_unavailable_and_failed(tmp_path: Path) -> None:
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "unknown",
                "connectivity": "unavailable",
                "adapter": "copilot_cli",
                "auth_status": "unauthenticated",
                "cli_status": "installed",
                "status": "failed",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert get_copilot_status_lines(tmp_path) == [
        "Advisory report status: Advisory report unavailable",
        "Report generation: Enabled",
        "Copilot Assist: Unavailable",
        "Provider: github_copilot",
        "Adapter: copilot_cli",
        "Model: unknown",
        "Auth: Unauthenticated",
        "CLI: Installed",
        "Copilot Assist is advisory and does not affect migration result.",
    ]


def test_copilot_status_uses_state_for_pending_without_response(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="connected",
            adapter="copilot_cli",
            model="gpt-5-mini",
            auth_status="authenticated",
            cli_status="installed",
        ),
    )

    lines = get_copilot_status_lines(
        tmp_path,
        active_run=False,
        state={"copilot_report_enabled": True, "copilot_phase_statuses": {"final": "running"}},
    )

    assert "Advisory report status: Advisory report pending while run is active" in lines
    assert "Report generation: Enabled" in lines


def test_copilot_status_maps_fallback_warning_separately(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "gpt-5-mini",
                "connectivity": "connected",
                "adapter": "local_deterministic_template",
                "auth_status": "authenticated",
                "cli_status": "installed",
                "report_status": "generated_with_fallback",
                "warnings": ["copilot CLI report generation failed; used deterministic fallback: FileNotFoundError"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lines = get_copilot_status_lines(tmp_path)

    assert "Advisory report status: Advisory report generated via fallback" in lines
    assert "Copilot warning: CLI failed, fallback used" in lines


def test_copilot_status_maps_timeout_fallback_warning(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "gpt-5-mini",
                "connectivity": "connected",
                "adapter": "local_deterministic_template",
                "auth_status": "authenticated",
                "cli_status": "installed",
                "report_status": "generated_with_fallback",
                "fallback_reason": "timeout",
                "timed_out": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lines = get_copilot_status_lines(tmp_path)

    assert "Advisory report status: Advisory report generated via fallback" in lines
    assert "Copilot warning: CLI timed out, fallback used" in lines


def test_copilot_failure_does_not_change_migration_success_state(tmp_path: Path) -> None:
    vm = RunViewModel(
        run_id="run-001",
        status="COMPLETED",
        approval_status="COMPLETED",
        decision_options=(),
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        },
        blockers=(),
        warnings=(),
        artifact_refs={},
        raw_backend={
            "copilot_report_response": {"status": "failed"},
            "copilot_errors": ["copilot report failed"],
        },
        run_dir=tmp_path,
        returncode=0,
    )

    assert _view_launch_state(vm) == "Run completed"


def test_copilot_fallback_does_not_change_migration_success_state(tmp_path: Path) -> None:
    vm = RunViewModel(
        run_id="run-001",
        status="COMPLETED",
        approval_status="COMPLETED",
        decision_options=(),
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        },
        blockers=(),
        warnings=(),
        artifact_refs={},
        raw_backend={
            "copilot_report_response": {"status": "generated_with_fallback"},
            "copilot_warnings": ["copilot report generated_with_fallback"],
        },
        run_dir=tmp_path,
        returncode=0,
    )

    assert _view_launch_state(vm) == "Run completed"
