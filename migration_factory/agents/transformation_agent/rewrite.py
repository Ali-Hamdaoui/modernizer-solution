from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

DEFAULT_OPENREWRITE_MAVEN_PLUGIN_VERSION = "6.39.0"
OPENREWRITE_MAVEN_PLUGIN = ("org.openrewrite.maven", "rewrite-maven-plugin")
DEFAULT_PREVIEW_GOALS = ("dryRun", "dryRunNoFork", "discover")
DEFAULT_SANDBOX_APPLY_GOALS = ("run", "runNoFork", "rewrite:run", "rewrite:runNoFork")
DEFAULT_FORBIDDEN_APPLY_GOALS = ("run", "runNoFork", "rewrite:run", "rewrite:runNoFork")


class RewritePluginError(Exception):
    pass


@dataclass(frozen=True)
class RewritePluginInjection:
    pom_path: Path
    coordinates: tuple[str, str]


@dataclass(frozen=True)
class OpenRewriteExecutionContext:
    unit_id: str
    run_dir: Path | None = None
    workspace_path: Path | None = None
    approved_plan_lock_path: Path | None = None
    approval_decision: str | None = None
    approval_approved: bool = False
    sandbox_execution: bool = False


@dataclass(frozen=True)
class OpenRewritePolicy:
    preview_allowed: bool = True
    apply_allowed: bool = False
    sandbox_apply_allowed: bool = False
    sandbox_apply_requires_approval: bool = True
    sandbox_apply_requires_plan_lock: bool = True
    sandbox_apply_requires_workspace_under_run: bool = True
    allowed_preview_goals: tuple[str, ...] = DEFAULT_PREVIEW_GOALS
    allowed_sandbox_apply_goals: tuple[str, ...] = ()
    forbidden_apply_goals: tuple[str, ...] = DEFAULT_FORBIDDEN_APPLY_GOALS


def default_openrewrite_policy() -> OpenRewritePolicy:
    return OpenRewritePolicy()


def openrewrite_policy_from_mapping(payload: object) -> OpenRewritePolicy:
    if not isinstance(payload, dict):
        return default_openrewrite_policy()
    preview_allowed = payload.get("preview_allowed")
    apply_allowed = payload.get("apply_allowed")
    sandbox_apply_allowed = payload.get("sandbox_apply_allowed")
    sandbox_apply_requires_approval = payload.get("sandbox_apply_requires_approval")
    sandbox_apply_requires_plan_lock = payload.get("sandbox_apply_requires_plan_lock")
    sandbox_apply_requires_workspace_under_run = payload.get("sandbox_apply_requires_workspace_under_run")
    allowed_preview_goals = _string_tuple(payload.get("allowed_preview_goals")) or DEFAULT_PREVIEW_GOALS
    allowed_sandbox_apply_goals = _string_tuple(payload.get("allowed_sandbox_apply_goals"))
    forbidden_apply_goals = _string_tuple(payload.get("forbidden_apply_goals")) or DEFAULT_FORBIDDEN_APPLY_GOALS
    return OpenRewritePolicy(
        preview_allowed=True if preview_allowed is None else bool(preview_allowed),
        apply_allowed=False if apply_allowed is None else bool(apply_allowed),
        sandbox_apply_allowed=False if sandbox_apply_allowed is None else bool(sandbox_apply_allowed),
        sandbox_apply_requires_approval=(
            True if sandbox_apply_requires_approval is None else bool(sandbox_apply_requires_approval)
        ),
        sandbox_apply_requires_plan_lock=(
            True if sandbox_apply_requires_plan_lock is None else bool(sandbox_apply_requires_plan_lock)
        ),
        sandbox_apply_requires_workspace_under_run=(
            True
            if sandbox_apply_requires_workspace_under_run is None
            else bool(sandbox_apply_requires_workspace_under_run)
        ),
        allowed_preview_goals=allowed_preview_goals,
        allowed_sandbox_apply_goals=allowed_sandbox_apply_goals,
        forbidden_apply_goals=forbidden_apply_goals,
    )


