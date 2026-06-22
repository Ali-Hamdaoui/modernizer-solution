import json
import os
from pathlib import Path
from typing import Any

from migration_factory.tools.reference_delta_analyzer import analyze_reference_delta
from migration_factory.tools.runtime_contract_analyzer import analyze_runtime_contract


_REFERENCE_PATH_KEYS = (
    ("analysis", "reference_project_path"),
    ("analysis", "reference_path"),
    ("reference_project_path",),
    ("reference_path",),
)

_REFERENCE_ENV_KEYS = (
    "AIMF_REFERENCE_PROJECT_PATH",
    "MF_REFERENCE_PROJECT_PATH",
)


def generate_analysis_artifacts(context, legacy_root: str | Path) -> dict[str, Any]:
    legacy_path = Path(legacy_root).expanduser().resolve()
    runtime_output = context.get_output_path("runtime_contract.json")
    reference_output = context.get_output_path("reference_delta.json")
    reference_path = discover_reference_project_path(context)

    manifest = {
        "runtime_contract": {
            "status": "pending",
            "path": str(runtime_output),
            "reference_delta_path": None,
        },
        "reference_delta": {
            "status": "skipped_not_configured",
            "path": str(reference_output),
            "reference_project_path": None,
        },
        "reference_project_path": None,
    }

    reference_delta_path = None
    if reference_path is not None:
        manifest["reference_project_path"] = str(reference_path)
        reference_result = _write_reference_delta(legacy_path, reference_path, reference_output)
        manifest["reference_delta"] = reference_result
        if reference_result["status"] == "generated":
            reference_delta_path = reference_output

    runtime_result = _write_runtime_contract(legacy_path, runtime_output, reference_delta_path)
    manifest["runtime_contract"] = runtime_result

    return {
        "artifact_paths": {
            "runtime_contract": runtime_output,
            "reference_delta": reference_output,
        },
        "analysis_artifacts": manifest,
    }


def discover_reference_project_path(context) -> Path | None:
    env_path = _discover_env_reference_path()
    if env_path is not None:
        return env_path
    return _discover_profile_reference_path(context)


def _discover_env_reference_path() -> Path | None:
    for key in _REFERENCE_ENV_KEYS:
        raw_value = os.environ.get(key, "").strip()
        if not raw_value:
            continue
        candidate = Path(raw_value).expanduser()
        if not candidate.is_absolute():
            continue
        if candidate.exists():
            return candidate.resolve()
    return None


def _discover_profile_reference_path(context) -> Path | None:
    profile_candidates = []
    modernized = getattr(context, "modernized_app_path", None)
    legacy = getattr(context, "legacy_app_path", None)
    if modernized:
        profile_candidates.append(Path(modernized) / ".migration" / "ai_hub_profile.json")
    if legacy:
        profile_candidates.append(Path(legacy) / ".migration" / "ai_hub_profile.json")

    for profile_path in profile_candidates:
        if not profile_path.is_file():
            continue
        try:
            payload = json.loads(profile_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        candidate = _extract_reference_path(payload)
        if candidate is None:
            continue
        resolved = _resolve_relative_path(candidate, profile_path.parent)
        if resolved.exists():
            return resolved.resolve()
    return None


def _extract_reference_path(payload: dict[str, Any]) -> str | None:
    for path in _REFERENCE_PATH_KEYS:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if isinstance(current, str) and current.strip():
            return current.strip()
    return None


def _resolve_relative_path(raw_value: str, base_dir: Path) -> Path:
    candidate = Path(raw_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _write_reference_delta(legacy_path: Path, reference_path: Path, output_path: Path) -> dict[str, Any]:
    try:
        result = analyze_reference_delta(
            legacy_path=legacy_path,
            reference_path=reference_path,
            output_path=output_path,
        )
        return {
            "status": "generated",
            "path": str(result.output_path),
            "reference_project_path": str(result.reference_root),
        }
    except Exception as exc:
        return {
            "status": "failed_best_effort",
            "path": str(output_path),
            "reference_project_path": str(reference_path),
            "error": str(exc),
        }


def _write_runtime_contract(
    legacy_path: Path,
    output_path: Path,
    reference_delta_path: Path | None,
) -> dict[str, Any]:
    try:
        result = analyze_runtime_contract(
            project_path=legacy_path,
            output_path=output_path,
            reference_delta_path=reference_delta_path,
        )
        return {
            "status": "generated",
            "path": str(result.output_path),
            "reference_delta_path": str(reference_delta_path) if reference_delta_path else None,
        }
    except Exception as exc:
        return {
            "status": "failed_best_effort",
            "path": str(output_path),
            "reference_delta_path": str(reference_delta_path) if reference_delta_path else None,
            "error": str(exc),
        }
