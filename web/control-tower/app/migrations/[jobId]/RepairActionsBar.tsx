"use client";

import { useState } from "react";
import { RepairRevisionDialog } from "./RepairRevisionDialog";

export function RepairActionsBar({
  allowedActions,
  onViewDiff,
  onViewReviewerOpinion,
  onViewFilesChanged,
  onViewAttemptHistory,
  onRequestRevision,
  onApproveSandboxApply,
  revisionPending,
  approvePending,
  approveEnabled,
  revisionEnabled,
  checksumMismatch,
  directProposal,
  candidateDiff,
  hasAttemptHistory = false,
}: {
  allowedActions?: string[];
  onViewDiff: () => void;
  onViewReviewerOpinion: () => void;
  onViewFilesChanged: () => void;
  onViewAttemptHistory: () => void;
  onRequestRevision: (instruction: string) => Promise<void>;
  onApproveSandboxApply?: () => void;
  revisionPending: boolean;
  approvePending?: boolean;
  approveEnabled?: boolean;
  revisionEnabled?: boolean;
  checksumMismatch?: boolean;
  directProposal?: boolean;
  candidateDiff?: boolean;
  hasAttemptHistory?: boolean;
}) {
  const [showDialog, setShowDialog] = useState(false);
  const usingAllowedActions = Array.isArray(allowedActions);
  const allowed = new Set(allowedActions ?? []);
  const showRequestRevision = usingAllowedActions
    ? (
        allowed.has("request_revision") ||
        allowed.has("request_repair_revision") ||
        allowed.has("revise_repair_proposal")
      )
    : true;
  const showApprove = usingAllowedActions ? allowed.has("approve_sandbox_apply") : true;
  const showReadActions = usingAllowedActions
    ? (
        allowed.has("view_diff") ||
        allowed.has("view_reviewer_opinion") ||
        allowed.has("view_files_changed") ||
        allowed.has("ask_explanation") ||
        (hasAttemptHistory && allowed.has("view_attempt_history"))
      )
    : true;

  async function handleSubmit(instruction: string) {
    await onRequestRevision(instruction);
    setShowDialog(false);
  }

  return (
    <div className="repair-actions-bar" data-testid="repair-actions-bar">
      {showReadActions && (
        <div className="repair-actions-readonly">
          <strong>View</strong>
          {(!usingAllowedActions || allowed.has("view_diff")) && (
            <button type="button" onClick={onViewDiff} data-testid="action-view-diff">
              View diff
            </button>
          )}
          {(!usingAllowedActions || allowed.has("view_reviewer_opinion")) && (
            <button type="button" onClick={onViewReviewerOpinion} data-testid="action-view-opinion">
              View reviewer opinion
            </button>
          )}
          {(!usingAllowedActions || allowed.has("view_files_changed")) && (
            <button type="button" onClick={onViewFilesChanged} data-testid="action-view-files">
              View files changed
            </button>
          )}
          {(hasAttemptHistory && (!usingAllowedActions || allowed.has("view_attempt_history"))) && (
            <button type="button" onClick={onViewAttemptHistory} data-testid="action-view-history">
              View attempt history
            </button>
          )}
        </div>
      )}
      {(showRequestRevision || showApprove) && (
        <div className="repair-actions-mutation">
          <strong>Actions</strong>
          {showRequestRevision && (
            <button
              type="button"
              onClick={() => setShowDialog(true)}
              disabled={revisionPending || (!usingAllowedActions && revisionEnabled !== true)}
              title="Request another reviewed repair proposal"
              data-testid="action-request-revision"
            >
              {revisionPending ? "Requesting revision..." : "Request revision"}
            </button>
          )}
          {showApprove && (
            <button
              type="button"
              onClick={onApproveSandboxApply}
              disabled={approvePending || checksumMismatch || (!usingAllowedActions && approveEnabled !== true)}
              title={
                checksumMismatch
                  ? "Cannot approve: diff checksum mismatch detected"
                  : approvePending
                    ? (candidateDiff ? "Applying candidate diff..." : directProposal ? "Applying reviewer diff..." : "Applying...")
                    : candidateDiff
                      ? "Backend will apply the exact candidate diff shown above, then rerun validation"
                      : directProposal
                        ? "Backend will apply the exact reviewer diff shown above, then rerun validation"
                        : "Approve and apply reviewed repair to sandbox"
              }
              data-testid="action-approve-sandbox-apply"
            >
              {approvePending
                ? (candidateDiff ? "Applying candidate diff..." : directProposal ? "Applying reviewer diff..." : "Applying...")
                : candidateDiff
                  ? "Apply candidate diff"
                  : directProposal
                    ? "Apply reviewer diff"
                    : "Approve sandbox apply"}
            </button>
          )}
        </div>
      )}
      <RepairRevisionDialog
        open={showDialog}
        onClose={() => setShowDialog(false)}
        onSubmit={handleSubmit}
        pending={revisionPending}
      />
    </div>
  );
}
