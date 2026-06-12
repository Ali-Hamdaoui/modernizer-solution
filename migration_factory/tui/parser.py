from __future__ import annotations

import re
from pathlib import Path

from migration_factory.tui.config import TuiConfig

_POWERSHELL_ASSIGNMENT_RE = re.compile(
    r"""^\s*\$(?:env:)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*;?\s*$"""
)
_BASH_EXPORT_RE = re.compile(
    r"""^\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*?)\s*$"""
)
_VARIABLE_RE = re.compile(r"""\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))""")

_ALIASES = {
    "legacy": "legacy_app_path",
    "legacy_app": "legacy_app_path",
    "legacy_app_path": "legacy_app_path",
    "legacy_path": "legacy_app_path",
    "modernized": "modernized_app_path",
    "modernized_app": "modernized_app_path",
    "modernized_app_path": "modernized_app_path",
    "modernized_path": "modernized_app_path",
    "ai_hub": "ai_hub_path",
    "ai_hub_path": "ai_hub_path",
    "aihub": "ai_hub_path",
    "profile": "profile_id",
    "profile_id": "profile_id",
    "run_id": "run_id",
    "runid": "run_id",
    "mode": "mode",
    "approved_by": "approved_by",
    "approvedby": "approved_by",
    "java8_home": "source_jdk_home",
    "source_jdk_home": "source_jdk_home",
    "java21_home": "target_jdk_home",
    "target_jdk_home": "target_jdk_home",
    "java_home": "active_java_home",
    "active_java_home": "active_java_home",
}


def parse_config_variables(content: str, *, home: Path | None = None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    variables: dict[str, str] = {"HOME": _home_value(home)}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = _POWERSHELL_ASSIGNMENT_RE.match(line) or _BASH_EXPORT_RE.match(line)
        if not match:
            continue

        variable_name = match.group("name")
        field_name = _ALIASES.get(variable_name.lower())
        value = _parse_literal_value(match.group("value"), variables)
        variables[variable_name] = value
        if field_name is None:
            continue

        parsed[field_name] = value
    return parsed


def parse_powershell_variables(content: str) -> dict[str, str]:
    return parse_config_variables(content)


def config_from_paste(content: str, base: TuiConfig | None = None) -> TuiConfig:
    values = parse_config_variables(content)
    config = base or TuiConfig()
    return TuiConfig(**({**config.__dict__, **values}))


def config_from_powershell(content: str, base: TuiConfig | None = None) -> TuiConfig:
    return config_from_paste(content, base=base)


def _parse_literal_value(value: str, variables: dict[str, str]) -> str:
    value = value.strip()
    if value.endswith(";"):
        value = value[:-1].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    value = _expand_known_variables(value, variables)
    return _expand_home(value, variables["HOME"])


def _expand_known_variables(value: str, variables: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain") or ""
        return variables.get(name, match.group(0))

    return _VARIABLE_RE.sub(replace, value)


def _expand_home(value: str, home: str) -> str:
    if value == "~":
        return home
    if value.startswith("~/"):
        return f"{home}{value[1:]}"
    return value


def _home_value(home: Path | None) -> str:
    return (home or Path.home()).expanduser().as_posix()
