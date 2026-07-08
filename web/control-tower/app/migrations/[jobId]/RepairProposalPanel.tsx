"use client";

import { useEffect, useState } from "react";
import {
  createIdempotencyKey,
  getCurrentRepairProposal,
  getRepairProposalDiff,
  getRepairAttempts,
  getV2LlmActivity,
  requestRepairProposalRevision,
  approveRepairProposal,
} from "../../../lib/controlTowerApi";
import type {
  ReviewedDiffProposal,
  SafeDiffPreview as SafeDiffPreviewType,
  RepairAttemptSummary,
  RepairProposalApproveRequest,
  RepairMaterializationUnavailable,
  V2LlmInvocationEntry,
} from "../../../lib/contracts";
import { formatSafeRelativePath } from "../../../lib/safeDisplay";
import { ReviewedDiffTabs } from "./ReviewedDiffTabs";
import { RepairAttemptTimeline } from "./RepairAttemptTimeline";
import { RepairActionsBar } from "./RepairActionsBar";
import { ModelRoleActivity } from "./ModelRoleActivity";
import { ValidationProgressPanel } from "./ValidationProgressPanel";

type ProposalState =
  | { status: "loading" }
  | { status: "no-proposal"; unavailable?: RepairMaterializationUnavailable | null }
  | { status: "error"; message: string }
  | { status: "available"; proposal: ReviewedDiffProposal };

type DiffState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "available"; diff: SafeDiffPreviewType };

type AttemptsState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "available"; attempts: RepairAttemptSummary[] };

type ActivityState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string; invocations: V2LlmInvocationEntry[] }
  | { status: "available"; invocations: V2LlmInvocationEntry[] };

const REVIEWER_SCHEMA_FAILURE_SUMMARY =
  "Reviewer model output failed schema validation, so no reviewed diff was produced.";
const REVIEWER_SELF_REPAIR_SCHEMA_FAILURE_SUMMARY =
  "Reviewer self-repair output failed schema validation.";
const REVIEWER_UNAVAILABLE_SUMMARY =
  "Reviewer model did not produce a reviewed diff.";
const MAIN_SCHEMA_FAILURE_SUMMARY =
  "Main Model output failed schema validation, so the reviewer did not produce a reviewed diff.";

function normalized(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase();
}

function isMainInvocation(invocation: V2LlmInvocationEntry): boolean {
  return ["main", "proposer", "primary"].includes(normalized(invocation.role)) ||
    normalized(invocation.responsibility) === "repair_proposal";
}

function isReviewerInvocation(invocation: V2LlmInvocationEntry): boolean {
  return normalized(invocation.role) === "reviewer" ||
    normalized(invocation.responsibility) === "repair_review" ||
    normalized(invocation.responsibility) === "repair_review_self_repair";
}

function isMainSchemaInvalid(invocation: V2LlmInvocationEntry | null | undefined): boolean {
  if (!invocation) return false;
  const reasonCode = normalized(invocation.reason_code);
  const redactedError = normalized(invocation.redacted_error);
  const summary = normalized(invocation.redacted_summary);
  return reasonCode === "main_schema_invalid" ||
    reasonCode === "proposer_schema_invalid" ||
    redactedError === "proposer_schema_invalid" ||
    normalized(invocation.status) === "schema_invalid" ||
    summary.includes("schema validation") ||
    summary.includes("schema invalid");
}

function isReviewerSchemaInvalid(invocation: V2LlmInvocationEntry | null | undefined): boolean {
  if (!invocation) return false;
  const reasonCode = normalized(invocation.reason_code);
  const redactedError = normalized(invocation.redacted_error);
  const schemaName = normalized(invocation.schema_name);
  const summary = normalized(invocation.redacted_summary);
  return reasonCode === "reviewer_schema_invalid" ||
    redactedError === "reviewer_schema_invalid" ||
    (normalized(invocation.status) === "schema_invalid" && isReviewerInvocation(invocation)) ||
    (schemaName.includes("reviewer") && summary.includes("schema validation")) ||
    (schemaName.includes("reviewer") && summary.includes("schema invalid"));
}

function displayStatus(invocation: V2LlmInvocationEntry | null | undefined, schemaInvalid = false): string {
  if (schemaInvalid) return "schema invalid";
  if (!invocation) return "pending";
  if (invocation.status === "fallback") return "completed with fallback";
  return invocation.status.replace(/_/g, " ");
}

