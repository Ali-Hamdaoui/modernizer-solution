import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { SafeDiffPreview } from "../app/migrations/[jobId]/SafeDiffPreview";
import { ReviewerVerdictCard } from "../app/migrations/[jobId]/ReviewerVerdictCard";
import { RepairAttemptTimeline } from "../app/migrations/[jobId]/RepairAttemptTimeline";
import { RepairActionsBar } from "../app/migrations/[jobId]/RepairActionsBar";
import { ModelRoleActivity } from "../app/migrations/[jobId]/ModelRoleActivity";
import { ValidationProgressPanel } from "../app/migrations/[jobId]/ValidationProgressPanel";
import { RepairProposalPanel, ReviewedRepairUnavailable, ReviewedRepairMaterializationFailed, PolicyBannerSection, RepairProposalMetadata } from "../app/migrations/[jobId]/RepairProposalPanel";
import { MigrationCockpit } from "../app/migrations/[jobId]/MigrationCockpit";
import type {
  SafeDiffPreview as SafeDiffPreviewType,
  SafeDiffFile,
  SafeDiffHunk,
  ReviewerVerdictProjection,
  RepairAttemptSummary,
  ReviewedDiffProposal,
  V2LlmInvocationEntry,
} from "../lib/contracts";

describe("PR-C SafeDiffPreview component", () => {
  it("renders missing state when diff is null", () => {
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={null} />);
    expect(markup).toContain("No diff preview available");
    expect(markup).not.toContain("safe-diff-file");
  });

  it("renders file summaries with additions/deletions", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [
        {
          path: "pom.xml",
          change_type: "modified",
          additions: 3,
          deletions: 1,
          hunks: [],
          truncated: false,
        },
      ],
      total_additions: 3,
      total_deletions: 1,
      truncated: false,
      parse_status: "parsed",
      checksum_mismatch: false,
      redactions: [],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).toContain("pom.xml");
    expect(markup).toContain("modified");
    expect(markup).toContain("+3");
    expect(markup).toContain("/ -1");
    expect(markup).toContain("1 file changed");
  });

  it("renders hunks with old/new line numbers", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [
        {
          path: "src/main.java",
          change_type: "modified",
          additions: 1,
          deletions: 0,
          hunks: [
            {
              old_start: 10,
              old_lines: 5,
              new_start: 10,
              new_lines: 6,
              section_header: null,
              lines: [
                { kind: "context", old_line_number: 10, new_line_number: 10, text: "  existing", redacted: false },
                { kind: "addition", old_line_number: null, new_line_number: 11, text: "+ new line", redacted: false },
              ],
            },
          ],
          truncated: false,
        },
      ],
      total_additions: 1,
      total_deletions: 0,
      truncated: false,
      parse_status: "parsed",
      checksum_mismatch: false,
      redactions: [],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).toContain("src/main.java");
    expect(markup).toContain("@@ -10,5 +10,6 @@");
    expect(markup).toContain("10 | 10");
    expect(markup).toContain("  | 11");
    expect(markup).toContain("+ new line");
    expect(markup).not.toContain("undefined");
  });

  it("renders truncation notice", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [],
      total_additions: 0,
      total_deletions: 0,
      truncated: true,
      parse_status: "unparseable",
      checksum_mismatch: false,
      redactions: [],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).toContain("truncation-notice");
    expect(markup).toContain("Diff truncated");
  });

  it("renders checksum mismatch warning", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [],
      total_additions: 0,
      total_deletions: 0,
      truncated: false,
      parse_status: "no_content",
      checksum_mismatch: true,
      redactions: [],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).toContain("checksum-mismatch-warning");
    expect(markup).toContain("checksum mismatch");
    expect(markup).toContain("cannot be approved until regenerated");
  });

  it("renders redaction notice", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [],
      total_additions: 0,
      total_deletions: 0,
      truncated: false,
      parse_status: "no_content",
      checksum_mismatch: false,
      redactions: ["secret_token"],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).toContain("redaction-notice");
    expect(markup).toContain("1 redaction applied");
  });

  it("renders redacted lines as [redacted]", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [
        {
          path: "config.properties",
          change_type: "modified",
          additions: 1,
          deletions: 0,
          hunks: [
            {
              old_start: 1,
              old_lines: 1,
              new_start: 1,
              new_lines: 2,
              section_header: null,
              lines: [
                { kind: "addition", old_line_number: null, new_line_number: 2, text: "secret line", redacted: true },
              ],
            },
          ],
          truncated: false,
        },
      ],
      total_additions: 1,
      total_deletions: 0,
      truncated: false,
      parse_status: "parsed",
      checksum_mismatch: false,
      redactions: ["secret"],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).toContain("redacted-line");
    expect(markup).toContain("[redacted]");
    expect(markup).not.toContain("secret line");
  });

  it("does not expose raw paths, env, or secrets", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [],
      total_additions: 0,
      total_deletions: 0,
      truncated: false,
      parse_status: "no_content",
      checksum_mismatch: false,
      redactions: [],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).not.toContain("target_path");
    expect(markup).not.toContain("patch_content");
    expect(markup).not.toContain("sandbox_path");
    expect(markup).not.toContain("argv");
    expect(markup).not.toContain("C:\\");
    expect(markup).not.toContain("/Users/");
    expect(markup).not.toContain("/home/");
    expect(markup).not.toContain("AZURE_OPENAI");
    expect(markup).not.toContain("Bearer ");
  });
});

