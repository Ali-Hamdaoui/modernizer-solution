from __future__ import annotations

from pathlib import Path

from migration_factory.orchestrator.phase_services import run_sandbox_transform_phase
from migration_factory.orchestrator.state import build_initial_state
from migration_factory.transform_v1_after_approval import TransformSandboxResult


def test_sandbox_transform_phase_propagates_powermock_review_warning_and_artifact(monkeypatch, tmp_path: Path) -> None:
    run_id = "run-001"
    state = build_initial_state(
        run_id=run_id,
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
        ai_hub_path=str(tmp_path / "ai-hub"),
        profile_id="java17",
    )
    run_dir = Path(state["run_dir"])
    sandbox_path = run_dir / "workspaces" / "sandbox"
    log_path = run_dir / "logs" / "phase2_transform.log"
    plan_path = run_dir / "transformation" / "transformation_execution_plan.yaml"
    ledger_path = sandbox_path / ".migration" / "ledger.json"
    powermock_review = sandbox_path / ".migration" / "review" / "powermock_review.json"
    for path in (sandbox_path, log_path.parent, plan_path.parent, ledger_path.parent, powermock_review.parent):
        path.mkdir(parents=True, exist_ok=True)
    log_path.write_text("ok\n", encoding="utf-8")
    plan_path.write_text("recipes: []\n", encoding="utf-8")
    ledger_path.write_text("{}\n", encoding="utf-8")
    powermock_review.write_text("{}\n", encoding="utf-8")

    def fake_apply_approved_sandbox_transform(**_: object) -> TransformSandboxResult:
        return TransformSandboxResult(
            exit_code=0,
            status="TRANSFORM_APPLIED_IN_SANDBOX",
            message="ok",
            sandbox_path=sandbox_path,
            log_file=log_path,
            warnings=["PowerMock legacy test strategy detected; manual review required before trusting Boot 3 test behavior."],
            generated_plan=plan_path,
            ledger_file=ledger_path,
            transform_status="TRANSFORM_APPLIED_IN_SANDBOX",
            build_status="BUILD_PASSED_IN_SANDBOX",
            test_status="TEST_PASSED",
            test_totals={"tests": 1, "passed": 1, "failures": 0, "errors": 0, "skipped": 0},
            powermock_review_path=powermock_review,
        )

    monkeypatch.setattr(
        "migration_factory.transform_v1_after_approval.apply_approved_sandbox_transform",
        fake_apply_approved_sandbox_transform,
    )

    result = run_sandbox_transform_phase(state)

    assert result["artifact_refs"]["powermock_review"].endswith("powermock_review.json")
    assert any("PowerMock legacy test strategy detected" in warning for warning in result["warnings"])


def test_sandbox_transform_phase_propagates_jakarta_hybrid_warning_and_artifact(monkeypatch, tmp_path: Path) -> None:
    run_id = "run-001"
    state = build_initial_state(
        run_id=run_id,
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
        ai_hub_path=str(tmp_path / "ai-hub"),
        profile_id="java17",
    )
    run_dir = Path(state["run_dir"])
    sandbox_path = run_dir / "workspaces" / "sandbox"
    log_path = run_dir / "logs" / "phase2_transform.log"
    plan_path = run_dir / "transformation" / "transformation_execution_plan.yaml"
    ledger_path = sandbox_path / ".migration" / "ledger.json"
    jakarta_review = sandbox_path / ".migration" / "review" / "jakarta_hybrid_strategy.json"
    for path in (sandbox_path, log_path.parent, plan_path.parent, ledger_path.parent, jakarta_review.parent):
        path.mkdir(parents=True, exist_ok=True)
    log_path.write_text("ok\n", encoding="utf-8")
    plan_path.write_text("recipes: []\n", encoding="utf-8")
    ledger_path.write_text("{}\n", encoding="utf-8")
    jakarta_review.write_text("{}\n", encoding="utf-8")

    def fake_apply_approved_sandbox_transform(**_: object) -> TransformSandboxResult:
        return TransformSandboxResult(
            exit_code=0,
            status="TRANSFORM_APPLIED_IN_SANDBOX",
            message="ok",
            sandbox_path=sandbox_path,
            log_file=log_path,
            warnings=["Public API or DTO package uses javax.* namespace; consumer compatibility review required."],
            generated_plan=plan_path,
            ledger_file=ledger_path,
            transform_status="TRANSFORM_APPLIED_IN_SANDBOX",
            build_status="BUILD_PASSED_IN_SANDBOX",
            test_status="TEST_PASSED",
            test_totals={"tests": 1, "passed": 1, "failures": 0, "errors": 0, "skipped": 0},
            jakarta_hybrid_strategy_path=jakarta_review,
        )

    monkeypatch.setattr(
        "migration_factory.transform_v1_after_approval.apply_approved_sandbox_transform",
        fake_apply_approved_sandbox_transform,
    )

    result = run_sandbox_transform_phase(state)

    assert result["artifact_refs"]["jakarta_hybrid_strategy"].endswith("jakarta_hybrid_strategy.json")
    assert any("consumer compatibility review required" in warning.lower() for warning in result["warnings"])


def test_sandbox_transform_phase_propagates_azure_review_warning_and_artifact(monkeypatch, tmp_path: Path) -> None:
    run_id = "run-001"
    state = build_initial_state(
        run_id=run_id,
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
        ai_hub_path=str(tmp_path / "ai-hub"),
        profile_id="java17",
    )
    run_dir = Path(state["run_dir"])
    sandbox_path = run_dir / "workspaces" / "sandbox"
    log_path = run_dir / "logs" / "phase2_transform.log"
    plan_path = run_dir / "transformation" / "transformation_execution_plan.yaml"
    ledger_path = sandbox_path / ".migration" / "ledger.json"
    azure_review = sandbox_path / ".migration" / "review" / "azure_sdk_migration_review.json"
    for path in (sandbox_path, log_path.parent, plan_path.parent, ledger_path.parent, azure_review.parent):
        path.mkdir(parents=True, exist_ok=True)
    log_path.write_text("ok\n", encoding="utf-8")
    plan_path.write_text("recipes: []\n", encoding="utf-8")
    ledger_path.write_text("{}\n", encoding="utf-8")
    azure_review.write_text("{}\n", encoding="utf-8")

    def fake_apply_approved_sandbox_transform(**_: object) -> TransformSandboxResult:
        return TransformSandboxResult(
            exit_code=0,
            status="TRANSFORM_APPLIED_IN_SANDBOX",
            message="ok",
            sandbox_path=sandbox_path,
            log_file=log_path,
            warnings=["Mixed old and new Azure SDK usage detected; partial coexistence requires human review to avoid duplicate runtime stacks."],
            generated_plan=plan_path,
            ledger_file=ledger_path,
            transform_status="TRANSFORM_APPLIED_IN_SANDBOX",
            build_status="BUILD_PASSED_IN_SANDBOX",
            test_status="TEST_PASSED",
            test_totals={"tests": 1, "passed": 1, "failures": 0, "errors": 0, "skipped": 0},
            azure_sdk_migration_review_path=azure_review,
        )

    monkeypatch.setattr(
        "migration_factory.transform_v1_after_approval.apply_approved_sandbox_transform",
        fake_apply_approved_sandbox_transform,
    )

    result = run_sandbox_transform_phase(state)

    assert result["artifact_refs"]["azure_sdk_migration_review"].endswith("azure_sdk_migration_review.json")
    assert any("azure sdk usage" in warning.lower() for warning in result["warnings"])