export function RepairProposalPanel({ jobId }: { jobId: string }) {
  const [proposalState, setProposalState] = useState<ProposalState>({ status: "loading" });
  const [diffState, setDiffState] = useState<DiffState>({ status: "idle" });
  const [attemptsState, setAttemptsState] = useState<AttemptsState>({ status: "idle" });
  const [activityState, setActivityState] = useState<ActivityState>({ status: "idle" });
  const [showAttempts, setShowAttempts] = useState(false);
  const [revisionPending, setRevisionPending] = useState(false);
  const [approvePending, setApprovePending] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    async function load() {
      try {
        const response = await getCurrentRepairProposal(jobId);
        if (cancelled) return;
        if (response.proposal) {
          setProposalState({ status: "available", proposal: response.proposal });
          // AMF-252: Seed diff preview from embedded safe_diff_preview if available
          const embeddedPreview = response.proposal.safe_diff_preview;
          if (embeddedPreview) {
            setDiffState({ status: "available", diff: embeddedPreview });
          } else {
            setDiffState({ status: "loading" });
          }
          setAttemptsState({ status: "loading" });
          setActivityState({ status: "loading" });
          const [diffResponse, attemptsResponse, activityResponse] = await Promise.all([
            getRepairProposalDiff(jobId, response.proposal.proposal_id).catch(() => null),
            getRepairAttempts(jobId).catch(() => null),
            getV2LlmActivity(jobId).catch(() => null),
          ]);
          if (cancelled) return;
          if (diffResponse?.safe_diff_preview) {
            setDiffState({ status: "available", diff: diffResponse.safe_diff_preview });
          } else if (!embeddedPreview) {
            setDiffState({ status: "error", message: diffResponse?.reason ?? "Diff unavailable" });
          }
          if (attemptsResponse?.attempts) {
            setAttemptsState({ status: "available", attempts: attemptsResponse.attempts });
          } else {
            setAttemptsState({ status: "available", attempts: [] });
          }
          if (activityResponse?.invocations) {
            setActivityState({ status: "available", invocations: activityResponse.invocations });
          } else {
            setActivityState({ status: "error", message: "Activity not available", invocations: [] });
          }
        } else {
          setProposalState({ status: "no-proposal", unavailable: response.unavailable ?? null });
          setActivityState({ status: "loading" });
          const activityResponse = await getV2LlmActivity(jobId).catch(() => null);
          if (cancelled) return;
          if (activityResponse?.invocations) {
            setActivityState({ status: "available", invocations: activityResponse.invocations });
          } else {
            setActivityState({ status: "available", invocations: [] });
          }
        }
      } catch (e) {
        if (!cancelled) {
          setProposalState({
            status: "error",
            message: e instanceof Error ? e.message : "Failed to load proposal",
          });
        }
      }
    }
    load();
    return () => { cancelled = true; };
  }, [jobId]);

  useEffect(() => {
    if (errorBanner) {
      const timer = setTimeout(() => setErrorBanner(null), 15000);
      return () => clearTimeout(timer);
    }
  }, [errorBanner]);

  async function refreshProposalData() {
    if (!jobId) return;
    setErrorBanner(null);
    try {
      const response = await getCurrentRepairProposal(jobId);
      if (response.proposal) {
        setProposalState({ status: "available", proposal: response.proposal });
        // AMF-252: Seed diff preview from embedded safe_diff_preview if available
        const embeddedPreview = response.proposal.safe_diff_preview;
        if (embeddedPreview) {
          setDiffState({ status: "available", diff: embeddedPreview });
        } else {
          setDiffState({ status: "loading" });
        }
        setAttemptsState({ status: "loading" });
        setActivityState({ status: "loading" });
        const [diffResponse, attemptsResponse, activityResponse] = await Promise.all([
          getRepairProposalDiff(jobId, response.proposal.proposal_id).catch(() => null),
          getRepairAttempts(jobId).catch(() => null),
          getV2LlmActivity(jobId).catch(() => null),
        ]);
        if (diffResponse?.safe_diff_preview) {
          setDiffState({ status: "available", diff: diffResponse.safe_diff_preview });
        } else if (!embeddedPreview) {
          setDiffState({ status: "error", message: diffResponse?.reason ?? "Diff unavailable" });
        }
        if (attemptsResponse?.attempts) {
          setAttemptsState({ status: "available", attempts: attemptsResponse.attempts });
        } else {
          setAttemptsState({ status: "available", attempts: [] });
        }
        if (activityResponse?.invocations) {
          setActivityState({ status: "available", invocations: activityResponse.invocations });
        } else {
          setActivityState({ status: "error", message: "Activity not available", invocations: [] });
        }
      } else {
        setProposalState({ status: "no-proposal", unavailable: response.unavailable ?? null });
        setActivityState({ status: "loading" });
        const activityResponse = await getV2LlmActivity(jobId).catch(() => null);
        if (activityResponse?.invocations) {
          setActivityState({ status: "available", invocations: activityResponse.invocations });
        } else {
          setActivityState({ status: "available", invocations: [] });
        }
      }
    } catch {
      setProposalState({
        status: "error",
        message: "Failed to refresh proposal data",
      });
    }
  }

  async function handleRequestRevision(instruction: string) {
    if (!jobId) return;
    setRevisionPending(true);
    const state = proposalState;
    if (state.status !== "available") { setRevisionPending(false); return; }
    // AMF-252: Block revision for direct proposals
    if (state.proposal.kind === "direct_reviewed_diff" || state.proposal.kind === "direct_candidate_diff" || state.proposal.gate_id == null) {
      setErrorBanner("Revision is not available for direct reviewer diffs yet.");
      setRevisionPending(false);
      return;
    }
    try {
      setErrorBanner(null);
      const state = proposalState;
      if (state.status !== "available") return;
      await requestRepairProposalRevision(jobId, state.proposal.proposal_id, {
        user_instruction: instruction,
        previous_diff_checksum: state.proposal.diff_checksum,
        previous_reviewer_verdict_id:
          state.proposal.reviewer_verdict?.reviewer_verdict_id ?? "",
      });
      await refreshProposalData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Revision request failed";
      setErrorBanner(`Revision request failed — ${msg}`);
    } finally {
      setRevisionPending(false);
    }
  }

  async function handleApproveSandboxApply() {
    if (!jobId) return;
    const state = proposalState;
    if (state.status !== "available") return;
    setApprovePending(true);
    try {
      setErrorBanner(null);
      const reviewerVerdictId = state.proposal.reviewer_verdict?.reviewer_verdict_id;
      const gateId = state.proposal.gate_id;
      // AMF-252: Direct proposals may have null reviewer_verdict_id and gate_id
      const body: RepairProposalApproveRequest = {
        proposal_id: state.proposal.proposal_id,
        diff_checksum: state.proposal.diff_checksum,
        idempotency_key: createIdempotencyKey(),
        reviewer_verdict_id: reviewerVerdictId ?? null,
        gate_id: gateId ?? null,
      };
      await approveRepairProposal(jobId, state.proposal.proposal_id, body);
      await refreshProposalData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Approval failed";
      if (msg.includes("409") || msg.includes("GATE_NOT_OPEN") || msg.includes("Conflict")) {
        setErrorBanner("Approval failed — this repair gate is no longer open. The proposal may have been superseded by a revision request. Refreshing state...");
        await refreshProposalData();
        setErrorBanner("The proposal has been refreshed. If the approve button is hidden, the gate has been superseded.");
      } else {
        setErrorBanner(`Approval failed — ${msg}`);
      }
    } finally {
      setApprovePending(false);
    }
  }

  if (proposalState.status === "loading") {
    return (
      <section className="panel" data-testid="repair-proposal-panel">
        <h2>Repair Proposal</h2>
        <p className="meta">Loading proposal...</p>
      </section>
    );
  }

  if (proposalState.status === "no-proposal") {
    if (proposalState.unavailable?.kind === "materialization_failed") {
      const unavailableInvocations = activityState.status === "available" || activityState.status === "error"
        ? activityState.invocations
        : [];
      return (
        <ReviewedRepairMaterializationFailed
          invocations={unavailableInvocations}
          loading={activityState.status === "loading"}
          error={activityState.status === "error" ? activityState.message : null}
          diagnostic={proposalState.unavailable}
        />
      );
    }
    const unavailableInvocations = activityState.status === "available" || activityState.status === "error"
      ? activityState.invocations
      : [];
    const hasReviewChainActivity = unavailableInvocations.some((invocation) => (
      ["repair_proposal", "repair_review", "revision_proposal", "revision_review"].includes(
        invocation.responsibility.toLowerCase(),
      )
    ));
    if (hasReviewChainActivity) {
      const sorted = [...unavailableInvocations].sort((a, b) => b.created_at.localeCompare(a.created_at));
      const reviewerInvocation = sorted.find(isReviewerInvocation);
      const mainInvocation = sorted.find(isMainInvocation);
      const mainCompleted = Boolean(mainInvocation && normalized(mainInvocation.status) === "completed");
      const reviewerCompleted = reviewerInvocation && ["completed", "fallback"].includes(normalized(reviewerInvocation.status));
      const latestMainSchemaInvalid = isMainSchemaInvalid(mainInvocation);
      const reviewerSchemaInvalid = isReviewerSchemaInvalid(reviewerInvocation);
      if (mainCompleted && reviewerSchemaInvalid) {
        return (
          <ReviewedRepairUnavailable
            invocations={unavailableInvocations}
            loading={activityState.status === "loading"}
            error={activityState.status === "error" ? activityState.message : null}
            reviewerSchemaInvalid
          />
        );
      }
      if (reviewerCompleted && mainCompleted) {
        return (
          <ReviewedRepairMaterializationFailed
            invocations={unavailableInvocations}
            loading={activityState.status === "loading"}
            error={activityState.status === "error" ? activityState.message : null}
          />
        );
      }
      return (
        <ReviewedRepairUnavailable
          invocations={unavailableInvocations}
          loading={activityState.status === "loading"}
          error={activityState.status === "error" ? activityState.message : null}
          mainSchemaInvalid={latestMainSchemaInvalid && !mainCompleted}
        />
      );
    }
    return (
      <section className="panel" data-testid="repair-proposal-panel">
        <h2>Repair Proposal</h2>
        <p className="meta">No repair proposal available for this job.</p>
      </section>
    );
  }

  if (proposalState.status === "error") {
    return (
      <section className="panel" data-testid="repair-proposal-panel">
        <h2>Repair Proposal</h2>
        <p className="meta" role="alert">{proposalState.message}</p>
      </section>
    );
  }

  const proposal = proposalState.proposal;
  const diff = diffState.status === "available" ? diffState.diff : null;
  const attempts = attemptsState.status === "available" ? attemptsState.attempts : [];
  const llmInvocations = activityState.status === "available" || activityState.status === "error"
    ? activityState.invocations
    : [];
  const activityError = activityState.status === "error" ? activityState.message : null;

  // approve_failed is a terminal read-only state
  const isDirectProposal =
    proposal.kind === "direct_reviewed_diff" ||
    proposal.kind === "direct_candidate_diff" ||
    (proposal.kind == null && proposal.gate_id == null);
  const isCandidateDiff = proposal.kind === "direct_candidate_diff";
  const isApproveFailed = proposal.status === "approve_failed";
  const isApplyCheckFailed = proposal.reason_code === "PATCH_CHECK_FAILED";
  const isPatchApplyFailed = proposal.reason_code === "PATCH_APPLY_FAILED";

  const approveAllowed = !isApproveFailed && proposal.allowed_actions.includes("approve_sandbox_apply");
  const revisionAllowed =
    !isDirectProposal &&
    !isApproveFailed &&
    proposal.allowed_actions.some((a) => ["request_revision", "request_repair_revision", "revise_repair_proposal"].includes(a));
  const latestMainSummary = [...llmInvocations]
    .filter((invocation) => (
      ["main", "proposer", "primary"].includes(invocation.role.toLowerCase()) ||
      ["repair_proposal", "revision_proposal"].includes(invocation.responsibility.toLowerCase())
    ))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]?.redacted_summary;
  const policyStatus = (proposal.policy_status ?? "").trim().toLowerCase();
  const policyReason = proposal.policy_reason?.trim() ?? "";
  const policyReasonCode = proposal.policy_reason_code?.trim() ?? "";
  const policyValidationChecksum = proposal.policy_validation_checksum?.trim() ?? "";
  const policyBanner =
    policyStatus === "human_review_required"
      ? {
          tone: "review",
          title: "Human review required",
          copy: "Backend policy marked this repair for human review because the rule is not allowlisted. The diff is structurally valid and will not be applied unless you approve it.",
        }
      : policyStatus === "allowed"
        ? {
            tone: "allowed",
            title: "Backend policy allowed this diff",
            copy: "Backend policy found this reviewed diff safe to present for approval. It will only be applied after you approve it.",
          }
        : policyStatus
          ? {
              tone: "warning",
              title: policyStatus.replace(/_/g, " "),
              copy: policyReason || "Backend policy state is available for review.",
            }
          : null;

  const actionsNotEnabled = proposal.status === "user_review_required" &&
    !approveAllowed && !revisionAllowed;

  return (
    <section className="panel repair-proposal-panel" data-testid="repair-proposal-panel">
      <div className="repair-proposal-layout">
        <div className="repair-proposal-main">
          <div className="repair-panel-kicker">{isCandidateDiff ? "Candidate Repair Diff" : isDirectProposal ? "Direct Reviewer Diff" : "Backend-governed repair gate"}</div>
          <h2>{isCandidateDiff ? "Candidate Repair Diff Ready" : isDirectProposal ? "Reviewer Diff Ready" : "Reviewed Repair Proposal"}</h2>

          {errorBanner && (
            <div className="error-banner" data-testid="approve-error-banner" role="alert">
              <p>{errorBanner}</p>
              <button type="button" onClick={() => setErrorBanner(null)}>Dismiss</button>
            </div>
          )}

          {isApproveFailed && (
            <div className="failure-summary" data-testid="approve-failed-summary">
              <strong>
                {isApplyCheckFailed
                  ? "Reviewed Repair Apply-Check Failed"
                  : isPatchApplyFailed
                    ? "Reviewed Repair Patch Apply Failed"
                    : "Reviewed Repair Validation Failed"}
              </strong>
              <p className="meta">
                {isApplyCheckFailed
                  ? "Backend apply-check failed; new proposal required. No build/test rerun was started."
                  : isPatchApplyFailed
                    ? "Backend patch apply failed after review approval. No build/test rerun was started."
                    : "Reviewer accepted and backend applied the diff, but validation failed after apply. The reviewed diff is still viewable."}
              </p>
              {proposal.reason_code && (
                <p className="meta warning-text" data-testid="apply-reason-code">Reason code: {proposal.reason_code}</p>
              )}
              {proposal.status_reason && (
                <p className="meta" data-testid="apply-status-reason">{proposal.status_reason}</p>
              )}
            </div>
          )}

          {!isDirectProposal && (
            <PolicyBannerSection
              status={policyStatus}
              reason={policyReason}
              reasonCode={policyReasonCode}
              validationChecksum={policyValidationChecksum}
              banner={policyBanner}
            />
          )}
          {isDirectProposal && !isCandidateDiff && (
            <div className="reviewed-repair-banner reviewed-repair-banner-allowed" data-testid="direct-proposal-banner">
              <div className="reviewed-repair-banner-top">
                <strong>Reviewer diff ready for apply</strong>
                <span className="status-badge">DIRECT</span>
              </div>
              <p className="meta">Reviewer accepted this repair and produced the diff below. Backend will apply the exact reviewer diff shown above, then rerun validation.</p>
            </div>
          )}
          {isCandidateDiff && (
            <div className="reviewed-repair-banner reviewed-repair-banner-review" data-testid="candidate-diff-banner">
              <div className="reviewed-repair-banner-top">
                <strong>Candidate Diff Ready</strong>
                <span className="status-badge">CANDIDATE</span>
              </div>
              <p className="meta">Reviewer requested revision, but the main LLM candidate diff is available for your review and decision.</p>
            </div>
          )}

          {proposal.failure_summary && (
            <div className="failure-summary" data-testid="failure-summary">
              <strong>Failure Summary</strong>
              <p className="meta">{proposal.failure_summary}</p>
            </div>
          )}

          <div className="main-diagnosis-summary" data-testid="main-model-diagnosis-summary">
            <strong>Main Model Diagnosis</strong>
            <div className="meta diagnosis-fields">
              <div><span className="diagnosis-label">Root cause:</span> {proposal.hypothesis || "N/A"}</div>
              <div><span className="diagnosis-label">Fix strategy:</span> {proposal.patch_summary || "N/A"}</div>
              {proposal.kind && <div><span className="diagnosis-label">Kind:</span> {proposal.kind === "direct_reviewed_diff" ? "Direct reviewer diff" : proposal.kind === "direct_candidate_diff" ? "Direct candidate diff" : "Reviewed gate"}</div>}
              {proposal.files_changed.length > 0 && (
                <div><span className="diagnosis-label">Changed files:</span> {proposal.files_changed.map((f) => formatSafeRelativePath(f.path)).join(", ")}</div>
              )}
            </div>
          </div>

          {actionsNotEnabled && (
            <div className="warning-text" data-testid="approval-actions-not-enabled">
              Approval actions are not currently enabled by the backend for this proposal.
            </div>
          )}

          <RepairProposalMetadata proposal={proposal} />

          <ReviewedDiffTabs
            proposal={proposal}
            diff={diff}
            diffMessage={diffState.status === "error" ? diffState.message : null}
            candidateDiff={isCandidateDiff}
          />

          {showAttempts && attempts.length > 0 && (
            <RepairAttemptTimeline attempts={attempts} />
          )}

          <RepairActionsBar
            allowedActions={proposal.allowed_actions}
            onViewDiff={() => {
              const tabEl = document.querySelector('[data-testid="tab-diff"]') as HTMLButtonElement | null;
              tabEl?.click();
            }}
            onViewReviewerOpinion={() => {
              const tabEl = document.querySelector('[data-testid="tab-reviewer-opinion"]') as HTMLButtonElement | null;
              tabEl?.click();
            }}
            onViewFilesChanged={() => {
              const tabEl = document.querySelector('[data-testid="tab-files-changed"]') as HTMLButtonElement | null;
              tabEl?.click();
            }}
            onViewAttemptHistory={() => setShowAttempts((v) => !v)}
            onRequestRevision={handleRequestRevision}
            onApproveSandboxApply={handleApproveSandboxApply}
            revisionPending={revisionPending}
            approvePending={approvePending}
            checksumMismatch={diff?.checksum_mismatch ?? false}
            directProposal={isDirectProposal}
            candidateDiff={isCandidateDiff}
            hasAttemptHistory={attempts.length > 0}
          />
        </div>

        <div className="repair-proposal-side">
          <ModelRoleActivity
            invocations={llmInvocations}
            loading={activityState.status === "loading"}
            error={activityError}
          />
          {attempts.length > 0 && (
            <ValidationProgressPanel
              attempts={attempts}
              proposalStatus={proposal.status}
              reasonCode={proposal.reason_code}
            />
          )}
        </div>
      </div>
    </section>
  );
}