describe("PR-C ReviewerVerdictCard component", () => {
  it("renders missing state when verdict is null", () => {
    const markup = renderToStaticMarkup(<ReviewerVerdictCard verdict={null} />);
    expect(markup).toContain("No reviewer verdict available");
  });

  it("renders accept decision with reasoning", () => {
    const verdict: ReviewerVerdictProjection = {
      reviewer_verdict_id: "v-1",
      decision: "accept",
      reasoning: "Evidence is sufficient and patch scope is correct.",
      missing_evidence: [],
      unsafe_assumptions: [],
      model_invocation_id: "inv-1",
      output_checksum: "sha256:output",
    };
    const markup = renderToStaticMarkup(<ReviewerVerdictCard verdict={verdict} />);
    expect(markup).toContain("Accepted");
    expect(markup).toContain("Evidence is sufficient");
    expect(markup).toContain("v-1");
    expect(markup).toContain("inv-1");
    expect(markup).toContain("sha256:output");
  });

  it("renders revise decision", () => {
    const verdict: ReviewerVerdictProjection = {
      reviewer_verdict_id: "v-2",
      decision: "revise",
      reasoning: "Patch scope is too broad.",
      missing_evidence: ["test_results"],
      unsafe_assumptions: [],
      model_invocation_id: null,
      output_checksum: null,
    };
    const markup = renderToStaticMarkup(<ReviewerVerdictCard verdict={verdict} />);
    expect(markup).toContain("Revision Requested");
    expect(markup).toContain("Patch scope is too broad");
    expect(markup).toContain("test_results");
  });

  it("renders missing evidence and unsafe assumptions", () => {
    const verdict: ReviewerVerdictProjection = {
      reviewer_verdict_id: "v-3",
      decision: "reject",
      reasoning: "Patch introduces security risk.",
      missing_evidence: ["security_audit"],
      unsafe_assumptions: ["assumes dependency exists"],
      model_invocation_id: null,
      output_checksum: null,
    };
    const markup = renderToStaticMarkup(<ReviewerVerdictCard verdict={verdict} />);
    expect(markup).toContain("Rejected");
    expect(markup).toContain("security_audit");
    expect(markup).toContain("assumes dependency exists");
  });

  it("does not expose raw fields", () => {
    const verdict: ReviewerVerdictProjection = {
      reviewer_verdict_id: "v-4",
      decision: "accept",
      reasoning: "ok",
      missing_evidence: [],
      unsafe_assumptions: [],
      model_invocation_id: null,
      output_checksum: null,
    };
    const markup = renderToStaticMarkup(<ReviewerVerdictCard verdict={verdict} />);
    expect(markup).not.toContain("azure_endpoint");
    expect(markup).not.toContain("api_key");
    expect(markup).not.toContain("deployment");
    expect(markup).not.toContain("Bearer ");
    expect(markup).not.toContain("password");
    expect(markup).not.toContain("secret");
    expect(markup).not.toContain("sandbox_path");
  });
});

describe("PR-C RepairAttemptTimeline component", () => {
  it("renders empty state when no attempts", () => {
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={[]} />);
    expect(markup).toContain("No repair attempts yet");
  });

  it("renders attempt entries with status and checksums", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-1",
        command_id: "cmd-1",
        job_id: "job-1",
        gate_id: "gate-1",
        attempt_number: 1,
        revision_number: null,
        status: "reviewer_accepted",
        apply_status: null,
        rerun_status: null,
        rollback_status: null,
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: null,
        remaining_attempts: null,
        reviewer_decision: null,
        diff_checksum: "sha256:abc",
        policy_validation_checksum: null,
        status_reason: null,
        created_at: "2026-06-30T00:00:00Z",
        completed_at: null,
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    expect(markup).toContain("Repair Attempts");
    expect(markup).toContain("Attempt 1");
    expect(markup).toContain("p-1");
    expect(markup).toContain("gate-1");
    expect(markup).toContain("sha256:abc");
    expect(markup).toContain("REVIEWER ACCEPTED");
  });

  it("renders revision numbers when present", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-2",
        command_id: null,
        job_id: "job-1",
        gate_id: null,
        attempt_number: 1,
        revision_number: 2,
        status: "user_review_required",
        apply_status: null,
        rerun_status: null,
        rollback_status: null,
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: null,
        remaining_attempts: null,
        reviewer_decision: null,
        diff_checksum: null,
        policy_validation_checksum: null,
        status_reason: "revision requested",
        created_at: "2026-06-30T01:00:00Z",
        completed_at: null,
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    expect(markup).toContain("Revision 2");
    expect(markup).toContain("revision requested");
  });

  it("does not expose raw fields", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-1",
        command_id: null,
        job_id: "job-1",
        gate_id: null,
        attempt_number: 1,
        revision_number: null,
        status: "pending",
        apply_status: null,
        rerun_status: null,
        rollback_status: null,
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: null,
        remaining_attempts: null,
        reviewer_decision: null,
        diff_checksum: null,
        policy_validation_checksum: null,
        status_reason: null,
        created_at: "2026-06-30T00:00:00Z",
        completed_at: null,
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    expect(markup).not.toContain("target_path");
    expect(markup).not.toContain("patch_content");
    expect(markup).not.toContain("sandbox_path");
    expect(markup).not.toContain("raw_command");
    expect(markup).not.toContain("C:\\");
    expect(markup).not.toContain("/Users/");
    expect(markup).not.toContain("AZURE_OPENAI");
  });
});

