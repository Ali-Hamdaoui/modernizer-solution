import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from rewrite_catalog_loader import load_rewrite_catalog
from rewrite_command_builder import build_rewrite_maven_command
from rewrite_impact_analyzer import analyze_rewrite_patch
from rewrite_plugin_plan_writer import write_rewrite_plugin_plan


def _find_dry_run_patch(project_dir: Path):
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


def _hash_project_sources(project_dir: Path):
    digest = hashlib.sha256()
    root_dirs = [project_dir / "src", project_dir / "pom.xml"]
    tracked = []
    for root in root_dirs:
        if root.is_file():
            tracked.append(root)
        elif root.is_dir():
            tracked.extend(sorted(p for p in root.rglob("*") if p.is_file()))

    for path in sorted(tracked):
        rel = path.relative_to(project_dir).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(path.read_bytes())

    return digest.hexdigest()


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)


def _impact_summary(
    context,
    status,
    overall_impact,
    *,
    analysis=None,
    blocked_reasons=None,
    source_modified=False,
):
    analysis = analysis or {}
    return {
        "schema_version": "1.0.0",
        "run_id": getattr(context, "run_id", "unknown"),
        "agent": "analysis_agent",
        "phase": "analysis",
        "status": status,
        "overall_impact": overall_impact,
        "changed_files": analysis.get("changed_files", []),
        "high_risk_files": analysis.get("high_risk_files", []),
        "migration_signals": analysis.get(
            "migration_signals",
            {
                "api_or_boot_upgrade": False,
                "javax_removed": False,
                "boot_2_to_3_gap": False,
                "java_11_to_17_gap": False,
                "javax_present": False,
                "security_config_touched": False,
                "datasource_config_touched": False,
            },
        ),
        "blocked_reasons": blocked_reasons or [],
        "source_modified": source_modified,
        "artifact_refs": {"self": "rewrite_impact_summary.json"},
    }


def run_openrewrite_dryrun(context, analysis_facts=None):
    result_data = {"status": "SKIPPED", "warnings": []}
    project_dir = Path(context.legacy_app_path)
    preview_path = context.get_output_path("rewrite_preview.json")
    plan_path = context.get_output_path("rewrite_plugin_plan.json")
    impact_path = context.get_output_path("rewrite_impact_summary.json")

    catalog = load_rewrite_catalog(context)
    write_rewrite_plugin_plan(plan_path, context, catalog)

    if catalog["status"] != "USED":
        if catalog.get("errors"):
            result_data["warnings"].extend(catalog["errors"])
        if catalog["status"] == "FAILED":
            result_data["status"] = "FAILED"
        _write_json(preview_path, result_data)
        _write_json(impact_path, _impact_summary(context, "SKIPPED", "UNKNOWN"))
        return result_data

    before_hash = _hash_project_sources(project_dir)

    try:
        cmd = build_rewrite_maven_command(catalog["openrewrite"])
        subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True, check=True)
        result_data["status"] = "USED"

        patch_source = _find_dry_run_patch(project_dir)
        if patch_source:
            patch_target = Path(context.get_output_path("rewrite_dry_run.patch"))
            shutil.copyfile(patch_source, patch_target)
            result_data["patch_file"] = "rewrite_dry_run.patch"
            impact = analyze_rewrite_patch(
                patch_target.read_text(encoding="utf-8"),
                analysis_facts=analysis_facts,
            )
            _write_json(
                impact_path,
                _impact_summary(
                    context,
                    "PASS",
                    impact["overall_impact"],
                    analysis=impact,
                ),
            )
        else:
            impact = analyze_rewrite_patch("", analysis_facts=analysis_facts)
            _write_json(
                impact_path,
                _impact_summary(
                    context,
                    "WARNING",
                    impact["overall_impact"],
                    analysis=impact,
                ),
            )

    except FileNotFoundError:
        result_data["status"] = "SKIPPED"
        result_data["warnings"].append("OpenRewrite dry-run skipped: Maven executable not found")
        _write_json(impact_path, _impact_summary(context, "SKIPPED", "UNKNOWN"))
    except Exception as exc:
        result_data["status"] = "FAILED"
        result_data["warnings"].append(f"OpenRewrite dry-run failed: {exc}")
        _write_json(
            impact_path,
            _impact_summary(context, "FAIL", "BLOCKED", blocked_reasons=[str(exc)]),
        )
    finally:
        after_hash = _hash_project_sources(project_dir)
        if before_hash != after_hash:
            result_data["status"] = "FAILED"
            result_data["warnings"].append(
                "Source safety violation: project sources changed during dry-run"
            )
            _write_json(
                impact_path,
                _impact_summary(
                    context,
                    "FAIL",
                    "BLOCKED",
                    blocked_reasons=[
                        "Source safety violation: project sources changed during dry-run"
                    ],
                    source_modified=True,
                ),
            )

        _write_json(preview_path, result_data)

    return result_data
