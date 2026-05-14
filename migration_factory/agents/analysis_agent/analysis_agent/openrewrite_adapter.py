import json
import shutil
import subprocess
from pathlib import Path


def _find_dry_run_patch(project_dir: Path):
    """Return first existing OpenRewrite dry-run patch/diff file path."""
    candidates = [
        project_dir / "rewrite.patch",
        project_dir / "target" / "rewrite.patch",
        project_dir / "target" / "site" / "rewrite" / "rewrite.patch",
        project_dir / "target" / "openrewrite" / "rewrite.patch",
        project_dir / "target" / "openrewrite" / "rewrite.diff",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def run_openrewrite_dryrun(context):
    print("🔮 Lancement de la simulation OpenRewrite (Dry-Run)...")

    result_data = {
        "status": "skipped",
        "warnings": [],
    }

    output_file = context.get_output_path("rewrite_preview.json")
    project_dir = Path(context.legacy_app_path)

    cmd = [
        "mvn",
        "rewrite:dryRun",
        "-Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:RELEASE",
        "-Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0",
    ]

    try:
        subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True, check=True)
        result_data["status"] = "used"

        patch_source = _find_dry_run_patch(project_dir)
        if patch_source:
            patch_target = Path(context.get_output_path("rewrite_dry_run.patch"))
            shutil.copyfile(patch_source, patch_target)
            result_data["patch_file"] = "rewrite_dry_run.patch"
    except FileNotFoundError:
        result_data["status"] = "skipped"
        result_data["warnings"].append("OpenRewrite dry-run skipped: Maven executable not found")
    except subprocess.CalledProcessError as exc:
        result_data["status"] = "failed"
        result_data["warnings"].append(f"OpenRewrite dry-run failed: {exc}")
        print("⚠️ Avertissement : La simulation OpenRewrite a échoué, mais l'analyse continue.")
    except Exception as exc:
        result_data["status"] = "failed"
        result_data["warnings"].append(f"OpenRewrite dry-run failed: {exc}")
        print("⚠️ Avertissement : La simulation OpenRewrite a échoué, mais l'analyse continue.")
    finally:
        with open(output_file, "w", encoding="utf-8") as handle:
            json.dump(result_data, handle, indent=4)

    return result_data
