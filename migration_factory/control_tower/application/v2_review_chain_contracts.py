"""F2 review-chain foundation contracts — deterministic artifact, primary LLM, reviewer LLM.

Core rule: A model reviews another model.
Deterministic fallback alone must not satisfy a model-required reviewed artifact.

The chain:
  deterministic artifact
  -> primary LLM output
  -> reviewer LLM validation
  -> reviewed artifact contract for Analysis and Planning

This module defines the contract shapes and fail-closed validation.
It does NOT implement execution, approval, filesystem authority, or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from migration_factory.control_tower.domain.checksums import sha256_canonical_json


# ── Enums ──────────────────────────────────────────────────────────────


class ArtifactPhase(str, Enum):
    ANALYSIS = "analysis"
    PLANNING = "planning"


class ReviewerDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    REQUEST_REVISION = "request_revision"


class ReviewDimension(str, Enum):
    EVIDENCE_FIT = "evidence_fit"
    CORRECTNESS = "correctness"
    COMPLETENESS = "completeness"
    RISK_ASSESSMENT = "risk_assessment"
    POLICY_CONCERNS = "policy_concerns"
    CHECKSUM_MATCH = "checksum_match"
    STALE_INPUT_CHECK = "stale_input_check"


# ── Forbidden field patterns ───────────────────────────────────────────

# Fields that must NEVER appear in primary LLM input/output or reviewer context.
# These leak runtime internals and are forbidden by the three-tier permission model.
_FORBIDDEN_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "sandbox_path",
    "argv",
    "env",
    "raw_command",
    "filesystem_target",
    "provider",
    "endpoint",
    "deployment",
    "env_ref",
    "user_supplied_file_path",
})

_FORBIDDEN_DICT_KEY_SUBSTRINGS: tuple[str, ...] = (
    "provider",
    "endpoint",
    "deployment",
    "sandbox",
    "argv",
    "env_ref",
)


# ── AMF-254: Deterministic artifact contract ───────────────────────────


@dataclass(frozen=True)
class DeterministicAnalysisFacts:
    """Required deterministic facts extracted by the Analysis agent.

    These ground all model-required output before primary LLM reasoning.
    """

    detected_framework: str | None = None
    detected_language: str | None = None
    build_tool: str | None = None
    source_java_version: str | None = None
    source_spring_boot_version: str | None = None
    dependency_count: int | None = None
    javax_import_count: int | None = None
    jakarta_import_count: int | None = None
    spring_import_count: int | None = None
    module_count: int | None = None
    test_file_count: int | None = None
    has_datasource_config: bool = False
    has_security_config: bool = False
    has_actuator_config: bool = False
    openrewrite_impact: str | None = None
    openrewrite_risk: str | None = None
    risk_facts: tuple[str, ...] = ()
    uncertainty_notes: tuple[str, ...] = ()
    file_refs_checksums: tuple[tuple[str, str], ...] = ()  # (path, checksum)


@dataclass(frozen=True)
class DeterministicPlanningFacts:
    """Required deterministic facts produced by the Planning agent.

    These define the migration plan before primary LLM reasoning.
    """

    selected_migration_stages: tuple[str, ...] = ()
    included_stages: tuple[str, ...] = ()
    excluded_skipped_stages: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    target_java_version: str | None = None
    target_spring_boot_version: str | None = None
    profile_id: str | None = None
    strategy: str | None = None
    risk_level: str | None = None
    executable: bool = False
    requires_human_approval: bool = True
    blocker_count: int = 0
    warning_count: int = 0
    unit_count: int = 0
    required_downstream_inputs: tuple[str, ...] = ()
    file_refs_checksums: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DeterministicArtifactBinding:
    """Binds a deterministic artifact for model input.

    A deterministic artifact binding links a concrete artifact (file, content)
    to the review chain, providing the facts extracted from it and its
    integrity checksums.
    """

    artifact_role: str  # "deterministic"
    artifact_phase: str  # "analysis" or "planning"
    job_id: str
    stage_index: int
    artifact_ref: str  # stable reference to the artifact
    artifact_revision_id: str | None = None
    content_checksum: str = ""
    input_checksum: str = ""
    source_evidence_refs: tuple[str, ...] = ()
    file_evidence_refs: tuple[str, ...] = ()
    profile_context: dict[str, Any] | None = None
    deterministic_facts: DeterministicAnalysisFacts | DeterministicPlanningFacts | None = None
    created_at: str = ""
    schema_version: str = "1.0.0"


# ── Validation: deterministic artifact ──────────────────────────────────


class DeterministicArtifactValidationError(ValueError):
    """Raised when a deterministic artifact fails contract validation."""


def validate_deterministic_artifact_binding(
    binding: DeterministicArtifactBinding,
) -> list[str]:
    """Validate a deterministic artifact binding. Returns list of failures.

    Fail-closed: any failure means the binding is invalid and must not be
    accepted for model input.
    """
    failures: list[str] = []

    if not binding.artifact_ref or not binding.artifact_ref.strip():
        failures.append("missing artifact_ref")
    if not binding.content_checksum or not binding.content_checksum.strip():
        failures.append("missing content_checksum")
    if not binding.job_id or not binding.job_id.strip():
        failures.append("missing job_id")
    if binding.artifact_phase not in (ArtifactPhase.ANALYSIS.value, ArtifactPhase.PLANNING.value):
        failures.append(
            f"unknown artifact_phase {binding.artifact_phase!r}; "
            f"must be 'analysis' or 'planning'"
        )
    if binding.artifact_role != "deterministic":
        failures.append(
            f"invalid artifact_role {binding.artifact_role!r}; must be 'deterministic'"
        )
    if binding.stage_index < 1 or binding.stage_index > 3:
        failures.append(f"stage_index {binding.stage_index} out of range [1,3]")

    if binding.deterministic_facts is None:
        failures.append("missing deterministic_facts")
    else:
        facts = binding.deterministic_facts
        if isinstance(facts, DeterministicAnalysisFacts):
            failures.extend(_validate_analysis_facts(facts))
        elif isinstance(facts, DeterministicPlanningFacts):
            failures.extend(_validate_planning_facts(facts))
        else:
            failures.append(
                f"unknown deterministic_facts type: {type(facts).__name__}"
            )

    return failures


def _validate_analysis_facts(facts: DeterministicAnalysisFacts) -> list[str]:
    failures: list[str] = []
    if not facts.detected_framework and not facts.detected_language and not facts.build_tool:
        failures.append(
            "deterministic Analysis facts must include at least one of "
            "detected_framework, detected_language, build_tool"
        )
    return failures


def _validate_planning_facts(facts: DeterministicPlanningFacts) -> list[str]:
    failures: list[str] = []
    if not facts.selected_migration_stages:
        failures.append("deterministic Planning facts must include selected_migration_stages")
    return failures


# ── AMF-255: Primary LLM contract ───────────────────────────────────────


@dataclass(frozen=True)
class PrimaryLLMInput:
    """Primary LLM input contract — backend-owned and artifact-bound.

    Must reference deterministic artifacts by ref and checksum.
    Must NOT include sandbox_path, argv, env, raw command, filesystem target,
    provider, endpoint, deployment, env ref, or user-supplied file paths.
    """

    deterministic_artifact_ref: str
    deterministic_artifact_checksum: str
    phase: str  # "analysis" or "planning"
    job_id: str
    stage_index: int

    source_profile: dict[str, Any] | None = None
    target_profile: dict[str, Any] | None = None
    allowed_user_comments: tuple[str, ...] = ()
    safe_artifact_preview_text: str | None = None


@dataclass(frozen=True)
class PrimaryLLMOutput:
    """Primary LLM output contract.

    Must include reasoning, risks, confidence, recommended next step,
    draft Markdown, and machine-readable metadata.
    Must NOT include execution instructions, runtime internals, or
    forbidden fields.
    """

    reasoning: str
    risks: tuple[str, ...]
    confidence: float
    recommended_next_step: str
    draft_markdown: str
    machine_readable_metadata: dict[str, Any] = field(default_factory=dict)
    output_checksum: str = ""


class PrimaryLLMOutputValidationError(ValueError):
    """Raised when primary LLM output fails validation."""


_PRIMARY_REQUIRED_FIELDS: tuple[str, ...] = (
    "reasoning",
    "risks",
    "confidence",
    "recommended_next_step",
    "draft_markdown",
)


def validate_primary_llm_input(input_: PrimaryLLMInput) -> list[str]:
    """Validate primary LLM input. Returns list of failures. Fail-closed."""
    failures: list[str] = []

    if not input_.deterministic_artifact_ref or not input_.deterministic_artifact_ref.strip():
        failures.append("missing deterministic_artifact_ref")
    if not input_.deterministic_artifact_checksum or not input_.deterministic_artifact_checksum.strip():
        failures.append("missing deterministic_artifact_checksum")
    if input_.phase not in (ArtifactPhase.ANALYSIS.value, ArtifactPhase.PLANNING.value):
        failures.append(f"unknown phase {input_.phase!r}; must be 'analysis' or 'planning'")
    if not input_.job_id or not input_.job_id.strip():
        failures.append("missing job_id")
    if input_.stage_index < 1 or input_.stage_index > 3:
        failures.append(f"stage_index {input_.stage_index} out of range [1,3]")

    failures.extend(_check_forbidden_fields(input_, "PrimaryLLMInput"))
    return failures


def validate_primary_llm_output(output: PrimaryLLMOutput) -> list[str]:
    """Validate primary LLM output. Returns list of failures. Fail-closed.

    Malformed output must fail closed:
    - missing reasoning, draft_markdown, or confidence -> invalid
    - unsupported recommended next step -> invalid
    - attempted execution instruction -> invalid
    - provider/runtime leak -> invalid
    """
    failures: list[str] = []

    missing = [f for f in _PRIMARY_REQUIRED_FIELDS if not _field_present(output, f)]
    for field_name in missing:
        failures.append(f"missing {field_name}")

    if not (0.0 <= output.confidence <= 1.0):
        failures.append(
            f"confidence {output.confidence} out of range [0.0, 1.0]"
        )

    if not output.draft_markdown or not output.draft_markdown.strip():
        failures.append("draft_markdown must not be empty")

    if not output.reasoning or not output.reasoning.strip():
        failures.append("reasoning must not be empty")

    failures.extend(_check_forbidden_fields(output, "PrimaryLLMOutput"))
    failures.extend(_check_execution_instruction(output))
    return failures


def _field_present(obj: Any, field_name: str) -> bool:
    value = getattr(obj, field_name, None)
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple)) and len(value) == 0:
        return False
    return True


# ── AMF-256: Reviewer LLM contract ─────────────────────────────────────


@dataclass(frozen=True)
class ReviewerLLMInput:
    """Reviewer LLM input contract.

    Binds deterministic artifact and primary LLM output by exact checksums.
    Must reference both the deterministic artifact and the primary output
    it is reviewing.
    """

    deterministic_artifact_ref: str
    deterministic_artifact_checksum: str
    primary_output_ref: str
    primary_output_checksum: str
    primary_reasoning: str
    draft_markdown: str
    phase: str
    job_id: str
    stage_index: int
    policy_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewerLLMOutput:
    """Reviewer LLM output contract.

    Binds its decision to exact deterministic and primary output checksums.
    Decision must be accept, reject, or request_revision.
    """

    decision: str  # accept | reject | request_revision
    notes: tuple[str, ...]
    confidence: float
    risks: tuple[str, ...]
    policy_concerns: tuple[str, ...]
    reviewed_artifact_checksum: str
    reviewed_primary_output_checksum: str
    reviewer_output_checksum: str = ""
    review_dimensions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewerValidationResult:
    """Structured result of reviewer validation against the contract."""

    ok: bool
    decision: str | None
    failures: tuple[str, ...]
    checksum_matched: bool
    deterministic_artifact_checksum: str
    primary_output_checksum: str
    reviewer_output_checksum: str


class ReviewerLLMOutputValidationError(ValueError):
    """Raised when reviewer LLM output fails validation."""


def validate_reviewer_llm_input(input_: ReviewerLLMInput) -> list[str]:
    """Validate reviewer LLM input. Returns list of failures. Fail-closed."""
    failures: list[str] = []

    if not input_.deterministic_artifact_ref or not input_.deterministic_artifact_ref.strip():
        failures.append("missing deterministic_artifact_ref")
    if not input_.deterministic_artifact_checksum or not input_.deterministic_artifact_checksum.strip():
        failures.append("missing deterministic_artifact_checksum")
    if not input_.primary_output_ref or not input_.primary_output_ref.strip():
        failures.append("missing primary_output_ref")
    if not input_.primary_output_checksum or not input_.primary_output_checksum.strip():
        failures.append("missing primary_output_checksum")
    if not input_.primary_reasoning or not input_.primary_reasoning.strip():
        failures.append("missing primary_reasoning")
    if not input_.draft_markdown or not input_.draft_markdown.strip():
        failures.append("missing draft_markdown")
    if input_.phase not in (ArtifactPhase.ANALYSIS.value, ArtifactPhase.PLANNING.value):
        failures.append(f"unknown phase {input_.phase!r}; must be 'analysis' or 'planning'")
    if not input_.job_id or not input_.job_id.strip():
        failures.append("missing job_id")
    if input_.stage_index < 1 or input_.stage_index > 3:
        failures.append(f"stage_index {input_.stage_index} out of range [1,3]")

    failures.extend(_check_forbidden_fields(input_, "ReviewerLLMInput"))
    return failures


def validate_reviewer_llm_output(output: ReviewerLLMOutput) -> list[str]:
    """Validate reviewer LLM output. Returns list of failures. Fail-closed.

    Reviewer validation fails closed when:
    - reviewer output missing or malformed
    - decision not in {accept, reject, request_revision}
    - confidence out of range
    - missing checksum fields
    """
    failures: list[str] = []

    if output.decision not in (
        ReviewerDecision.ACCEPT.value,
        ReviewerDecision.REJECT.value,
        ReviewerDecision.REQUEST_REVISION.value,
    ):
        failures.append(
            f"invalid decision {output.decision!r}; "
            f"must be accept, reject, or request_revision"
        )

    if not (0.0 <= output.confidence <= 1.0):
        failures.append(
            f"confidence {output.confidence} out of range [0.0, 1.0]"
        )

    if not output.reviewed_artifact_checksum or not output.reviewed_artifact_checksum.strip():
        failures.append("missing reviewed_artifact_checksum")
    if not output.reviewed_primary_output_checksum or not output.reviewed_primary_output_checksum.strip():
        failures.append("missing reviewed_primary_output_checksum")

    failures.extend(_check_forbidden_fields(output, "ReviewerLLMOutput"))
    return failures


# ── Checksum binding ───────────────────────────────────────────────────


class ChecksumBindingValidationError(ValueError):
    """Raised when checksum binding fails."""


def validate_checksum_binding(
    deterministic_artifact_checksum: str,
    primary_output_checksum: str,
    reviewer_output: ReviewerLLMOutput,
) -> list[str]:
    """Validate that reviewer output is checksum-bound to exact artifacts.

    Returns list of failures. Fail-closed.
    """
    failures: list[str] = []

    if reviewer_output.reviewed_artifact_checksum != deterministic_artifact_checksum:
        failures.append(
            f"checksum mismatch on deterministic artifact: "
            f"reviewer recorded {reviewer_output.reviewed_artifact_checksum!r} "
            f"but expected {deterministic_artifact_checksum!r}"
        )

    if reviewer_output.reviewed_primary_output_checksum != primary_output_checksum:
        failures.append(
            f"checksum mismatch on primary output: "
            f"reviewer recorded {reviewer_output.reviewed_primary_output_checksum!r} "
            f"but expected {primary_output_checksum!r}"
        )

    return failures


def validate_reviewed_output_contract(
    deterministic_artifact_checksum: str,
    primary_output_checksum: str,
    reviewer_output: ReviewerLLMOutput,
) -> ReviewerValidationResult:
    """Full fail-closed reviewer validation: output shape + checksum binding.

    Returns a ReviewerValidationResult with ok=False if:
    - reviewer output is malformed
    - reviewer rejects or requests revision
    - checksum mismatch
    - reviewer decision not bound to exact primary output
    """
    failures: list[str] = []

    output_failures = validate_reviewer_llm_output(reviewer_output)
    failures.extend(output_failures)

    if output_failures:
        return ReviewerValidationResult(
            ok=False,
            decision=reviewer_output.decision if reviewer_output else None,
            failures=tuple(failures),
            checksum_matched=False,
            deterministic_artifact_checksum=deterministic_artifact_checksum,
            primary_output_checksum=primary_output_checksum,
            reviewer_output_checksum=reviewer_output.reviewer_output_checksum if reviewer_output else "",
        )

    binding_failures = validate_checksum_binding(
        deterministic_artifact_checksum,
        primary_output_checksum,
        reviewer_output,
    )
    failures.extend(binding_failures)
    checksum_matched = len(binding_failures) == 0

    decision_ok = reviewer_output.decision == ReviewerDecision.ACCEPT.value

    if reviewer_output.decision == ReviewerDecision.REJECT.value:
        failures.append("reviewer rejected the output")
    elif reviewer_output.decision == ReviewerDecision.REQUEST_REVISION.value:
        failures.append("reviewer requested revision")

    ok = decision_ok and checksum_matched and len(failures) == 0

    return ReviewerValidationResult(
        ok=ok,
        decision=reviewer_output.decision,
        failures=tuple(failures),
        checksum_matched=checksum_matched,
        deterministic_artifact_checksum=deterministic_artifact_checksum,
        primary_output_checksum=primary_output_checksum,
        reviewer_output_checksum=reviewer_output.reviewer_output_checksum,
    )


# ── Forbidden field detection ──────────────────────────────────────────


def _check_forbidden_fields(obj: Any, label: str) -> list[str]:
    """Scan a dataclass instance for forbidden top-level fields.

    Returns list of failure messages if forbidden fields are found.
    """
    failures: list[str] = []
    if not hasattr(obj, "__dataclass_fields__"):
        return failures

    for field_name in obj.__dataclass_fields__:
        if field_name in _FORBIDDEN_TOP_LEVEL_KEYS:
            value = getattr(obj, field_name, None)
            if value is not None:
                failures.append(
                    f"{label} contains forbidden field {field_name!r}"
                )

    for field_name in obj.__dataclass_fields__:
        value = getattr(obj, field_name, None)
        if isinstance(value, dict):
            for key in value:
                for forbidden_substr in _FORBIDDEN_DICT_KEY_SUBSTRINGS:
                    if forbidden_substr in str(key).lower():
                        if _has_value(value[key]):
                            failures.append(
                                f"{label} field {field_name!r} contains "
                                f"forbidden dict key {key!r}"
                            )

    return failures


def _check_execution_instruction(output: PrimaryLLMOutput) -> list[str]:
    """Check primary LLM output for execution instructions.

    Returns list of failure messages.
    """
    failures: list[str] = []
    text = " ".join(
        [
            output.reasoning or "",
            output.recommended_next_step or "",
            output.draft_markdown or "",
        ]
    ).lower()

    execution_signals = [
        "execute command",
        "run command",
        "apply patch",
        "modify file",
        "write to disk",
        "delete file",
        "rm -rf",
        "sudo ",
    ]
    for signal in execution_signals:
        if signal in text:
            failures.append(
                f"primary LLM output contains execution instruction: {signal!r}"
            )
    return failures


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple, dict)) and len(value) == 0:
        return False
    return True


# ── Checksum helpers ───────────────────────────────────────────────────


def compute_primary_output_checksum(output: PrimaryLLMOutput) -> str:
    """Compute checksum for primary LLM output (without output_checksum field)."""
    payload = {
        "reasoning": output.reasoning,
        "risks": list(output.risks),
        "confidence": output.confidence,
        "recommended_next_step": output.recommended_next_step,
        "draft_markdown": output.draft_markdown,
        "machine_readable_metadata": output.machine_readable_metadata,
    }
    return sha256_canonical_json(payload)


def compute_reviewer_output_checksum(output: ReviewerLLMOutput) -> str:
    """Compute checksum for reviewer LLM output (without reviewer_output_checksum)."""
    payload = {
        "decision": output.decision,
        "notes": list(output.notes),
        "confidence": output.confidence,
        "risks": list(output.risks),
        "policy_concerns": list(output.policy_concerns),
        "reviewed_artifact_checksum": output.reviewed_artifact_checksum,
        "reviewed_primary_output_checksum": output.reviewed_primary_output_checksum,
        "review_dimensions": output.review_dimensions,
    }
    return sha256_canonical_json(payload)
