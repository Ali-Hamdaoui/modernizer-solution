from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

AUTO_APPLY_DETERMINISTIC = "AUTO_APPLY_DETERMINISTIC"
HUMAN_REVIEW_ONLY = "HUMAN_REVIEW_ONLY"
LLM_PROPOSAL_ALLOWED = "LLM_PROPOSAL_ALLOWED"
LLM_DISABLED_REPORT_ONLY = "LLM_DISABLED_REPORT_ONLY"

_DEFAULT_FORBIDDEN_ACTIONS = [
    "external_llm_call",
    "automatic_source_patch",
    "test_modification",
    "approval_bypass",
]


@dataclass(frozen=True)
class LlmPolicy:
    enabled: bool = False
    provider: str = "github_copilot_enterprise"
    max_calls_per_run: int = 0
    max_files_per_call: int = 0
    max_diff_lines_per_patch: int = 0
    require_human_approval: bool = True
    allowed_categories: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=lambda: list(_DEFAULT_FORBIDDEN_ACTIONS))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RemediationDecision:
    decision: str
    reason: str
    affected_category: str = ""
    deterministic_available: bool = False


def load_llm_policy(ai_hub_path: str | Path | None, profile_id: str | None) -> LlmPolicy:
    policy = LlmPolicy()
    if not ai_hub_path or not profile_id:
        return policy
    profile_path = Path(ai_hub_path).expanduser().resolve() / "profiles" / f"{profile_id}.yaml"
    if not profile_path.is_file():
        return policy
    try:
        payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return policy
    if not isinstance(payload, dict):
        return policy
    raw = payload.get("llm_policy")
    if not isinstance(raw, dict):
        return policy
    return LlmPolicy(
        enabled=bool(raw.get("enabled", policy.enabled)),
        provider=str(raw.get("provider") or policy.provider),
        max_calls_per_run=int(raw.get("max_calls_per_run", policy.max_calls_per_run) or 0),
        max_files_per_call=int(raw.get("max_files_per_call", policy.max_files_per_call) or 0),
        max_diff_lines_per_patch=int(raw.get("max_diff_lines_per_patch", policy.max_diff_lines_per_patch) or 0),
        require_human_approval=bool(raw.get("require_human_approval", policy.require_human_approval)),
        allowed_categories=[str(item) for item in raw.get("allowed_categories", policy.allowed_categories) or []],
        forbidden_actions=[str(item) for item in raw.get("forbidden_actions", policy.forbidden_actions) or []],
    )


def decide_remediation(
    *,
    state: dict[str, Any],
    llm_policy: LlmPolicy,
    build_error_contract: dict[str, Any] | None = None,
    failure_classification: dict[str, Any] | None = None,
) -> RemediationDecision:
    from migration_factory.remediation.agent import decide_remediation_v1

    decision = decide_remediation_v1(
        llm_policy=llm_policy,
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
    )
    affected_category = _primary_category(failure_classification, build_error_contract)
    deterministic_available = decision == "AUTO_APPLY_DETERMINISTIC_CANDIDATE"
    reason_map = {
        "AUTO_APPLY_DETERMINISTIC_CANDIDATE": "Deterministic remediation path exists for this failure shape.",
        LLM_DISABLED_REPORT_ONLY: "LLM remediation is disabled by policy; emit report-only remediation plan for human review.",
        HUMAN_REVIEW_ONLY: "Human review is required because automatic remediation is not selected.",
        LLM_PROPOSAL_ALLOWED: "LLM proposals are policy-allowed only after human approval; no automatic patching is permitted.",
        "NO_REMEDIATION_AVAILABLE": "No remediation candidate is currently available from deterministic artifacts.",
    }
    normalized = AUTO_APPLY_DETERMINISTIC if deterministic_available else decision
    if decision == "NO_REMEDIATION_AVAILABLE":
        normalized = HUMAN_REVIEW_ONLY
    return RemediationDecision(
        decision=normalized,
        reason=reason_map.get(decision, "Human review is required."),
        affected_category=affected_category,
        deterministic_available=deterministic_available,
    )


def build_remediation_plan(
    *,
    state: dict[str, Any],
    output_dir: str | Path,
    llm_policy: LlmPolicy,
    build_error_contract: dict[str, Any] | None = None,
    failure_classification: dict[str, Any] | None = None,
) -> Path:
    from migration_factory.remediation.agent import generate_remediation_plan

    return generate_remediation_plan(
        state=state,
        output_dir=output_dir,
        llm_policy=llm_policy,
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
    ).path


def _primary_category(
    failure_classification: dict[str, Any] | None,
    build_error_contract: dict[str, Any] | None,
) -> str:
    counts = _category_counts(failure_classification, build_error_contract)
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda row: (-int(row[1]), str(row[0])))[0][0]


def _category_counts(
    failure_classification: dict[str, Any] | None,
    build_error_contract: dict[str, Any] | None,
) -> dict[str, int]:
    for payload in (failure_classification, build_error_contract):
        if not isinstance(payload, dict):
            continue
        raw = payload.get("category_counts") if "category_counts" in payload else payload.get("failure_categories")
        if isinstance(raw, dict):
            return {str(key): int(value) for key, value in raw.items()}
    return {}


def _deterministic_remediation_available(
    build_error_contract: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
) -> bool:
    if _category_counts(failure_classification, build_error_contract):
        return False
    result_kind = str((build_error_contract or {}).get("result_kind") or "")
    return result_kind in {"dependency_error", "compilation_error", "missing_config"}
