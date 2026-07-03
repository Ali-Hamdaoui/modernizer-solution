"""Governed repair recipe registry for R11A.

This registry describes backend repair recipe eligibility. It is policy only:
it does not execute patches, does not approve repairs, and does not override
family/subfamily governance.
"""

from __future__ import annotations

from dataclasses import dataclass


RECIPE_STATUSES = frozenset({
    "apply_enabled",
    "dry_run_only",
    "strategy_only",
    "human_refactor_required",
    "unsupported",
})


@dataclass(frozen=True)
class RepairRecipePolicy:
    recipe_id: str
    family: str
    subfamily: str
    recipe_status: str
    risk_level: str
    backend_recipe_available: bool
    apply_candidate_allowed: bool
    dry_run_available: bool
    required_evidence: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]
    verification_requirements: tuple[str, ...]
    rollback_required: bool
    proof_required: bool
    rag_reuse_enabled: bool
    promotion_notes: str

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "family": self.family,
            "subfamily": self.subfamily,
            "recipe_status": self.recipe_status,
            "risk_level": self.risk_level,
            "backend_recipe_available": self.backend_recipe_available,
            "apply_candidate_allowed": self.apply_candidate_allowed,
            "dry_run_available": self.dry_run_available,
            "required_evidence": list(self.required_evidence),
            "forbidden_patterns": list(self.forbidden_patterns),
            "verification_requirements": list(self.verification_requirements),
            "rollback_required": self.rollback_required,
            "proof_required": self.proof_required,
            "rag_reuse_enabled": self.rag_reuse_enabled,
            "promotion_notes": self.promotion_notes,
        }


