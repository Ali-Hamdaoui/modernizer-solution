import json
from pathlib import Path


_REQUIRED_KEYS = (
    "openrewrite.plugin",
    "openrewrite.recipe_artifacts",
    "openrewrite.active_recipes",
    "openrewrite.dry_run",
)


def _catalog_candidates(context):
    modernized = Path(getattr(context, "modernized_app_path", ""))
    legacy = Path(getattr(context, "legacy_app_path", ""))
    return [
        modernized / ".migration" / "ai_hub_profile.json",
        modernized / ".migration" / "catalog.json",
        modernized / "ai_hub_profile.json",
        legacy / ".migration" / "ai_hub_profile.json",
        legacy / "ai_hub_profile.json",
    ]


def load_rewrite_catalog(context):
    for candidate in _catalog_candidates(context):
        if not candidate.is_file():
            continue

        with candidate.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        missing = [key for key in _REQUIRED_KEYS if key not in payload]
        if missing:
            return {
                "status": "FAILED",
                "errors": [f"Catalog missing required fields: {', '.join(missing)}"],
                "path": str(candidate),
            }

        return {
            "status": "USED",
            "path": str(candidate),
            "openrewrite": {
                "plugin": str(payload["openrewrite.plugin"]),
                "recipe_artifacts": str(payload["openrewrite.recipe_artifacts"]),
                "active_recipes": str(payload["openrewrite.active_recipes"]),
                "dry_run": str(payload["openrewrite.dry_run"]),
            },
        }

    return {
        "status": "SKIPPED",
        "errors": ["OpenRewrite catalog/profile not found"],
        "path": None,
    }
