import json
from pathlib import Path

from rewrite_catalog_loader import load_rewrite_catalog


class DummyContext:
    def __init__(self, legacy: Path, modernized: Path):
        self.legacy_app_path = str(legacy)
        self.modernized_app_path = str(modernized)


def test_catalog_loads_valid_openrewrite_config(tmp_path):
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    legacy.mkdir()
    (modernized / ".migration").mkdir(parents=True)

    payload = {
        "openrewrite.plugin": "org.openrewrite.maven:rewrite-maven-plugin:5.40.0",
        "openrewrite.recipe_artifacts": "org.openrewrite.recipe:rewrite-spring:6.0.0",
        "openrewrite.active_recipes": "org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0",
        "openrewrite.dry_run": "dryRun",
    }
    (modernized / ".migration" / "ai_hub_profile.json").write_text(json.dumps(payload), encoding="utf-8")

    result = load_rewrite_catalog(DummyContext(legacy, modernized))
    assert result["status"] == "USED"
    assert result["openrewrite"]["plugin"].startswith("org.openrewrite.maven")


def test_missing_catalog_skipped_cleanly(tmp_path):
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    legacy.mkdir()
    modernized.mkdir()

    result = load_rewrite_catalog(DummyContext(legacy, modernized))
    assert result["status"] == "SKIPPED"