export function ReviewedRepairUnavailable({
  invocations,
  loading,
  error,
  mainSchemaInvalid: mainSchemaInvalidProp,
  reviewerSchemaInvalid,
}: {
  invocations: V2LlmInvocationEntry[];
  loading: boolean;
  error: string | null;
  mainSchemaInvalid?: boolean;
  reviewerSchemaInvalid?: boolean;
}) {
  const sorted = [...invocations].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const mainInvocation = sorted.find(isMainInvocation);
  const reviewerInvocation = sorted.find(isReviewerInvocation);

  const isProposerSchemaInvalid = mainSchemaInvalidProp === true || isMainSchemaInvalid(mainInvocation);
  const isReviewerSchemaFailure = reviewerSchemaInvalid === true || isReviewerSchemaInvalid(reviewerInvocation);
  const selfRepairInvocation = sorted.find(
    (inv) => normalized(inv.responsibility) === "repair_review_self_repair"
  );
  const isReviewerSelfRepairSchemaFailure = isReviewerSchemaFailure && (
    (selfRepairInvocation !== undefined && isReviewerSchemaInvalid(selfRepairInvocation)) ||
    normalized(reviewerInvocation?.responsibility) === "repair_review_self_repair"
  );

  const mainModelStatus = displayStatus(mainInvocation, isProposerSchemaInvalid);
  const reviewerModelStatus = reviewerInvocation
    ? displayStatus(reviewerInvocation, isReviewerSchemaFailure)
    : isProposerSchemaInvalid
      ? "not run"
      : "pending";

  const exactReason = isProposerSchemaInvalid && mainInvocation?.redacted_summary
    && !normalized(mainInvocation.redacted_summary).includes("schema validation")
    && !normalized(mainInvocation.redacted_summary).includes("schema invalid")
    ? mainInvocation.redacted_summary
    : null;
  const summary = isReviewerSelfRepairSchemaFailure
    ? REVIEWER_SELF_REPAIR_SCHEMA_FAILURE_SUMMARY
    : isReviewerSchemaFailure
      ? REVIEWER_SCHEMA_FAILURE_SUMMARY
      : isProposerSchemaInvalid
        ? MAIN_SCHEMA_FAILURE_SUMMARY
        : REVIEWER_UNAVAILABLE_SUMMARY;
  const nextAction = isReviewerSelfRepairSchemaFailure
    ? "Reviewer self-repair output failed schema validation; retry after Reviewer prompt/config fix"
    : isReviewerSchemaFailure
      ? "Retry after reviewer/schema contract fix"
      : isProposerSchemaInvalid
          ? "Retry after Main model/schema/config fix"
          : "Retry after reviewer/model availability fix";
  const safeReasonCode = isReviewerSchemaFailure
    ? reviewerInvocation?.reason_code || reviewerInvocation?.redacted_error
    : isProposerSchemaInvalid
      ? mainInvocation?.reason_code || mainInvocation?.redacted_error
      : reviewerInvocation?.reason_code || mainInvocation?.reason_code || reviewerInvocation?.redacted_error || mainInvocation?.redacted_error;

  return (
    <section className="panel repair-proposal-panel" data-testid="repair-proposal-panel">
      <div className="repair-proposal-layout">
        <div className="repair-proposal-main">
          <div className="repair-panel-kicker">Reviewed Repair Gate</div>
          <h2>Reviewed Repair Unavailable</h2>
          <div className="failure-summary" data-testid="reviewed-repair-unavailable">
            <strong>Failure Summary</strong>
            {exactReason ? (
              <p className="meta warning-text" data-testid="exact-failure-reason">{exactReason}</p>
            ) : (
              <p className="meta">{summary}</p>
            )}
          </div>
          <div className="table-list repair-metadata-grid">
            <div className="table-row">
              <span className="meta">{mainInvocation?.model_display_name || "Main Model"}</span>
              <strong className={isProposerSchemaInvalid ? "status-badge failed" : ""}>{mainModelStatus}</strong>
            </div>
            {mainInvocation?.redacted_summary && (
              <div className="table-row">
                <span className="meta">Failure reason</span>
                <strong className="warning-text">{mainInvocation.redacted_summary}</strong>
              </div>
            )}
            {mainInvocation?.provider_alias && (
              <div className="table-row">
                <span className="meta">Provider</span>
                <strong>{mainInvocation.provider_alias}</strong>
              </div>
            )}
            {mainInvocation?.deployment_alias_hash && (
              <div className="table-row">
                <span className="meta">Deployment hash</span>
                <strong className="checksum">{mainInvocation.deployment_alias_hash}</strong>
              </div>
            )}
            <div className="table-row">
              <span className="meta">{reviewerInvocation?.model_display_name || "Reviewer Model"}</span>
              <strong className={isProposerSchemaInvalid ? "status-badge blocked" : ""}>{reviewerModelStatus}</strong>
            </div>
            <div className="table-row">
              <span className="meta">Reviewed diff</span>
              <strong>Not available</strong>
            </div>
            {safeReasonCode && (
              <div className="table-row">
                <span className="meta">Reason code</span>
                <strong>{safeReasonCode}</strong>
              </div>
            )}
            <div className="table-row">
              <span className="meta">Next action</span>
              <strong>{nextAction}</strong>
            </div>
          </div>
          {!isProposerSchemaInvalid && mainInvocation?.redacted_error && (
            <div className="main-diagnosis-summary" data-testid="main-model-error">
              <strong>Main Model Error</strong>
              <p className="warning-text">{mainInvocation.redacted_error}</p>
            </div>
          )}
        </div>
        <div className="repair-proposal-side">
          <ModelRoleActivity invocations={invocations} loading={loading} error={error} />
        </div>
      </div>
    </section>
  );
}

