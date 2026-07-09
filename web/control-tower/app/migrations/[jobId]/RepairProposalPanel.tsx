"use client";

import { useEffect, useState } from "react";
import {
  getCurrentRepairProposal,
  getRepairProposalDiff,
  getRepairAttempts,
  requestRepairProposalRevision,
  approveRepairProposal,
} from "../../../lib/controlTowerApi";
import type {
  ReviewedDiffProposal,
  SafeDiffPreview as SafeDiffPreviewType,
  RepairAttemptSummary,
  RepairState,
} from "../../../lib/contracts";
import { ReviewedDiffTabs } from "./ReviewedDiffTabs";
import { RepairAttemptTimeline } from "./RepairAttemptTimeline";
import { RepairActionsBar } from "./RepairActionsBar";

type ProposalState =
  | { status: "loading" }
  | { status: "no-proposal"; repairState?: RepairState }
  | { status: "unavailable"; repairState: RepairState }
  | { status: "error"; message: string }
  | { status: "available"; proposal: ReviewedDiffProposal; repairState?: RepairState };

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

export function RepairProposalPanel({ jobId, repairRefreshKey }: { jobId: string; repairRefreshKey?: number }) {
  const [proposalState, setProposalState] = useState<ProposalState>({ status: "loading" });
  const [diffState, setDiffState] = useState<DiffState>({ status: "idle" });
  const [attemptsState, setAttemptsState] = useState<AttemptsState>({ status: "idle" });
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
          setProposalState({ status: "available", proposal: response.proposal, repairState: response.repair_state ?? undefined });
          setDiffState({ status: "loading" });
          setAttemptsState({ status: "loading" });
          const [diffResponse, attemptsResponse] = await Promise.all([
            getRepairProposalDiff(jobId, response.proposal.proposal_id).catch(() => null),
            getRepairAttempts(jobId).catch(() => null),
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
        } else if (response.repair_state) {
          if (
            response.repair_state.status === "unavailable" ||
            response.repair_state.status === "blocked" ||
            response.repair_state.status === "attempts_exhausted" ||
            response.repair_state.status === "error"
          ) {
            setProposalState({ status: "unavailable", repairState: response.repair_state });
          } else {
            setProposalState({ status: "no-proposal", repairState: response.repair_state });
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
  }, [jobId, repairRefreshKey]);

  async function refreshProposalData() {
    if (!jobId) return;
    try {
      const response = await getCurrentRepairProposal(jobId);
      if (response.proposal) {
        setProposalState({ status: "available", proposal: response.proposal });
        setDiffState({ status: "loading" });
        setAttemptsState({ status: "loading" });
        const [diffResponse, attemptsResponse] = await Promise.all([
          getRepairProposalDiff(jobId, response.proposal.proposal_id).catch(() => null),
          getRepairAttempts(jobId).catch(() => null),
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
      } else if (response.repair_state) {
        if (
          response.repair_state.status === "unavailable" ||
          response.repair_state.status === "blocked" ||
          response.repair_state.status === "attempts_exhausted" ||
          response.repair_state.status === "error"
        ) {
          setProposalState({ status: "unavailable", repairState: response.repair_state });
        } else {
          setProposalState({ status: "no-proposal", repairState: response.repair_state });
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
        await approveRepairProposal(jobId, state.proposal.proposal_id, {
          proposal_id: state.proposal.proposal_id,
          diff_checksum: state.proposal.diff_checksum,
          idempotency_key: crypto.randomUUID(),
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
        {proposalState.repairState?.status ? (
          <p className="meta">Repair state: {proposalState.repairState.status}</p>
        ) : null}
      </section>
    );
  }

  if (proposalState.status === "unavailable") {
    const rs = proposalState.repairState;
    return (
      <section className="panel" data-testid="repair-proposal-panel">
        <h2>Reviewed Repair</h2>
        <p className="meta">Reviewed repair unavailable</p>
        <p className="meta">No reviewed diff was created.</p>
        {rs.reason_code && <p className="meta">Reason: {rs.reason_code}</p>}
        {rs.detail && <p className="meta">Details: {rs.detail}</p>}
        {rs.created_at && <p className="meta">At: {rs.created_at}</p>}
        <p className="meta">No apply action is available.</p>
        {rs.allowed_actions?.includes("view_failure_summary") && (
          <p className="meta">See failure summary for details.</p>
        )}
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

  return (
    <section className="panel repair-proposal-panel" data-testid="repair-proposal-panel">
      <h2>Repair Proposal</h2>

      <div className="table-list">
        <div className="table-row">
          <span className="meta">Status</span>
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
        {proposal.diff_checksum && (
          <div className="table-row">
            <span className="meta">Diff checksum</span>
            <strong className="checksum">{proposal.diff_checksum}</strong>
          </div>
        )}
        {proposal.reviewer_verdict?.decision && (
          <div className="table-row">
            <span className="meta">Reviewer decision</span>
            <strong>{proposal.reviewer_verdict.decision}</strong>
          </div>
        )}
      </div>

      {proposal.failure_summary && (
        <div className="failure-summary" data-testid="failure-summary">
          <strong>Failure Summary</strong>
          <p className="meta">{proposal.failure_summary}</p>
        </div>
      )}

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
        approveEnabled={
          (proposal.status === "user_review_required" || proposal.status === "reviewer_accepted") &&
          (proposal.allowed_actions?.includes("approve_sandbox_apply") ||
            proposalState.repairState?.allowed_actions?.includes("approve_sandbox_apply")) &&
          diff?.checksum_mismatch !== true &&
          diff?.parse_status !== "unparseable" &&
          diff?.parse_status !== "hunk_count_mismatch"
        }
        checksumMismatch={diff?.checksum_mismatch ?? false}
        rejectDisabled={true}
      />
    </section>
  );
}
