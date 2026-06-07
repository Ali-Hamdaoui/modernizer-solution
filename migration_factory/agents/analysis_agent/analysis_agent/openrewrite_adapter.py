import hashlib
import json
import os
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
        project_dir / "target" / "rewrite" / "rewrite.patch",
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


def _tail(text, limit=4000):
    text = text or ""
    return text[-limit:]


def _failure_diagnostic(exc, cmd, cwd):
    diagnostic = {
        "command": list(cmd or []),
        "cwd": str(cwd),
        "exit_code": getattr(exc, "returncode", None),
        "stdout_tail": _tail(getattr(exc, "stdout", "")),
        "stderr_tail": _tail(getattr(exc, "stderr", "")),
    }
    if diagnostic["exit_code"] is None:
        diagnostic["error"] = str(exc)
    return diagnostic


def _java_command(java_home: str | None):
    if not java_home:
        return "java"
    bin_dir = Path(java_home) / "bin"
    windows_java = bin_dir / "java.exe"
    if windows_java.is_file():
        return str(windows_java)
    return str(bin_dir / "java")


def _java_version_from_output(stdout: str, stderr: str):
    combined = "\n".join(part for part in (stdout, stderr) if part)
    marker = 'version "'
    if marker not in combined:
        return None
    version = combined.split(marker, 1)[1].split('"', 1)[0].strip()
    return version or None


def _detect_java_version(java_home: str | None):
    if not java_home:
        return None
    java_exe = _java_command(java_home)
    try:
        completed = subprocess.run(
            [java_exe, "-version"],
            capture_output=True,
            text=True,
            check=False,
            env=_build_java_env(java_home),
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return _java_version_from_output(completed.stdout, completed.stderr)


def _build_java_env(java_home: str | None):
    if not java_home:
        return None
    env = os.environ.copy()
    env["JAVA_HOME"] = java_home
    env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def _resolve_preview_java_runtime(catalog):
    requested_env = catalog.get("source_jdk_home_env")
    fallback_java_home = os.environ.get("JAVA_HOME")
    if not requested_env:
        return {
            "status": "FALLBACK_CURRENT_PROCESS",
            "java_home_env_used": "JAVA_HOME" if fallback_java_home else None,
            "java_home_used": fallback_java_home,
            "java_version_used": _detect_java_version(fallback_java_home),
            "warning": "OpenRewrite preview source JDK not configured; using current process Java runtime.",
            "error": None,
            "requested_java_home_env": None,
            "env": None,
        }

    java_home = os.environ.get(requested_env)
    if not java_home:
        compatible = _compatible_current_java_fallback(requested_env, fallback_java_home)
        if compatible is not None:
            return compatible
        return {
            "status": "INVALID_SOURCE_JDK_ENV",
            "java_home_env_used": requested_env,
            "java_home_used": None,
            "java_version_used": None,
            "warning": None,
            "error": f"OpenRewrite preview source JDK env '{requested_env}' is not set.",
            "requested_java_home_env": requested_env,
            "env": None,
        }

    java_home_path = Path(java_home)
    java_exe = Path(_java_command(java_home))
    if not java_home_path.is_dir() or not java_exe.is_file():
        return {
            "status": "INVALID_SOURCE_JDK_ENV",
            "java_home_env_used": requested_env,
            "java_home_used": java_home,
            "java_version_used": None,
            "warning": None,
            "error": (
                f"OpenRewrite preview source JDK env '{requested_env}' points to invalid JAVA_HOME: "
                f"{java_home}"
            ),
            "requested_java_home_env": requested_env,
            "env": None,
        }

    return {
        "status": "SOURCE_PROFILE_JDK",
        "java_home_env_used": requested_env,
        "java_home_used": java_home,
        "java_version_used": _detect_java_version(java_home),
        "warning": None,
        "error": None,
        "requested_java_home_env": requested_env,
        "env": _build_java_env(java_home),
    }


def _compatible_current_java_fallback(requested_env: str, fallback_java_home: str | None):
    if not fallback_java_home:
        return None
    java_version = _detect_java_version(fallback_java_home)
    required_major = _requested_env_java_major(requested_env)
    current_major = _java_major_from_text(java_version)
    if required_major is not None and current_major is not None and current_major < required_major:
        return None
    return {
        "status": "FALLBACK_COMPATIBLE_CURRENT_PROCESS",
        "java_home_env_used": "JAVA_HOME" if fallback_java_home else None,
        "java_home_used": fallback_java_home,
        "java_version_used": java_version,
        "warning": (
            f"OpenRewrite preview source JDK env '{requested_env}' is unavailable; "
            "using compatible current process Java runtime."
        ),
        "error": None,
        "requested_java_home_env": requested_env,
        "env": _build_java_env(fallback_java_home),
    }


def _requested_env_java_major(requested_env: str | None):
    if not requested_env:
        return None
    digits = "".join(ch for ch in str(requested_env) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _java_major_from_text(version: str | None):
    if not version:
        return None
    token = str(version).strip()
    if token.startswith("1.8"):
        return 8
    digits = token.split(".", 1)[0]
    try:
        return int(digits)
    except ValueError:
        return None


def _impact_summary(
    context,
    status,
    overall_impact,
    *,
    analysis=None,
    blocked_reasons=None,
    warnings=None,
    source_modified=False,
    failure_diagnostic=None,
    java_runtime=None,
):
    analysis = analysis or {}
    java_runtime = java_runtime or {}
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
                "boot_2_to_4_gap": False,
                "boot4_target": False,
                "java_8_to_21_gap": False,
                "java_21_target": False,
                "security_config_touched": False,
                "datasource_config_touched": False,
            },
        ),
        "blocked_reasons": blocked_reasons or [],
        "warnings": warnings or [],
        "failure_diagnostic": failure_diagnostic,
        "failure_category": (
            failure_diagnostic.get("classification") if isinstance(failure_diagnostic, dict) else None
        ),
        "java_home_env_used": java_runtime.get("java_home_env_used"),
        "java_home_used": java_runtime.get("java_home_used"),
        "java_version_used": java_runtime.get("java_version_used"),
        "jdk_diagnostic": {
            "status": java_runtime.get("status"),
            "requested_java_home_env": java_runtime.get("requested_java_home_env"),
            "warning": java_runtime.get("warning"),
            "error": java_runtime.get("error"),
        },
        "source_modified": source_modified,
        "artifact_refs": {"self": "rewrite_impact_summary.json"},
    }


