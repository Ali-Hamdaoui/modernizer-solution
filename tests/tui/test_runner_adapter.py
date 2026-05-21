from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from migration_factory.tui.config import TuiConfig
from migration_factory.tui.runner_adapter import (
    RunnerAdapter,
    format_backend_result,
    format_resume_result,
)


def test_launch_invokes_orchestrator_runner_with_configured_inputs() -> None:
    calls: list[list[str]] = []

    def fake_run(args, *, capture_output, text, check):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "human_approval_required",
                    "approval_status": "INTERRUPTED",
                    "run_id": "generated-run",
                    "decision_options": ["approved", "rejected", "replan_required"],
                }
            ),
            stderr="",
        )

    adapter = RunnerAdapter(
        subprocess_runner=fake_run,
        run_id_factory=lambda: "generated-run",
    )

    result = adapter.launch(
        TuiConfig(
            legacy_app_path="/legacy",
            modernized_app_path="/modernized",
            ai_hub_path="/ai-hub",
            profile_id="java17",
            run_id="stale-config-run",
            mode="full_sandbox_migration",
        )
    )

    assert calls == [
        [
            sys.executable,
            "-m",
            "migration_factory.orchestrator.runner",
            "--run-id",
            "generated-run",
            "--legacy",
            "/legacy",
            "--modernized",
            "/modernized",
            "--ai-hub",
            "/ai-hub",
            "--profile",
            "java17",
            "--mode",
            "full_sandbox_migration",
        ]
    ]
    assert result.run_id == "generated-run"
    assert result.human_approval_required is True
    assert result.backend_result["approval_status"] == "INTERRUPTED"


def test_launch_returns_backend_error_payload_for_stderr_only_result() -> None:
    def fake_run(args, *, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=2,
            stdout="",
            stderr="legacy_app_path not found",
        )

    adapter = RunnerAdapter(
        subprocess_runner=fake_run,
        run_id_factory=lambda: "generated-run",
    )

    result = adapter.launch(TuiConfig())

    assert result.returncode == 2
    assert result.backend_result == {
        "status": "backend_error",
        "message": "legacy_app_path not found",
    }
    assert result.human_approval_required is False


def test_launch_returns_backend_error_payload_for_subprocess_exception() -> None:
    def fake_run(args, *, capture_output, text, check):
        raise OSError("cannot start backend")

    adapter = RunnerAdapter(
        subprocess_runner=fake_run,
        run_id_factory=lambda: "generated-run",
    )

    result = adapter.launch(TuiConfig())

    assert result.run_id == "generated-run"
    assert result.returncode == 1
    assert result.run_dir is None
    assert result.backend_result == {
        "status": "backend_error",
        "message": "cannot start backend",
        "error_type": "OSError",
    }


def test_format_backend_result_displays_backend_payload_only() -> None:
    def fake_run(args, *, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"status": "human_approval_required"}),
            stderr="debug noise",
        )

    adapter = RunnerAdapter(
        subprocess_runner=fake_run,
        run_id_factory=lambda: "generated-run",
    )

    rendered = format_backend_result(adapter.launch(TuiConfig()))

    assert "human_approval_required" in rendered
    assert "debug noise" not in rendered


def test_load_approval_state_uses_interrupt_payload() -> None:
    adapter = RunnerAdapter()

    approval = adapter.load_approval_state(
        TuiConfig(modernized_app_path="/modernized", mode="full_sandbox_migration"),
        payload={
            "run_id": "run-approval",
            "blockers": ["blocked"],
            "warnings": ["review"],
            "decision_options": ["approved", "rejected", "unsupported"],
            "artifact_refs": {"plan": "planning/migration_plan.yaml"},
        },
    )

    assert approval is not None
    assert approval.run_id == "run-approval"
    assert approval.run_dir == Path("/modernized/.migration/runs/run-approval")
    assert approval.blockers == ("blocked",)
    assert approval.warnings == ("review",)
    assert approval.decision_options == ("approved", "rejected")
    assert approval.artifact_refs == {"plan": "planning/migration_plan.yaml"}
    assert approval.mode == "full_sandbox_migration"


def test_load_approval_state_falls_back_to_interrupt_state_file(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    state_dir = modernized / ".migration" / "runs" / "run-file" / "orchestration"
    state_dir.mkdir(parents=True)
    (state_dir / "approval_interrupt_state.json").write_text(
        json.dumps(
            {
                "run_id": "run-file",
                "blockers": [],
                "warnings": ["from file"],
                "artifact_refs": {"assessment": "assessment/assessment_report.json"},
            }
        ),
        encoding="utf-8",
    )

    approval = RunnerAdapter().load_approval_state(
        TuiConfig(modernized_app_path=str(modernized), run_id="run-file")
    )

    assert approval is not None
    assert approval.run_id == "run-file"
    assert approval.warnings == ("from file",)
    assert approval.decision_options == ("approved", "rejected", "replan_required")
    assert approval.artifact_refs == {"assessment": "assessment/assessment_report.json"}


def test_resume_requires_approved_by_and_blocks_approve_with_blockers() -> None:
    approval = RunnerAdapter().load_approval_state(
        TuiConfig(modernized_app_path="/modernized"),
        payload={
            "run_id": "run-approval",
            "blockers": ["blocked"],
            "decision_options": ["approved", "rejected", "replan_required"],
        },
    )
    assert approval is not None

    adapter = RunnerAdapter()

    try:
        adapter.resume(approval, decision="rejected", approved_by="")
    except ValueError as exc:
        assert str(exc) == "approved_by is required"
    else:
        raise AssertionError("resume accepted missing approved_by")

    try:
        adapter.resume(approval, decision="approved", approved_by="ada")
    except ValueError as exc:
        assert str(exc) == "Cannot approve while blockers exist"
    else:
        raise AssertionError("resume approved a blocked run")


def test_resume_delegates_to_orchestrator_resume_function() -> None:
    calls = []

    def fake_resume(*, run_id, run_dir, decision, approved_by, comments=""):
        calls.append(
            {
                "run_id": run_id,
                "run_dir": run_dir,
                "decision": decision,
                "approved_by": approved_by,
                "comments": comments,
            }
        )
        return {"final_status": "REJECTED", "approval_decision": decision}

    adapter = RunnerAdapter(resume_function=fake_resume)
    approval = adapter.load_approval_state(
        TuiConfig(modernized_app_path="/modernized"),
        payload={
            "run_id": "run-approval",
            "decision_options": ["approved", "rejected", "replan_required"],
        },
    )
    assert approval is not None

    result = adapter.resume(
        approval,
        decision="rejected",
        approved_by=" ada ",
        comments="stop",
    )

    assert calls == [
        {
            "run_id": "run-approval",
            "run_dir": Path("/modernized/.migration/runs/run-approval"),
            "decision": "rejected",
            "approved_by": "ada",
            "comments": "stop",
        }
    ]
    assert result.stopped is True
    assert "REJECTED" in format_resume_result(result)
