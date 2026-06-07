from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


DEFAULT_CONSUMER_COMMAND = "mvn clean test"


def plan_migration_wave(
    projects: list[str | Path | dict[str, Any]],
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    project_records = [_load_project_record(item) for item in projects]
    coordinate_index = {
        (record["coordinates"]["groupId"], record["coordinates"]["artifactId"]): record["project_id"]
        for record in project_records
        if record["coordinates"]["groupId"] and record["coordinates"]["artifactId"]
    }

    edges: list[dict[str, Any]] = []
    consumers_by_producer: dict[str, list[str]] = defaultdict(list)
    warnings: list[str] = []
    missing_or_ambiguous_coordinates: list[dict[str, Any]] = []
    for record in project_records:
        if not record["coordinates"]["groupId"] or not record["coordinates"]["artifactId"]:
            missing_or_ambiguous_coordinates.append(
                {
                    "project_id": record["project_id"],
                    "project_path": record["project_path"],
                    "reason": "missing_coordinates",
                }
            )
        for dependency in record["dependencies"]:
            producer_id = coordinate_index.get((dependency["groupId"], dependency["artifactId"]))
            if not producer_id or producer_id == record["project_id"]:
                continue
            edge = {
                "consumer_project_id": record["project_id"],
                "producer_project_id": producer_id,
                "scope": dependency["scope"],
                "version": dependency["version"],
            }
            edges.append(edge)
            if record["project_id"] not in consumers_by_producer[producer_id]:
                consumers_by_producer[producer_id].append(record["project_id"])

    waves, cycle_nodes = _compute_waves([record["project_id"] for record in project_records], edges)
    cycles = _detect_cycles([record["project_id"] for record in project_records], edges, cycle_nodes)
    if cycles:
        warnings.append("Internal dependency cycles detected; human review required before planning migration waves.")
    if missing_or_ambiguous_coordinates:
        warnings.append("Some project coordinates could not be detected; internal dependency graph may be incomplete.")

    consumer_validation_plan = []
    for record in project_records:
        project_id = record["project_id"]
        consumer_validation_plan.append(
            {
                "migrated_project": project_id,
                "consumers": sorted(consumers_by_producer.get(project_id, [])),
                "suggested_command": DEFAULT_CONSUMER_COMMAND,
            }
        )

    payload = {
        "projects": [
            {
                "project_id": record["project_id"],
                "project_path": record["project_path"],
                "coordinates": record["coordinates"],
                "packaging": record["coordinates"]["packaging"],
            }
            for record in project_records
        ],
        "detected_coordinates": {
            record["project_id"]: record["coordinates"]
            for record in project_records
        },
        "internal_dependency_edges": edges,
        "migration_waves": waves,
        "consumer_validation_plan": consumer_validation_plan,
        "cycles": cycles,
        "missing_or_ambiguous_coordinates": missing_or_ambiguous_coordinates,
        "warnings": warnings,
        "human_review_required": bool(cycles),
        "recommended_next_actions": _recommended_next_actions(cycles, missing_or_ambiguous_coordinates),
    }

    report_path = output_root / "migration_wave_plan.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path = output_root / "migration_wave_summary.md"
    summary_path.write_text(_build_summary(payload), encoding="utf-8")
    return {
        "report_path": str(report_path),
        "summary_path": str(summary_path),
        "payload": payload,
    }


def _load_project_record(item: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        project_path = Path(str(item.get("path") or item.get("project_path") or "")).expanduser().resolve()
        project_id = str(item.get("project_id") or project_path.name or project_path.as_posix())
        overrides = dict(item.get("coordinates") or item.get("coordinate_overrides") or {})
    else:
        project_path = Path(str(item)).expanduser().resolve()
        project_id = project_path.name
        overrides = {}
    pom_path = project_path / "pom.xml"
    pom_payload = _parse_pom(pom_path)
    coordinates = {
        "groupId": str(overrides.get("groupId") or pom_payload["coordinates"]["groupId"] or ""),
        "artifactId": str(overrides.get("artifactId") or pom_payload["coordinates"]["artifactId"] or ""),
        "version": str(overrides.get("version") or pom_payload["coordinates"]["version"] or ""),
        "packaging": str(overrides.get("packaging") or pom_payload["coordinates"]["packaging"] or ""),
    }
    return {
        "project_id": project_id,
        "project_path": str(project_path),
        "coordinates": coordinates,
        "dependencies": pom_payload["dependencies"],
    }


def _parse_pom(pom_path: Path) -> dict[str, Any]:
    if not pom_path.is_file():
        return {
            "coordinates": {"groupId": "", "artifactId": "", "version": "", "packaging": ""},
            "dependencies": [],
        }
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return {
            "coordinates": {"groupId": "", "artifactId": "", "version": "", "packaging": ""},
            "dependencies": [],
        }
    namespace = _namespace(root.tag)
    parent_info = _parse_parent_coordinates(root, namespace, pom_path.parent)
    properties = _project_properties(root, namespace, parent_info)
    group_id = _resolve_property(_child_text(root, namespace, "groupId"), properties) or parent_info["groupId"]
    artifact_id = _resolve_property(_child_text(root, namespace, "artifactId"), properties)
    version = _resolve_property(_child_text(root, namespace, "version"), properties) or parent_info["version"]
    packaging = _resolve_property(_child_text(root, namespace, "packaging"), properties) or "jar"
    coordinates = {
        "groupId": group_id,
        "artifactId": artifact_id,
        "version": version,
        "packaging": packaging,
    }
    dependencies = []
    for dependency in root.findall(f".//{_tag(namespace, 'dependencies')}/{_tag(namespace, 'dependency')}"):
        dep_group = _resolve_property(_child_text(dependency, namespace, "groupId"), properties)
        dep_artifact = _resolve_property(_child_text(dependency, namespace, "artifactId"), properties)
        if not dep_group or not dep_artifact:
            continue
        dependencies.append(
            {
                "groupId": dep_group,
                "artifactId": dep_artifact,
                "version": _resolve_property(_child_text(dependency, namespace, "version"), properties),
                "scope": _resolve_property(_child_text(dependency, namespace, "scope"), properties) or "compile",
            }
        )
    return {
        "coordinates": coordinates,
        "dependencies": dependencies,
    }


def _parse_parent_coordinates(root: ET.Element, namespace: str, project_dir: Path) -> dict[str, str]:
    parent = root.find(_tag(namespace, "parent"))
    parent_group = _child_text(parent, namespace, "groupId")
    parent_version = _child_text(parent, namespace, "version")
    relative_path = _child_text(parent, namespace, "relativePath") or "../pom.xml"
    parent_path = (project_dir / relative_path).resolve()
    if parent_path.is_file():
        parsed = _parse_pom(parent_path)
        parent_group = parent_group or parsed["coordinates"]["groupId"]
        parent_version = parent_version or parsed["coordinates"]["version"]
    return {
        "groupId": parent_group,
        "version": parent_version,
    }


def _project_properties(root: ET.Element, namespace: str, parent_info: dict[str, str]) -> dict[str, str]:
    properties: dict[str, str] = {}
    properties_node = root.find(_tag(namespace, "properties"))
    if properties_node is not None:
        for child in list(properties_node):
            local_name = child.tag.rsplit("}", 1)[-1]
            properties[local_name] = (child.text or "").strip()
    project_group = _child_text(root, namespace, "groupId") or parent_info["groupId"]
    project_artifact = _child_text(root, namespace, "artifactId")
    project_version = _child_text(root, namespace, "version") or parent_info["version"]
    properties.update(
        {
            "project.groupId": project_group,
            "project.artifactId": project_artifact,
            "project.version": project_version,
            "groupId": project_group,
            "artifactId": project_artifact,
            "version": project_version,
        }
    )
    return properties


def _resolve_property(value: str, properties: dict[str, str]) -> str:
    text = (value or "").strip()
    if text.startswith("${") and text.endswith("}"):
        return properties.get(text[2:-1], text)
    return text


def _compute_waves(project_ids: list[str], edges: list[dict[str, Any]]) -> tuple[list[list[str]], list[str]]:
    indegree = {project_id: 0 for project_id in project_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        producer = str(edge["producer_project_id"])
        consumer = str(edge["consumer_project_id"])
        adjacency[producer].append(consumer)
        indegree[consumer] = indegree.get(consumer, 0) + 1
        indegree.setdefault(producer, 0)
    queue = deque(sorted(project_id for project_id, degree in indegree.items() if degree == 0))
    waves: list[list[str]] = []
    visited_count = 0
    while queue:
        level_size = len(queue)
        wave: list[str] = []
        for _ in range(level_size):
            node = queue.popleft()
            wave.append(node)
            visited_count += 1
            for consumer in sorted(adjacency.get(node, [])):
                indegree[consumer] -= 1
                if indegree[consumer] == 0:
                    queue.append(consumer)
        waves.append(wave)
    cycle_nodes = sorted(project_id for project_id, degree in indegree.items() if degree > 0)
    if visited_count != len(indegree) and cycle_nodes:
        acyclic = {project_id for wave in waves for project_id in wave}
        remaining = [project_id for project_id in project_ids if project_id not in acyclic]
        if remaining:
            waves.append(sorted(remaining))
    return waves, cycle_nodes


def _detect_cycles(project_ids: list[str], edges: list[dict[str, Any]], cycle_nodes: list[str]) -> list[list[str]]:
    if not cycle_nodes:
        return []
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        producer = str(edge["producer_project_id"])
        consumer = str(edge["consumer_project_id"])
        adjacency[producer].add(consumer)
    node_set = set(cycle_nodes)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in sorted(adjacency.get(node, set())):
            if neighbor not in node_set:
                continue
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while stack:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or (len(component) == 1 and component[0] in adjacency.get(component[0], set())):
                components.append(sorted(component))

    for project_id in project_ids:
        if project_id in node_set and project_id not in indices:
            strongconnect(project_id)
    return sorted(components)


def _recommended_next_actions(cycles: list[list[str]], missing_coords: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if cycles:
        actions.append("Break internal dependency cycles or define manual wave boundaries before executing migrations.")
    if missing_coords:
        actions.append("Fill missing Maven coordinates or provide coordinate overrides so internal dependency detection is complete.")
    actions.append("Feed consumer_validation_plan into consumer compatibility validation after each migrated producer/library.")
    return actions


def _build_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Migration Wave Summary",
        "",
        f"- Projects: {len(list(payload.get('projects', []) or []))}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        "",
        "## Migration Waves",
        "",
    ]
    for index, wave in enumerate(list(payload.get("migration_waves", []) or []), start=1):
        if not isinstance(wave, list):
            continue
        lines.append(f"- Wave {index}: {', '.join(str(item) for item in wave)}")
    edges = list(payload.get("internal_dependency_edges", []) or [])
    if edges:
        lines.extend(["", "## Internal Dependencies", ""])
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            lines.append(
                f"- {edge.get('consumer_project_id', '')} depends on {edge.get('producer_project_id', '')}"
            )
    cycles = list(payload.get("cycles", []) or [])
    if cycles:
        lines.extend(["", "## Cycles", ""])
        for cycle in cycles:
            if not isinstance(cycle, list):
                continue
            lines.append(f"- {' -> '.join(str(item) for item in cycle)}")
    consumer_plan = list(payload.get("consumer_validation_plan", []) or [])
    if consumer_plan:
        lines.extend(["", "## Consumer Validation Plan", ""])
        for item in consumer_plan:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('migrated_project', '')}: consumers="
                f"{', '.join(str(x) for x in list(item.get('consumers', []) or [])) or 'none'}"
            )
    warnings = list(payload.get("warnings", []) or [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).rstrip() + "\n"


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _tag(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def _child_text(element: ET.Element | None, namespace: str, local_name: str) -> str:
    if element is None:
        return ""
    child = element.find(_tag(namespace, local_name))
    return (child.text or "").strip() if child is not None and child.text else ""