def inject_rewrite_plugin(
    project_path: Path,
    plugin_txt_path: str | Path,
    *,
    module: str | None = None,
    backup: bool = True,
) -> RewritePluginInjection:
    pom_path = _resolve_pom(project_path, module)
    plugin_element = _parse_plugin_xml(Path(plugin_txt_path).expanduser().resolve())
    coordinates = _plugin_coordinates(plugin_element)

    tree = ET.parse(pom_path)
    root = tree.getroot()
    namespace = _namespace_uri(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    build = _find_or_create_child(root, "build", namespace)
    plugins = _find_or_create_child(build, "plugins", namespace)
    _upsert_plugin(plugins, plugin_element, coordinates, namespace)

    if backup:
        shutil.copyfile(pom_path, pom_path.with_suffix(".xml.bak"))
    tree.write(pom_path, encoding="utf-8", xml_declaration=True)
    return RewritePluginInjection(pom_path=pom_path, coordinates=coordinates)


def build_rewrite_run_command(
    active_recipes: list[str],
    *,
    recipe_artifacts: list[str] | None = None,
    plugin_version: str = DEFAULT_OPENREWRITE_MAVEN_PLUGIN_VERSION,
    apply_goal: str | None = None,
    maven_args: list[str] | None = None,
    policy: OpenRewritePolicy | None = None,
    context: OpenRewriteExecutionContext | None = None,
) -> str:
    goal_name = validate_openrewrite_goal(apply_goal, policy=policy, context=context)
    goal = f"{OPENREWRITE_MAVEN_PLUGIN[0]}:{OPENREWRITE_MAVEN_PLUGIN[1]}:{_concrete_plugin_version(plugin_version)}:{goal_name}"
    args = [goal]
    if active_recipes:
        args.append(f"-Drewrite.activeRecipes={','.join(active_recipes)}")
    if recipe_artifacts:
        args.append(f"-Drewrite.recipeArtifactCoordinates={','.join(recipe_artifacts)}")
    if maven_args:
        args.extend(str(item) for item in maven_args)
    return "mvn " + " ".join(args)


def rewrite_plugin_version_from_xml(plugin_txt_path: str | Path) -> str:
    plugin_element = _parse_plugin_xml(Path(plugin_txt_path).expanduser().resolve())
    group_id, artifact_id = _plugin_coordinates(plugin_element)
    if (group_id, artifact_id) != OPENREWRITE_MAVEN_PLUGIN:
        return DEFAULT_OPENREWRITE_MAVEN_PLUGIN_VERSION
    return _concrete_plugin_version(_child_text(plugin_element, "version"))


def validate_openrewrite_goal(
    requested_goal: str | None,
    *,
    policy: OpenRewritePolicy | None = None,
    context: OpenRewriteExecutionContext | None = None,
) -> str:
    effective_policy = policy or default_openrewrite_policy()
    normalized_goal = normalize_openrewrite_goal(requested_goal)
    allowed_preview = {
        normalize_openrewrite_goal(goal)
        for goal in effective_policy.allowed_preview_goals
    }
    allowed_sandbox_apply = {
        normalize_openrewrite_goal(goal)
        for goal in effective_policy.allowed_sandbox_apply_goals
    }
    forbidden_apply = {
        normalize_openrewrite_goal(goal)
        for goal in effective_policy.forbidden_apply_goals
    }

    if normalized_goal in allowed_preview:
        if not effective_policy.preview_allowed:
            raise RewritePluginError(
                f"OPENREWRITE_GOAL_FORBIDDEN preview goal '{requested_goal or normalized_goal}' "
                f"blocked by policy"
            )
        return normalized_goal

    if normalized_goal in forbidden_apply or normalized_goal in allowed_sandbox_apply:
        if effective_policy.apply_allowed:
            return normalized_goal
        sandbox_reason = _validate_sandbox_apply_context(
            normalized_goal,
            policy=effective_policy,
            context=context,
        )
        if sandbox_reason is None:
            return normalized_goal
        raise RewritePluginError(
            f"OPENREWRITE_GOAL_FORBIDDEN apply goal '{requested_goal or normalized_goal}' "
            f"blocked by policy: {sandbox_reason}"
        )

    raise RewritePluginError(
        f"OPENREWRITE_GOAL_FORBIDDEN goal '{requested_goal or normalized_goal}' not allowed by policy"
    )


def normalize_openrewrite_goal(goal: str | None) -> str:
    value = str(goal or "").strip()
    if not value:
        return "dryRun"
    suffix = value.split(":")[-1]
    if suffix in {"dryRun", "dryRunNoFork", "discover", "run", "runNoFork"}:
        return suffix
    return value


def _validate_sandbox_apply_context(
    normalized_goal: str,
    *,
    policy: OpenRewritePolicy,
    context: OpenRewriteExecutionContext | None,
) -> str | None:
    if not policy.sandbox_apply_allowed:
        return "sandbox apply is not enabled"

    allowed_sandbox_apply = {
        normalize_openrewrite_goal(goal)
        for goal in policy.allowed_sandbox_apply_goals
    }
    if normalized_goal not in allowed_sandbox_apply:
        return f"goal '{normalized_goal}' is not in allowed_sandbox_apply_goals"

    if context is None:
        return "sandbox execution context is missing"

    if not context.sandbox_execution:
        return f"unit={context.unit_id} is not running in sandbox execution mode"

    if policy.sandbox_apply_requires_approval and not context.approval_approved:
        decision = str(context.approval_decision or "").strip() or "missing"
        return f"unit={context.unit_id} approval is not approved (decision={decision})"

    if policy.sandbox_apply_requires_plan_lock:
        lock_path = context.approved_plan_lock_path
        if lock_path is None:
            return f"unit={context.unit_id} approved plan lock path is missing"
        if not lock_path.is_file():
            return f"unit={context.unit_id} approved plan lock not found at {lock_path}"

    if policy.sandbox_apply_requires_workspace_under_run:
        run_dir = context.run_dir
        workspace_path = context.workspace_path
        if run_dir is None or workspace_path is None:
            return f"unit={context.unit_id} run_dir/workspace_path is missing"
        sandbox_root = run_dir.resolve() / "workspaces" / "sandbox"
        try:
            workspace_path.resolve().relative_to(sandbox_root.resolve())
        except ValueError:
            return (
                f"unit={context.unit_id} workspace {workspace_path} is outside sandbox root {sandbox_root}"
            )

    return None


def _resolve_pom(project_path: Path, module: str | None) -> Path:
    pom_path = project_path / module / "pom.xml" if module else project_path / "pom.xml"
    if not pom_path.is_file():
        raise RewritePluginError(f"Could not find pom.xml at: {pom_path}")
    return pom_path


def _parse_plugin_xml(plugin_txt_path: Path) -> ET.Element:
    if not plugin_txt_path.is_file():
        raise RewritePluginError(f"OpenRewrite plugin file does not exist: {plugin_txt_path}")
    content = plugin_txt_path.read_text(encoding="utf-8").strip()
    if not content:
        raise RewritePluginError("OpenRewrite plugin file is empty")
    try:
        element = ET.fromstring(content)
    except ET.ParseError as exc:
        raise RewritePluginError(f"OpenRewrite plugin file is not valid XML: {exc}") from exc
    if _local_name(element.tag) != "plugin":
        raise RewritePluginError("OpenRewrite plugin file must contain one <plugin> element")
    return element


def _plugin_coordinates(plugin_element: ET.Element) -> tuple[str, str]:
    group_id = (_child_text(plugin_element, "groupId") or "org.openrewrite.maven").strip()
    artifact_id = (_child_text(plugin_element, "artifactId") or "").strip()
    if not artifact_id:
        raise RewritePluginError("OpenRewrite plugin XML must include <artifactId>")
    return group_id, artifact_id


def _concrete_plugin_version(version: str | None) -> str:
    value = str(version or "").strip()
    if not value or value.upper() == "RELEASE":
        return DEFAULT_OPENREWRITE_MAVEN_PLUGIN_VERSION
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    return (text,)


def _upsert_plugin(
    plugins_node: ET.Element,
    plugin_element: ET.Element,
    coordinates: tuple[str, str],
    namespace: str | None,
) -> None:
    expected_group, expected_artifact = coordinates
    for existing in list(plugins_node):
        if _local_name(existing.tag) != "plugin":
            continue
        existing_group = (_child_text(existing, "groupId") or "org.apache.maven.plugins").strip()
        existing_artifact = (_child_text(existing, "artifactId") or "").strip()
        if existing_group == expected_group and existing_artifact == expected_artifact:
            plugins_node.remove(existing)
            break
    plugins_node.append(_with_namespace(plugin_element, namespace))


def _with_namespace(element: ET.Element, namespace: str | None) -> ET.Element:
    copied = ET.fromstring(ET.tostring(element, encoding="unicode"))
    if not namespace:
        return copied
    for node in copied.iter():
        node.tag = f"{{{namespace}}}{_local_name(node.tag)}"
    return copied


def _find_or_create_child(parent: ET.Element, name: str, namespace: str | None) -> ET.Element:
    child = _find_child(parent, name)
    if child is not None:
        return child
    tag = f"{{{namespace}}}{name}" if namespace else name
    child = ET.Element(tag)
    parent.append(child)
    return child


def _find_child(parent: ET.Element, local_name: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == local_name:
            return child
    return None


def _child_text(parent: ET.Element, local_name: str) -> str | None:
    child = _find_child(parent, local_name)
    if child is None or child.text is None:
        return None
    return child.text


def _namespace_uri(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag
