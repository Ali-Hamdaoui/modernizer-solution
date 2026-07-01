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
  V2LlmInvocationEntry,
} from "../../../lib/contracts";
import { ReviewedDiffTabs } from "./ReviewedDiffTabs";
import { RepairAttemptTimeline } from "./RepairAttemptTimeline";
import { RepairActionsBar } from "./RepairActionsBar";
import { ModelRoleActivity } from "./ModelRoleActivity";
import { ValidationProgressPanel } from "./ValidationProgressPanel";

type ProposalState =
  | { status: "loading" }
  | { status: "no-proposal" }
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

export function RepairProposalPanel({ jobId }: { jobId: string }) {
  const [proposalState, setProposalState] = useState<ProposalState>({ status: "loading" });
  const [diffState, setDiffState] = useState<DiffState>({ status: "idle" });
  const [attemptsState, setAttemptsState] = useState<AttemptsState>({ status: "idle" });
  const [activityState, setActivityState] = useState<ActivityState>({ status: "idle" });
  const [showAttempts, setShowAttempts] = useState(false);
  const [revisionPending, setRevisionPending] = useState(false);
  const [approvePending, setApprovePending] = useState(false);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    async function load() {
      try {
        const response = await getCurrentRepairProposal(jobId);
        if (cancelled) return;
        if (response.proposal) {
          setProposalState({ status: "available", proposal: response.proposal });
          setDiffState({ status: "loading" });
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
          } else {
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
          setProposalState({ status: "no-proposal" });
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

  async function refreshProposalData() {
    if (!jobId) return;
    try {
      const response = await getCurrentRepairProposal(jobId);
      if (response.proposal) {
        setProposalState({ status: "available", proposal: response.proposal });
        setDiffState({ status: "loading" });
        setAttemptsState({ status: "loading" });
        setActivityState({ status: "loading" });
        const [diffResponse, attemptsResponse, activityResponse] = await Promise.all([
          getRepairProposalDiff(jobId, response.proposal.proposal_id).catch(() => null),
          getRepairAttempts(jobId).catch(() => null),
          getV2LlmActivity(jobId).catch(() => null),
        ]);
        if (diffResponse?.safe_diff_preview) {
          setDiffState({ status: "available", diff: diffResponse.safe_diff_preview });
        } else {
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
        setProposalState({ status: "no-proposal" });
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
    try {
      const state = proposalState;
      if (state.status !== "available") return;
      await requestRepairProposalRevision(jobId, state.proposal.proposal_id, {
        user_instruction: instruction,
        previous_diff_checksum: state.proposal.diff_checksum,
        previous_reviewer_verdict_id:
          state.proposal.reviewer_verdict?.reviewer_verdict_id ?? "",
      });
      await refreshProposalData();
    } catch {
      // Safe error display — no raw paths/stacks
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
      const reviewerVerdictId = state.proposal.reviewer_verdict?.reviewer_verdict_id;
      const gateId = state.proposal.gate_id;
      if (!reviewerVerdictId || !gateId) return;
      await approveRepairProposal(jobId, state.proposal.proposal_id, {
        proposal_id: state.proposal.proposal_id,
        diff_checksum: state.proposal.diff_checksum,
        reviewer_verdict_id: reviewerVerdictId,
        gate_id: gateId,
        idempotency_key: createIdempotencyKey(),
      });
      await refreshProposalData();
    } catch {
      // Safe error display — no raw paths/stacks
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
  const approveAllowed = proposal.allowed_actions.includes("approve_sandbox_apply");
  const revisionAllowed = proposal.allowed_actions.some((action) => (
    action === "request_revision" ||
    action === "request_repair_revision" ||
    action === "revise_repair_proposal"
  ));
  const latestMainSummary = [...llmInvocations]
    .filter((invocation) => (
      ["main", "proposer", "primary"].includes(invocation.role.toLowerCase()) ||
      ["repair_proposal", "revision_proposal"].includes(invocation.responsibility.toLowerCase())
    ))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]?.redacted_summary;

  return (
    <section className="panel repair-proposal-panel" data-testid="repair-proposal-panel">
      <div className="repair-proposal-layout">
        <div className="repair-proposal-main">
          <div className="repair-panel-kicker">Backend-governed repair gate</div>
          <h2>Reviewed Repair Proposal</h2>

          {proposal.failure_summary && (
            <div className="failure-summary" data-testid="failure-summary">
              <strong>Failure Summary</strong>
              <p className="meta">{proposal.failure_summary}</p>
            </div>
          )}

          <div className="main-diagnosis-summary" data-testid="main-model-diagnosis-summary">
            <strong>Main Model Diagnosis</strong>
            <p className="meta">
              {latestMainSummary || "Diagnosis summary will appear after backend model activity is recorded."}
            </p>
          </div>

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
            {proposal.diff_checksum && (
              <div className="table-row">
                <span className="meta">Reviewed diff checksum</span>
                <strong className="checksum">{proposal.diff_checksum}</strong>
              </div>
            )}
            {proposal.allowed_actions.length > 0 && (
              <div className="table-row">
                <span className="meta">Allowed actions</span>
                <strong>{proposal.allowed_actions.join(", ")}</strong>
              </div>
            )}
          </div>

          <ReviewedDiffTabs proposal={proposal} diff={diff} />

          {showAttempts && (
            <RepairAttemptTimeline attempts={attempts} />
          )}

          <RepairActionsBar
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
            approveEnabled={approveAllowed}
            revisionEnabled={revisionAllowed}
            checksumMismatch={diff?.checksum_mismatch ?? false}
            rejectDisabled={true}
          />
        </div>

        <div className="repair-proposal-side">
          <ModelRoleActivity
            invocations={llmInvocations}
            loading={activityState.status === "loading"}
            error={activityError}
          />
          <ValidationProgressPanel attempts={attempts} />
        </div>
      </div>
    </section>
  );
}
