from migration_factory.remediation.agent import (
    AUTO_APPLY_DETERMINISTIC_CANDIDATE,
    NO_REMEDIATION_AVAILABLE,
    decide_remediation_v1,
    generate_remediation_plan,
)
from migration_factory.remediation.behavioral_context import (
    BEHAVIORAL_CONTEXT_ONLY,
    HUMAN_REVIEW_ONLY as BEHAVIORAL_HUMAN_REVIEW_ONLY,
    LLM_PROPOSAL_ALLOWED_BY_POLICY,
    BehavioralFailureContextResult,
    generate_behavioral_failure_context_pack,
    should_generate_behavioral_context,
)
from migration_factory.remediation.legacy_equivalence import (
    LEGACY_BEHAVIOR_EQUIVALENCE_GATE,
    LegacyBehaviorEquivalenceResult,
    generate_legacy_behavior_equivalence_report,
)
from migration_factory.remediation.test_context_repair import (
    TEST_CONTEXT_REPAIR_GATE,
    TestContextRepairProposalResult,
    generate_test_context_repair_proposal,
)
from migration_factory.remediation.legacy_guided_patch_proposal import (
    LEGACY_GUIDED_PATCH_GATE,
    LegacyGuidedPatchProposalResult,
    generate_legacy_guided_patch_proposal,
)
from migration_factory.remediation.mockito_bean_placement import (
    MOCKITO_BEAN_PLACEMENT_GATE,
    MockitoBeanPlacementResult,
    generate_mockito_bean_placement_report,
)
from migration_factory.remediation.approved_patch_apply import (
    APPROVED_PATCH_APPLY_GATE,
    ApprovedPatchApplyResult,
    apply_approved_behavioral_patch,
)
from migration_factory.remediation.strategy_router import (
    APPROVED_PATCH_APPLIED_RERUN_FAILED,
    AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE,
    BEHAVIORAL_REMEDIATION_STRATEGY_GATE,
    ESCALATE_TO_LLM_PROPOSAL,
    HUMAN_REVIEW_ONLY as STRATEGY_ROUTER_HUMAN_REVIEW_ONLY,
    LLM_DISABLED_HUMAN_REVIEW_REQUIRED,
    NO_BEHAVIORAL_REMEDIATION_NEEDED,
    STOP_REPEATED_BEHAVIORAL_PATCH_CHASING,
    BehavioralRemediationStrategyResult,
    generate_behavioral_remediation_strategy,
)
from migration_factory.remediation.executor import (
    DEFAULT_MAX_AUTO_REMEDIATION_ATTEMPTS_PER_UNIT,
    AutoRemediationLoopResult,
    execute_auto_remediation_loop,
)
from migration_factory.remediation.policy import (
    AUTO_APPLY_DETERMINISTIC,
    HUMAN_REVIEW_ONLY,
    LLM_DISABLED_REPORT_ONLY,
    LLM_PROPOSAL_ALLOWED,
    LlmPolicy,
    build_remediation_plan,
    decide_remediation,
    load_llm_policy,
)

__all__ = [
    "AUTO_APPLY_DETERMINISTIC_CANDIDATE",
    "AUTO_APPLY_DETERMINISTIC",
    "AutoRemediationLoopResult",
    "BEHAVIORAL_CONTEXT_ONLY",
    "APPROVED_PATCH_APPLY_GATE",
    "ApprovedPatchApplyResult",
    "APPROVED_PATCH_APPLIED_RERUN_FAILED",
    "AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE",
    "BEHAVIORAL_HUMAN_REVIEW_ONLY",
    "BEHAVIORAL_REMEDIATION_STRATEGY_GATE",
    "BehavioralFailureContextResult",
    "BehavioralRemediationStrategyResult",
    "DEFAULT_MAX_AUTO_REMEDIATION_ATTEMPTS_PER_UNIT",
    "ESCALATE_TO_LLM_PROPOSAL",
    "HUMAN_REVIEW_ONLY",
    "LLM_DISABLED_HUMAN_REVIEW_REQUIRED",
    "LEGACY_BEHAVIOR_EQUIVALENCE_GATE",
    "LEGACY_GUIDED_PATCH_GATE",
    "LegacyBehaviorEquivalenceResult",
    "LegacyGuidedPatchProposalResult",
    "MOCKITO_BEAN_PLACEMENT_GATE",
    "MockitoBeanPlacementResult",
    "TEST_CONTEXT_REPAIR_GATE",
    "TestContextRepairProposalResult",
    "LLM_DISABLED_REPORT_ONLY",
    "LLM_PROPOSAL_ALLOWED_BY_POLICY",
    "LLM_PROPOSAL_ALLOWED",
    "NO_REMEDIATION_AVAILABLE",
    "NO_BEHAVIORAL_REMEDIATION_NEEDED",
    "LlmPolicy",
    "STOP_REPEATED_BEHAVIORAL_PATCH_CHASING",
    "STRATEGY_ROUTER_HUMAN_REVIEW_ONLY",
    "decide_remediation_v1",
    "execute_auto_remediation_loop",
    "generate_behavioral_remediation_strategy",
    "generate_behavioral_failure_context_pack",
    "generate_legacy_behavior_equivalence_report",
    "generate_legacy_guided_patch_proposal",
    "generate_mockito_bean_placement_report",
    "generate_remediation_plan",
    "generate_test_context_repair_proposal",
    "build_remediation_plan",
    "apply_approved_behavioral_patch",
    "decide_remediation",
    "load_llm_policy",
    "should_generate_behavioral_context",
]
