"""Generic repair subfamily promotion registry for R10."""

from __future__ import annotations

from dataclasses import dataclass


PROMOTION_STATUSES = frozenset({
    "safe_recipe_candidate",
    "medium_risk_recipe_candidate",
    "strategy_only",
    "human_refactor_required",
    "unsupported",
})


@dataclass(frozen=True)
class RepairSubfamilyPolicy:
    family: str
    subfamily: str
    risk_level: str
    promotion_status: str
    backend_recipe_available: bool
    apply_candidate_allowed: bool
    human_gate_required: bool
    required_evidence: tuple[str, ...]
    detected_patterns: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]
    verification_requirements: tuple[str, ...]
    rollback_required: bool
    proof_required: bool
    recommended_engineer_action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "subfamily": self.subfamily,
            "risk_level": self.risk_level,
            "promotion_status": self.promotion_status,
            "backend_recipe_available": self.backend_recipe_available,
            "apply_candidate_allowed": self.apply_candidate_allowed,
            "human_gate_required": self.human_gate_required,
            "required_evidence": list(self.required_evidence),
            "detected_patterns": list(self.detected_patterns),
            "forbidden_patterns": list(self.forbidden_patterns),
            "verification_requirements": list(self.verification_requirements),
            "rollback_required": self.rollback_required,
            "proof_required": self.proof_required,
            "recommended_engineer_action": self.recommended_engineer_action,
        }


