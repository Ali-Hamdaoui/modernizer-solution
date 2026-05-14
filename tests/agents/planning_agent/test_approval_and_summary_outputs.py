import json
from pathlib import Path

from migration_factory.agents.planning_agent.node import planning_node


def _write_analysis_fixture(analysis_dir: Path) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "inventory": {
                    "build_tool": "maven",
                    "java_version": "11",
                    "spring_boot_version": "2.7",
                    "javax_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "dependency_graph.json").write_text(
        json.dumps({"nodes": [], "edges": []}), encoding="utf-8"
    )
    (analysis_dir / "test_inventory.json").write_text(
        json.dumps({"tests": []}), encoding="utf-8"
    )
    (analysis_dir / "analysis_summary.md").write_text("analysis ok\n", encoding="utf-8")


def _write_profile(ai_hub_dir: Path, profile_id: str = "java17") -> None:
    profiles_dir = ai_hub_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / f"{profile_id}.yaml").write_text(
        """
source:
  java: 11
  spring_boot: 2.7
  build: maven
target:
  java: 17
  spring_boot: 3.5.14
  build: maven
rules: {}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _state(app_dir: Path, hub_dir: Path, run_id: str = "run-1", profile: str = "java17") -> dict:
    return {
        "run_id": run_id,
        "profile": profile,
        "modernized_app_path": str(app_dir),
        "ai_hub_path": str(hub_dir),
    }


def test_approval_request_has_required_human_review_contract(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    hub_dir = tmp_path / "ai-hub"
    run_id = "approval-contract"

    analysis_dir = app_dir / ".migration" / "runs" / run_id / "analysis"
    _write_analysis_fixture(analysis_dir)
    _write_profile(hub_dir)

    result = planning_node(_state(app_dir, hub_dir, run_id=run_id))
    assert result["planning_status"] == "PASS"

    approval_path = app_dir / ".migration" / "runs" / run_id / "planning" / "approval_request.json"
    payload = json.loads(approval_path.read_text(encoding="utf-8"))

    assert payload["requires_human_approval"] is True
    assert payload["decision_options"] == ["approve", "approve_with_changes", "reject", "replan"]
    assert "units_to_execute" in payload
    assert isinstance(payload["units_to_execute"], list)
    assert payload["units_to_execute"]
    assert "blockers" in payload
    assert isinstance(payload["blockers"], list)
    assert "warnings" in payload
    assert isinstance(payload["warnings"], list)


def test_plan_summary_contains_required_human_review_sections(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    hub_dir = tmp_path / "ai-hub"
    run_id = "summary-sections"

    analysis_dir = app_dir / ".migration" / "runs" / run_id / "analysis"
    _write_analysis_fixture(analysis_dir)
    _write_profile(hub_dir)

    result = planning_node(_state(app_dir, hub_dir, run_id=run_id))
    assert result["planning_status"] == "PASS"

    summary_path = app_dir / ".migration" / "runs" / run_id / "planning" / "plan_summary.md"
    summary = summary_path.read_text(encoding="utf-8")

    required_headings = (
        "## Source Stack",
        "## Target Stack",
        "## Migration Unit Order",
        "## Required Approval",
        "## Risks",
        "## Test Strategy",
        "## What Will Not Happen",
        "## Next Command",
    )

    for heading in required_headings:
        assert heading in summary
