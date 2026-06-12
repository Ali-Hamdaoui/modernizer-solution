from pathlib import Path

from migration_factory.tui.config import TuiConfig
from migration_factory.tui.validation import validate_setup


def _write_profile(ai_hub_path: Path, profile_id: str = "java17") -> None:
    profile_dir = ai_hub_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / f"{profile_id}.yaml").write_text("id: java17\n", encoding="utf-8")


def test_validate_setup_wraps_backend_preflight_success(tmp_path: Path) -> None:
    legacy_app_path = tmp_path / "legacy"
    modernized_app_path = tmp_path / "modernized"
    ai_hub_path = tmp_path / "ai-hub"
    legacy_app_path.mkdir()
    ai_hub_path.mkdir()
    _write_profile(ai_hub_path)

    result = validate_setup(
        TuiConfig(
            legacy_app_path=str(legacy_app_path),
            modernized_app_path=str(modernized_app_path),
            ai_hub_path=str(ai_hub_path),
            profile_id="java17",
            run_id="run-001",
        )
    )

    assert result.ok is True
    assert result.state is not None
    assert result.state["run_id"] == "run-001"
    assert result.langgraph_config == {"configurable": {"thread_id": "run-001"}}
    assert modernized_app_path.is_dir()


def test_validate_setup_wraps_backend_preflight_failure(tmp_path: Path) -> None:
    result = validate_setup(
        TuiConfig(
            legacy_app_path=str(tmp_path / "missing"),
            modernized_app_path=str(tmp_path / "modernized"),
            ai_hub_path=str(tmp_path / "ai-hub"),
            profile_id="java17",
            run_id="run-001",
        )
    )

    assert result.ok is False
    assert "legacy_app_path not found" in result.message
    assert result.state is not None
    assert result.langgraph_config == {"configurable": {"thread_id": "run-001"}}