def run_openrewrite_dryrun(context, analysis_facts=None):
    result_data = {
        "status": "SKIPPED",
        "warnings": [],
        "command": [],
        "cwd": None,
        "exit_code": None,
        "patch_path": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "patch_produced": False,
        "failure_category": None,
        "java_home_env_used": None,
        "java_home_used": None,
        "java_version_used": None,
        "jdk_diagnostic": {
            "status": "UNSET",
            "requested_java_home_env": None,
            "warning": None,
            "error": None,
        },
    }
    project_dir = Path(getattr(context, "project_root_path", context.legacy_app_path))
    preview_path = context.get_output_path("rewrite_preview.json")
    plan_path = context.get_output_path("rewrite_plugin_plan.json")
    impact_path = context.get_output_path("rewrite_impact_summary.json")

    catalog = load_rewrite_catalog(context)
    write_rewrite_plugin_plan(plan_path, context, catalog)
    before_hash = _hash_project_sources(project_dir)
    java_runtime = _resolve_preview_java_runtime(catalog)
    result_data["java_home_env_used"] = java_runtime.get("java_home_env_used")
    result_data["java_home_used"] = java_runtime.get("java_home_used")
    result_data["java_version_used"] = java_runtime.get("java_version_used")
    result_data["jdk_diagnostic"] = {
        "status": java_runtime.get("status"),
        "requested_java_home_env": java_runtime.get("requested_java_home_env"),
        "warning": java_runtime.get("warning"),
        "error": java_runtime.get("error"),
    }
    if java_runtime.get("warning"):
        result_data["warnings"].append(java_runtime["warning"])
    preview_maven_args = catalog.get("openrewrite", {}).get("analysis_preview_maven_args", [])
    preview_skip_warning = None
    if "-Denforcer.skip=true" in preview_maven_args:
        preview_skip_warning = (
            "Legacy Maven Enforcer Java range skipped for OpenRewrite preview only; "
            "final sandbox validation must run without preview-only skip."
        )
        result_data["warnings"].append(preview_skip_warning)

    if catalog["status"] != "USED":
        if catalog.get("errors"):
            result_data["warnings"].extend(catalog["errors"])
        if catalog["status"] == "FAILED":
            result_data["status"] = "FAILED"
        _write_json(preview_path, result_data)
        _write_json(impact_path, _impact_summary(context, "SKIPPED", "UNKNOWN", java_runtime=java_runtime))
        return result_data

    if java_runtime.get("error"):
        result_data["status"] = "FAILED"
        result_data["failure_category"] = "rewrite_preview_failed"
        result_data["warnings"].append(java_runtime["error"])
        diagnostic = {
            "classification": "rewrite_preview_failed",
            "command": [],
            "cwd": str(project_dir),
            "exit_code": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "error": java_runtime["error"],
            "java_home_env_used": java_runtime.get("java_home_env_used"),
            "java_home_used": java_runtime.get("java_home_used"),
            "java_version_used": java_runtime.get("java_version_used"),
        }
        result_data["failure_diagnostic"] = diagnostic
        _write_json(
            impact_path,
            _impact_summary(
                context,
                "FAIL",
                "BLOCKED",
                blocked_reasons=[java_runtime["error"]],
                warnings=[preview_skip_warning] if preview_skip_warning else [],
                failure_diagnostic=diagnostic,
                java_runtime=java_runtime,
            ),
        )
        _write_json(preview_path, result_data)
        return result_data

    try:
        cmd = build_rewrite_maven_command(catalog["openrewrite"])
        completed = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=True,
            env=java_runtime.get("env"),
        )
        result_data["status"] = "USED"
        result_data["command"] = list(cmd)
        result_data["cwd"] = str(project_dir)
        result_data["exit_code"] = completed.returncode
        result_data["stdout_tail"] = _tail(completed.stdout)
        result_data["stderr_tail"] = _tail(completed.stderr)

        patch_source = _find_dry_run_patch(project_dir)
        if patch_source:
            patch_target = Path(context.get_output_path("rewrite_dry_run.patch"))
            shutil.copyfile(patch_source, patch_target)
            result_data["patch_file"] = "rewrite_dry_run.patch"
            result_data["patch_path"] = str(patch_source)
            result_data["patch_produced"] = True
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
                    warnings=[preview_skip_warning] if preview_skip_warning else [],
                    java_runtime=java_runtime,
                ),
            )
        else:
            result_data["patch_path"] = None
            result_data["patch_produced"] = False
            impact = analyze_rewrite_patch("", analysis_facts=analysis_facts)
            _write_json(
                impact_path,
                _impact_summary(
                    context,
                    "WARNING",
                    impact["overall_impact"],
                    analysis=impact,
                    warnings=[preview_skip_warning] if preview_skip_warning else [],
                    java_runtime=java_runtime,
                ),
            )

    except FileNotFoundError:
        result_data["command"] = list(locals().get("cmd") or [])
        result_data["cwd"] = str(project_dir)
        result_data["status"] = "SKIPPED"
        result_data["warnings"].append("OpenRewrite dry-run skipped: Maven executable not found")
        _write_json(impact_path, _impact_summary(context, "SKIPPED", "UNKNOWN", java_runtime=java_runtime))
    except Exception as exc:
        diagnostic = _failure_diagnostic(exc, locals().get("cmd"), project_dir)
        diagnostic["classification"] = "rewrite_preview_failed"
        diagnostic["java_home_env_used"] = java_runtime.get("java_home_env_used")
        diagnostic["java_home_used"] = java_runtime.get("java_home_used")
        diagnostic["java_version_used"] = java_runtime.get("java_version_used")
        result_data["status"] = "FAILED"
        result_data["failure_category"] = "rewrite_preview_failed"
        result_data["warnings"].append(f"OpenRewrite dry-run failed: {exc}")
        result_data["failure_diagnostic"] = diagnostic
        result_data["command"] = diagnostic["command"]
        result_data["cwd"] = diagnostic["cwd"]
        result_data["exit_code"] = diagnostic["exit_code"]
        result_data["stdout_tail"] = diagnostic["stdout_tail"]
        result_data["stderr_tail"] = diagnostic["stderr_tail"]
        result_data["patch_path"] = None
        result_data["patch_produced"] = False
        blocked = [f"OpenRewrite dry-run failed with exit code {diagnostic.get('exit_code')}"]
        if diagnostic.get("stdout_tail"):
            blocked.append(f"OpenRewrite stdout tail: {diagnostic['stdout_tail']}")
        if diagnostic.get("stderr_tail"):
            blocked.append(f"OpenRewrite stderr tail: {diagnostic['stderr_tail']}")
        _write_json(
            impact_path,
            _impact_summary(
                context,
                "FAIL",
                "BLOCKED",
                blocked_reasons=blocked,
                warnings=[preview_skip_warning] if preview_skip_warning else [],
                failure_diagnostic=diagnostic,
                java_runtime=java_runtime,
            ),
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
                    java_runtime=java_runtime,
                ),
            )

        _write_json(preview_path, result_data)

    return result_data
