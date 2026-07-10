import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RepairInvestigationPanel } from "../app/migrations/[jobId]/RepairInvestigationPanel";
import type { V2RepairApplyCandidateResponse, V2RepairAttemptResponse } from "../lib/contracts";

const noop = async () => {};

function attempt(overrides: Partial<V2RepairAttemptResponse> = {}): V2RepairAttemptResponse {
  return {
    attempt_id: "repair-attempt-1",
    attempt_number: 1,
    attempt_source: "llm",
    attempt_checksum: "sha256:attempt",
    job_id: "job-1",
    stage_index: 1,
    command_id: "cmd-1",
    candidate_kind: "llm_unknown_family",
    applicability_status: "applicable",
    repair_workflow_state: "repair_candidate_ready",
    failure_summary: "Compilation failed in PaymentService",
    failing_command: "mvn test",
    failing_test: "PaymentServiceTest",
    exception: "cannot find symbol",
    stack_trace_preview: "PaymentService.java:42 cannot find symbol",
    log_artifact_references: { build_log: "build.log" },
    failure_evidence_checksum: "sha256:evidence",
    context_checksum: "sha256:context",
    source_evidence: [{ path: "src/main/java/PaymentService.java", checksum: "sha256:source", byte_length: 120 }],
    proposer_root_cause: "Missing compatibility method",
    proposer_strategy: "Add the bounded production adapter",
    proposer_confidence: 0.8,
    proposer_risks: ["behavioral_change"],
    exact_proposed_diff: "diff --git a/src/main/java/PaymentService.java b/src/main/java/PaymentService.java\n+fixed\n",
    diff_checksum: "sha256:diff",
    changed_files: ["src/main/java/PaymentService.java"],
    actual_touched_paths: ["src/main/java/PaymentService.java"],
    hard_gate_status: "passed",
    hard_gate_reason_codes: [],
    reviewer_outcome: "rejected",
    reviewer_availability: true,
    reviewer_risk_level: "HIGH",
    reviewer_reason_codes: ["business_semantics_unclear"],
    reviewer_summary: "Reviewer does not recommend this repair.",
    reviewer_recommended_action: "operator_review",
    reviewer_output_checksum: "sha256:review",
    reviewed_context_checksum: "sha256:context",
    reviewed_proposal_checksum: "sha256:proposal",
    reviewed_diff_checksum: "sha256:diff",
    artifact_references: { proposer_raw: "primary_raw_response.txt", reviewer_validated: "reviewer_validated_output.json" },
    advisory_warnings: ["business_semantics_unclear"],
    approval_mode_required: "reviewer_override_approval",
    operator_actions_available: ["request_corrected_proposal", "request_additional_context", "submit_manual_diff"],
    apply_enabled: false,
    resume_enabled: false,
    next_operator_action: "approve_or_remediate",
    current_checkpoint: "repair",
    created_at: "2026-07-10T00:00:00Z",
    ...overrides,
  };
}

function candidate(overrides: Partial<V2RepairApplyCandidateResponse> = {}): V2RepairApplyCandidateResponse {
  return {
    job_id: "job-1",
    stage_index: 1,
    repair_candidate_id: "candidate-1",
    candidate_kind: "llm_unknown_family",
    status: "read_only",
    family: "llm_unknown_family",
    patch_source: "llm_reviewed",
    policy_id: "generic_reviewed_llm_patch_v1",
    llm_source: "advisory_only",
    target_file: "src/main/java/PaymentService.java",
    pre_apply_checksum: "",
    target_file_checksum: "sha256:repo",
    patch_checksum: "sha256:diff",
    review_checksum: "sha256:review",
    proposal_checksum: "sha256:proposal",
    candidate_checksum: "sha256:candidate",
    approval_required: true,
    approval_mode_required: "reviewer_override_approval",
    reviewer_decision: "reject",
    reviewer_outcome: "rejected",
    reviewer_availability: true,
    reviewer_invocation_id: "review-invocation-1",
    reviewer_output_checksum: "sha256:review",
    approval_enabled: true,
    apply_enabled: false,
    sandbox_only: true,
    legacy_mutation_allowed: false,
    downstream_start_allowed: false,
    llm_can_apply: false,
    browser_can_supply_patch: false,
    verification_status: "not_started",
    rollback_status: "not_started",
    proof_artifact: "",
    created_at: "2026-07-10T00:00:00Z",
    ...overrides,
  };
}

function render(current: V2RepairAttemptResponse, currentCandidate: V2RepairApplyCandidateResponse | null = candidate(), history = [current]) {
  return renderToStaticMarkup(
    <RepairInvestigationPanel
      attempt={current}
      attempts={history}
      candidate={currentCandidate}
      busy={false}
      onApprove={noop}
      onApply={noop}
      onAction={noop}
    />
  );
}