_POLICIES: dict[str, RepairRecipePolicy] = {
    "INITMOCKS_DIRECT_REPLACEMENT": RepairRecipePolicy(
        recipe_id="recipe-initmocks-direct-replacement-v1",
        family="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        subfamily="INITMOCKS_DIRECT_REPLACEMENT",
        recipe_status="apply_enabled",
        risk_level="low",
        backend_recipe_available=True,
        apply_candidate_allowed=True,
        dry_run_available=True,
        required_evidence=("sandbox", "test_source", "test_report"),
        forbidden_patterns=(),
        verification_requirements=(
            "checksum-bound target file",
            "human approval",
            "sandbox apply",
            "verification proof",
        ),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Already validated by the governed R10.1A green repair workflow.",
    ),
    "JAKARTA_IMPORT_ONLY": RepairRecipePolicy(
        recipe_id="recipe-jakarta-import-only-v1",
        family="JAKARTA_NAMESPACE_MISMATCH",
        subfamily="JAKARTA_IMPORT_ONLY",
        recipe_status="dry_run_only",
        risk_level="medium",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=True,
        required_evidence=("source_ref", "build_error_contract", "pom_xml"),
        forbidden_patterns=(
            "pom.xml change",
            "dependency version change",
            "business logic change",
            "method body change",
            "security behavior change",
            "runtime configuration change",
            "test assertion change",
        ),
        verification_requirements=(
            "compile proof",
            "targeted tests",
            "namespace-only diff review",
        ),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Dry-run only in R11A. Promote later only with strict namespace-only evidence gates.",
    ),
    "MOCKBEAN_DIRECT_REPLACEMENT": RepairRecipePolicy(
        recipe_id="recipe-mockbean-direct-replacement-v1",
        family="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        subfamily="MOCKBEAN_DIRECT_REPLACEMENT",
        recipe_status="dry_run_only",
        risk_level="medium",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=True,
        required_evidence=("test_source", "test_report", "pom_xml"),
        forbidden_patterns=("Spring test context behavior change",),
        verification_requirements=("Spring test context proof", "targeted tests"),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Dry-run only until Spring Boot/Test compatibility is proven.",
    ),
    "DEPENDENCY_VERSION_BUMP_ONLY": RepairRecipePolicy(
        recipe_id="recipe-dependency-version-bump-only-v1",
        family="DEPENDENCY_VERSION_ALIGNMENT",
        subfamily="DEPENDENCY_VERSION_BUMP_ONLY",
        recipe_status="dry_run_only",
        risk_level="medium",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=True,
        required_evidence=("pom_xml", "dependency_graph", "build_error_contract"),
        forbidden_patterns=("source change", "behavioral change", "transitive conflict"),
        verification_requirements=("dependency tree proof", "build proof"),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Dry-run only until dependency tree and build verification gates are complete.",
    ),
    "POWERMOCK_STATIC_MOCK_SIMPLE": RepairRecipePolicy(
        recipe_id="recipe-powermock-static-mock-simple-v1",
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        subfamily="POWERMOCK_STATIC_MOCK_SIMPLE",
        recipe_status="dry_run_only",
        risk_level="medium",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=True,
        required_evidence=("pom_xml", "test_source", "test_report", "build_error_contract"),
        forbidden_patterns=("PowerMockito.whenNew", "Whitebox", "private method mocking", "final class mocking"),
        verification_requirements=("behavior equivalence review", "targeted tests"),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Dry-run only. Do not auto-apply PowerMock migrations in R11A.",
    ),
    "POWERMOCK_CONSTRUCTOR_MOCKING": RepairRecipePolicy(
        recipe_id="recipe-powermock-constructor-mocking-v1",
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        subfamily="POWERMOCK_CONSTRUCTOR_MOCKING",
        recipe_status="human_refactor_required",
        risk_level="high",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=False,
        required_evidence=("pom_xml", "test_source", "test_report", "build_error_contract"),
        forbidden_patterns=("PowerMockito.whenNew", "constructor mocking"),
        verification_requirements=("engineer refactor plan", "targeted tests", "behavior proof"),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Human refactor required. Prefer dependency injection or test redesign.",
    ),
    "POWERMOCK_PRIVATE_OR_FINAL_MOCKING": RepairRecipePolicy(
        recipe_id="recipe-powermock-private-final-mocking-v1",
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        subfamily="POWERMOCK_PRIVATE_OR_FINAL_MOCKING",
        recipe_status="human_refactor_required",
        risk_level="high",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=False,
        required_evidence=("pom_xml", "test_source", "test_report", "build_error_contract"),
        forbidden_patterns=("Whitebox", "private method mocking", "final class mocking"),
        verification_requirements=("engineer refactor plan", "targeted tests", "behavior proof"),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Human refactor required. Do not generate an apply candidate.",
    ),
    "SPRING_SECURITY_BEHAVIORAL_CHANGE": RepairRecipePolicy(
        recipe_id="recipe-spring-security-behavioral-change-v1",
        family="SPRING_SECURITY_API_DRIFT",
        subfamily="SPRING_SECURITY_BEHAVIORAL_CHANGE",
        recipe_status="strategy_only",
        risk_level="high",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=False,
        required_evidence=("pom_xml", "runtime_contract", "test_report", "source_ref"),
        forbidden_patterns=("authorization behavior", "csrf behavior", "security behavior change"),
        verification_requirements=("security regression proof", "runtime proof"),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Strategy-only. Security behavior changes require human design review.",
    ),
    "JUNIT4_RULE_COMPLEX": RepairRecipePolicy(
        recipe_id="recipe-junit4-rule-complex-v1",
        family="JUNIT4_TO_JUNIT5_TEST_MIGRATION",
        subfamily="JUNIT4_RULE_COMPLEX",
        recipe_status="human_refactor_required",
        risk_level="high",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=False,
        required_evidence=("test_source", "test_report", "pom_xml"),
        forbidden_patterns=("@ClassRule", "TemporaryFolder", "ExpectedException"),
        verification_requirements=("engineer migration plan", "JUnit test proof"),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Human refactor required for complex JUnit4 rule migration.",
    ),
    "UNKNOWN_SUBFAMILY": RepairRecipePolicy(
        recipe_id="recipe-unknown-subfamily-v1",
        family="UNKNOWN_FAILURE",
        subfamily="UNKNOWN_SUBFAMILY",
        recipe_status="unsupported",
        risk_level="unknown",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        dry_run_available=False,
        required_evidence=("test_source", "test_report", "build_error_contract"),
        forbidden_patterns=(),
        verification_requirements=("collect missing evidence",),
        rollback_required=True,
        proof_required=True,
        rag_reuse_enabled=True,
        promotion_notes="Unsupported until evidence is sufficient to classify the repair subfamily.",
    ),
}


def registered_repair_recipes() -> tuple[str, ...]:
    return tuple(_POLICIES)


def repair_recipe_policy(subfamily: str | None) -> RepairRecipePolicy:
    key = str(subfamily or "").strip() or "UNKNOWN_SUBFAMILY"
    return _POLICIES.get(key, _POLICIES["UNKNOWN_SUBFAMILY"])