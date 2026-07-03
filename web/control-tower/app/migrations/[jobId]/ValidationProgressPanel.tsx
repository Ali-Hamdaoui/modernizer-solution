"use client";

import type { RepairAttemptSummary } from "../../../lib/contracts";

function latestAttempt(attempts: RepairAttemptSummary[]): RepairAttemptSummary | null {
  return [...attempts].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
}

function normalize(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase();
}

function phaseStatus(phase: "apply" | "rebuild" | "test" | "continue", attempt: RepairAttemptSummary | null): string {
  if (!attempt) return "pending";
  const applyStatus = normalize(attempt.apply_status);
  const rerunStatus = normalize(attempt.rerun_status || attempt.status);
  const gateStatus = normalize(attempt.next_gate_status);
  if (phase === "apply") {
    if (applyStatus.includes("applied") || normalize(attempt.status).includes("applied")) return "completed";
    if (applyStatus.includes("fail") || normalize(attempt.status).includes("approve_failed")) return "failed";
    return "pending";
  }
  if (phase === "rebuild") {
    if (rerunStatus.includes("passed") || rerunStatus.includes("validation_passed")) return "completed";
    if (rerunStatus.includes("failed") || rerunStatus.includes("validation_failed")) return "failed";
    return applyStatus.includes("applied") ? "running" : "pending";
  }
  if (phase === "test") {
    if (rerunStatus.includes("passed") || rerunStatus.includes("validation_passed")) return "validation passed";
    if (rerunStatus.includes("failed") || rerunStatus.includes("validation_failed")) return "validation failed";
    return applyStatus.includes("applied") ? "running" : "pending";
  }
  if (gateStatus.includes("resolved") || rerunStatus.includes("passed")) return "completed";
  if (rerunStatus.includes("failed")) return "blocked";
  return "pending";
}

function statusClass(status: string): string {
  if (status === "completed" || status === "validation passed") return "completed";
  if (status === "failed" || status === "validation failed") return "failed";
  if (status === "running") return "running";
  if (status === "blocked") return "blocked";
  return "pending";
}

export function ValidationProgressPanel({
  attempts,
  proposalStatus,
  unavailableSummary,
}: {
  attempts: RepairAttemptSummary[];
  proposalStatus?: string;
  unavailableSummary?: string;
}) {
  const attempt = latestAttempt(attempts);
  const waitingForApproval = proposalStatus === "user_review_required" && !attempt;
  const noProposal = !proposalStatus && attempts.length === 0;
  const phases = [
    ["Applying reviewed diff to sandbox", phaseStatus("apply", attempt)],
    ["Rebuilding", phaseStatus("rebuild", attempt)],
    ["Running tests", phaseStatus("test", attempt)],
    ["Migration continuing", phaseStatus("continue", attempt)],
  ] as const;

  if (noProposal) {
    return (
      <aside className="validation-progress-panel" data-testid="validation-progress-panel">
        <span className="meta">Backend validation path</span>
        <h3>Reviewed Repair Unavailable</h3>
        <p className="meta" data-testid="no-proposal-message">
          {unavailableSummary ?? "Reviewed diff is not available for backend validation."}
        </p>
        <div className="validation-phase-list">
          <div className="validation-phase-row" data-testid="validation-phase-row">
            <span className="activity-dot blocked" aria-hidden="true" />
            <strong>Backend validation path</strong>
            <span className="status-badge blocked">Not available</span>
          </div>
        </div>
      </aside>
    );
  }

  if (waitingForApproval) {
    return (
      <aside className="validation-progress-panel" data-testid="validation-progress-panel">
        <span className="meta">Backend validation path</span>
        <h3>Apply, Rebuild, Test</h3>
        <div className="validation-phase-list">
          {phases.map(([label]) => (
            <div key={label} className="validation-phase-row" data-testid="validation-phase-row">
              <span className="activity-dot pending" aria-hidden="true" />
              <strong>{label}</strong>
              <span className="status-badge pending" data-testid="waiting-for-approval">Waiting for your approval</span>
            </div>
          ))}
        </div>
      </aside>
    );
  }

  return (
    <aside className="validation-progress-panel" data-testid="validation-progress-panel">
      <span className="meta">Backend validation path</span>
      <h3>Apply, Rebuild, Test</h3>
      <div className="validation-phase-list">
        {phases.map(([label, status]) => (
          <div key={label} className="validation-phase-row" data-testid="validation-phase-row">
            <span className={`activity-dot ${statusClass(status)}`} aria-hidden="true" />
            <strong>{label}</strong>
            <span className={`status-badge ${statusClass(status)}`}>{status === "pending" ? "Waiting for your approval" : status}</span>
          </div>
        ))}
      </div>
      {attempt?.remaining_attempts != null && (
        <p className="meta">Remaining attempts: {attempt.remaining_attempts}</p>
      )}
      {attempt?.status_reason && <p className="warning-text">{attempt.status_reason}</p>}
    </aside>
  );
}