describe("operator-governed repair investigation", () => {
  it("keeps a rejected proposal, exact diff, evidence, and reviewer artifacts visible", () => {
    const markup = render(attempt());
    expect(markup).toContain("Compilation failed in PaymentService");
    expect(markup).toContain("diff --git a/src/main/java/PaymentService.java");
    expect(markup).toContain("Reviewer does not recommend this repair");
    expect(markup).toContain("primary_raw_response.txt");
    expect(markup).toContain("Override reviewer and approve for sandbox");
    expect(markup).toContain("reviewer rejected this repair");
  });

  it("renders redacted display diffs as display-only while keeping the exact checksum visible", () => {
    const markup = render(attempt({
      exact_proposed_diff: "diff --git a/src/main/java/PaymentService.java b/src/main/java/PaymentService.java\n+[redacted-windows-path]\n",
      display_proposed_diff: "diff --git a/src/main/java/PaymentService.java b/src/main/java/PaymentService.java\n+[redacted-windows-path]\n",
      display_diff_redacted: true,
      display_diff_status: "redacted",
      exact_diff_checksum: "sha256:exact-diff",
    }));

    expect(markup).toContain("Public display diff was redacted");
    expect(markup).toContain("Apply uses the exact backend-persisted diff");
    expect(markup).toContain("Exact diff checksum: sha256:exact-diff");
    expect(markup).toContain("[redacted-windows-path]");
  });

  it("keeps an unavailable review visible and offers an explicit override form", () => {
    const current = attempt({ reviewer_outcome: "unavailable", reviewer_availability: false, reviewer_output_checksum: "", reviewer_summary: "" });
    const markup = render(current, candidate({ reviewer_decision: "unavailable", reviewer_outcome: "unavailable", reviewer_availability: false, reviewer_output_checksum: "", review_checksum: "" }));
    expect(markup).toContain("Outcome: unavailable");
    expect(markup).toContain("reviewer was unavailable");
    expect(markup).toContain("Override reviewer and approve for sandbox");
  });

  it("renders normal and acknowledged-risk approval modes distinctly", () => {
    const accepted = render(
      attempt({ reviewer_outcome: "accepted", approval_mode_required: "normal_approval" }),
      candidate({ reviewer_decision: "accept", reviewer_outcome: "accepted", approval_mode_required: "normal_approval" }),
    );
    expect(accepted).toContain("Approve for sandbox");
    expect(accepted).not.toContain("Operator approval justification");

    const concerns = render(
      attempt({ reviewer_outcome: "accepted_with_concerns", approval_mode_required: "acknowledged_risk_approval" }),
      candidate({ reviewer_decision: "revise", reviewer_outcome: "accepted_with_concerns", approval_mode_required: "acknowledged_risk_approval" }),
    );
    expect(concerns).toContain("accepted with concerns");
    expect(concerns).toContain("Operator approval justification");
    expect(concerns).toContain("Approve with acknowledged risks");
    expect(concerns).toContain("disabled");
  });

  it("never offers apply or override for a hard-gate-blocked exact diff", () => {
    const markup = render(
      attempt({ applicability_status: "blocked", candidate_kind: "blocked_attempt", hard_gate_status: "blocked", hard_gate_reason_codes: ["path_traversal"], approval_mode_required: "" }),
      null,
    );
    expect(markup).toContain("path_traversal");
    expect(markup).toContain("Apply and reviewer override are unavailable");
    expect(markup).not.toContain("Override reviewer and approve for sandbox");
    expect(markup).not.toContain("Apply approved repair to sandbox");
    expect(markup).toContain("Request corrected proposal");
    expect(markup).toContain("Submit manual Git diff");
  });

  it("shows apply and checkpoint resume only when backend projections enable them", () => {
    const disabled = render(attempt(), candidate());
    expect(disabled).not.toContain("Apply approved repair to sandbox");
    expect(disabled).not.toContain("Resume from repair checkpoint");

    const enabled = render(
      attempt({ apply_enabled: true, resume_enabled: true }),
      candidate({ status: "approved", approval_enabled: false, apply_enabled: true }),
    );
    expect(enabled).toContain("Apply approved repair to sandbox");
    expect(enabled).toContain("Resume from repair checkpoint");
  });

  it("keeps previous attempts, action inputs, and sandbox authority notices visible", () => {
    const current = attempt({ attempt_id: "repair-attempt-2", attempt_number: 2, previous_attempt_id: "repair-attempt-1" });
    const markup = render(current, candidate(), [attempt(), current]);
    expect(markup).toContain("View previous attempts (1)");
    expect(markup).toContain("Corrected proposal guidance");
    expect(markup).toContain("Additional context request");
    expect(markup).toContain("Manual Git diff");
    expect(markup).toContain("Changes apply only to the sandbox");
    expect(markup).toContain("rollback occurs on verification failure");
  });
});
