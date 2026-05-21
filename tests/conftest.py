from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_tui_config_path(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path | None:
    if "tui" not in Path(str(request.path)).parts:
        return None

    from migration_factory.tui import app as app_module
    from migration_factory.tui import config as config_module

    config_path = tmp_path / ".ega-migration" / "config.json"

    def load_isolated_config(path: Path = config_path):
        return config_module.load_config(path)

    def save_isolated_config(config, path: Path = config_path) -> None:
        config_module.save_config(config, path)

    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_module, "load_config", load_isolated_config)
    monkeypatch.setattr(app_module, "save_config", save_isolated_config)

    return config_path
