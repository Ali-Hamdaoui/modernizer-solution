from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable
import xml.etree.ElementTree as ET


CONSUMER_COMPATIBILITY_VALIDATION = "CONSUMER_COMPATIBILITY_VALIDATION"
DEFAULT_INSTALL_COMMAND = "mvn clean install -DskipTests"
DEFAULT_CONSUMER_COMMAND = "mvn clean test"
LIBRARY_PROJECT_KINDS = {"shared_library", "contract_library"}


@dataclass(frozen=True)
class CommandRunResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ConsumerCompatibilityResult:
    report_path: Path
    summary_path: Path
    status: str
    warnings: list[str]
    human_review_required: bool
    production_allowed: bool


CommandRunner = Callable[[str, Path], CommandRunResult]


def run_consumer_compatibility_validation(
    *,
    run_id: str,
    migrated_project_path: Path,
    output_dir: Path,
    config: dict[str, Any] | None = None,
    project_kind: str | None = None,
    command_runner: CommandRunner | None = None,
) -> ConsumerCompatibilityResult:
    migrated_project_path = Path(migrated_project_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    command_runner = command_runner or _default_command_runner
    coordinates = _detect_maven_coordinates(migrated_project_path / "pom.xml")
    config = dict(config or {})
    consumers = list(config.get("consumers") or [])
    install_command = str(config.get("install_command") or DEFAULT_INSTALL_COMMAND)
    default_consumer_command = str(config.get("consumer_command") or DEFAULT_CONSUMER_COMMAND)
    warnings: list[str] = []

    install_log_path = output_dir / "consumer_compatibility_install.log"
    consumer_results: list[dict[str, Any]] = []
    recommended_next_actions: list[str] = []
    status = "NOT_CONFIGURED"
    human_review_required = False
    production_allowed = False

    if not consumers:
        if (project_kind or "").strip() in LIBRARY_PROJECT_KINDS:
            warnings.append("No downstream consumers configured; consumer compatibility validation is required for library migrations.")
            recommended_next_actions.append("Configure downstream consumer projects and rerun consumer compatibility validation before trusting library migration readiness.")
        else:
            recommended_next_actions.append("Configure downstream consumer projects if this artifact has known internal consumers.")
    else:
        install_result = command_runner(install_command, migrated_project_path)
        install_log_path.write_text(_command_log(install_command, migrated_project_path, install_result), encoding="utf-8")
        if install_result.exit_code != 0:
            status = "ERROR"
            human_review_required = True
            warnings.append("Consumer compatibility validation could not install migrated artifact into local Maven repository.")
            recommended_next_actions.append("Review migrated library install failure before validating downstream consumers.")
        else:
            for index, consumer in enumerate(consumers, start=1):
                consumer_path = Path(str(_consumer_path(consumer))).expanduser().resolve()
                consumer_command = str(_consumer_command(consumer) or default_consumer_command)
                before = _source_snapshot(consumer_path)
                run_result = command_runner(consumer_command, consumer_path)
                after = _source_snapshot(consumer_path)
                log_path = output_dir / f"consumer_{index}.log"
                log_path.write_text(_command_log(consumer_command, consumer_path, run_result), encoding="utf-8")
                consumer_results.append(
                    {
                        "consumer_project_path": str(consumer_path),
                        "command": consumer_command,
                        "status": "PASSED" if run_result.exit_code == 0 else "FAILED",
                        "exit_code": run_result.exit_code,
                        "log_path": str(log_path),
                        "source_files_modified": before != after,
                    }
                )
            if any(result["status"] == "FAILED" for result in consumer_results):
                status = "FAILED"
                human_review_required = True
                warnings.append("One or more downstream consumer validations failed against migrated sandbox artifact.")
                recommended_next_actions.append("Review failing consumer test/build results before considering production promotion.")
            else:
                status = "PASSED"
                production_allowed = True
                recommended_next_actions.append("Consumer validations passed; confidence increased, but explicit human approval is still required before production promotion.")

    if not recommended_next_actions:
        recommended_next_actions.append("Review consumer compatibility evidence and decide whether downstream confidence is sufficient.")

    payload = {
        "run_id": run_id,
        "gate_id": CONSUMER_COMPATIBILITY_VALIDATION,
        "status": status,
        "migrated_coordinates": coordinates,
        "migrated_project_path": str(migrated_project_path),
        "consumers_configured": len(consumers),
        "consumer_results": consumer_results,
        "human_review_required": human_review_required,
        "production_allowed": production_allowed,
        "recommended_next_actions": recommended_next_actions,
        "command_outputs": {
            "install_command": install_command,
            "install_log_path": str(install_log_path) if consumers else "",
        },
        "warnings": warnings,
        "limitations": [
            "Consumer projects are validated read-only; no source changes are applied.",
            "Successful consumer validation does not bypass explicit human approval.",
        ],
    }
    report_path = output_dir / "consumer_compatibility_report.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path = output_dir / "consumer_compatibility_summary.md"
    summary_path.write_text(_build_summary(payload), encoding="utf-8")
    return ConsumerCompatibilityResult(
        report_path=report_path,
        summary_path=summary_path,
        status=status,
        warnings=warnings,
        human_review_required=human_review_required,
        production_allowed=production_allowed,
    )


def _detect_maven_coordinates(pom_path: Path) -> dict[str, str]:
    if not pom_path.is_file():
        return {"groupId": "", "artifactId": "", "version": ""}
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return {"groupId": "", "artifactId": "", "version": ""}
    namespace = _namespace(root.tag)
    group_id = _child_text(root, namespace, "groupId") or _child_text(root.find(_tag(namespace, "parent")), namespace, "groupId")
    artifact_id = _child_text(root, namespace, "artifactId")
    version = _child_text(root, namespace, "version") or _child_text(root.find(_tag(namespace, "parent")), namespace, "version")
    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "version": version,
    }


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _tag(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def _child_text(element: ET.Element | None, namespace: str, local_name: str) -> str:
    if element is None:
        return ""
    child = element.find(_tag(namespace, local_name))
    return (child.text or "").strip() if child is not None and child.text else ""


def _consumer_path(consumer: Any) -> Any:
    if isinstance(consumer, dict):
        return consumer.get("path")
    return consumer


def _consumer_command(consumer: Any) -> str:
    if isinstance(consumer, dict):
        return str(consumer.get("command") or "")
    return ""


def _default_command_runner(command: str, cwd: Path) -> CommandRunResult:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return CommandRunResult(
        exit_code=int(completed.returncode),
        stdout=str(completed.stdout or ""),
        stderr=str(completed.stderr or ""),
    )


def _command_log(command: str, cwd: Path, result: CommandRunResult) -> str:
    return (
        f"cwd: {cwd}\n"
        f"command: {command}\n"
        f"exit_code: {result.exit_code}\n"
        f"\n[stdout]\n{result.stdout}\n"
        f"\n[stderr]\n{result.stderr}\n"
    )


def _source_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.is_dir():
        return snapshot
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = _safe_relative(path, root)
        if not rel or _ignored_path(rel):
            continue
        snapshot[rel] = _sha256(path)
    return snapshot


def _ignored_path(relative_path: str) -> bool:
    parts = [part.lower() for part in Path(relative_path).parts]
    return any(part in {"target", ".git", ".migration"} for part in parts)


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _build_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Consumer Compatibility Summary",
        "",
        f"- Status: {payload.get('status', '')}",
        f"- Consumers Configured: {payload.get('consumers_configured', 0)}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- Production Allowed: {str(payload.get('production_allowed')).lower()}",
        "",
    ]
    coordinates = dict(payload.get("migrated_coordinates", {}) or {})
    if any(coordinates.values()):
        lines.extend(
            [
                "## Migrated Coordinates",
                "",
                f"- groupId: {coordinates.get('groupId', '')}",
                f"- artifactId: {coordinates.get('artifactId', '')}",
                f"- version: {coordinates.get('version', '')}",
                "",
            ]
        )
    consumer_results = list(payload.get("consumer_results", []) or [])
    if consumer_results:
        lines.extend(["## Consumer Results", ""])
        for result in consumer_results:
            if not isinstance(result, dict):
                continue
            lines.append(
                f"- {result.get('consumer_project_path', '')}: {result.get('status', '')} "
                f"(exit_code={result.get('exit_code', '')})"
            )
        lines.append("")
    warnings = list(payload.get("warnings", []) or [])
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    actions = list(payload.get("recommended_next_actions", []) or [])
    if actions:
        lines.extend(["## Recommended Next Actions", ""])
        lines.extend(f"- {action}" for action in actions)
    return "\n".join(lines).rstrip() + "\n"
