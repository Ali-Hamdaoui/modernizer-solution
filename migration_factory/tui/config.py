from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping

CONFIG_PATH = Path("~/.ega-migration/config.json").expanduser()


class ConfigError(ValueError):
    """Raised when the persisted TUI config cannot be loaded."""


@dataclass
class TuiConfig:
    legacy_app_path: str = ""
    modernized_app_path: str = ""
    ai_hub_path: str = ""
    profile_id: str = ""
    run_id: str = ""
    mode: str = "read_only_assessment"
    approved_by: str = ""
    source_jdk_home: str = ""
    target_jdk_home: str = ""
    active_java_home: str = ""


ENV_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("LEGACY_APP", "legacy_app_path"),
    ("MODERNIZED_APP", "modernized_app_path"),
    ("AI_HUB", "ai_hub_path"),
    ("PROFILE", "profile_id"),
    ("APPROVED_BY", "approved_by"),
    ("RUN_ID", "run_id"),
    ("MODE", "mode"),
    ("JAVA8_HOME", "source_jdk_home"),
    ("JAVA21_HOME", "target_jdk_home"),
    ("JAVA_HOME", "active_java_home"),
)


def load_config(path: Path = CONFIG_PATH) -> TuiConfig:
    if not path.exists():
        return TuiConfig()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config is not valid JSON: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Config cannot be read: {path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config must be a JSON object: {path}")

    valid_keys = {field.name for field in fields(TuiConfig)}
    return TuiConfig(
        **{key: value for key, value in raw.items() if key in valid_keys}
    )


def save_config(config: TuiConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(asdict(config))
    temp_name = ""

    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def fill_config_from_environment(
    config: TuiConfig,
    *,
    environ: Mapping[str, str] | None = None,
    saved_config_exists: bool = True,
) -> tuple[TuiConfig, tuple[str, ...]]:
    """Fill empty config values from process env without replacing saved values."""

    source = environ or os.environ
    values = dict(config.__dict__)
    imported: list[str] = []
    default_config = TuiConfig()

    for env_key, field_name in ENV_FIELD_MAP:
        env_value = source.get(env_key, "").strip()
        if not env_value:
            continue

        current_value = str(values.get(field_name, ""))
        is_default_from_missing_file = (
            not saved_config_exists
            and field_name == "mode"
            and current_value == default_config.mode
        )
        if current_value and not is_default_from_missing_file:
            continue

        values[field_name] = env_value
        imported.append(field_name)

    return TuiConfig(**values), tuple(imported)


def _json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
