"""Generic repair-family registry for governed R9 strategy packets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepairFamilyPolicy:
    family: str
    risk_level: str
    category: str
    stage_applicability: tuple[str, ...]
    evidence_required: tuple[str, ...]
    llm_proposer_enabled: bool
    llm_reviewer_required: bool
    fallback_enabled: bool
    backend_recipe_available: bool
    apply_candidate_allowed: bool
    human_gate_required: bool
    recommended_outputs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "risk_level": self.risk_level,
            "category": self.category,
            "stage_applicability": list(self.stage_applicability),
            "evidence_required": list(self.evidence_required),
            "llm_proposer_enabled": self.llm_proposer_enabled,
            "llm_reviewer_required": self.llm_reviewer_required,
            "fallback_enabled": self.fallback_enabled,
            "backend_recipe_available": self.backend_recipe_available,
            "apply_candidate_allowed": self.apply_candidate_allowed,
            "human_gate_required": self.human_gate_required,
            "recommended_outputs": list(self.recommended_outputs),
        }


STAGES = ("stage_1", "stage_2", "stage_3", "stage_4")
GUIDANCE_OUTPUTS = (
    "root_cause",
    "affected_files",
    "usage_patterns",
    "migration_options",
    "risk_notes",
    "engineer_checklist",
)


_POLICIES: dict[str, RepairFamilyPolicy] = {
    "INITMOCKS_TO_OPENMOCKS_CANDIDATE": RepairFamilyPolicy(
        family="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        risk_level="low",
        category="test_modernization",
        stage_applicability=STAGES,
        evidence_required=("test_source", "test_report"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=True,
        apply_candidate_allowed=True,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "POWERMOCK_LEGACY_TEST_STRATEGY": RepairFamilyPolicy(
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        risk_level="high",
        category="test_modernization",
        stage_applicability=STAGES,
        evidence_required=("pom_xml", "test_source_markers", "build_error_contract", "test_report"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE": RepairFamilyPolicy(
        family="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        risk_level="medium",
        category="test_modernization",
        stage_applicability=("stage_2", "stage_3", "stage_4"),
        evidence_required=("test_source", "test_report", "pom_xml"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "JAKARTA_NAMESPACE_MISMATCH": RepairFamilyPolicy(
        family="JAKARTA_NAMESPACE_MISMATCH",
        risk_level="medium",
        category="source_namespace",
        stage_applicability=("stage_2", "stage_3", "stage_4"),
        evidence_required=("build_error_contract", "source_ref", "pom_xml"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "JUNIT4_TO_JUNIT5_TEST_MIGRATION": RepairFamilyPolicy(
        family="JUNIT4_TO_JUNIT5_TEST_MIGRATION",
        risk_level="medium",
        category="test_modernization",
        stage_applicability=STAGES,
        evidence_required=("test_source", "test_report", "pom_xml"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "DEPENDENCY_VERSION_ALIGNMENT": RepairFamilyPolicy(
        family="DEPENDENCY_VERSION_ALIGNMENT",
        risk_level="medium",
        category="dependency_alignment",
        stage_applicability=STAGES,
        evidence_required=("pom_xml", "dependency_graph", "build_error_contract"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "SPRING_SECURITY_API_DRIFT": RepairFamilyPolicy(
        family="SPRING_SECURITY_API_DRIFT",
        risk_level="high",
        category="behavioral_api_drift",
        stage_applicability=("stage_2", "stage_3", "stage_4"),
        evidence_required=("pom_xml", "runtime_contract", "test_report", "source_ref"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "SPRING_DATA_SORT_API_DRIFT": RepairFamilyPolicy(
        family="SPRING_DATA_SORT_API_DRIFT",
        risk_level="low",
        category="source_api_drift",
        stage_applicability=STAGES,
        evidence_required=("build_error_contract", "pom_xml", "source_ref"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=True,
        apply_candidate_allowed=True,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
    "UNKNOWN_FAILURE": RepairFamilyPolicy(
        family="UNKNOWN_FAILURE",
        risk_level="unknown",
        category="unknown",
        stage_applicability=STAGES,
        evidence_required=("build_error_contract", "test_report", "test_agent_log"),
        llm_proposer_enabled=True,
        llm_reviewer_required=True,
        fallback_enabled=True,
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        recommended_outputs=GUIDANCE_OUTPUTS,
    ),
}


_ALIASES = {
    "unknown": "UNKNOWN_FAILURE",
    "blocked_pending_evidence": "UNKNOWN_FAILURE",
    "SPRING_SECURITY_BEHAVIOR_REVIEW": "SPRING_SECURITY_API_DRIFT",
    "JAKARTA_IMPORT_MECHANICAL_SOURCE": "JAKARTA_NAMESPACE_MISMATCH",
    "JAKARTA_HYBRID_STRATEGY_REVIEW": "JAKARTA_NAMESPACE_MISMATCH",
    "DEPENDENCY_REPLACE_JAVAX_SERVLET_API_WITH_JAKARTA": "DEPENDENCY_VERSION_ALIGNMENT",
    "DEPENDENCY_REPLACE_JAVAX_VALIDATION_WITH_JAKARTA": "DEPENDENCY_VERSION_ALIGNMENT",
    "DEPENDENCY_ADD_VALIDATION_STARTER": "DEPENDENCY_VERSION_ALIGNMENT",
    "DEPENDENCY_REMOVE_TOMCAT9_OVERRIDE_BOOT3": "DEPENDENCY_VERSION_ALIGNMENT",
}


def registered_repair_families() -> tuple[str, ...]:
    return tuple(_POLICIES)


def repair_family_policy(family: str | None) -> RepairFamilyPolicy:
    key = str(family or "").strip() or "UNKNOWN_FAILURE"
    key = _ALIASES.get(key, key)
    return _POLICIES.get(key, _POLICIES["UNKNOWN_FAILURE"])
