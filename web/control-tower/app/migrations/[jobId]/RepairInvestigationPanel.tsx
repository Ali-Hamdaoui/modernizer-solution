"use client";

import { useState } from "react";
import type {
  V2RepairApplyCandidateResponse,
  V2RepairApprovalInput,
  V2RepairAttemptActionRequest,
  V2RepairAttemptResponse,
} from "../../../lib/contracts";

export function RepairInvestigationPanel({
  attempt,
  attempts,
  candidate,
  busy,
  onApprove,
  onApply,
  onAction,
}: {
  attempt: V2RepairAttemptResponse;
  attempts: V2RepairAttemptResponse[];
  candidate?: V2RepairApplyCandidateResponse | null;
  busy: boolean;
  onApprove: (candidate: V2RepairApplyCandidateResponse, decision: V2RepairApprovalInput) => Promise<void>;
  onApply: (candidate: V2RepairApplyCandidateResponse) => Promise<void>;
  onAction: (request: V2RepairAttemptActionRequest) => Promise<void>;
}) {
  const [justification, setJustification] = useState("");
  const [riskAcknowledged, setRiskAcknowledged] = useState(false);
  const [guidance, setGuidance] = useState("");
  const [contextRequest, setContextRequest] = useState("");
  const [manualDiff, setManualDiff] = useState("");
  const [manualJustification, setManualJustification] = useState("");
  const hardBlocked = attempt.applicability_status !== "applicable";
  const approvalMode = candidate?.approval_mode_required ?? attempt.approval_mode_required;
  const displayDiff = attempt.display_proposed_diff ?? attempt.exact_proposed_diff;
  const exactDiffChecksum = attempt.exact_diff_checksum ?? attempt.diff_checksum;
  const riskCodes = attempt.reviewer_reason_codes.length > 0
    ? attempt.reviewer_reason_codes
    : attempt.advisory_warnings.length > 0
      ? attempt.advisory_warnings
      : ["reviewer_advisory_risk"];
  const requiresRiskDecision = approvalMode === "acknowledged_risk_approval" || approvalMode === "reviewer_override_approval";
  const approvalReady = !requiresRiskDecision || (justification.trim().length > 0 && riskAcknowledged);

  function action(actionName: V2RepairAttemptActionRequest["action"], extra: Partial<V2RepairAttemptActionRequest> = {}) {
    return onAction({
      action: actionName,
      expected_attempt_checksum: attempt.attempt_checksum,
      ...extra,
    });
  }

  return (
    <section className="repair-investigation" data-testid="repair-investigation-panel">
      <h3>Repair Investigation · Attempt {attempt.attempt_number}</h3>

      <div className="trace-section" data-testid="repair-failure-evidence">
        <strong>1. Failure Evidence</strong>
        <p className="meta">{attempt.failure_summary || "Failure evidence is persisted for this attempt."}</p>
        <p className="meta">Stage {attempt.stage_index} · command {attempt.failing_command || attempt.command_id || "n/a"}</p>
        {attempt.failing_test && <p className="meta">Failing test: {attempt.failing_test}</p>}
        {attempt.exception && <p className="meta">Compiler/exception evidence: {attempt.exception}</p>}
        {attempt.stack_trace_preview && <pre className="diff-preview"><code>{attempt.stack_trace_preview}</code></pre>}
        <p className="meta">Logs: {Object.entries(attempt.log_artifact_references).map(([kind, ref]) => `${kind}: ${ref}`).join(" · ") || "none listed"}</p>
        <p className="checksum">Evidence checksum: {attempt.failure_evidence_checksum || "n/a"}</p>
        <p className="checksum">Context checksum: {attempt.context_checksum || "n/a"}</p>
        <p className="meta">Context sources: {attempt.source_evidence.map((item) => item.path).filter(Boolean).join(", ") || "none listed"}</p>
      </div>

      <div className="trace-section" data-testid="repair-proposed-repair">
        <strong>2. Proposed Repair</strong>
        <p className="meta">Source: {attempt.attempt_source.toUpperCase()} · state: {attempt.repair_workflow_state}</p>
        <p className="meta">Root cause: {attempt.proposer_root_cause || "Proposal contract was invalid or unavailable."}</p>
        <p className="meta">Strategy: {attempt.proposer_strategy || "No validated strategy."}</p>
        <p className="meta">Changed files: {attempt.changed_files.join(", ") || "none"}</p>
        <p className="meta">Hard gate: {attempt.hard_gate_status}</p>
        {attempt.hard_gate_reason_codes.length > 0 && (
          <p className="meta" data-testid="hard-gate-reason-codes">Technical block reasons: {attempt.hard_gate_reason_codes.join(", ")}</p>
        )}
        <p className="checksum">Exact diff checksum: {exactDiffChecksum || "n/a"}</p>
        {attempt.display_diff_redacted && (
          <p className="warning-text" data-testid="repair-display-diff-redacted">
            Public display diff was redacted. Apply uses the exact backend-persisted diff bound to this checksum.
          </p>
        )}
        <pre className="diff-preview" data-testid="repair-exact-diff"><code>{displayDiff || "No canonical Git diff was validated for this attempt."}</code></pre>
      </div>

      <div className="trace-section" data-testid="repair-reviewer-assessment">
        <strong>3. Reviewer Assessment</strong>
        <p className="meta">Outcome: {attempt.reviewer_outcome.replace(/_/g, " ")}</p>
        <p className="meta">Available: {attempt.reviewer_availability ? "yes" : "no"} · risk: {attempt.reviewer_risk_level || "unknown"}</p>
        <p className="meta">Reason codes: {attempt.reviewer_reason_codes.join(", ") || "none"}</p>
        <p className="meta">Summary: {attempt.reviewer_summary || "No validated reviewer summary was available."}</p>
        <p className="meta">Recommended action: {attempt.reviewer_recommended_action || "operator review"}</p>
        <p className="checksum">Reviewed context: {attempt.reviewed_context_checksum || "n/a"}</p>
        <p className="checksum">Reviewed proposal: {attempt.reviewed_proposal_checksum || "n/a"}</p>
        <p className="checksum">Reviewer output: {attempt.reviewer_output_checksum || "not available"}</p>
        <p className="meta">This advisory outcome remains immutable and visible after any operator override.</p>
      </div>

      <div className="trace-section" data-testid="repair-operator-actions">
        <strong>4. Operator Actions</strong>
        {hardBlocked && (
          <p className="warning-text" data-testid="hard-gate-no-override">This exact diff is technically blocked. Apply and reviewer override are unavailable.</p>
        )}
        {!hardBlocked && candidate && candidate.approval_enabled && (
          <div>
            {requiresRiskDecision && (
              <>
                <p className="warning-text">
                  {approvalMode === "reviewer_override_approval"
                    ? `The reviewer ${attempt.reviewer_outcome === "unavailable" ? "was unavailable" : "rejected this repair"}. An override is permanently recorded.`
                    : "The reviewer accepted with concerns. Acknowledgment is required."}
                </p>
                <textarea
                  aria-label="Operator approval justification"
                  value={justification}
                  onChange={(event) => setJustification(event.target.value)}
                  placeholder="Explain why sandbox application is authorized despite the advisory risks."
                  maxLength={4000}
                />
                <label>
                  <input type="checkbox" checked={riskAcknowledged} onChange={(event) => setRiskAcknowledged(event.target.checked)} />
                  Acknowledge risks: {riskCodes.join(", ")}
                </label>
              </>
            )}
            <button
              type="button"
              disabled={busy || !approvalReady}
              data-testid="approve-repair-decision"
              onClick={() => onApprove(candidate, {
                approval_mode: (approvalMode || "normal_approval") as V2RepairApprovalInput["approval_mode"],
                operator_justification: justification.trim(),
                acknowledged_risk_codes: requiresRiskDecision ? riskCodes : [],
              })}
            >
              {approvalMode === "reviewer_override_approval" ? "Override reviewer and approve for sandbox" : approvalMode === "acknowledged_risk_approval" ? "Approve with acknowledged risks" : "Approve for sandbox"}
            </button>
          </div>
        )}
        {candidate?.apply_enabled && (
          <button type="button" disabled={busy} onClick={() => onApply(candidate)}>Apply approved repair to sandbox</button>
        )}

        <textarea aria-label="Corrected proposal guidance" value={guidance} onChange={(event) => setGuidance(event.target.value)} placeholder="Guide the next proposal, for example: do not modify tests; inspect production code." maxLength={4000} />
        <button type="button" disabled={busy || !guidance.trim()} onClick={() => action("request_corrected_proposal", { operator_guidance: guidance.trim() })}>Request corrected proposal</button>

        <input aria-label="Additional context request" value={contextRequest} onChange={(event) => setContextRequest(event.target.value)} placeholder="Sandbox-relative path, Java class, symbol, module, or POM" />
        <button type="button" disabled={busy || !contextRequest.trim()} onClick={() => action("request_additional_context", { requested_context: contextRequest.split(/[\n,]/).map((value) => value.trim()).filter(Boolean) })}>Add context and create attempt</button>

        <textarea aria-label="Manual Git diff" value={manualDiff} onChange={(event) => setManualDiff(event.target.value)} placeholder="Paste an exact canonical Git unified diff beginning with diff --git" />
        <textarea aria-label="Manual diff justification" value={manualJustification} onChange={(event) => setManualJustification(event.target.value)} placeholder="Operator investigation and justification" maxLength={4000} />
        <button type="button" disabled={busy || !manualDiff.trim() || !manualJustification.trim()} onClick={() => action("submit_manual_diff", { manual_diff: manualDiff, operator_justification: manualJustification.trim() })}>Submit manual Git diff</button>

        <button type="button" disabled={busy} onClick={() => action("reject_current_attempt")}>Reject current attempt</button>
        <button type="button" disabled={busy} onClick={() => action("mark_manual_remediation_required")}>Mark manual remediation required</button>
        {attempt.resume_enabled && <button type="button" disabled={busy} onClick={() => action("resume_from_repair_checkpoint")}>Resume from repair checkpoint</button>}
      </div>

      <div className="trace-section" data-testid="repair-artifact-references">
        <strong>Artifacts and Previous Attempts</strong>
        <p className="meta">Artifacts: {Object.entries(attempt.artifact_references).map(([kind, ref]) => `${kind}: ${ref}`).join(" · ") || "none listed"}</p>
        <details>
          <summary>View previous attempts ({Math.max(0, attempts.length - 1)})</summary>
          {attempts.filter((item) => item.attempt_id !== attempt.attempt_id).map((item) => (
            <p className="meta" key={item.attempt_id}>Attempt {item.attempt_number}: {item.applicability_status} · {item.reviewer_outcome} · {item.repair_workflow_state}</p>
          ))}
        </details>
      </div>

      <p className="meta">
        Changes apply only to the sandbox; legacy source is protected. Approval does not prove correctness.
        Maven/tests and post-repair verification determine the result, rollback occurs on verification failure,
        and every prior attempt remains available.
      </p>
    </section>
  );
}