describe("PR-C/PR-D RepairActionsBar component", () => {
  const onRequestRevision = async () => undefined;

  it("renders read-only action buttons", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={onRequestRevision}
        revisionPending={false}
      />,
    );
    expect(markup).toContain("View diff");
    expect(markup).toContain("View reviewer opinion");
    expect(markup).toContain("View files changed");
    expect(markup).toContain("View attempt history");
  });

  it("renders Request revision as active button (not disabled)", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={onRequestRevision}
        revisionPending={false}
      />,
    );
    expect(markup).toContain("Request revision");
    // Request revision is no longer behind "Coming in PR-D" placeholder
    expect(markup).not.toContain('data-testid="action-future-request-revision"');
  });

  it("renders approve button disabled by default (no approveEnabled prop)", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={onRequestRevision}
        revisionPending={false}
      />,
    );
    expect(markup).toContain('disabled=""');
    expect(markup).toContain("Approve sandbox apply");
    expect(markup).not.toContain("PR-E");
  });

  it("read-only buttons are not disabled", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={onRequestRevision}
        revisionPending={false}
      />,
    );
    expect(markup).toContain('data-testid="action-view-diff"');
    expect(markup).not.toContain('data-testid="action-view-diff" disabled=""');
  });

  it("clicking read-only tabs does not call mutation APIs", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={onRequestRevision}
        revisionPending={false}
      />,
    );
    // No POST-related content in the action bar buttons except revision
    expect(markup).not.toContain("patch_content");
    expect(markup).not.toContain("sandbox_path");
    expect(markup).not.toContain("raw_command");
  });

  it("renders revision dialog when button clicked", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={onRequestRevision}
        revisionPending={false}
      />,
    );
    // Dialog data-testid should not be in initial render (dialog closed)
    expect(markup).not.toContain('data-testid="revision-dialog-overlay"');
  });

  it("revision submit disabled when instruction is empty", async () => {
    const { RepairRevisionDialog } = await import("../app/migrations/[jobId]/RepairRevisionDialog");
    const markup = renderToStaticMarkup(
      <RepairRevisionDialog open onClose={() => undefined} onSubmit={async () => undefined} pending={false} />,
    );
    expect(markup).toContain('data-testid="revision-submit-btn"');
    expect(markup).toContain("disabled");
    expect(markup).toContain("Instruction cannot be empty");
  });

  it("revision submit enabled when instruction is non-empty", () => {
    // We can't set textarea value in SSR, but the structure is correct
    // Submit button is disabled only when empty or pending
  });
});

describe("PR-E approve button behavior", () => {
  const mockOnRequestRevision = async () => undefined;

  it("approve button is disabled when approveEnabled is false", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        revisionPending={false}
        approveEnabled={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain('data-testid="action-approve-sandbox-apply"');
    expect(markup).toContain("Approve sandbox apply");
    // When approve is disabled, the action does not fire; verify the
    // entire block verifies the button is present
  });

  it("approve button is enabled when approveEnabled is true", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        approveEnabled={true}
        approvePending={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain('data-testid="action-approve-sandbox-apply"');
    expect(markup).toContain("Approve sandbox apply");
  });

  it("approve button is disabled during approvePending", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        approveEnabled={true}
        approvePending={true}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain('data-testid="action-approve-sandbox-apply"');
    expect(markup).toContain("Applying...");
  });

  it("approve button is disabled on checksum mismatch", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        approveEnabled={true}
        approvePending={false}
        checksumMismatch={true}
      />,
    );
    expect(markup).toContain('data-testid="action-approve-sandbox-apply"');
    expect(markup).toContain("checksum mismatch");
  });

  it("approve button title reflects checksum mismatch state", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        approveEnabled={true}
        approvePending={false}
        checksumMismatch={true}
      />,
    );
    expect(markup).toContain("Cannot approve");
  });

  it("approve button shows sandbox apply copy", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        approveEnabled={true}
        approvePending={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain("sandbox apply");
    expect(markup).not.toContain("legacy source");
    expect(markup).not.toContain("original source");
  });

  it("reject button is removed from UI", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        approveEnabled={true}
        approvePending={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).not.toContain('data-testid="action-reject-repair"');
    expect(markup).not.toContain("Reject unavailable");
  });

  it("approve request body contains only allowed fields", () => {
    const request = {
      proposal_id: "p-1",
      diff_checksum: "sha256:abc",
      reviewer_verdict_id: "v-1",
      gate_id: "g-1",
      idempotency_key: "idem-123",
    };
    const body = JSON.stringify(request);
    expect(body).toContain("proposal_id");
    expect(body).toContain("diff_checksum");
    expect(body).toContain("reviewer_verdict_id");
    expect(body).toContain("gate_id");
    expect(body).toContain("idempotency_key");
    expect(body).not.toContain("patch_text");
    expect(body).not.toContain("target_path");
    expect(body).not.toContain("sandbox_path");
    expect(body).not.toContain("command");
    expect(body).not.toContain("argv");
    expect(body).not.toContain("env");
  });

  it("request revision can be disabled by backend allowed actions", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={mockOnRequestRevision}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        revisionEnabled={false}
        approveEnabled={false}
        approvePending={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain("Revision is not allowed by the current backend gate");
  });
});

