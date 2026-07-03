"use client";

import { useState } from "react";
import { RepairRevisionDialog } from "./RepairRevisionDialog";

export function RepairActionsBar({
  onViewDiff,
  onViewReviewerOpinion,
  onViewFilesChanged,
  onViewAttemptHistory,
  onRequestRevision,
  onApproveSandboxApply,
  revisionPending,
  approvePending,
  approveEnabled,
  revisionEnabled = true,
  checksumMismatch,
}: {
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
}) {
  const [showDialog, setShowDialog] = useState(false);

  async function handleSubmit(instruction: string) {
    await onRequestRevision(instruction);
    setShowDialog(false);
  }

  return (
    <div className="repair-actions-bar" data-testid="repair-actions-bar">
      <div className="repair-actions-readonly">
        <strong>View</strong>
        <button type="button" onClick={onViewDiff} data-testid="action-view-diff">
          View diff
        </button>
        <button type="button" onClick={onViewReviewerOpinion} data-testid="action-view-opinion">
          View reviewer opinion
        </button>
        <button type="button" onClick={onViewFilesChanged} data-testid="action-view-files">
          View files changed
        </button>
        <button type="button" onClick={onViewAttemptHistory} data-testid="action-view-history">
          View attempt history
        </button>
      </div>
      <div className="repair-actions-mutation">
        <strong>Actions</strong>
        <button
          type="button"
          onClick={() => setShowDialog(true)}
          disabled={revisionPending || !revisionEnabled}
          title={revisionEnabled ? "Request another reviewed repair proposal" : "Revision is not allowed by the current backend gate"}
          data-testid="action-request-revision"
        >
          {revisionPending ? "Requesting revision..." : "Request revision"}
        </button>
        <button
          type="button"
          onClick={onApproveSandboxApply}
          disabled={!approveEnabled || approvePending || checksumMismatch}
          title={
            checksumMismatch
              ? "Cannot approve: diff checksum mismatch detected"
              : approvePending
                ? "Approving and applying to sandbox..."
                : "Approve and apply reviewed repair to sandbox"
          }
          data-testid="action-approve-sandbox-apply"
        >
          {approvePending ? "Applying..." : "Approve sandbox apply"}
        </button>
      </div>
      <RepairRevisionDialog
        open={showDialog}
        onClose={() => setShowDialog(false)}
        onSubmit={handleSubmit}
        pending={revisionPending}
      />
    </div>
  );
}
