"""Read-only migration memory seed retrieval for governed stage failures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.redaction import redact_absolute_paths, redact_model_summary
from migration_factory.control_tower.domain.checksums import sha256_canonical_json


ALLOWED_TRUST_LEVELS = frozenset({
    "golden_reference_verified",
    "governed_success",
    "governed_partial_success",
    "reviewed_human_only",
    "untrusted_import",
    "failed_attempt",
    "anti_pattern",
})
ALLOWED_AUTHORITY_LEVELS = frozenset({
    "advisory_only",
    "classifier_hint_only",
    "human_review_gate_only",
    "future_proposer_context_only",
    "deterministic_rule_candidate_only",
})
TRUST_RANK = {
    "golden_reference_verified": 6,
    "governed_success": 5,
    "governed_partial_success": 4,
    "reviewed_human_only": 3,
    "untrusted_import": 2,
    "failed_attempt": 1,
    "anti_pattern": 0,
}
DEFAULT_SEED_PATH = Path(".migration/knowledge-audit/memory_seed_cases.json")


@dataclass(frozen=True)
class MigrationMemoryCase:
    memory_case_id: str
    source_branch: str
    source_commit: str
    source_path: str
    title: str
    summary: str
    trust_level: str
    authority_level: str
    stage_applicability: tuple[str, ...]
    source_boot_versions: tuple[str, ...]
    target_boot_versions: tuple[str, ...]
    source_java_versions: tuple[str, ...]
    target_java_versions: tuple[str, ...]
    failure_types: tuple[str, ...]
    repair_families: tuple[str, ...]
    governance_gate_types: tuple[str, ...]
    matched_signals: tuple[str, ...]
    required_evidence: tuple[str, ...]
    suggested_next_actions: tuple[str, ...]
    deterministic_rule_candidate: bool
    human_review_required: bool
    llm_candidate: bool
    known_risks: tuple[str, ...]
    anti_patterns: tuple[str, ...]
    promotion_status: str
    retrieved_for_statuses: tuple[str, ...]
    redaction_status: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MigrationMemoryCase":
        trust_level = _safe_enum(raw.get("trust_level"), ALLOWED_TRUST_LEVELS, "untrusted_import")
        authority_level = _safe_enum(raw.get("authority_level"), ALLOWED_AUTHORITY_LEVELS, "advisory_only")
        return cls(
            memory_case_id=_clean(raw.get("memory_case_id")),
            source_branch=_clean(raw.get("source_branch")),
            source_commit=_clean(raw.get("source_commit")),
            source_path=_clean(raw.get("source_path")),
            title=_clean(raw.get("title")),
            summary=_clean(raw.get("summary")),
            trust_level=trust_level,
            authority_level=authority_level,
            stage_applicability=_clean_tuple(raw.get("stage_applicability")),
            source_boot_versions=_clean_tuple(raw.get("source_boot_versions")),
            target_boot_versions=_clean_tuple(raw.get("target_boot_versions")),
            source_java_versions=_clean_tuple(raw.get("source_java_versions")),
            target_java_versions=_clean_tuple(raw.get("target_java_versions")),
            failure_types=_clean_tuple(raw.get("failure_types")),
            repair_families=_clean_tuple(raw.get("repair_families")),
            governance_gate_types=_clean_tuple(raw.get("governance_gate_types")),
            matched_signals=_clean_tuple(raw.get("matched_signals")),
            required_evidence=_clean_tuple(raw.get("required_evidence")),
            suggested_next_actions=_clean_tuple(raw.get("suggested_next_actions")),
            deterministic_rule_candidate=bool(raw.get("deterministic_rule_candidate")),
            human_review_required=bool(raw.get("human_review_required")),
            llm_candidate=bool(raw.get("llm_candidate")),
            known_risks=_clean_tuple(raw.get("known_risks")),
            anti_patterns=_clean_tuple(raw.get("anti_patterns")),
            promotion_status=_clean(raw.get("promotion_status")),
            retrieved_for_statuses=_clean_tuple(raw.get("retrieved_for_statuses")),
            redaction_status=_clean(raw.get("redaction_status")) or "path_redacted",
        )

    def to_summary(self, *, weak_stage_match: bool = False) -> dict[str, Any]:
        authority = self.authority_level if self.authority_level in ALLOWED_AUTHORITY_LEVELS else "advisory_only"
        if weak_stage_match:
            authority = "advisory_only"
        return {
            "memory_case_id": self.memory_case_id,
            "title": self.title,
            "summary": self.summary,
            "trust_level": self.trust_level,
            "authority_level": authority,
            "matched_signals": list(self.matched_signals[:8]),
            "required_evidence": list(self.required_evidence[:8]),
            "suggested_next_actions": list(self.suggested_next_actions[:6]),
            "stage_applicability": list(self.stage_applicability),
            "promotion_status": self.promotion_status,
            "redaction_status": self.redaction_status,
            "weak_stage_match": weak_stage_match,
        }


def load_memory_seed_cases(seed_path: Path | str = DEFAULT_SEED_PATH) -> tuple[MigrationMemoryCase, ...]:
    path = Path(seed_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw_cases = data.get("cases", [])
    if not isinstance(raw_cases, list):
        return ()
    cases = [MigrationMemoryCase.from_dict(item) for item in raw_cases if isinstance(item, dict)]
    return tuple(case for case in cases if case.memory_case_id and case.title)


def retrieve_migration_memory(
    context: dict[str, Any],
    *,
    seed_path: Path | str = DEFAULT_SEED_PATH,
    cases: tuple[MigrationMemoryCase, ...] | None = None,
) -> dict[str, Any]:
    seed_cases = cases if cases is not None else load_memory_seed_cases(seed_path)
    query = _query_from_context(context)
    if not seed_cases:
        return _empty_result("unavailable", query, "Migration memory unavailable.")

    scored: list[tuple[int, bool, MigrationMemoryCase]] = []
    for case in seed_cases:
        score, weak_stage_match = _score_case(case, query)
        if score > 0:
            scored.append((score, weak_stage_match, case))

    if not scored:
        return _empty_result("no_matches", query, "No relevant memory cases found.")

    scored.sort(key=lambda item: (item[0], TRUST_RANK.get(item[2].trust_level, 0), item[2].memory_case_id), reverse=True)
    selected = scored[:5]
    summaries = [case.to_summary(weak_stage_match=weak) for _, weak, case in selected]
    top = summaries[0]
    missing = _missing_evidence_suggestions(top.get("required_evidence", []), query["usable_artifacts"], query["missing_required_evidence"])
    advisory = "Memory match is advisory only. It can inform future proposer/reviewer prompts, but it cannot approve, apply, or override backend gates."
    return {
        "retrieval_status": "available",
        "query_signature": _query_signature(query),
        "memory_matches": summaries,
        "top_match": top,
        "trust_summary": _trust_summary(summaries),
        "advisory_summary": advisory,
        "missing_evidence_suggestions": missing,
        "retrieved_case_ids": [str(item["memory_case_id"]) for item in summaries],
        "authority_level": "advisory_only",
        "repair_enabled": False,
        "memory_can_apply": False,
        "memory_can_approve": False,
        "memory_can_start_downstream": False,
        "recommended_use": "human review gate / future RAG seed",
    }


def _query_from_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_index": int(context.get("stage_index") or 0),
        "source_boot_version": _clean(context.get("source_boot_version")),
        "target_boot_version": _clean(context.get("target_boot_version")),
        "source_java_version": _clean(context.get("source_java_version")),
        "target_java_version": _clean(context.get("target_java_version")),
        "classification_status": _clean(context.get("classification_status")),
        "failure_type": _clean(context.get("failure_type")),
        "repair_family_candidate": _clean(context.get("repair_family_candidate")),
        "governance_gate_type": _clean(context.get("governance_gate_type")),
        "matched_signals": _clean_tuple(context.get("matched_signals")),
        "usable_artifacts": _clean_tuple(context.get("usable_artifacts")),
        "missing_required_evidence": _clean_tuple(context.get("missing_required_evidence")),
        "markers": _markers(context),
    }


def _score_case(case: MigrationMemoryCase, query: dict[str, Any]) -> tuple[int, bool]:
    score = 0
    failure_type = query["failure_type"]
    repair_family = query["repair_family_candidate"]
    governance_gate = query["governance_gate_type"]
    signals = set(_norm_tuple(query["matched_signals"]))
    case_signals = set(_norm_tuple(case.matched_signals))
    markers = set(_norm_tuple(query["markers"]))
    stage_key = f"stage_{query['stage_index']}" if query["stage_index"] else ""

    if failure_type and failure_type in case.failure_types:
        score += 100
    if repair_family and repair_family in case.repair_families:
        score += 80
    overlap = signals.intersection(case_signals)
    score += len(overlap) * 25
    if governance_gate and governance_gate in case.governance_gate_types:
        score += 20
    marker_overlap = markers.intersection(case_signals)
    score += len(marker_overlap) * 8
    if score == 0:
        return 0, False

    stage_match = bool(stage_key and stage_key in case.stage_applicability)
    target_match = bool(query["target_boot_version"] and query["target_boot_version"] in case.target_boot_versions)
    java_match = bool(query["target_java_version"] and query["target_java_version"] in case.target_java_versions)
    if stage_match:
        score += 15
    if target_match:
        score += 10
    if java_match:
        score += 5

    weak_stage_match = bool(score > 0 and not (stage_match or target_match))
    if weak_stage_match:
        score = max(1, score - 20)
    return score, weak_stage_match


def _markers(context: dict[str, Any]) -> tuple[str, ...]:
    texts: list[str] = []
    for key in ("failure_summary", "confidence_reason", "stage_relevance"):
        value = context.get(key)
        if value:
            texts.append(str(value))
    for item in context.get("usable_artifacts", []) or []:
        if item:
            texts.append(str(item))
    for item in context.get("evidence_artifacts", []) or []:
        if isinstance(item, dict):
            texts.extend(str(item.get(k) or "") for k in ("kind", "ref", "excerpt"))
        elif item:
            texts.append(str(item))
    joined = " ".join(texts)
    markers = []
    for marker in ("powermock", "powermockito", "@preparefortest", "mockstatic", "whennew", "springfox", "mockbean", "mockitobean", "initmocks"):
        if marker in joined.lower():
            markers.append(marker)
    return tuple(markers)


def _empty_result(status: str, query: dict[str, Any], advisory_summary: str) -> dict[str, Any]:
    return {
        "retrieval_status": status,
        "query_signature": _query_signature(query),
        "memory_matches": [],
        "top_match": None,
        "trust_summary": "",
        "advisory_summary": advisory_summary,
        "missing_evidence_suggestions": [],
        "retrieved_case_ids": [],
        "authority_level": "advisory_only",
        "repair_enabled": False,
        "memory_can_apply": False,
        "memory_can_approve": False,
        "memory_can_start_downstream": False,
        "recommended_use": "human review gate / future RAG seed",
    }


def _missing_evidence_suggestions(required: Any, usable: tuple[str, ...], missing: tuple[str, ...]) -> list[str]:
    usable_set = set(usable)
    missing_set = set(missing)
    result = [item for item in _clean_tuple(required) if item not in usable_set]
    result.extend(item for item in missing if item not in result)
    return [item for item in result if item in missing_set or item not in usable_set][:8]


def _trust_summary(matches: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for match in matches:
        key = str(match.get("trust_level") or "untrusted_import")
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(f"{key}:{count}" for key, count in sorted(counts.items()))


def _query_signature(query: dict[str, Any]) -> str:
    payload = {
        "stage_index": query["stage_index"],
        "target_boot_version": query["target_boot_version"],
        "target_java_version": query["target_java_version"],
        "classification_status": query["classification_status"],
        "failure_type": query["failure_type"],
        "repair_family_candidate": query["repair_family_candidate"],
        "governance_gate_type": query["governance_gate_type"],
        "matched_signals": sorted(query["matched_signals"]),
    }
    return f"sha256:{sha256_canonical_json(payload)}"


def _safe_enum(value: Any, allowed: frozenset[str], default: str) -> str:
    text = _clean(value)
    return text if text in allowed else default


def _clean(value: Any) -> str:
    return redact_absolute_paths(redact_model_summary(str(value or ""))).strip()[:500]


def _clean_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    result: list[str] = []
    for item in value:
        text = _clean(item)
        if text:
            result.append(text)
    return tuple(result[:24])


def _norm_tuple(value: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(item.lower() for item in value)