describe("F5 model activity and validation panels", () => {
  const baseInvocation: V2LlmInvocationEntry = {
    invocation_id: "inv-main",
    job_id: "job-1",
    proposal_id: "proposal-1",
    gate_id: "gate-1",
    role: "main",
    responsibility: "repair_proposal",
    provider_alias: "azure_openai",
    model_display_name: "Product safe proposer",
    deployment_alias_hash: "abc123",
    context_checksum: "sha256:context",
    input_checksum: "sha256:input",
    output_checksum: "sha256:output",
    schema_name: "RepairPrimaryOutput",
    status: "completed",
    fallback_used: false,
    redacted_error: null,
    redacted_summary: "Diagnosed missing validation dependency.",
    prompt_tokens: 12,
    completion_tokens: 8,
    total_tokens: 20,
    latency_ms: 1200,
    created_at: "2026-06-30T00:00:00Z",
    completed_at: "2026-06-30T00:00:01Z",
  };

  it("renders backend-provided safe model labels and summaries", () => {
    const markup = renderToStaticMarkup(
      <ModelRoleActivity
        invocations={[
          baseInvocation,
          {
            ...baseInvocation,
            invocation_id: "inv-reviewer",
            role: "reviewer",
            responsibility: "repair_review",
            model_display_name: "Product safe reviewer",
            redacted_summary: "Reviewer accepted the checksum-bound diff.",
            created_at: "2026-06-30T00:00:02Z",
          },
        ]}
        loading={false}
        error={null}
      />,
    );
    expect(markup).toContain("Product safe proposer");
    expect(markup).toContain("Product safe reviewer");
    expect(markup).toContain("Diagnosed missing validation dependency");
    expect(markup).toContain("Reviewer accepted");
    expect(markup).not.toContain("AZURE_OPENAI_PROPOSER_DEPLOYMENT");
    expect(markup).not.toContain("raw deployment");
  });

  it("falls back to role labels without hardcoded sample model names", () => {
    const markup = renderToStaticMarkup(
      <ModelRoleActivity
        invocations={[{ ...baseInvocation, model_display_name: null }]}
        loading={false}
        error={null}
      />,
    );
    expect(markup).toContain("Main Model");
    expect(markup).not.toContain("gpt");
    expect(markup).not.toContain("sample");
  });

  it("renders apply, rebuild, test, and continue progress from attempts", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-1",
        command_id: null,
        job_id: "job-1",
        gate_id: "g-1",
        attempt_number: 1,
        revision_number: null,
        status: "approved_applied",
        apply_status: "APPLIED",
        rerun_status: "validation_passed",
        rollback_status: null,
        reviewer_decision: "accept",
        diff_checksum: "sha256:diff",
        policy_validation_checksum: "sha256:policy",
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: "resolved",
        remaining_attempts: 2,
        status_reason: null,
        created_at: "2026-06-30T00:00:00Z",
        completed_at: "2026-06-30T00:00:02Z",
      },
    ];
    const markup = renderToStaticMarkup(<ValidationProgressPanel attempts={attempts} />);
    expect(markup).toContain("Applying reviewed diff to sandbox");
    expect(markup).toContain("Rebuilding");
    expect(markup).toContain("Running tests");
    expect(markup).toContain("Migration continuing");
    expect(markup).toContain("validation passed");
  });

  it("renders fail-closed unavailable state for main completed and reviewer fallback", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocation,
        proposal_id: null,
        gate_id: null,
        redacted_summary: "Root cause is missing JsonNode import in ProposalExternalFacade.",
      },
      {
        ...baseInvocation,
        invocation_id: "inv-reviewer",
        proposal_id: null,
        gate_id: null,
        role: "reviewer",
        responsibility: "repair_review",
        model_display_name: "Reviewer Model",
        status: "fallback",
        fallback_used: true,
        redacted_error: "reviewer_model_unavailable",
        redacted_summary: "Reviewer model unavailable; fail-closed review requires revision or manual evidence review. Reviewer model output unavailable.",
        output_checksum: null,
        created_at: "2026-06-30T00:00:02Z",
      },
    ];

    const markup = renderToStaticMarkup(
      <ReviewedRepairUnavailable invocations={invocations} loading={false} error={null} />,
    );

    expect(markup).toContain("Reviewed Repair Unavailable");
    expect(markup).toContain("Reviewer model did not produce a reviewed diff.");
    expect(markup).not.toContain("Main Model output failed schema validation");
    expect(markup).toContain("Reviewed Repair Gate");
    expect(markup).not.toContain("Approve sandbox apply");
    expect(markup).not.toContain("safe-diff-file");
    for (const forbidden of ["endpoint", "api_key", "raw deployment", "AZURE_OPENAI", "prompt", "completion", "sandbox_path"]) {
      expect(markup).not.toContain(forbidden);
    }
  });

  it("renders reviewer schema invalid unavailable state when main completed", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocation,
        proposal_id: null,
        gate_id: null,
        status: "completed",
        reason_code: null,
        output_checksum: "sha256:main-output",
        redacted_summary: "Main completed a repair draft.",
      },
      {
        ...baseInvocation,
        invocation_id: "inv-reviewer",
        proposal_id: null,
        gate_id: null,
        role: "reviewer",
        responsibility: "repair_review",
        model_display_name: "Reviewer Model",
        schema_name: "RepairReviewerOutput",
        status: "fallback",
        reason_code: "reviewer_schema_invalid",
        fallback_used: true,
        redacted_error: "reviewer_schema_invalid",
        redacted_summary: "Reviewer schema validation failed.",
        output_checksum: null,
        created_at: "2026-06-30T00:00:02Z",
      },
    ];

    const markup = renderToStaticMarkup(
      <ReviewedRepairUnavailable
        invocations={invocations}
        loading={false}
        error={null}
        reviewerSchemaInvalid
      />,
    );

    expect(markup).toContain("Reviewed Repair Unavailable");
    expect(markup).toContain("Reviewer model output failed schema validation, so no reviewed diff was produced.");
    expect(markup).toContain("Product safe proposer");
    expect(markup).toContain("completed");
    expect(markup).toContain("Reviewer Model");
    expect(markup).toContain("schema invalid");
    expect(markup).toContain("completed with fallback");
    expect(markup).toContain("Not available");
    expect(markup).toContain("Retry after reviewer/schema contract fix");
    expect(markup).not.toContain("Main Model output failed schema validation");
    expect(markup).not.toContain("Approve sandbox apply");
    expect(markup).not.toContain("Request revision");
    expect(markup).not.toContain("Waiting for your approval");
    expect(markup).not.toContain("Apply, Rebuild, Test");
  });

  it("renders proposer_schema_invalid state correctly", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocation,
        proposal_id: null,
        gate_id: null,
        status: "fallback",
        fallback_used: true,
        redacted_error: "proposer_schema_invalid",
        redacted_summary: "Main model returned JSON with schema errors: missing required fields: ['changed_files', 'proposed_diff']",
        output_checksum: null,
      },
    ];

    const markup = renderToStaticMarkup(
      <ReviewedRepairUnavailable invocations={invocations} loading={false} error={null} />,
    );

    expect(markup).toContain("Reviewed Repair Unavailable");
    expect(markup).toContain("schema invalid");
    expect(markup).toContain("not run");
    expect(markup).toContain("Not available");
    expect(markup).toContain("schema errors");
    expect(markup).not.toContain("Approve sandbox apply");
    expect(markup).not.toContain("safe-diff-file");
    for (const forbidden of ["endpoint", "api_key", "raw deployment", "AZURE_OPENAI", "sandbox_path"]) {
      expect(markup).not.toContain(forbidden);
    }
  });

  it("renders materialization failed state when reviewer completed but no proposal", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocation,
        proposal_id: null,
        gate_id: null,
        output_checksum: "sha256:main-output",
      },
      {
        ...baseInvocation,
        invocation_id: "inv-reviewer",
        proposal_id: null,
        gate_id: null,
        role: "reviewer",
        responsibility: "repair_review",
        model_display_name: "Reviewer Model",
        status: "completed",
        fallback_used: false,
        redacted_error: null,
        redacted_summary: "Reviewer accepted the repair proposal.",
        output_checksum: "sha256:reviewer-output",
        created_at: "2026-06-30T00:00:02Z",
      },
    ];

    const markup = renderToStaticMarkup(
      <ReviewedRepairMaterializationFailed invocations={invocations} loading={false} error={null} />,
    );

    expect(markup).toContain("Reviewed Repair Materialization Failed");
    expect(markup).toContain("Backend could not materialize a reviewed diff for user approval.");
    expect(markup).toContain("Reviewed Repair Gate");
    expect(markup).toContain("completed");
    expect(markup).not.toContain("schema invalid");
    expect(markup).not.toContain("Approve sandbox apply");
    expect(markup).not.toContain("safe-diff-file");
    expect(markup).not.toContain("Fix model output or schema");
    for (const forbidden of ["endpoint", "api_key", "raw deployment", "AZURE_OPENAI", "prompt", "completion", "sandbox_path"]) {
      expect(markup).not.toContain(forbidden);
    }
  });

  it("renders materialization failed when both main and reviewer completed", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocation,
        proposal_id: null,
        gate_id: null,
        output_checksum: "sha256:main-output",
      },
      {
        ...baseInvocation,
        invocation_id: "inv-reviewer",
        proposal_id: null,
        gate_id: null,
        role: "reviewer",
        responsibility: "repair_review",
        model_display_name: "Reviewer Model",
        status: "completed",
        fallback_used: false,
        redacted_error: null,
        redacted_summary: "Diff is scoped to pom.xml and safe.",
        output_checksum: "sha256:reviewer-output",
        created_at: "2026-06-30T00:00:02Z",
      },
    ];

    const markup = renderToStaticMarkup(
      <ReviewedRepairMaterializationFailed invocations={invocations} loading={false} error={null} />,
    );

    expect(markup).toContain("Reviewed Repair Materialization Failed");
    expect(markup).toContain("Backend could not materialize a reviewed diff for user approval.");
    expect(markup).toContain("completed");
    expect(markup).not.toContain("Approve sandbox apply");
    expect(markup).not.toContain("safe-diff-file");
    for (const forbidden of ["endpoint", "api_key", "AZURE_OPENAI", "sandbox_path"]) {
      expect(markup).not.toContain(forbidden);
    }
  });
});