export function PolicyBannerSection({
  status,
  reason,
  reasonCode,
  validationChecksum,
  banner,
}: {
  status: string;
  reason: string;
  reasonCode: string;
  validationChecksum: string;
  banner: { tone: string; title: string; copy: string } | null;
}) {
  if (!banner) return null;
  return (
    <div className={`reviewed-repair-banner reviewed-repair-banner-${banner.tone}`} data-testid="reviewed-repair-policy-banner">
      <div className="reviewed-repair-banner-top">
        <strong>{banner.title}</strong>
        {status && <span className="status-badge">{status.replace(/_/g, " ").toUpperCase()}</span>}
      </div>
      <p className="meta">{banner.copy}</p>
      {(reason || reasonCode || validationChecksum) && (
        <div className="reviewed-repair-banner-details">
          {reasonCode && <span className="reviewed-repair-chip">Reason code: {reasonCode}</span>}
          {reason && <span className="reviewed-repair-chip">Reason: {reason}</span>}
          {validationChecksum && <span className="reviewed-repair-chip checksum">Policy checksum: {validationChecksum}</span>}
        </div>
      )}
    </div>
  );
}

export function RepairProposalMetadata({ proposal }: { proposal: ReviewedDiffProposal }) {
  return (
    <details className="repair-metadata-details" data-testid="repair-metadata-details">
      <summary data-testid="repair-metadata-summary">Show advanced details</summary>
      <div className="table-list repair-metadata-grid">
        <div className="table-row">
          <span className="meta">Proposal state</span>
          <strong>{proposal.status.replace(/_/g, " ").toUpperCase()}</strong>
        </div>
        {proposal.stage_index != null && (
          <div className="table-row">
            <span className="meta">Stage</span>
            <strong>{proposal.stage_index}</strong>
          </div>
        )}
        {proposal.route_step_index != null && (
          <div className="table-row">
            <span className="meta">Route step</span>
            <strong>{proposal.route_step_index}</strong>
          </div>
        )}
        {proposal.attempt_number != null && (
          <div className="table-row">
            <span className="meta">Attempt</span>
            <strong>{proposal.attempt_number}</strong>
          </div>
        )}
        {proposal.revision_number != null && (
          <div className="table-row">
            <span className="meta">Revision</span>
            <strong>{proposal.revision_number}</strong>
          </div>
        )}
        {proposal.gate_id && (
          <div className="table-row">
            <span className="meta">Gate</span>
            <strong>{proposal.gate_id}</strong>
          </div>
        )}
        {proposal.proposal_id && (
          <div className="table-row">
            <span className="meta">Proposal ID</span>
            <strong className="checksum">{proposal.proposal_id}</strong>
          </div>
        )}
        {proposal.diff_checksum && (
          <div className="table-row">
            <span className="meta">Reviewed diff checksum</span>
            <strong className="checksum">{proposal.diff_checksum}</strong>
          </div>
        )}
        {proposal.policy_status && (
          <div className="table-row">
            <span className="meta">Policy state</span>
            <strong>{proposal.policy_status.replace(/_/g, " ").toUpperCase()}</strong>
          </div>
        )}
        {proposal.policy_reason_code && (
          <div className="table-row">
            <span className="meta">Policy reason</span>
            <strong>{proposal.policy_reason_code}</strong>
          </div>
        )}
        {proposal.allowed_actions.length > 0 && (
          <div className="table-row">
            <span className="meta">Allowed actions</span>
            <strong>{proposal.allowed_actions.join(", ")}</strong>
          </div>
        )}
      </div>
    </details>
  );
}

