"use client";

const FUTURE_ACTIONS = [
  { label: "Request revision", description: "Coming in PR-D", disabled: true },
  { label: "Approve sandbox apply", description: "Coming in PR-E", disabled: true },
  { label: "Reject", description: "Coming in PR-D/PR-E", disabled: true },
];

export function RepairActionsBar({
  onViewDiff,
  onViewReviewerOpinion,
  onViewFilesChanged,
  onViewAttemptHistory,
}: {
  onViewDiff: () => void;
  onViewReviewerOpinion: () => void;
  onViewFilesChanged: () => void;
  onViewAttemptHistory: () => void;
}) {
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
      <div className="repair-actions-future">
        <strong>Future</strong>
        {FUTURE_ACTIONS.map((action) => (
          <button
            key={action.label}
            type="button"
            disabled={action.disabled}
            title={action.description}
            data-testid={`action-future-${action.label.toLowerCase().replace(/\s+/g, "-")}`}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