_POLICIES: dict[str, RepairSubfamilyPolicy] = {
    "INITMOCKS_DIRECT_REPLACEMENT": RepairSubfamilyPolicy(
        family="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        subfamily="INITMOCKS_DIRECT_REPLACEMENT",
        risk_level="low",
        promotion_status="safe_recipe_candidate",
        backend_recipe_available=True,
        apply_candidate_allowed=True,
        human_gate_required=True,
        required_evidence=("test_source", "test_report", "sandbox"),
        detected_patterns=("MockitoAnnotations.initMocks",),
        forbidden_patterns=(),
        verification_requirements=("single initMocks marker", "sandbox target checksum", "review checksum"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Use governed backend recipe to replace initMocks with openMocks after checksum-bound approval.",
    ),
    "MOCKBEAN_DIRECT_REPLACEMENT": RepairSubfamilyPolicy(
        family="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        subfamily="MOCKBEAN_DIRECT_REPLACEMENT",
        risk_level="medium",
        promotion_status="strategy_only",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("test_source", "test_report", "pom_xml"),
        detected_patterns=("@MockBean",),
        forbidden_patterns=(),
        verification_requirements=("Spring test context proof",),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Review MockBean replacement constraints before promoting to a backend recipe.",
    ),
    "POWERMOCK_STATIC_MOCK_SIMPLE": RepairSubfamilyPolicy(
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        subfamily="POWERMOCK_STATIC_MOCK_SIMPLE",
        risk_level="medium",
        promotion_status="medium_risk_recipe_candidate",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("pom_xml", "test_source", "test_report", "build_error_contract"),
        detected_patterns=("PowerMockito.mockStatic", "mockStatic"),
        forbidden_patterns=("PowerMockito.whenNew", "whenNew", "Whitebox", "private method mocking", "final class mocking"),
        verification_requirements=("test source proof", "targeted test run", "behavior equivalence review"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Assess simple static mocking for future Mockito inline recipe; do not auto-apply in R10.",
    ),
    "POWERMOCK_CONSTRUCTOR_MOCKING": RepairSubfamilyPolicy(
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        subfamily="POWERMOCK_CONSTRUCTOR_MOCKING",
        risk_level="high",
        promotion_status="human_refactor_required",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("pom_xml", "test_source", "test_report", "build_error_contract"),
        detected_patterns=("PowerMockito.whenNew", "whenNew"),
        forbidden_patterns=("PowerMockito.whenNew", "whenNew", "constructor mocking"),
        verification_requirements=("engineer refactor plan", "targeted tests", "rollback proof"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Refactor constructor mocking by injecting dependencies or redesigning the test.",
    ),
    "POWERMOCK_PRIVATE_OR_FINAL_MOCKING": RepairSubfamilyPolicy(
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        subfamily="POWERMOCK_PRIVATE_OR_FINAL_MOCKING",
        risk_level="high",
        promotion_status="human_refactor_required",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("pom_xml", "test_source", "test_report", "build_error_contract"),
        detected_patterns=("Whitebox", "private method mocking", "final class mocking"),
        forbidden_patterns=("private method mocking", "final class mocking"),
        verification_requirements=("engineer refactor plan", "targeted tests", "behavior proof"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Refactor private/final mocking with engineer review; no backend recipe candidate in R10.",
    ),
    "JUNIT4_RUNNER_SIMPLE": RepairSubfamilyPolicy(
        family="JUNIT4_TO_JUNIT5_TEST_MIGRATION",
        subfamily="JUNIT4_RUNNER_SIMPLE",
        risk_level="medium",
        promotion_status="strategy_only",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("test_source", "test_report", "pom_xml"),
        detected_patterns=("@RunWith",),
        forbidden_patterns=("@Rule", "ExternalResource", "PowerMockRunner"),
        verification_requirements=("JUnit test run proof",),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Review runner migration constraints before backend recipe promotion.",
    ),
    "JUNIT4_RULE_COMPLEX": RepairSubfamilyPolicy(
        family="JUNIT4_TO_JUNIT5_TEST_MIGRATION",
        subfamily="JUNIT4_RULE_COMPLEX",
        risk_level="high",
        promotion_status="human_refactor_required",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("test_source", "test_report", "pom_xml"),
        detected_patterns=("@Rule", "ExternalResource"),
        forbidden_patterns=("@ClassRule", "TemporaryFolder", "ExpectedException"),
        verification_requirements=("engineer migration plan", "JUnit test proof"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Review complex JUnit4 rules manually before migration.",
    ),
    "JAKARTA_IMPORT_ONLY": RepairSubfamilyPolicy(
        family="JAKARTA_NAMESPACE_MISMATCH",
        subfamily="JAKARTA_IMPORT_ONLY",
        risk_level="medium",
        promotion_status="medium_risk_recipe_candidate",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("source_ref", "build_error_contract", "pom_xml"),
        detected_patterns=("javax.", "jakarta."),
        forbidden_patterns=("runtime behavior change",),
        verification_requirements=("compile proof", "targeted tests"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Review namespace-only scope before backend recipe promotion.",
    ),
    "JAKARTA_DEPENDENCY_ALIGNMENT": RepairSubfamilyPolicy(
        family="JAKARTA_NAMESPACE_MISMATCH",
        subfamily="JAKARTA_DEPENDENCY_ALIGNMENT",
        risk_level="medium",
        promotion_status="strategy_only",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("pom_xml", "dependency_graph", "build_error_contract"),
        detected_patterns=("javax", "jakarta", "dependency"),
        forbidden_patterns=("behavioral change",),
        verification_requirements=("dependency tree proof", "compile proof"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Align dependencies with human-reviewed migration plan.",
    ),
    "DEPENDENCY_VERSION_BUMP_ONLY": RepairSubfamilyPolicy(
        family="DEPENDENCY_VERSION_ALIGNMENT",
        subfamily="DEPENDENCY_VERSION_BUMP_ONLY",
        risk_level="medium",
        promotion_status="medium_risk_recipe_candidate",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("pom_xml", "dependency_graph", "build_error_contract"),
        detected_patterns=("version", "dependency"),
        forbidden_patterns=("source change", "behavioral change"),
        verification_requirements=("dependency tree proof", "build proof"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Review version alignment and promote only checksum-bound dependency recipes.",
    ),
    "JACKSON_PROPERTY_BOM_ALIGNMENT": RepairSubfamilyPolicy(
        family="JACKSON_VERSION_ALIGNMENT_DRIFT",
        subfamily="JACKSON_PROPERTY_BOM_ALIGNMENT",
        risk_level="medium",
        promotion_status="medium_risk_recipe_candidate",
        backend_recipe_available=True,
        apply_candidate_allowed=True,
        human_gate_required=True,
        required_evidence=("pom_xml", "dependency_graph", "test_report", "sandbox"),
        detected_patterns=("ToStringSerializerBase", "jackson-databind", "omitted for conflict"),
        forbidden_patterns=("spring-boot.version>3", "jackson 2.20.0"),
        verification_requirements=("mvn -DskipTests clean compile", "mvn -Dtest=MessageUtilsTest test", "repair proof"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Review checksum-bound POM alignment candidate, approve exact checksums, then run targeted Jackson test proof.",
    ),
    "SPRING_SECURITY_BEHAVIORAL_CHANGE": RepairSubfamilyPolicy(
        family="SPRING_SECURITY_API_DRIFT",
        subfamily="SPRING_SECURITY_BEHAVIORAL_CHANGE",
        risk_level="high",
        promotion_status="strategy_only",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("pom_xml", "runtime_contract", "test_report", "source_ref"),
        detected_patterns=("SecurityFilterChain", "WebSecurityConfigurerAdapter", "authorizeHttpRequests"),
        forbidden_patterns=("authorization behavior", "csrf behavior"),
        verification_requirements=("security regression proof", "runtime proof"),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Create human-reviewed security migration plan and prove behavior.",
    ),
    "UNKNOWN_SUBFAMILY": RepairSubfamilyPolicy(
        family="UNKNOWN_FAILURE",
        subfamily="UNKNOWN_SUBFAMILY",
        risk_level="unknown",
        promotion_status="unsupported",
        backend_recipe_available=False,
        apply_candidate_allowed=False,
        human_gate_required=True,
        required_evidence=("test_source", "test_report", "build_error_contract"),
        detected_patterns=(),
        forbidden_patterns=(),
        verification_requirements=("collect missing evidence",),
        rollback_required=True,
        proof_required=True,
        recommended_engineer_action="Collect more evidence before selecting a repair subfamily.",
    ),
}


def registered_repair_subfamilies() -> tuple[str, ...]:
    return tuple(_POLICIES)


def repair_subfamily_policy(subfamily: str | None) -> RepairSubfamilyPolicy:
    key = str(subfamily or "").strip() or "UNKNOWN_SUBFAMILY"
    return _POLICIES.get(key, _POLICIES["UNKNOWN_SUBFAMILY"])
