"""Evidence-backed V2 migration report assembly and rendering.

The language model writes only the narrative sections. All versions, timings,
line counts, stage outcomes, and validation totals are computed from persisted
job evidence so the report remains useful when the model is unavailable.
"""

from __future__ import annotations

import difflib
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from migration_factory.control_tower.application.redaction import (
    redact_model_summary,
    redact_public_value,
)
from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
)
from migration_factory.control_tower.application.v2_llm_invocation_ledger import (
    V2LLMInvocationLedger,
    compute_content_checksum,
)
from migration_factory.control_tower.application.v2_llm_usage import build_llm_usage_summary
from migration_factory.control_tower.schemas.profile_model import (
    get_migration_profile,
    list_migration_profiles,
)

_LOGGER = logging.getLogger(__name__)

_IGNORED_DIRECTORY_NAMES = frozenset({
    ".git",
    ".gradle",
    ".idea",
    ".pytest_cache",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    ".migration",
    "out",
    "target",
})
_MAX_TEXT_FILE_BYTES = 5 * 1024 * 1024
_NOISY_EVENT_TYPES = frozenset({"stdout", "stderr"})
_MAX_TIMELINE_EVENTS = 200


def build_detailed_migration_report(
    *,
    uow: Any,
    job: Any,
    model_client: Any | None = None,
) -> dict[str, Any]:
    """Build a public-safe report from all persisted evidence for one job."""

    route = _route_context(uow, job)
    commands = _commands_by_stage(uow, job.job_id)
    route = _route_with_stage_evidence(route, commands)
    events = _events_for_job(uow, job.job_id)
    setup = _load_setup(uow, job)
    stages = _stage_reports(
        route=route,
        commands=commands,
        events=events,
        initial_source_path=_safe_path_value(getattr(setup, "legacy_app_path", None)),
    )
    timeline, omitted_output_events = _timeline(events)
    event_counts = dict(sorted(Counter(str(getattr(e, "type", "")) for e in events).items()))
    total_duration = _overall_duration_seconds(job, stages, events)
    totals = _aggregate_stage_totals(stages)
    llm_ledger = _llm_ledger(uow)
    report_invocation_id: str | None = None

    facts: dict[str, Any] = {
        "schema_version": "2.0.0",
        "job_id": str(job.job_id),
        "generated_at": _utc_now(),
        "status": "completed",
        "migration_scope": route,
        "summary": {
            "source": route["source_label"],
            "target": route["target_label"],
            "included_stages": list(route["included_stages"]),
            "stage_count": len(stages),
            "duration_seconds": total_duration,
            **totals,
        },
        "stages": stages,
        "timeline": timeline,
        "event_counts": event_counts,
        "omitted_console_events": omitted_output_events,
        "limitations": [
            "Line metrics exclude binary files, generated build output, dependency caches, and files larger than 5 MiB.",
            "LLM narrative is advisory; deterministic metrics and persisted stage evidence are authoritative.",
            "The report describes sandbox migration execution and does not claim production deployment or production validation.",
        ],
    }

    fallback = _deterministic_story(facts)
    client = model_client or V2AssistantModelClient()
    narrative_prompt = _narrative_prompt(facts)
    if llm_ledger is not None:
        try:
            report_invocation_id = llm_ledger.start_invocation(
                job_id=str(job.job_id),
                role="main",
                responsibility="explanation",
                input_checksum=compute_content_checksum(narrative_prompt),
                schema_name="DetailedMigrationReportNarrative",
            )
        except Exception as exc:
            _LOGGER.warning("Report usage capture failed: %s", type(exc).__name__)
    try:
        model_result = client.answer(
            prompt=narrative_prompt,
            fallback=fallback,
        )
        narrative = str(getattr(model_result, "content", "") or fallback).strip()
        narrative_source = (
            "azure_openai"
            if bool(getattr(model_result, "success", False))
            else "deterministic_fallback"
        )
        narrative_status = str(getattr(model_result, "model_status", "") or "fallback")
        if report_invocation_id is not None:
            try:
                if bool(getattr(model_result, "success", False)):
                    llm_ledger.complete_invocation(
                        report_invocation_id,
                        output=narrative,
                        redacted_summary=getattr(model_result, "redacted_summary", None),
                        prompt_tokens=getattr(model_result, "input_tokens", None),
                        completion_tokens=getattr(model_result, "output_tokens", None),
                        total_tokens=getattr(model_result, "total_tokens", None),
                    )
                else:
                    llm_ledger.fail_invocation(
                        report_invocation_id,
                        redacted_error=getattr(model_result, "failure_reason", None),
                        redacted_summary=getattr(model_result, "redacted_summary", None),
                        prompt_tokens=getattr(model_result, "input_tokens", None),
                        completion_tokens=getattr(model_result, "output_tokens", None),
                        total_tokens=getattr(model_result, "total_tokens", None),
                    )
            except Exception as exc:
                _LOGGER.warning("Report usage capture failed: %s", type(exc).__name__)
    except Exception:
        if report_invocation_id is not None:
            try:
                llm_ledger.fail_invocation(report_invocation_id, redacted_error="Report narrative generation failed.")
            except Exception as exc:
                _LOGGER.warning("Report usage capture failed: %s", type(exc).__name__)
        narrative = fallback
        narrative_source = "deterministic_fallback"
        narrative_status = "fallback"

    facts["migration_story"] = _safe_narrative(narrative, fallback=fallback)
    facts["llm_token_usage"] = _llm_usage_for_job(uow, job.job_id)
    facts["narrative_generation"] = {
        "source": narrative_source,
        "status": narrative_status,
    }
    return redact_public_value(facts)