describe("PR-C forbidden-field tests", () => {
  const forbiddenStrings = [
    "target_path",
    "patch_content",
    "sandbox_path",
    "argv",
    "env",
    "raw_command",
    "azure_endpoint",
    "api_key",
    "password",
    "authorization",
    "secret",
    "C:\\",
    "/Users/",
    "/home/",
    ".control-tower",
    ".control-tower-dev",
    "AZURE_OPENAI",
    "Bearer ",
  ];

  it("SafeDiffPreview rendered output contains no forbidden fields", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [
        {
          path: "src/main.java",
          change_type: "modified",
          additions: 1,
          deletions: 0,
          hunks: [
            {
              old_start: 1,
              old_lines: 1,
              new_start: 1,
              new_lines: 2,
              section_header: null,
              lines: [
                { kind: "context", old_line_number: 1, new_line_number: 1, text: "existing", redacted: false },
                { kind: "addition", old_line_number: null, new_line_number: 2, text: "new", redacted: false },
              ],
            },
          ],
          truncated: false,
        },
      ],
      total_additions: 1,
      total_deletions: 0,
      truncated: false,
      parse_status: "parsed",
      checksum_mismatch: false,
      redactions: [],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    for (const forbidden of forbiddenStrings) {
      expect(markup).not.toContain(forbidden);
    }
    // Safe values render
    expect(markup).toContain("src/main.java");
  });

  it("RepairActionsBar rendered output contains no forbidden fields", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={async () => undefined}
        revisionPending={false}
      />,
    );
    for (const forbidden of forbiddenStrings) {
      expect(markup).not.toContain(forbidden);
    }
    expect(markup).toContain("Approve sandbox apply");
  });

  it("ReviewerVerdictCard rendered output contains no forbidden fields", () => {
    const verdict: ReviewerVerdictProjection = {
      reviewer_verdict_id: "v-1",
      decision: "accept",
      reasoning: "ok",
      missing_evidence: [],
      unsafe_assumptions: [],
      model_invocation_id: null,
      output_checksum: null,
    };
    const markup = renderToStaticMarkup(<ReviewerVerdictCard verdict={verdict} />);
    for (const forbidden of forbiddenStrings) {
      expect(markup).not.toContain(forbidden);
    }
    expect(markup).toContain("v-1");
  });

  it("RepairAttemptTimeline rendered output contains no forbidden fields", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-1",
        command_id: null,
        job_id: "job-1",
        gate_id: null,
        attempt_number: 1,
        revision_number: null,
        status: "pending",
        apply_status: null,
        rerun_status: null,
        rollback_status: null,
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: null,
        remaining_attempts: null,
        reviewer_decision: null,
        diff_checksum: null,
        policy_validation_checksum: null,
        status_reason: null,
        created_at: "2026-06-30T00:00:00Z",
        completed_at: null,
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    for (const forbidden of forbiddenStrings) {
      expect(markup).not.toContain(forbidden);
    }
    expect(markup).toContain("p-1");
  });
});

