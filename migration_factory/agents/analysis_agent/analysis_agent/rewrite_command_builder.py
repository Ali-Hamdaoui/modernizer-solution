import shutil

_ALLOWED_GOALS = {"dryRun", "dryRunNoFork", "discover"}
_FORBIDDEN_GOALS = {"run", "runNoFork"}


def _parse_plugin(plugin):
    parts = plugin.split(":")
    if len(parts) < 3:
        raise ValueError("Invalid plugin coordinate, expected groupId:artifactId:version")
    return parts[0], parts[1], parts[2]


def _extract_goal(raw_goal):
    goal = str(raw_goal or "").strip()
    if ":" in goal:
        goal = goal.split(":")[-1]
    return goal


def build_rewrite_maven_command(catalog):
    plugin = catalog["plugin"]
    artifacts = catalog["recipe_artifacts"]
    recipes = catalog["active_recipes"]
    goal = _extract_goal(catalog["dry_run"])

    if goal in _FORBIDDEN_GOALS:
        raise ValueError(f"Forbidden OpenRewrite goal: {goal}")
    if goal not in _ALLOWED_GOALS:
        raise ValueError(f"Unsupported OpenRewrite goal: {goal}")

    group_id, artifact_id, version = _parse_plugin(plugin)

    maven_executable = shutil.which("mvn") or shutil.which("mvn.cmd") or "mvn"
    cmd = [
        maven_executable,
        f"{group_id}:{artifact_id}:{version}:{goal}",
        f"-Drewrite.activeRecipes={recipes}",
        f"-Drewrite.recipeArtifactCoordinates={artifacts}",
        "-Drewrite.failOnDryRunResults=false",
    ]
    return cmd