def render_detailed_report_markdown(report: dict[str, Any]) -> str:
    """Render the structured report as PDF-friendly Markdown."""

    scope = dict(report.get("migration_scope", {}) or {})
    summary = dict(report.get("summary", {}) or {})
    stages = list(report.get("stages", []) or [])
    llm_usage = dict(report.get("llm_token_usage", {}) or {})
    timeline = list(report.get("timeline", []) or [])
    event_counts = dict(report.get("event_counts", {}) or {})

    lines = [
        "# Detailed Migration Report",
        "",
        "## Executive Summary",
        "",
        (
            f"This migration moved the application from **{summary.get('source', 'not captured')}** "
            f"to **{summary.get('target', 'not captured')}**."
        ),
        "",
        "### Key Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Outcome | {report.get('status', 'completed')} |",
        f"| Duration | {_format_duration(summary.get('duration_seconds'))} |",
        f"| Migration stages | {summary.get('stage_count', 0)} |",
        f"| Files changed | {summary.get('files_changed', 0)} |",
        f"| Lines added | {summary.get('lines_added', 0)} |",
        f"| Lines deleted | {summary.get('lines_deleted', 0)} |",
        f"| Total lines changed | {summary.get('lines_changed', 0)} |",
        f"| Tests executed | {summary.get('tests', 0)} |",
        f"| Tests passed | {summary.get('tests_passed', 0)} |",
        f"| Repair attempts | {summary.get('repair_attempts', 0)} |",
        "",
        "## Migration Story",
        "",
        str(report.get("migration_story", "") or "No migration narrative was captured."),
        "",
        "## Migration Scope",
        "",
        f"- Source profile: {scope.get('source_label', 'not captured')}",
        f"- Target profile: {scope.get('target_label', 'not captured')}",
        f"- Included stages: {_join_values(scope.get('included_stages'))}",
        f"- Skipped earlier stages: {_join_values(scope.get('skipped_stages'))}",
        f"- Excluded later stages: {_join_values(scope.get('excluded_stages'))}",
        "",
        "## LLM Token Usage and Estimated Cost",
        "",
        f"- Model/deployment: {llm_usage.get('model_or_deployment', 'GPT-5 mini')}",
        f"- Currency: {llm_usage.get('currency', 'USD')}",
        "",
        f"- Total input tokens: {llm_usage.get('input_tokens', 0)}",
        f"- Total output tokens: {llm_usage.get('output_tokens', 0)}",
        f"- Total tokens: {llm_usage.get('total_tokens', 0)}",
        "",
        f"- Input price per 1M tokens: ${llm_usage.get('input_price_per_1m_tokens', '0.25')}",
        f"- Output price per 1M tokens: ${llm_usage.get('output_price_per_1m_tokens', '2.00')}",
        "",
        f"- Input cost: ${llm_usage.get('input_cost', '0')}",
        f"- Output cost: ${llm_usage.get('output_cost', '0')}",
        f"- Total estimated cost: ${llm_usage.get('total_estimated_cost', '0')}",
        "",
        str(llm_usage.get('note', '')),
        "",
        "## Stage-by-Stage Technical Details",
        "",
    ]

    for stage in stages:
        if not isinstance(stage, dict):
            continue
        metrics = dict(stage.get("change_metrics", {}) or {})
        tests = dict(stage.get("test_totals", {}) or {})
        phases = dict(stage.get("phase_durations_seconds", {}) or {})
        lines.extend([
            f"### Stage {stage.get('stage_index', '')}: {stage.get('transition', 'not captured')}",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Status | {stage.get('status', 'not captured')} |",
            f"| Duration | {_format_duration(stage.get('duration_seconds'))} |",
            f"| Files changed | {metrics.get('files_changed', 0)} |",
            f"| Lines added | {metrics.get('lines_added', 0)} |",
            f"| Lines deleted | {metrics.get('lines_deleted', 0)} |",
            f"| Total lines changed | {metrics.get('lines_changed', 0)} |",
            f"| Transform | {stage.get('transform_status', 'not captured')} |",
            f"| Build | {stage.get('build_status', 'not captured')} |",
            f"| Tests | {stage.get('test_status', 'not captured')} |",
            f"| Proof | {stage.get('proof_level', 'not captured')} |",
            f"| Test total / passed / failed | {tests.get('tests', 0)} / {tests.get('passed', 0)} / {tests.get('failed', 0)} |",
            f"| Repair attempts | {stage.get('repair_attempts', 0)} |",
            "",
        ])
        if phases:
            lines.extend(["#### Phase Timing", "", "| Phase | Duration |", "|---|---|"])
            for name, duration in sorted(phases.items()):
                lines.append(f"| {_display_name(name)} | {_format_duration(duration)} |")
            lines.append("")
        warnings = list(stage.get("warnings", []) or [])
        if warnings:
            lines.extend(["#### Warnings and Decisions", ""])
            lines.extend(f"- {warning}" for warning in warnings)
            lines.append("")

    lines.extend([
        "## Migration Process Timeline",
        "",
        "| Time | Stage | Event | Status | Detail |",
        "|---|---|---|---|---|",
    ])
    for event in timeline:
        if not isinstance(event, dict):
            continue
        lines.append(
            "| "
            + " | ".join([
                _table_text(event.get("created_at")),
                _table_text(event.get("stage", "job")),
                _table_text(_display_name(event.get("type"))),
                _table_text(event.get("status")),
                _table_text(event.get("message")),
            ])
            + " |"
        )
    if not timeline:
        lines.append("| not captured | job | No lifecycle events captured | not captured | - |")

    lines.extend([
        "",
        "## Event Coverage",
        "",
        "| Event Type | Count |",
        "|---|---|",
    ])
    for event_type, count in event_counts.items():
        lines.append(f"| {_table_text(_display_name(event_type))} | {count} |")
    lines.extend([
        "",
        (
            f"Console output events omitted from the narrative timeline: "
            f"{report.get('omitted_console_events', 0)}. Their aggregate count remains above."
        ),
        "",
        "## Report Provenance and Limitations",
        "",
        (
            "- Narrative generation: "
            f"{dict(report.get('narrative_generation', {}) or {}).get('source', 'not captured')} "
            f"({dict(report.get('narrative_generation', {}) or {}).get('status', 'not captured')})"
        ),
    ])
    lines.extend(f"- {item}" for item in list(report.get("limitations", []) or []))
    lines.extend([
        "",
        f"- Report generated at: {report.get('generated_at', '')}",
        f"- Migration job: {report.get('job_id', '')}",
        "",
    ])
    return "\n".join(lines)