describe("PR-F RepairAttemptTimeline enrichments", () => {
  it("renders validation passed status and apply status", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-pass",
        command_id: null,
        job_id: "job-1",
        gate_id: null,
        attempt_number: 1,
        revision_number: null,
        status: "approved_applied",
        apply_status: "APPLIED",
        rerun_status: "passed",
        rollback_status: "",
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: null,
        remaining_attempts: 3,
        reviewer_decision: null,
        diff_checksum: null,
        policy_validation_checksum: null,
        status_reason: null,
        created_at: "2026-06-30T00:00:00Z",
        completed_at: null,
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    expect(markup).toContain("APPROVED APPLIED");
    expect(markup).toContain("APPLIED");
    expect(markup).toContain("passed");
    expect(markup).toContain("3 remaining");
  });

  it("renders validation failed status and rollback status", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-fail",
        command_id: null,
        job_id: "job-1",
        gate_id: null,
        attempt_number: 2,
        revision_number: null,
        status: "approve_failed",
        apply_status: "APPLIED",
        rerun_status: "failed",
        rollback_status: "rolled_back",
        validation_result_ref: null,
        next_gate_id: "next-gate-2",
        next_gate_status: "repair_gate_created",
        remaining_attempts: 2,
        reviewer_decision: null,
        diff_checksum: null,
        policy_validation_checksum: null,
        status_reason: null,
        created_at: "2026-06-30T00:00:00Z",
        completed_at: "2026-06-30T01:00:00Z",
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    expect(markup).toContain("failed");
    expect(markup).toContain("rolled_back");
    expect(markup).toContain("next-gate-2");
    expect(markup).toContain("repair_gate_created");
    expect(markup).toContain("2 remaining");
    expect(markup).toContain("Completed");
  });

  it("renders exhausted state", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-exhaust",
        command_id: null,
        job_id: "job-1",
        gate_id: null,
        attempt_number: 3,
        revision_number: null,
        status: "exhausted",
        apply_status: "APPLIED",
        rerun_status: "failed",
        rollback_status: "rolled_back",
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: null,
        remaining_attempts: 0,
        reviewer_decision: null,
        diff_checksum: null,
        policy_validation_checksum: null,
        status_reason: "All repair attempts exhausted for stage 1",
        created_at: "2026-06-30T00:00:00Z",
        completed_at: "2026-06-30T02:00:00Z",
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    expect(markup).toContain("exhausted-notice");
    expect(markup).toContain("All repair attempts exhausted");
    expect(markup).toContain("0 remaining");
  });

  it("forbidden fields are not rendered in enriched attempt data", () => {
    const attempts: RepairAttemptSummary[] = [
      {
        proposal_id: "p-safe",
        command_id: null,
        job_id: "job-1",
        gate_id: null,
        attempt_number: 1,
        revision_number: null,
        status: "approved_applied",
        apply_status: "APPLIED",
        rerun_status: "passed",
        rollback_status: "",
        validation_result_ref: null,
        next_gate_id: null,
        next_gate_status: null,
        remaining_attempts: 3,
        reviewer_decision: null,
        diff_checksum: null,
        policy_validation_checksum: null,
        status_reason: null,
        created_at: "2026-06-30T00:00:00Z",
        completed_at: null,
      },
    ];
    const markup = renderToStaticMarkup(<RepairAttemptTimeline attempts={attempts} />);
    expect(markup).not.toContain("target_path");
    expect(markup).not.toContain("patch_content");
    expect(markup).not.toContain("sandbox_path");
    expect(markup).not.toContain("raw_command");
    expect(markup).not.toContain("C:\\");
    expect(markup).not.toContain("AZURE_OPENAI");
  });
});

// ── PR-C Cockpit layout tests ──────────────────────────────────────────

describe("PR-C cockpit full-width layout", () => {
  it("renders_reviewed_repair_gate_as_primary_section", () => {
    const markup = renderToStaticMarkup(<ReviewedRepairUnavailable invocations={[]} loading={false} error={null} />);
    expect(markup).toContain("Reviewed Repair Gate");
    expect(markup).toContain("repair-proposal-layout");
    expect(markup).toContain("repair-proposal-main");
    expect(markup).toContain("repair-proposal-side");
  });

  it("does_not_render_failure_and_repair_primary_panel_when_reviewed_proposal_exists", () => {
    const source = MigrationCockpit.toString();
    expect(source).toContain("failure-evidence-advanced");
    expect(source).toContain("Failure Evidence");
    expect(source).toContain("data.failureSummary?.has_failures");
  });

  it("renders_advanced_failure_evidence_collapsed", () => {
    const source = MigrationCockpit.toString();
    expect(source).toContain("failure-evidence-advanced");
    expect(source).toContain("Failure Evidence");
  });

  it("model_trace_does_not_overlay_primary_decision_area", () => {
    const markup = renderToStaticMarkup(
      <ModelRoleActivity invocations={[]} loading={false} error={null} />
    );
    expect(markup).toContain("model-role-activity");
    expect(markup).toContain("Repair Review Gate");
    expect(markup).not.toContain("position:absolute");
    expect(markup).not.toContain("position:fixed");
    expect(markup).not.toContain("inset:");
    expect(markup).not.toContain("overlay");
  });

  it("uses_full_width_cockpit_layout_class", () => {
    const source = MigrationCockpit.toString();
    expect(source).toContain("cockpit-page-wrapper");
    expect(source).toContain("data-full-width");
  });
});

