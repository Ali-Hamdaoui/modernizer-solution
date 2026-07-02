"use client";

import type { V2LlmInvocationEntry } from "../../../lib/contracts";

type ActivityPhase = {
  key: string;
  label: string;
  status: string;
  detail: string;
  invocation: V2LlmInvocationEntry | null;
};

function roleFallbackLabel(role: string): string {
  const normalized = role.trim().toLowerCase();
  if (normalized === "main" || normalized === "proposer" || normalized === "primary") {
    return "Main Model";
  }
  if (normalized === "reviewer") return "Reviewer Model";
  if (normalized === "fallback") return "Fallback Model";
  return "Model";
}

function modelLabel(invocation: V2LlmInvocationEntry | null, fallbackRole: string): string {
  if (!invocation) return roleFallbackLabel(fallbackRole);
  return invocation.model_display_name || roleFallbackLabel(invocation.role);
}

function statusLabel(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === "started" || normalized === "running") return "running";
  if (normalized === "completed") return "completed";
  if (normalized === "fallback") return "completed with fallback";
  if (normalized === "failed") return "failed";
  if (normalized === "request_revision") return "needs revision";
  return normalized || "pending";
}

function statusClass(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === "completed" || normalized === "fallback" || normalized === "accepted") return "completed";
  if (normalized === "failed" || normalized === "rejected" || normalized === "schema invalid") return "failed";
  if (normalized === "request_revision" || normalized === "needs_revision") return "blocked";
  if (normalized === "started" || normalized === "running") return "running";
  if (normalized === "not run") return "pending";
  return "pending";
}

function newestFor(
  invocations: V2LlmInvocationEntry[],
  roles: string[],
  responsibilities: string[],
): V2LlmInvocationEntry | null {
  const roleSet = new Set(roles.map((r) => r.toLowerCase()));
  const responsibilitySet = new Set(responsibilities.map((r) => r.toLowerCase()));
  return invocations.find((invocation) => (
    roleSet.has(invocation.role.toLowerCase()) ||
    responsibilitySet.has(invocation.responsibility.toLowerCase())
  )) ?? null;
}

export function buildRepairModelActivity(invocations: V2LlmInvocationEntry[]): ActivityPhase[] {
  const sorted = [...invocations].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const proposer = newestFor(sorted, ["main", "proposer", "primary"], ["repair_proposal", "revision_proposal"]);
  const reviewer = newestFor(sorted, ["reviewer"], ["repair_review", "revision_review"]);

  const isProposerSchemaInvalid = proposer?.redacted_error === "proposer_schema_invalid"
    || (proposer?.redacted_summary ?? "").toLowerCase().includes("schema validation")
    || (proposer?.redacted_summary ?? "").toLowerCase().includes("schema invalid");
  const reviewerRun = !isProposerSchemaInvalid && reviewer;

  return [
    {
      key: "main-analyzing",
      label: `${modelLabel(proposer, "main")} analyzing failure`,
      status: proposer ? statusLabel(proposer.status) : "pending",
      detail: proposer?.redacted_summary || "Waiting for backend failure evidence and repair context.",
      invocation: proposer,
    },
    {
      key: "main-proposing",
      label: `${modelLabel(proposer, "main")} producing internal draft`,
      status: proposer ? statusLabel(proposer.status) : "pending",
      detail: "Internal draft is sent to reviewer automatically and is not user approval authority.",
      invocation: proposer,
    },
    {
      key: "reviewer-reviewing",
      label: `${modelLabel(reviewerRun || null, "reviewer")} reviewing proposal`,
      status: reviewerRun ? statusLabel(reviewerRun.status) : (isProposerSchemaInvalid ? "not run" : "pending"),
      detail: reviewerRun
        ? (reviewerRun.redacted_summary || "Reviewer checks the proposal, risk, policy, and checksum binding.")
        : (isProposerSchemaInvalid
          ? "Reviewer was not invoked because Main Model output failed schema validation."
          : "Reviewer checks the proposal, risk, policy, and checksum binding."),
      invocation: reviewerRun || null,
    },
  ];
}

export function ModelRoleActivity({
  invocations,
  loading,
  error,
}: {
  invocations: V2LlmInvocationEntry[];
  loading: boolean;
  error: string | null;
}) {
  const phases = buildRepairModelActivity(invocations);

  return (
    <aside className="model-role-activity" data-testid="model-role-activity" aria-label="Repair model activity">
      <div className="repair-side-header">
        <span className="meta">Automatic model trace</span>
        {loading && <span className="status-badge running" data-testid="model-activity-loading">running</span>}
        {error && <span className="status-badge failed" role="alert">failed</span>}
      </div>
      <h3>Repair Review Gate</h3>
      {error && <p className="warning-text">Model activity unavailable: {error}</p>}
      <div className="model-activity-list">
        {phases.map((phase) => (
          <div key={phase.key} className="model-activity-row" data-testid="model-activity-row">
            <span className={`activity-dot ${statusClass(phase.status)}`} aria-hidden="true" />
            <div>
              <div className="model-activity-title">
                <strong>{phase.label}</strong>
                <span className={`status-badge ${statusClass(phase.status)}`}>
                  {statusLabel(phase.status)}
                </span>
              </div>
              <p className="meta">{phase.detail}</p>
              {phase.invocation?.fallback_used && (
                <p className="meta">Fallback model used.</p>
              )}
              {phase.invocation?.redacted_error && (
                <p className="warning-text">{phase.invocation.redacted_error}</p>
              )}
              {phase.invocation?.provider_alias && (
                <p className="checksum">
                  Provider alias: {phase.invocation.provider_alias}
                  {phase.invocation.deployment_alias_hash ? ` / deployment hash ${phase.invocation.deployment_alias_hash}` : ""}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