def included_stages_for_job(uow: Any, job: Any) -> tuple[int, ...]:
    route = _route_context(uow, job)
    return tuple(int(value) for value in route.get("included_stages", []) or [])


def terminal_stage_for_job(uow: Any, job: Any) -> int:
    included = included_stages_for_job(uow, job)
    return max(int(value) for value in included) if included else 0


def _route_context(uow: Any, job: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    repository = getattr(uow, "run_configurations", None)
    if repository is not None and callable(getattr(repository, "get_for_job", None)):
        record = repository.get_for_job(job.job_id)
        if record is not None:
            payload = _json_object(getattr(record, "payload_json", None))

    source_id = str(payload.get("source_profile") or "")
    target_id = str(payload.get("target_profile") or "")
    source = get_migration_profile(source_id)
    target = get_migration_profile(target_id)

    if source is None or target is None:
        command_stages = sorted(_commands_by_stage(uow, job.job_id))
        first_stage = command_stages[0] if command_stages else 1
        last_stage = command_stages[-1] if command_stages else 4
        profiles = {profile.stage_index: profile for profile in list_migration_profiles()}
        source = profiles.get(max(first_stage - 1, 0))
        target = profiles.get(last_stage)

    if source is None or target is None:
        included = tuple(sorted(_commands_by_stage(uow, job.job_id)))
        source_label = source_id or "Source profile not captured"
        target_label = target_id or "Target profile not captured"
        source_stage = min(included, default=1) - 1
        target_stage = max(included, default=4)
    else:
        source_id = str(source.profile_id)
        target_id = str(target.profile_id)
        source_label = str(source.display_name)
        target_label = str(target.display_name)
        source_stage = int(source.stage_index)
        target_stage = int(target.stage_index)
        included = tuple(range(source_stage + 1, target_stage + 1))

    all_stages = set(range(1, 5))
    return {
        "source_profile": source_id,
        "source_label": source_label,
        "target_profile": target_id,
        "target_label": target_label,
        "included_stages": list(included),
        "skipped_stages": sorted(stage for stage in all_stages if stage <= source_stage),
        "excluded_stages": sorted(stage for stage in all_stages if stage > target_stage),
    }


def _route_with_stage_evidence(
    route: dict[str, Any],
    commands: dict[int, list[Any]],
) -> dict[str, Any]:
    updated = dict(route)
    included = [int(value) for value in route.get("included_stages", []) or []]
    if not included:
        return updated

    first_command = _preferred_command(commands.get(min(included), []))
    last_command = _preferred_command(commands.get(max(included), []))
    source_stack = _stack_from_result(
        _json_object(getattr(first_command, "result_json", None)),
        stack_names=("source_stack", "source_profile_facts", "profile_facts"),
        artifact_names=("source_profile_detection", "assessment_report", "analysis_report"),
    )
    target_stack = _stack_from_result(
        _json_object(getattr(last_command, "result_json", None)),
        stack_names=("target_stack", "full_migration_target_stack"),
        artifact_names=("assessment_report", "migration_plan", "target_dependency_plan"),
    )
    source_label = _stack_label(source_stack)
    target_label = _stack_label(target_stack)
    if source_label:
        updated["source_label"] = source_label
        updated["source_stack"] = source_stack
    if target_label:
        updated["target_label"] = target_label
        updated["target_stack"] = target_stack
    return updated


def _stack_from_result(
    result: dict[str, Any],
    *,
    stack_names: tuple[str, ...],
    artifact_names: tuple[str, ...],
) -> dict[str, str]:
    candidate = _find_named_mapping(result, stack_names)
    normalized = _normalize_stack(candidate)
    if normalized:
        return normalized
    refs = result.get("artifact_refs")
    if not isinstance(refs, dict):
        return {}
    for artifact_name in artifact_names:
        document = _read_structured_artifact(refs.get(artifact_name))
        candidate = _find_named_mapping(document, stack_names)
        normalized = _normalize_stack(candidate)
        if normalized:
            return normalized
    return {}


def _find_named_mapping(value: Any, names: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    for name in names:
        candidate = value.get(name)
        if isinstance(candidate, dict):
            return candidate
    for child in value.values():
        if isinstance(child, dict):
            candidate = _find_named_mapping(child, names)
            if candidate:
                return candidate
    return {}


def _normalize_stack(value: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    java = str(value.get("java") or value.get("java_version") or "").strip()
    spring_boot = str(
        value.get("spring_boot")
        or value.get("spring_boot_version")
        or value.get("spring_boot_line")
        or ""
    ).strip()
    result: dict[str, str] = {}
    if java and java.lower() != "unknown":
        result["java"] = java
    if spring_boot and spring_boot.lower() != "unknown":
        result["spring_boot"] = spring_boot
    return result


def _stack_label(stack: dict[str, str]) -> str:
    parts = []
    if stack.get("spring_boot"):
        parts.append(f"Spring Boot {stack['spring_boot']}")
    if stack.get("java"):
        parts.append(f"Java {stack['java']}")
    return " / ".join(parts)


def _read_structured_artifact(value: Any) -> dict[str, Any]:
    path = _safe_path_value(value)
    if path is None or not path.is_file():
        return {}
    try:
        if path.stat().st_size > _MAX_TEXT_FILE_BYTES:
            return {}
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            parsed = yaml.safe_load(text)
        else:
            parsed = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _commands_by_stage(uow: Any, job_id: str) -> dict[int, list[Any]]:
    repository = getattr(uow, "v2_commands", None)
    if repository is None or not callable(getattr(repository, "list_by_job", None)):
        return {}
    grouped: dict[int, list[Any]] = {}
    for command in repository.list_by_job(job_id):
        grouped.setdefault(int(command.stage_index), []).append(command)
    return grouped


def _events_for_job(uow: Any, job_id: str) -> list[Any]:
    repository = getattr(uow, "v2_events", None)
    if repository is None or not callable(getattr(repository, "list_by_job", None)):
        return []
    return list(repository.list_by_job(job_id))


def _load_setup(uow: Any, job: Any) -> Any | None:
    repository = getattr(uow, "v2_setups", None)
    if repository is None or not callable(getattr(repository, "get", None)):
        return None
    return repository.get(job.setup_id)


def _stage_reports(
    *,
    route: dict[str, Any],
    commands: dict[int, list[Any]],
    events: list[Any],
    initial_source_path: Path | None,
) -> list[dict[str, Any]]:
    profiles = {profile.stage_index: profile for profile in list_migration_profiles()}
    current_source_path = initial_source_path
    reports: list[dict[str, Any]] = []
    for stage_index in route.get("included_stages", []):
        stage_index = int(stage_index)
        stage_commands = commands.get(stage_index, [])
        command = _preferred_command(stage_commands)
        result = _json_object(getattr(command, "result_json", None)) if command is not None else {}
        stage_events = [event for event in events if getattr(event, "stage", None) == stage_index]
        duration = _stage_duration_seconds(command, result, stage_events)
        output_path = _stage_output_path(result, stage_events)
        metrics = _extract_change_metrics(result)
        if metrics is None:
            metrics = _compare_source_trees(current_source_path, output_path)
        if metrics is None:
            metrics = {
                "files_changed": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "lines_changed": 0,
                "source": "not_captured",
            }

        source_profile = profiles.get(stage_index - 1)
        target_profile = profiles.get(stage_index)
        tests = _test_totals(result)
        reports.append({
            "stage_index": stage_index,
            "transition": (
                f"{source_profile.display_name} to {target_profile.display_name}"
                if source_profile is not None and target_profile is not None
                else f"Stage {stage_index}"
            ),
            "status": str(getattr(command, "status", "") or result.get("final_status") or "not captured"),
            "started_at": _stage_boundary(stage_events, command, first=True),
            "completed_at": _stage_boundary(stage_events, command, first=False),
            "duration_seconds": duration,
            "change_metrics": metrics,
            "transform_status": _fact_text(result, "transform_status"),
            "build_status": _fact_text(result, "build_status"),
            "test_status": _fact_text(result, "test_status"),
            "proof_level": _fact_text(result, "final_proof_level"),
            "test_totals": tests,
            "repair_attempts": _int_value(result.get("repair_attempts_count")),
            "phase_durations_seconds": _phase_durations(result),
            "warnings": _safe_text_list(result.get("warnings")),
            "event_count": len(stage_events),
        })
        if output_path is not None:
            current_source_path = output_path
    return reports


def _preferred_command(commands: list[Any]) -> Any | None:
    if not commands:
        return None
    successful = [
        command
        for command in commands
        if str(getattr(command, "status", "")) == "completed"
        and _looks_like_success(_json_object(getattr(command, "result_json", None)))
    ]
    candidates = successful or commands
    return max(candidates, key=lambda item: str(getattr(item, "updated_at", "")))


def _extract_change_metrics(result: dict[str, Any]) -> dict[str, Any] | None:
    containers = [result]
    for key in ("change_metrics", "diff_stats", "diff_summary", "rewrite_summary", "transform_summary"):
        value = result.get(key)
        if isinstance(value, dict):
            containers.insert(0, value)

    aliases = {
        "files_changed": ("files_changed", "changed_files_count", "modified_files"),
        "lines_added": ("lines_added", "added_lines", "insertions"),
        "lines_deleted": ("lines_deleted", "deleted_lines", "deletions", "lines_removed"),
        "lines_changed": ("lines_changed", "changed_lines", "total_lines_changed"),
    }
    found: dict[str, int] = {}
    for output_key, input_keys in aliases.items():
        value = _find_numeric_value(containers, input_keys)
        if value is not None:
            found[output_key] = value
    if not found:
        return None
    added = found.get("lines_added", 0)
    deleted = found.get("lines_deleted", 0)
    found.setdefault("files_changed", 0)
    found.setdefault("lines_added", added)
    found.setdefault("lines_deleted", deleted)
    found.setdefault("lines_changed", added + deleted)
    found["source"] = "stage_evidence"
    return found


def _find_numeric_value(containers: list[dict[str, Any]], keys: tuple[str, ...]) -> int | None:
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
    return None


def _compare_source_trees(source: Path | None, target: Path | None) -> dict[str, Any] | None:
    if source is None or target is None or not source.is_dir() or not target.is_dir():
        return None
    try:
        if source.resolve() == target.resolve():
            return None
    except OSError:
        return None

    source_files = _text_file_snapshot(source)
    target_files = _text_file_snapshot(target)
    files_changed = 0
    lines_added = 0
    lines_deleted = 0
    for relative_path in sorted(set(source_files) | set(target_files)):
        before = source_files.get(relative_path)
        after = target_files.get(relative_path)
        if before == after:
            continue
        files_changed += 1
        if before is None:
            lines_added += len(after or [])
            continue
        if after is None:
            lines_deleted += len(before)
            continue
        matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
        for opcode, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if opcode in {"replace", "delete"}:
                lines_deleted += old_end - old_start
            if opcode in {"replace", "insert"}:
                lines_added += new_end - new_start
    return {
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "lines_changed": lines_added + lines_deleted,
        "source": "source_tree_comparison",
    }


def _text_file_snapshot(root: Path) -> dict[str, list[str]]:
    snapshot: dict[str, list[str]] = {}
    try:
        candidates = root.rglob("*")
        for path in candidates:
            try:
                relative = path.relative_to(root)
                if any(part in _IGNORED_DIRECTORY_NAMES for part in relative.parts):
                    continue
                if not path.is_file() or path.stat().st_size > _MAX_TEXT_FILE_BYTES:
                    continue
                raw = path.read_bytes()
                if b"\x00" in raw:
                    continue
                text = raw.decode("utf-8", errors="strict")
                snapshot[relative.as_posix()] = text.splitlines()
            except (OSError, UnicodeError):
                continue
    except OSError:
        return {}
    return snapshot


def _timeline(events: list[Any]) -> tuple[list[dict[str, Any]], int]:
    omitted_console_events = 0
    result: list[dict[str, Any]] = []
    for event in events:
        event_type = str(getattr(event, "type", "") or "")
        if event_type in _NOISY_EVENT_TYPES:
            omitted_console_events += 1
            continue
        if len(result) >= _MAX_TIMELINE_EVENTS:
            continue
        result.append({
            "created_at": str(getattr(event, "created_at", "") or ""),
            "stage": getattr(event, "stage", None),
            "type": event_type,
            "status": str(getattr(event, "status", "") or ""),
            "message": str(redact_model_summary(str(getattr(event, "message", "") or ""))),
        })
    return result, omitted_console_events


def _overall_duration_seconds(job: Any, stages: list[dict[str, Any]], events: list[Any]) -> float:
    start = _parse_datetime(getattr(job, "created_at", None))
    completed_events = [
        event
        for event in events
        if str(getattr(event, "type", "")) in {"migration_completed", "job_completed", "stage_completed"}
    ]
    parsed_completion_times = [
        parsed
        for event in completed_events
        if (parsed := _parse_datetime(getattr(event, "created_at", None))) is not None
    ]
    end = max(
        parsed_completion_times,
        default=None,
    )
    if start is not None and end is not None and end >= start:
        return round((end - start).total_seconds(), 3)
    return round(sum(float(stage.get("duration_seconds") or 0) for stage in stages), 3)


def _aggregate_stage_totals(stages: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "files_changed": 0,
        "lines_added": 0,
        "lines_deleted": 0,
        "lines_changed": 0,
        "tests": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "repair_attempts": 0,
    }
    for stage in stages:
        metrics = dict(stage.get("change_metrics", {}) or {})
        tests = dict(stage.get("test_totals", {}) or {})
        totals["files_changed"] += _int_value(metrics.get("files_changed"))
        totals["lines_added"] += _int_value(metrics.get("lines_added"))
        totals["lines_deleted"] += _int_value(metrics.get("lines_deleted"))
        totals["lines_changed"] += _int_value(metrics.get("lines_changed"))
        totals["tests"] += _int_value(tests.get("tests"))
        totals["tests_passed"] += _int_value(tests.get("passed"))
        totals["tests_failed"] += _int_value(tests.get("failed"))
        totals["repair_attempts"] += _int_value(stage.get("repair_attempts"))
    return totals


def _llm_ledger(uow: Any) -> V2LLMInvocationLedger | None:
    repository = getattr(uow, "v2_llm_invocations", None)
    return V2LLMInvocationLedger(repository) if repository is not None else None


def _llm_usage_for_job(uow: Any, job_id: str) -> dict[str, Any]:
    repository = getattr(uow, "v2_llm_invocations", None)
    records = repository.list_by_job(job_id) if repository is not None else ()
    return build_llm_usage_summary(records)

def _narrative_prompt(facts: dict[str, Any]) -> str:
    narrative_facts = {
        "migration_scope": facts.get("migration_scope"),
        "summary": facts.get("summary"),
        "stages": facts.get("stages"),
        "timeline": list(facts.get("timeline", []) or [])[:80],
        "event_counts": facts.get("event_counts"),
    }
    return (
        "Write the 'Migration Story' section of a polished engineering migration report for "
        "technical leaders and delivery stakeholders. Use only the evidence in the JSON below. "
        "Write clear, well-structured paragraphs that explain the migration journey "
        "chronologically: scope, stage-by-stage technical work, validation outcomes, repairs or "
        "approvals, timing, and line-change impact. Emphasize what changed, how it was validated, "
        "and what limitations remain. Do not mention excluded migrations as if they ran. Never "
        "invent missing facts; say 'not captured' when needed. Do not expose paths, environment "
        "variables, commands, endpoints, deployment names, secrets, or raw model prompts. Return "
        "5-8 concise Markdown paragraphs with no top-level heading, no table, and no bullet list.\n\n"
        + json.dumps(narrative_facts, sort_keys=True)
    )


def _deterministic_story(facts: dict[str, Any]) -> str:
    summary = dict(facts.get("summary", {}) or {})
    stages = list(facts.get("stages", []) or [])
    paragraphs = [
        (
            f"The migration began at {summary.get('source', 'a source profile that was not captured')} "
            f"and finished at {summary.get('target', 'a target profile that was not captured')}. "
            f"It covered {summary.get('stage_count', 0)} migration stage(s) in "
            f"{_format_duration(summary.get('duration_seconds'))}."
        ),
        (
            f"Across the included route, {summary.get('files_changed', 0)} files changed, with "
            f"{summary.get('lines_added', 0)} lines added and {summary.get('lines_deleted', 0)} "
            f"lines deleted ({summary.get('lines_changed', 0)} total changed lines)."
        ),
    ]
    for stage in stages:
        metrics = dict(stage.get("change_metrics", {}) or {})
        paragraphs.append(
            f"Stage {stage.get('stage_index')} moved from {stage.get('transition')}. "
            f"It finished with status {stage.get('status')} in "
            f"{_format_duration(stage.get('duration_seconds'))}; "
            f"{metrics.get('files_changed', 0)} files and {metrics.get('lines_changed', 0)} "
            f"lines changed. Build status was {stage.get('build_status')}, test status was "
            f"{stage.get('test_status')}, and proof level was {stage.get('proof_level')}."
        )
    paragraphs.append(
        "The recorded outcome is limited to the governed sandbox migration. Production deployment "
        "and production behavior were outside this run."
    )
    return "\n\n".join(paragraphs)


def _safe_narrative(value: str, *, fallback: str) -> str:
    safe = str(redact_public_value(redact_model_summary(value))).strip()
    return safe or fallback


def _stage_duration_seconds(command: Any, result: dict[str, Any], events: list[Any]) -> float:
    timing = _phase_durations(result)
    total_run = timing.get("total_run")
    if isinstance(total_run, (int, float)):
        return round(float(total_run), 3)
    parsed_event_times = [
        parsed
        for event in events
        if (parsed := _parse_datetime(getattr(event, "created_at", None))) is not None
    ]
    start = min(parsed_event_times, default=None)
    end_candidates = [
        parsed
        for event in events
        if str(getattr(event, "type", "")).endswith(("completed", "failed", "cancelled"))
        if (parsed := _parse_datetime(getattr(event, "created_at", None))) is not None
    ]
    end = max(end_candidates, default=None)
    if start is None and command is not None:
        start = _parse_datetime(getattr(command, "created_at", None))
    if end is None and command is not None:
        end = _parse_datetime(getattr(command, "updated_at", None))
    if start is not None and end is not None and end >= start:
        return round((end - start).total_seconds(), 3)
    return 0.0


def _stage_boundary(events: list[Any], command: Any, *, first: bool) -> str:
    values = [
        str(getattr(event, "created_at", "") or "")
        for event in events
        if str(getattr(event, "created_at", "") or "")
    ]
    if values:
        return min(values) if first else max(values)
    if command is None:
        return ""
    return str(getattr(command, "created_at" if first else "updated_at", "") or "")


def _phase_durations(result: dict[str, Any]) -> dict[str, float]:
    timing = result.get("timing")
    if not isinstance(timing, dict):
        return {}
    raw = timing.get("phase_durations_seconds")
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): round(float(duration), 3)
        for name, duration in raw.items()
        if isinstance(duration, (int, float)) and duration >= 0
    }


def _test_totals(result: dict[str, Any]) -> dict[str, int]:
    raw = result.get("test_totals")
    if not isinstance(raw, dict):
        raw = {}
    failures = _int_value(raw.get("failures"))
    errors = _int_value(raw.get("errors"))
    return {
        "tests": _int_value(raw.get("tests")),
        "passed": _int_value(raw.get("passed")),
        "failed": failures + errors,
        "skipped": _int_value(raw.get("skipped")),
    }


def _event_payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", None)
    if isinstance(payload, dict):
        return payload
    payload_json = getattr(event, "payload_json", None)
    if isinstance(payload_json, dict):
        return payload_json
    if isinstance(payload_json, str) and payload_json.strip():
        try:
            parsed = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}