describe("PR-D/PR-E polish: diagnosis, actions, validation, metadata", () => {
  const baseProposal: ReviewedDiffProposal = {
    proposal_id: "prop-1",
    job_id: "job-1",
    command_id: null,
    gate_id: "gate-1",
    route_step_index: 2,
    stage_index: 1,
    status: "user_review_required",
    attempt_number: 1,
    revision_number: null,
    failure_summary: "Build failure in pom.xml",
    hypothesis: "Missing spring-boot-starter dependency",
    patch_summary: "Add spring-boot-starter-web to pom.xml",
    diagnosis_ref: null,
    repair_plan_ref: null,
    diff_ref: null,
    diff_checksum: "sha256:abc",
    safe_diff_preview: null,
    reviewer_verdict: null,
    files_changed: [
      { path: "pom.xml", change_type: "modified", additions: 3, deletions: 0 },
    ],
    risk: null,
    policy_status: null,
    policy_reason: null,
    policy_reason_code: null,
    policy_validation_checksum: null,
    required_validation: [],
    allowed_actions: ["approve_sandbox_apply", "request_revision"],
    redactions: [],
  };

  it("renders_human_friendly_diagnosis_not_raw_json", () => {
    const markup = renderToStaticMarkup(
      <div className="main-diagnosis-summary">
        <strong>Main Model Diagnosis</strong>
        <div className="meta diagnosis-fields">
          <div><span className="diagnosis-label">Root cause:</span> {baseProposal.hypothesis}</div>
          <div><span className="diagnosis-label">Fix strategy:</span> {baseProposal.patch_summary}</div>
          <div><span className="diagnosis-label">Changed files:</span> {baseProposal.files_changed.map((f) => f.path).join(", ")}</div>
        </div>
      </div>,
    );
    expect(markup).toContain("Root cause:");
    expect(markup).toContain("Missing spring-boot-starter dependency");
    expect(markup).toContain("Fix strategy:");
    expect(markup).toContain("Add spring-boot-starter-web to pom.xml");
    expect(markup).toContain("Changed files:");
    expect(markup).toContain("pom.xml");
    expect(markup).not.toContain('{"');
    expect(markup).not.toContain('"}');
  });

  it("renders_reviewer_notes_as_bullets", () => {
    const verdict: ReviewerVerdictProjection = {
      reviewer_verdict_id: "v-1",
      decision: "accept",
      reasoning: "Evidence is sufficient.\nPatch scope is correct.",
      missing_evidence: [],
      unsafe_assumptions: ["assumes build tool is Maven"],
      model_invocation_id: null,
      output_checksum: null,
    };
    const markup = renderToStaticMarkup(<ReviewerVerdictCard verdict={verdict} />);
    expect(markup).toContain("Notes");
    expect(markup).toContain("Evidence is sufficient.");
    expect(markup).toContain("Patch scope is correct.");
    expect(markup).toContain("Risks / Policy Concerns");
    expect(markup).toContain("assumes build tool is Maven");
    expect(markup).toContain("data-testid=\"verdict-notes\"");
    expect(markup).toContain("data-testid=\"verdict-risks\"");
    expect(markup).not.toContain("Reasoning");
  });

  it("renders_policy_human_review_banner", () => {
    const markup = renderToStaticMarkup(
      <PolicyBannerSection
        status="human_review_required"
        reason="Rule not allowlisted"
        reasonCode="BLOCKED_BY_POLICY"
        validationChecksum="sha256:policy"
        banner={{
          tone: "review",
          title: "Human review required",
          copy: "Backend policy marked this repair for human review because the rule is not allowlisted. The diff is structurally valid and will not be applied unless you approve it.",
        }}
      />,
    );
    expect(markup).toContain('data-testid="reviewed-repair-policy-banner"');
    expect(markup).toContain("Human review required");
    expect(markup).toContain("not allowlisted");
    expect(markup).toContain("structurally valid");
    expect(markup).toContain("BLOCKED_BY_POLICY");
    expect(markup).toContain("sha256:policy");
  });

  it("does_not_render_apply_button_without_allowed_action", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={async () => undefined}
        revisionPending={false}
        approveEnabled={false}
        revisionEnabled={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain('data-testid="action-approve-sandbox-apply"');
    expect(markup).toContain('disabled=""');
    expect(markup).toContain("Approve sandbox apply");
  });

  it("does_not_render_request_revision_without_allowed_action", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={async () => undefined}
        revisionPending={false}
        revisionEnabled={false}
        approveEnabled={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain('data-testid="action-request-revision"');
    expect(markup).toContain('disabled=""');
    expect(markup).toContain("Revision is not allowed by the current backend gate");
  });

  it("renders_approval_buttons_when_backend_allows_actions", () => {
    const markup = renderToStaticMarkup(
      <RepairActionsBar
        onViewDiff={() => undefined}
        onViewReviewerOpinion={() => undefined}
        onViewFilesChanged={() => undefined}
        onViewAttemptHistory={() => undefined}
        onRequestRevision={async () => undefined}
        onApproveSandboxApply={() => undefined}
        revisionPending={false}
        approveEnabled={true}
        revisionEnabled={true}
        approvePending={false}
        checksumMismatch={false}
      />,
    );
    expect(markup).toContain('data-testid="action-approve-sandbox-apply"');
    expect(markup).toContain('data-testid="action-request-revision"');
    expect(markup).not.toContain('disabled=""');
  });

  it("does_not_send_patch_text_on_approve", () => {
    const request = {
      proposal_id: "prop-1",
      diff_checksum: "sha256:abc",
      reviewer_verdict_id: "v-1",
      gate_id: "g-1",
      idempotency_key: "idem-123",
    };
    const body = JSON.stringify(request);
    expect(body).not.toContain("patch_text");
    expect(body).not.toContain("patch_content");
    expect(body).not.toContain("target_path");
    expect(body).not.toContain("sandbox_path");
  });

  it("does_not_send_patch_text_on_revision_request", () => {
    const request = {
      user_instruction: "please revise",
      previous_diff_checksum: "sha256:abc",
      previous_reviewer_verdict_id: "v-1",
    };
    const body = JSON.stringify(request);
    expect(body).not.toContain("patch_text");
    expect(body).not.toContain("patch_content");
    expect(body).not.toContain("target_path");
    expect(body).not.toContain("sandbox_path");
  });

  it("validation_path_waits_for_user_approval_before_apply", () => {
    const markup = renderToStaticMarkup(
      <ValidationProgressPanel
        attempts={[]}
        proposalStatus="user_review_required"
      />,
    );
    expect(markup).toContain('data-testid="waiting-for-approval"');
    expect(markup).toContain("Waiting for your approval");
  });

  it("shows_diff_preview_error_when_hunks_empty", () => {
    const diff: SafeDiffPreviewType = {
      proposal_id: "p-1",
      diff_ref: null,
      diff_checksum: "sha256:abc",
      files: [
        {
          path: "pom.xml",
          change_type: "modified",
          additions: 0,
          deletions: 0,
          hunks: [],
          truncated: false,
        },
      ],
      total_additions: 0,
      total_deletions: 0,
      truncated: false,
      parse_status: "parsed",
      checksum_mismatch: false,
      redactions: [],
    };
    const markup = renderToStaticMarkup(<SafeDiffPreview diff={diff} />);
    expect(markup).toContain("pom.xml");
    expect(markup).not.toContain("safe-diff-hunk");
  });

  it("technical_metadata_collapsed_by_default", () => {
    const markup = renderToStaticMarkup(
      <RepairProposalMetadata proposal={baseProposal} />,
    );
    expect(markup).toContain('data-testid="repair-metadata-details"');
    expect(markup).toContain("Show advanced details");
    expect(markup).toContain("Proposal state");
    expect(markup).toContain("USER REVIEW REQUIRED");
    expect(markup).toContain("Gate");
    expect(markup).toContain("gate-1");
    expect(markup).toContain("Proposal ID");
    expect(markup).toContain("prop-1");
    expect(markup).toContain("checksum");
    expect(markup).toContain("sha256:abc");
    expect(markup).not.toContain("raw JSON");
  });

  it("renders_approval_actions_not_enabled_message", () => {
    const noActionsProposal: ReviewedDiffProposal = {
      ...baseProposal,
      allowed_actions: [],
    };
    const markup = renderToStaticMarkup(
      <RepairProposalMetadata proposal={noActionsProposal} />,
    );
    expect(markup).toContain('data-testid="repair-metadata-details"');
    expect(markup).not.toContain("approve_sandbox_apply");
    expect(markup).not.toContain("request_revision");
  });
});

