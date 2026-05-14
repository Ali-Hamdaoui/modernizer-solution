import pytest

from rewrite_command_builder import build_rewrite_maven_command


def _catalog(goal):
    return {
        "plugin": "org.openrewrite.maven:rewrite-maven-plugin:5.40.0",
        "recipe_artifacts": "org.openrewrite.recipe:rewrite-spring:6.0.0",
        "active_recipes": "org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0",
        "dry_run": goal,
    }


def test_allows_only_dryrun_like_goals():
    cmd = build_rewrite_maven_command(_catalog("dryRun"))
    assert cmd[1] == "org.openrewrite.maven:rewrite-maven-plugin:5.40.0:dryRun"


def test_rejects_run_goals():
    with pytest.raises(ValueError):
        build_rewrite_maven_command(_catalog("rewrite:run"))
    with pytest.raises(ValueError):
        build_rewrite_maven_command(_catalog("runNoFork"))


def test_uses_catalog_recipes_and_artifacts():
    cmd = build_rewrite_maven_command(_catalog("discover"))
    assert "-Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0" in cmd
    assert "-Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:6.0.0" in cmd
    assert "-Drewrite.failOnDryRunResults=false" in cmd
