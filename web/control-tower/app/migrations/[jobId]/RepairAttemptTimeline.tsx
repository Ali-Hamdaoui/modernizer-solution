"use client";

import type { RepairAttemptSummary } from "../../../lib/contracts";

function attemptStatusLabel(status: string): string {
  return status.replace(/_/g, " ").toUpperCase();
}

export function RepairAttemptTimeline({
  attempts,
}: {
  attempts: RepairAttemptSummary[];
}) {
  if (attempts.length === 0) {
    return (
      <div className="attempt-timeline-empty" data-testid="attempt-timeline-empty">
        <p className="meta">No repair attempts yet.</p>
      </div>
    );
  }

  return (
    <div className="attempt-timeline" data-testid="attempt-timeline">
      <strong>Repair Attempts</strong>
      {attempts.map((attempt) => (
        <div key={attempt.proposal_id} className="attempt-entry" data-testid="attempt-entry">
          <div className="stage-header">
            <span className="meta">Attempt {attempt.attempt_number ?? "?"}</span>
            {attempt.revision_number != null && (
              <span className="meta">Revision {attempt.revision_number}</span>
            )}
            <span className={`status-badge ${attempt.status}`}>
              {attemptStatusLabel(attempt.status)}
            </span>
          </div>
          <p className="meta">Proposal: {attempt.proposal_id}</p>
          {attempt.gate_id && <p className="meta">Gate: {attempt.gate_id}</p>}
          {attempt.diff_checksum && <p className="checksum">Diff checksum: {attempt.diff_checksum}</p>}
          {attempt.status_reason && <p className="meta">Reason: {attempt.status_reason}</p>}
          {attempt.created_at && <p className="meta">{new Date(attempt.created_at).toLocaleString()}</p>}
        </div>
      ))}
    </div>
  );
}