def _stage_output_path(result: dict[str, Any], events: list[Any]) -> Path | None:
    path = _result_output_path(result)
    if path is not None:
        return path
    for event in reversed(events):
        if not _is_output_event(event):
            continue
        payload = _event_payload(event)
        for key in ("sandbox_path", "modernized_app_path", "output_app_path"):
            path = _safe_path_value(payload.get(key))
            if path is not None:
                return path
        if str(payload.get("artifact_kind") or "") == "sandbox":
            path = _safe_path_value(payload.get("relative_path") or payload.get("path"))
            if path is not None:
                return path
        refs = payload.get("artifact_refs")
        if isinstance(refs, dict):
            for key in ("sandbox", "sandbox_path", "modernized_app", "modernized_app_path"):
                path = _safe_path_value(refs.get(key))
                if path is not None:
                    return path
    return None

def _is_output_event(event: Any) -> bool:
    event_type = str(getattr(event, "type", "") or "")
    if event_type in {"stage_completed", "sandbox_transform_completed"}:
        return True
    if event_type != "artifact_written":
        return False
    payload = _event_payload(event)
    return str(payload.get("artifact_kind") or "") == "sandbox"

def _result_output_path(result: dict[str, Any]) -> Path | None:
    for key in ("sandbox_path", "modernized_app_path", "output_app_path"):
        path = _safe_path_value(result.get(key))
        if path is not None:
            return path
    artifact_refs = result.get("artifact_refs")
    if isinstance(artifact_refs, dict):
        for key in ("sandbox", "modernized_app"):
            path = _safe_path_value(artifact_refs.get(key))
            if path is not None:
                return path
    return None


def _safe_path_value(value: Any) -> Path | None:
    if not isinstance(value, (str, Path)):
        return None
    text = str(value).strip()
    return Path(text) if text else None


def _looks_like_success(result: dict[str, Any]) -> bool:
    status = str(result.get("final_status") or result.get("status") or "")
    return status in {"PASS", "COMPLETED", "TRANSFORM_APPLIED_IN_SANDBOX", "completed"}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fact_text(result: dict[str, Any], key: str) -> str:
    value = str(result.get(key) or "").strip()
    return value or "not captured"


def _safe_text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        str(redact_model_summary(str(item)))
        for item in value
        if str(item).strip()
    ][:50]


def _int_value(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0


def _format_duration(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "not captured"
    seconds = max(float(value), 0.0)
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    minutes, remainder = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {remainder}s"


def _join_values(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        return "none"
    return ", ".join(str(item) for item in value)


def _display_name(value: Any) -> str:
    return str(value or "not captured").replace("_", " ").strip().title()


def _table_text(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "/").replace("\n", " ").strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
