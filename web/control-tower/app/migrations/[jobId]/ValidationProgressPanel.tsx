"use client";

import type { RepairAttemptSummary } from "../../../lib/contracts";

function latestAttempt(attempts: RepairAttemptSummary[]): RepairAttemptSummary | null {
  return [...attempts].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
}

function normalize(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase();
}

function isPatchApplyFailure(reasonCode: string): boolean {
  return reasonCode === "patch_apply_failed" || reasonCode === "patch_check_failed";
}

function phaseStatus(
  phase: "apply" | "rebuild" | "test" | "continue",
  attempt: RepairAttemptSummary | null,
  reasonCode?: string | null,
): string {
  if (!attempt) return "pending";
  const applyStatus = normalize(attempt.apply_status);
  const rerunStatus = normalize(attempt.rerun_status);
  const gateStatus = normalize(attempt.next_gate_status);
  const normalizedReasonCode = normalize(reasonCode);
  const directApplyFailure = isPatchApplyFailure(normalizedReasonCode);
  if (phase === "apply") {
    if (directApplyFailure) return "failed";
    if (applyStatus.includes("applied") || normalize(attempt.status).includes("applied")) return "completed";
    if (applyStatus.includes("fail") || normalize(attempt.status).includes("approve_failed")) return "failed";
    return "pending";
  }
  if (phase === "rebuild") {
    if (directApplyFailure) return "not started";
    if (rerunStatus.includes("passed") || rerunStatus.includes("validation_passed")) return "completed";
    if (rerunStatus.includes("failed") || rerunStatus.includes("validation_failed")) return "failed";
    return applyStatus.includes("applied") ? "running" : "pending";
  }
  if (phase === "test") {
    if (directApplyFailure) return "not started";
    if (rerunStatus.includes("passed") || rerunStatus.includes("validation_passed")) return "validation passed";
    if (rerunStatus.includes("failed") || rerunStatus.includes("validation_failed")) return "validation failed";
    return applyStatus.includes("applied") ? "running" : "pending";
  }
  if (directApplyFailure) return "blocked";
  if (gateStatus.includes("resolved") || rerunStatus.includes("passed")) return "completed";
  if (rerunStatus.includes("failed")) return "blocked";
  return "pending";
}

function statusCopy(
  phase: "apply" | "rebuild" | "test" | "continue",
  status: string,
  reasonCode?: string | null,
): string {
  const normalizedReasonCode = normalize(reasonCode);
  if (phase === "rebuild" || phase === "test") {
    if (isPatchApplyFailure(normalizedReasonCode) && status === "not started") {
      return "not started";
    }
  }
  if (phase === "continue" && isPatchApplyFailure(normalizedReasonCode) && status === "blocked") {
    return "blocked";
  }
  if (phase === "continue" && status === "completed") {
    return "continuing";
  }
  return status;
}

function statusClass(status: string): string {
  if (status === "completed" || status === "validation passed" || status === "continuing") return "completed";
  if (status === "failed" || status === "validation failed") return "failed";
  if (status === "running") return "running";
  if (status === "blocked") return "blocked";
  return "pending";
}

export function ValidationProgressPanel({
  attempts,
  proposalStatus,
  unavailableSummary,
  reasonCode,
}: {
  attempts: RepairAttemptSummary[];
  proposalStatus?: string;
  unavailableSummary?: string;
  reasonCode?: string | null;
}) {
  if (attempts.length === 0) {
    return null;
  }
  const attempt = latestAttempt(attempts);
  const normalizedReasonCode = normalize(reasonCode);
  const applyStatus = normalize(attempt?.apply_status);
  const rerunStatus = normalize(attempt?.rerun_status);
  const isPatchFailure = isPatchApplyFailure(normalizedReasonCode);
  const isPatchApplyFailed = normalizedReasonCode === "patch_apply_failed";
  const isPatchCheckFailed = normalizedReasonCode === "patch_check_failed";
  const isRerunPassed = rerunStatus.includes("passed") || rerunStatus.includes("validation_passed");
  const isRerunFailed = rerunStatus.includes("failed") || rerunStatus.includes("validation_failed");
  const summaryCopy = isPatchApplyFailed
    ? "Patch apply failed after approval. Rebuild/test were not started."
    : isPatchCheckFailed
      ? "Patch precheck failed. Rebuild/test were not started."
      : isRerunPassed
        ? "Validation passed; migration continuing."
        : isRerunFailed
          ? "Validation failed after apply."
          : null;
  const phases = [
    ["Applying reviewed diff to sandbox", phaseStatus("apply", attempt, reasonCode)],
    ["Rebuilding", phaseStatus("rebuild", attempt, reasonCode)],
    ["Running tests", phaseStatus("test", attempt, reasonCode)],
    ["Migration continuing", phaseStatus("continue", attempt, reasonCode)],
  ] as const;

  return (
    <aside className="validation-progress-panel" data-testid="validation-progress-panel">
      <span className="meta">Backend validation path</span>
      <h3>Apply, Rebuild, Test</h3>
      {summaryCopy && <p className="warning-text">{summaryCopy}</p>}
      <div className="validation-phase-list">
        {phases.map(([label, status]) => (
          <div key={label} className="validation-phase-row" data-testid="validation-phase-row">
            <span className={`activity-dot ${statusClass(status)}`} aria-hidden="true" />
            <strong>{label}</strong>
            <span className={`status-badge ${statusClass(status)}`}>{status === "pending" ? "Waiting for your approval" : statusCopy(label === "Applying reviewed diff to sandbox" ? "apply" : label === "Rebuilding" ? "rebuild" : label === "Running tests" ? "test" : "continue", status, reasonCode)}</span>
          </div>
        ))}
      </div>
      {attempt?.remaining_attempts != null && (
        <p className="meta">Remaining attempts: {attempt.remaining_attempts}</p>
      )}
      {attempt?.status_reason && <p className="warning-text">{attempt.status_reason}</p>}
      {!isPatchFailure && applyStatus.includes("applied") && rerunStatus.includes("passed") && (
        <p className="meta">Validation passed; migration continuing.</p>
      )}
    </aside>
  );
}