export function ReviewedRepairMaterializationFailed({
  invocations,
  loading,
  error,
  policyReasonCode,
  diagnostic,
}: {
  invocations: V2LlmInvocationEntry[];
  loading: boolean;
  error: string | null;
  policyReasonCode?: string | null;
  diagnostic?: RepairMaterializationUnavailable | null;
}) {
  const sorted = [...invocations].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const mainInvocation = sorted.find((invocation) => (
    ["main", "proposer", "primary"].includes(invocation.role.toLowerCase()) ||
    invocation.responsibility.toLowerCase() === "repair_proposal"
  ));
  const reviewerInvocation = sorted.find(isReviewerInvocation);

  const mainModelStatus = mainInvocation
    ? mainInvocation.status.replace(/_/g, " ")
    : "pending";
  const reviewerModelStatus = reviewerInvocation
    ? reviewerInvocation.status.replace(/_/g, " ")
    : "pending";

  const policyReasonDisplay = {
    missing_diff_git_header: "missing Git diff header",
    missing_file_headers: "missing file headers (---/+++)",
    missing_hunk: "missing hunk (@@ ... @@)",
    no_changes: "no added/removed lines",
    unsafe_path: "unsafe file path",
    absolute_path: "absolute file path rejected",
    path_traversal: "path traversal rejected",
    malformed_patch: "malformed patch",
    empty_diff: "empty diff",
    binary_diff: "binary diff not allowed",
  } as const;

  const displayReason = policyReasonCode
    ? policyReasonDisplay[policyReasonCode as keyof typeof policyReasonDisplay] ?? policyReasonCode
    : null;
  const reasonCode = diagnostic?.reason_code?.trim() ?? "";
  const detail = diagnostic?.struct_issue?.trim() || diagnostic?.detail?.trim() || "";
  const title = diagnostic?.title?.trim() || "Reviewed Repair Materialization Failed";
  const summary = diagnostic?.message?.trim() || "Backend could not materialize a reviewed diff for user approval.";
  const isMalformedDiff = reasonCode === "MALFORMED_DIFF";
  const isReviewedDiffStructuralInvalid = reasonCode === "REVIEWED_DIFF_STRUCTURAL_INVALID";
  const isPatchCheckFailed = reasonCode === "PATCH_CHECK_FAILED";
  const isDuplicateMainBlocked = reasonCode === "duplicate_main_blocked";
  const blockedByReasonCode = diagnostic?.blocked_by_reason_code?.trim() ?? "";
  const blockedByStructIssue = diagnostic?.blocked_by_struct_issue?.trim() ?? "";
  const hasBlockedBy = blockedByReasonCode !== "";
  const reviewerSelfRepairFailureReason = diagnostic?.reviewer_self_repair_failure_reason?.trim() ?? "";
  const reviewerMechanicalValidationIssue = diagnostic?.reviewer_mechanical_validation_issue?.trim() ?? "";
  const reviewerAcceptContractIssue = diagnostic?.reviewer_accept_contract_issue?.trim() ?? "";
  const reviewerDecision = diagnostic?.reviewer_decision?.trim() ?? "";
  const reviewedDiffChecksum = diagnostic?.reviewed_diff_checksum?.trim() ?? "";
  const reviewerStatusFromDiag = diagnostic?.reviewer_status?.trim() ?? null;
  const mainStatusFromDiag = diagnostic?.main_status?.trim() ?? null;
  const contextChecksum = diagnostic?.context_checksum || reviewerInvocation?.context_checksum || mainInvocation?.context_checksum || null;
  const nextActionFromDiag = diagnostic?.next_action?.trim() ?? null;
  const effectiveMainStatus = mainStatusFromDiag ?? mainModelStatus;
  const effectiveReviewerStatus = reviewerStatusFromDiag ?? reviewerModelStatus;
  const failureSummaryText = (isMalformedDiff || isReviewedDiffStructuralInvalid)
    ? "Latest reviewed diff failed structural validation"
    : isPatchCheckFailed
      ? "Backend apply-check failed; new proposal required."
      : hasBlockedBy
        ? "Backend encountered a secondary blocking condition after the primary diagnostic was raised."
        : summary;
  const malformedExplainer = (isMalformedDiff || isReviewedDiffStructuralInvalid)
    ? "Reviewer accepted the repair, but backend structural validation rejected the reviewed diff before user approval."
    : null;
  const noValidationPath = diagnostic
    ? (isPatchCheckFailed
      ? "No build/test rerun was started because the reviewed diff was not applicable."
      : "No backend validation or apply path is available until a valid reviewed diff is materialized.")
    : null;

  return (
    <section className="panel repair-proposal-panel" data-testid="repair-proposal-panel">
      <div className="repair-proposal-layout">
        <div className="repair-proposal-main">
          <div className="repair-panel-kicker">Reviewed Repair Gate</div>
          <h2>{title}</h2>
          <div className="failure-summary" data-testid="reviewed-repair-materialization-failed">
            <strong>Failure Summary</strong>
            <p className="meta">{failureSummaryText}</p>
            {malformedExplainer && (
              <p className="meta">
                {malformedExplainer}
              </p>
            )}
            {hasBlockedBy && (
              <p className="meta warning-text" data-testid="blocked-by-message">
                Blocked by: {blockedByReasonCode}{blockedByStructIssue ? `: ${blockedByStructIssue}` : ""}
              </p>
            )}
            {isPatchCheckFailed && diagnostic?.apply_check_stderr_summary && (
              <p className="meta warning-text" data-testid="apply-check-summary">
                {diagnostic.apply_check_stderr_summary}
              </p>
            )}
            {noValidationPath && <p className="meta warning-text">{noValidationPath}</p>}
            {displayReason && (
              <p className="meta policy-reason" data-testid="policy-reason">
                Backend reason: {displayReason}
              </p>
            )}
            {diagnostic?.allowed_actions?.length ? (
              <div className="table-row">
                <span className="meta">Allowed actions</span>
                <strong>{diagnostic.allowed_actions.join(", ")}</strong>
              </div>
            ) : null}
          </div>
          <div className="table-list repair-metadata-grid">
            <div className="table-row">
              <span className="meta">Main Model</span>
              <strong data-testid="main-model-status">{effectiveMainStatus}</strong>
            </div>
            {mainInvocation?.redacted_summary && (
              <div className="table-row">
                <span className="meta">Output summary</span>
                <strong>{mainInvocation.redacted_summary}</strong>
              </div>
            )}
            {mainInvocation?.provider_alias && (
              <div className="table-row">
                <span className="meta">Provider</span>
                <strong>{mainInvocation.provider_alias}</strong>
              </div>
            )}
            {mainInvocation?.deployment_alias_hash && (
              <div className="table-row">
                <span className="meta">Deployment hash</span>
                <strong className="checksum">{mainInvocation.deployment_alias_hash}</strong>
              </div>
            )}
            <div className="table-row">
              <span className="meta">Reviewer Model</span>
              <strong data-testid="reviewer-model-status">{effectiveReviewerStatus}</strong>
            </div>
            {reviewerInvocation?.redacted_summary && (
              <div className="table-row">
                <span className="meta">Reviewer output</span>
                <strong>{reviewerInvocation.redacted_summary}</strong>
              </div>
            )}
            {reasonCode && (
              <div className="table-row">
                <span className="meta">Reason code</span>
                <strong data-testid="materialization-reason-code">{reasonCode}</strong>
              </div>
            )}
            {detail && (
              <div className="table-row">
                <span className="meta">Detail</span>
                <strong data-testid="materialization-detail">{detail}</strong>
              </div>
            )}
            {reviewerAcceptContractIssue && (
              <div className="table-row">
                <span className="meta">Reviewer accept contract</span>
                <strong data-testid="reviewer-accept-contract-issue">{reviewerAcceptContractIssue}</strong>
              </div>
            )}
            {reviewerDecision && (
              <div className="table-row">
                <span className="meta">Reviewer decision</span>
                <strong data-testid="reviewer-decision">{reviewerDecision}</strong>
              </div>
            )}
            {blockedByReasonCode && (
              <div className="table-row">
                <span className="meta">Blocked by</span>
                <strong data-testid="blocked-by-reason-code">{blockedByReasonCode}{blockedByStructIssue ? `: ${blockedByStructIssue}` : ""}</strong>
              </div>
            )}
            {typeof diagnostic?.reviewer_self_repair_attempted === "boolean" && (
              <div className="table-row">
                <span className="meta">Reviewer self-repair attempted</span>
                <strong>{diagnostic.reviewer_self_repair_attempted ? "true" : "false"}</strong>
              </div>
            )}
            {typeof diagnostic?.reviewer_self_repair_succeeded === "boolean" && (
              <div className="table-row">
                <span className="meta">Reviewer self-repair succeeded</span>
                <strong>{diagnostic.reviewer_self_repair_succeeded ? "true" : "false"}</strong>
              </div>
            )}
            {typeof diagnostic?.reviewer_self_repair_schema_repair_attempted === "boolean" && (
              <div className="table-row">
                <span className="meta">Self-repair schema repair attempted</span>
                <strong>{diagnostic.reviewer_self_repair_schema_repair_attempted ? "true" : "false"}</strong>
              </div>
            )}
            {typeof diagnostic?.reviewer_self_repair_schema_repair_succeeded === "boolean" && (
              <div className="table-row">
                <span className="meta">Self-repair schema repair succeeded</span>
                <strong>{diagnostic.reviewer_self_repair_schema_repair_succeeded ? "true" : "false"}</strong>
              </div>
            )}
            {diagnostic?.reviewer_self_repair_schema_repair_failure_reason && (
              <div className="table-row">
                <span className="meta">Self-repair schema repair failure</span>
                <strong>{diagnostic.reviewer_self_repair_schema_repair_failure_reason}</strong>
              </div>
            )}
            {diagnostic?.reviewer_self_repair_schema_repair_parse_failure_category && (
              <div className="table-row">
                <span className="meta">Self-repair schema repair parse failure</span>
                <strong>{diagnostic.reviewer_self_repair_schema_repair_parse_failure_category}</strong>
              </div>
            )}
            {reviewerMechanicalValidationIssue && (
              <div className="table-row">
                <span className="meta">Reviewer mechanical issue</span>
                <strong>{reviewerMechanicalValidationIssue}</strong>
              </div>
            )}
            {reviewerSelfRepairFailureReason && (
              <div className="table-row">
                <span className="meta">Reviewer self-repair failure</span>
                <strong>{reviewerSelfRepairFailureReason}</strong>
              </div>
            )}
            {typeof diagnostic?.backend_import_replacement_fallback_attempted === "boolean" && (
              <div className="table-row">
                <span className="meta">Backend import replacement fallback attempted</span>
                <strong data-testid="backend-fallback-attempted">{diagnostic.backend_import_replacement_fallback_attempted ? "true" : "false"}</strong>
              </div>
            )}
            {typeof diagnostic?.backend_import_replacement_fallback_succeeded === "boolean" && (
              <div className="table-row">
                <span className="meta">Backend import replacement fallback succeeded</span>
                <strong data-testid="backend-fallback-succeeded">{diagnostic.backend_import_replacement_fallback_succeeded ? "true" : "false"}</strong>
              </div>
            )}
            {diagnostic?.backend_import_replacement_fallback_reason_code && (
              <div className="table-row">
                <span className="meta">Backend fallback reason</span>
                <strong data-testid="backend-fallback-reason">{diagnostic.backend_import_replacement_fallback_reason_code}</strong>
              </div>
            )}
            {typeof diagnostic?.backend_generated_diff === "boolean" && (
              <div className="table-row">
                <span className="meta">Backend generated diff</span>
                <strong data-testid="backend-generated-diff">{diagnostic.backend_generated_diff ? "true" : "false"}</strong>
              </div>
            )}
            {diagnostic?.backend_generated_diff_checksum && (
              <div className="table-row">
                <span className="meta">Backend generated diff checksum</span>
                <strong className="checksum" data-testid="backend-generated-diff-checksum">{diagnostic.backend_generated_diff_checksum}</strong>
              </div>
            )}
            {diagnostic?.backend_generated_diff_changed_files && diagnostic.backend_generated_diff_changed_files.length > 0 && (
              <div className="table-row">
                <span className="meta">Backend changed files</span>
                <strong data-testid="backend-changed-files">{diagnostic.backend_generated_diff_changed_files.join(", ")}</strong>
              </div>
            )}
            {diagnostic?.backend_generated_diff_replacement_count != null && diagnostic.backend_generated_diff_replacement_count > 0 && (
              <div className="table-row">
                <span className="meta">Backend replacement count</span>
                <strong data-testid="backend-replacement-count">{diagnostic.backend_generated_diff_replacement_count}</strong>
              </div>
            )}
            {diagnostic?.deployment_alias_hash && (
              <div className="table-row">
                <span className="meta">Diagnostic deployment hash</span>
                <strong className="checksum">{diagnostic.deployment_alias_hash}</strong>
              </div>
            )}
            {contextChecksum && (
              <div className="table-row">
                <span className="meta">Context checksum</span>
                <strong className="checksum">{contextChecksum}</strong>
              </div>
            )}
            {reviewedDiffChecksum && (
              <div className="table-row">
                <span className="meta">Reviewed diff checksum</span>
                <strong className="checksum">{reviewedDiffChecksum}</strong>
              </div>
            )}
            <div className="table-row">
              <span className="meta">Reviewed diff</span>
              <strong>Not available</strong>
            </div>
            {diagnostic && (
              <>
                <div className="table-row">
                  <span className="meta">Backend validation path</span>
                  <strong>Unavailable</strong>
                </div>
                <div className="table-row">
                  <span className="meta">Retry status</span>
                  <strong>{diagnostic.retry_status === "retry_required" ? "Backend retry required" : "No retry action available"}</strong>
                </div>
              </>
            )}
            <div className="table-row">
              <span className="meta">Next action</span>
              <strong>{nextActionFromDiag ?? (diagnostic?.retry_status === "retry_required" ? "Backend retry required; no approve action available." : "Request backend retry or revision.")}</strong>
            </div>
          </div>
        </div>
        <div className="repair-proposal-side">
          <ModelRoleActivity invocations={invocations} loading={loading} error={error} />
        </div>
      </div>
    </section>
  );
}