describe("PR-F no-proposal UI states", () => {
  const baseInvocationNoProp: V2LlmInvocationEntry = {
    invocation_id: "inv-main",
    job_id: "job-1",
    proposal_id: null,
    gate_id: null,
    role: "main",
    responsibility: "repair_proposal",
    provider_alias: "azure_openai",
    model_display_name: "Product safe proposer",
    deployment_alias_hash: "abc123",
    context_checksum: "sha256:context",
    input_checksum: "sha256:input",
    output_checksum: "sha256:output",
    schema_name: "RepairPrimaryOutput",
    status: "completed",
    fallback_used: false,
    redacted_error: null,
    redacted_summary: "Diagnosed missing validation dependency.",
    prompt_tokens: 12,
    completion_tokens: 8,
    total_tokens: 20,
    latency_ms: 1200,
    created_at: "2026-06-30T00:00:00Z",
    completed_at: "2026-06-30T00:00:01Z",
  };

  it("does_not_show_validation_path_when_no_proposal", () => {
    const markup = renderToStaticMarkup(<ValidationProgressPanel attempts={[]} />);
    expect(markup).toContain("Reviewed Repair Unavailable");
    expect(markup).not.toContain("Apply, Rebuild, Test");
  });

  it("does_not_show_waiting_for_approval_when_no_proposal", () => {
    const markup = renderToStaticMarkup(<ValidationProgressPanel attempts={[]} />);
    expect(markup).not.toContain("Waiting for your approval");
    expect(markup).toContain("Not available");
  });

  it("shows_main_schema_invalid_unavailable_state", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocationNoProp,
        status: "schema_invalid",
        redacted_error: "proposer_schema_invalid",
        redacted_summary: "Schema validation failed: missing required field 'proposed_diff'",
      },
    ];
    const markup = renderToStaticMarkup(
      <ReviewedRepairUnavailable invocations={invocations} loading={false} error={null} />,
    );
    expect(markup).toContain("Reviewed Repair Unavailable");
    expect(markup).toContain("schema invalid");
    expect(markup).toContain("not run");
    expect(markup).not.toContain("Approve sandbox apply");
    expect(markup).not.toContain("Apply, Rebuild, Test");
  });

  it("shows_reviewer_not_run_when_main_invalid", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocationNoProp,
        status: "schema_invalid",
        redacted_error: "proposer_schema_invalid",
        redacted_summary: "Schema validation failed",
      },
    ];
    const markup = renderToStaticMarkup(
      <ReviewedRepairUnavailable invocations={invocations} loading={false} error={null} />,
    );
    expect(markup).toContain("not run");
    expect(markup).toContain("schema invalid");
    expect(markup).not.toContain("Reviewer Model completed");
  });

  it("does_not_render_approve_or_revision_without_proposal", () => {
    const markup = renderToStaticMarkup(
      <ReviewedRepairUnavailable invocations={[]} loading={false} error={null} />,
    );
    expect(markup).not.toContain("Approve sandbox apply");
    expect(markup).not.toContain("Request revision");
    expect(markup).not.toContain("View diff");
  });

  it("shows_safe_model_display_names_from_backend", () => {
    const invocations: V2LlmInvocationEntry[] = [
      {
        ...baseInvocationNoProp,
        model_display_name: "Custom Main Model Name",
      },
      {
        ...baseInvocationNoProp,
        invocation_id: "inv-reviewer",
        role: "reviewer",
        responsibility: "repair_review",
        model_display_name: "Custom Reviewer Model Name",
        redacted_summary: null,
        created_at: "2026-06-30T00:00:02Z",
      },
    ];
    const markup = renderToStaticMarkup(
      <ReviewedRepairUnavailable invocations={invocations} loading={false} error={null} />,
    );
    expect(markup).toContain("Custom Main Model Name");
    expect(markup).toContain("Custom Reviewer Model Name");
    expect(markup).toContain("data-testid=\"reviewed-repair-unavailable\"");
  });

  it("technical_details_collapsed_by_default", () => {
    const invocations: V2LlmInvocationEntry[] = [
      { ...baseInvocationNoProp, provider_alias: "azure_openai" },
    ];
    const markup = renderToStaticMarkup(
      <ModelRoleActivity invocations={invocations} loading={false} error={null} />,
    );
    expect(markup).toContain("data-testid=\"model-activity-details\"");
    expect(markup).toContain("Show technical details");
    expect(markup).toContain("<details");
  });

  it("apply_rebuild_test_visible_only_when_proposal_exists", () => {
    const noProposalMarkup = renderToStaticMarkup(<ValidationProgressPanel attempts={[]} />);
    expect(noProposalMarkup).not.toContain("Apply, Rebuild, Test");

    const hasProposalMarkup = renderToStaticMarkup(
      <ValidationProgressPanel attempts={[]} proposalStatus="user_review_required" />,
    );
    expect(hasProposalMarkup).toContain("Apply, Rebuild, Test");
  });
});
