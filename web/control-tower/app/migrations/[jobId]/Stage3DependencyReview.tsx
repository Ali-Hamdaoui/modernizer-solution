"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  getStage3Pom,
  getStage3DependencyReview,
  proposePomChange,
  applyPomChange,
  listPomChanges,
  getPomValidationResult,
  rollbackPomChange,
} from "../../../lib/controlTowerApi";
import type {
  PomView,
  PomDependencyReview,
  PomChangeProposal,
  PomApplyResult,
  PomChangeRecordSummary,
  PomValidationRun,
  PomRollbackResult,
  PomDependencyFinding,
} from "../../../lib/contracts";

// ── Props ───────────────────────────────────────────────────────────────

type Stage3DependencyReviewProps = {
  jobId: string;
  stage3Completed: boolean;
  events?: Array<{ type: string; payload?: Record<string, unknown> }>;
};

// ── Helpers ─────────────────────────────────────────────────────────────

function riskBadgeColor(risk: string): string {
  switch (risk) {
    case "low":
      return "bg-green-100 text-green-800 border-green-300";
    case "medium":
      return "bg-yellow-100 text-yellow-800 border-yellow-300";
    case "high":
      return "bg-orange-100 text-orange-800 border-orange-300";
    case "blocked":
      return "bg-red-100 text-red-800 border-red-300";
    case "evidence_insufficient":
      return "bg-gray-100 text-gray-600 border-gray-300";
    default:
      return "bg-gray-100 text-gray-600 border-gray-300";
  }
}

function statusBadgeColor(status: string): string {
  switch (status) {
    case "applied_pending_validation":
    case "validation_running":
      return "bg-blue-100 text-blue-800 border-blue-300";
    case "validated_passed":
      return "bg-green-100 text-green-800 border-green-300";
    case "validated_failed":
      return "bg-red-100 text-red-800 border-red-300";
    case "rolled_back":
      return "bg-gray-100 text-gray-600 border-gray-300";
    default:
      return "bg-gray-100 text-gray-600 border-gray-300";
  }
}

// ── Main component ──────────────────────────────────────────────────────

export default function Stage3DependencyReview({
  jobId,
  stage3Completed,
  events,
}: Stage3DependencyReviewProps) {
  const [activeTab, setActiveTab] = useState<string>("pom");
  const [pomView, setPomView] = useState<PomView | null>(null);
  const [review, setReview] = useState<PomDependencyReview | null>(null);
  const [proposal, setProposal] = useState<PomChangeProposal | null>(null);
  const [applyResult, setApplyResult] = useState<PomApplyResult | null>(null);
  const [changes, setChanges] = useState<PomChangeRecordSummary[]>([]);
  const [validation, setValidation] = useState<PomValidationRun | null>(null);
  const [rollbackResult, setRollbackResult] = useState<PomRollbackResult | null>(null);

  const [loading, setLoading] = useState(false);
  const [pomLoading, setPomLoading] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userInput, setUserInput] = useState("");
  const [applying, setApplying] = useState(false);

  // ── Load POM ──────────────────────────────────────────────────────────

  const loadPom = useCallback(async () => {
    setPomLoading(true);
    setError(null);
    try {
      const view = await getStage3Pom(jobId);
      setPomView(view);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load POM");
    } finally {
      setPomLoading(false);
    }
  }, [jobId]);

  // ── Load review ───────────────────────────────────────────────────────

  const loadReview = useCallback(async () => {
    setReviewLoading(true);
    setError(null);
    try {
      const r = await getStage3DependencyReview(jobId);
      setReview(r);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load dependency review");
    } finally {
      setReviewLoading(false);
    }
  }, [jobId]);

  // ── Load changes ──────────────────────────────────────────────────────

  const loadChanges = useCallback(async () => {
    try {
      const result = await listPomChanges(jobId);
      setChanges(result.changes);
    } catch {
      // Silently fail
    }
  }, [jobId]);

  // ── Propose ──────────────────────────────────────────────────────────

  const handlePropose = async () => {
    if (!userInput.trim()) return;
    setLoading(true);
    setError(null);
    setProposal(null);
    try {
      const p = await proposePomChange(jobId, {
        user_request: userInput.trim(),
        idempotency_key: crypto.randomUUID(),
      });
      setProposal(p);
      setActiveTab("proposed");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to propose change");
    } finally {
      setLoading(false);
    }
  };

  // ── Apply ─────────────────────────────────────────────────────────────

  const handleApply = async (proposalId?: string) => {
    setApplying(true);
    setError(null);
    setApplyResult(null);
    try {
      const result = await applyPomChange(jobId, {
        proposal_id: proposalId,
        user_request: proposalId ? undefined : userInput.trim(),
        idempotency_key: crypto.randomUUID(),
      });
      setApplyResult(result);
      setActiveTab("changes");
      await loadChanges();
      // Start polling validation
      if (result.validation_id) {
        pollValidation(result.validation_id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to apply change");
    } finally {
      setApplying(false);
    }
  };

  // ── Poll validation ───────────────────────────────────────────────────

  const pollValidation = async (validationId: string) => {
    try {
      const v = await getPomValidationResult(jobId, validationId);
      setValidation(v);
      if (v.status === "running") {
        setTimeout(() => pollValidation(validationId), 3000);
      }
    } catch {
      // Silently fail
    }
  };

  // ── Rollback ──────────────────────────────────────────────────────────

  const handleRollback = async (changeId: string) => {
    setLoading(true);
    setError(null);
    try {
      const r = await rollbackPomChange(jobId, changeId, crypto.randomUUID());
      setRollbackResult(r);
      await loadChanges();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Rollback failed");
    } finally {
      setLoading(false);
    }
  };

  // ── Effects ───────────────────────────────────────────────────────────

  useEffect(() => {
    if (stage3Completed) {
      loadPom();
      loadReview();
      loadChanges();
    }
  }, [stage3Completed, loadPom, loadReview, loadChanges]);

  // ── SSE-driven refresh for F14 POM events ────────────────────────────
  useEffect(() => {
    if (!events || events.length === 0) return;

    // Only process the latest event
    const latest = events[events.length - 1];
    const eventType = latest.type;

    // Map of F14 event types to refresh actions
    const F14_REFRESH_EVENTS = new Set([
      "pom_change_applied",
      "pom_change_rolled_back",
    ]);
    const F14_VALIDATION_EVENTS = new Set([
      "pom_validation_passed",
      "pom_validation_failed",
    ]);

    if (F14_REFRESH_EVENTS.has(eventType)) {
      // Refresh changes list when a change is applied or rolled back
      loadChanges();
      // If we have an active validation poll, stop it — events drive updates now
      if (eventType === "pom_change_applied") {
        const validationId = latest.payload?.validation_id as string | undefined;
        if (validationId) {
          // Load the validation result once (SSE will update further)
          getPomValidationResult(jobId, validationId).then(setValidation).catch(() => {});
        }
      }
    }

    if (F14_VALIDATION_EVENTS.has(eventType)) {
      // Validation completed — refresh
      const validationId = (latest.payload?.validation_id as string) || "";
      if (validationId) {
        getPomValidationResult(jobId, validationId).then(setValidation).catch(() => {});
      }
      loadChanges();
    }

    if (eventType === "pom_repair_plan_created") {
      // Repair plan created — refresh validation to get diagnosis + plan
      const validationId = (latest.payload?.validation_id as string) || "";
      if (validationId) {
        getPomValidationResult(jobId, validationId).then(setValidation).catch(() => {});
      }
    }

    if (eventType === "pom_validation_started") {
      // Validation started — show running state
      setValidation({
        validation_id: (latest.payload?.validation_id as string) || "",
        change_id: (latest.payload?.change_id as string) || "",
        status: "running",
        command: (latest.payload?.command_desc as string) || "mvn clean compile test",
        build_status: "unknown",
        test_status: "unknown",
        exit_code: null,
        duration_ms: null,
        log_ref: null,
        test_log_ref: null,
        diagnosis: null,
        repair_plan: null,
        created_at: new Date().toISOString(),
        completed_at: null,
      });
    }
  }, [events, jobId, loadChanges]);

  if (!stage3Completed) {
    return (
      <div className="p-6 border rounded-lg bg-yellow-50 text-yellow-800">
        <h3 className="text-lg font-semibold mb-2">Stage 3 Not Yet Completed</h3>
        <p>Dependency editing is not available until Stage 3 setup is complete.</p>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="border rounded-lg bg-white shadow-sm">
      {/* Tab bar */}
      <div className="flex border-b overflow-x-auto">
        {["pom", "review", "proposed", "changes", "validation", "repair", "evidence"].map(
          (tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          )
        )}
      </div>

      {/* Error display */}
      {error && (
        <div className="m-4 p-3 border border-red-300 rounded bg-red-50 text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* User input area */}
      <div className="p-4 border-b bg-gray-50">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Request a dependency change:
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="e.g., change gson to 2.11.0"
            className="flex-1 border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => {
              if (e.key === "Enter") handlePropose();
            }}
          />
          <button
            onClick={handlePropose}
            disabled={loading || !userInput.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Proposing..." : "Propose / Review"}
          </button>
          {proposal?.can_apply && (
            <button
              onClick={() => handleApply(proposal.proposal_id)}
              disabled={applying}
              className="px-4 py-2 bg-green-600 text-white rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50"
            >
              {applying ? "Applying..." : "Apply Change"}
            </button>
          )}
        </div>
        {proposal && (
          <div className="mt-3 text-sm">
            <span className="font-medium">Risk: </span>
            <span
              className={`inline-block px-2 py-0.5 rounded border text-xs font-medium ${riskBadgeColor(
                proposal.risk
              )}`}
            >
              {proposal.risk}
            </span>
            {proposal.warnings.length > 0 && (
              <div className="mt-1 text-yellow-700">
                {proposal.warnings.map((w: string, i: number) => (
                  <div key={i}>⚠ {w}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tab content */}
      <div className="p-4">
        {/* POM tab */}
        {activeTab === "pom" && (
          <div>
            <h3 className="text-lg font-semibold mb-2">Current Stage 3 POM</h3>
            {pomLoading ? (
              <p className="text-gray-500">Loading POM...</p>
            ) : pomView ? (
              <div>
                {pomView.detected_baseline && (
                  <div className="mb-3 p-3 bg-blue-50 rounded border text-sm">
                    <strong>Detected Baseline:</strong> Java {pomView.detected_baseline.java_version},
                    Spring Boot {pomView.detected_baseline.spring_boot_version}
                    (from {pomView.detected_baseline.spring_boot_version_location})
                  </div>
                )}
                {pomView.exists ? (
                  <pre className="bg-gray-900 text-green-400 p-4 rounded text-xs overflow-x-auto max-h-96">
                    {pomView.content}
                  </pre>
                ) : (
                  <p className="text-gray-500">POM not available.</p>
                )}
                {pomView.truncated && (
                  <p className="text-sm text-gray-400 mt-1">Content truncated for display.</p>
                )}
              </div>
            ) : (
              <p className="text-gray-500">No POM data loaded.</p>
            )}
          </div>
        )}

        {/* Review tab */}
        {activeTab === "review" && (
          <div>
            <h3 className="text-lg font-semibold mb-2">Dependency Review</h3>
            {reviewLoading ? (
              <p className="text-gray-500">Loading review...</p>
            ) : review ? (
              <div>
                {Object.entries(review.buckets as Record<string, PomDependencyFinding[]>).map(([bucket, findings]) =>
                  findings.length > 0 ? (
                    <div key={bucket} className="mb-4">
                      <h4 className="font-medium text-sm text-gray-600 uppercase mb-2">
                        {bucket.replace(/_/g, " ")}
                      </h4>
                      <table className="w-full text-sm border">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="px-3 py-2 text-left">Dependency</th>
                            <th className="px-3 py-2 text-left">Version</th>
                            <th className="px-3 py-2 text-left">Mode</th>
                            <th className="px-3 py-2 text-left">Risk</th>
                            <th className="px-3 py-2 text-left">Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {findings.map((f: PomDependencyFinding, i: number) => (
                            <tr key={i} className="border-t">
                              <td className="px-3 py-2 font-mono text-xs">{f.dependency_name}</td>
                              <td className="px-3 py-2">{f.current_version || "—"}</td>
                              <td className="px-3 py-2 text-xs text-gray-600">{f.control_mode}</td>
                              <td className="px-3 py-2">
                                <span
                                  className={`inline-block px-2 py-0.5 rounded border text-xs ${riskBadgeColor(
                                    f.risk
                                  )}`}
                                >
                                  {f.risk}
                                </span>
                              </td>
                              <td className="px-3 py-2 text-xs">{f.recommended_action}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null
                )}
              </div>
            ) : (
              <p className="text-gray-500">No review data loaded.</p>
            )}
          </div>
        )}

        {/* Proposed tab */}
        {activeTab === "proposed" && (
          <div>
            <h3 className="text-lg font-semibold mb-2">Proposed Changes</h3>
            {proposal ? (
              <div className="p-4 border rounded bg-yellow-50">
                <p className="text-sm mb-2">
                  <strong>Status:</strong> Proposal (no file written)
                </p>
                <pre className="bg-gray-900 text-green-400 p-4 rounded text-xs overflow-x-auto max-h-96">
                  {JSON.stringify(proposal.server_validated_plan_preview, null, 2)}
                </pre>
              </div>
            ) : (
              <p className="text-gray-500">
                No proposals yet. Use the input above to request a dependency review or change.
              </p>
            )}
          </div>
        )}

        {/* Changes tab */}
        {activeTab === "changes" && (
          <div>
            <h3 className="text-lg font-semibold mb-2">Applied Changes</h3>
            {changes.length === 0 ? (
              <p className="text-gray-500">No changes applied yet.</p>
            ) : (
              <div className="space-y-3">
                {changes.map((c: PomChangeRecordSummary) => (
                  <div key={c.change_id} className="p-3 border rounded">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-mono text-sm">{c.target_desc}</span>
                      <span
                        className={`inline-block px-2 py-0.5 rounded border text-xs ${statusBadgeColor(
                          c.status
                        )}`}
                      >
                        {c.status}
                      </span>
                    </div>
                    <div className="text-xs text-gray-600">
                      {c.operation}: {c.before_version || "?"} → {c.after_version || "?"}
                    </div>
                    <div className="flex gap-2 mt-2">
                      {c.validation_id && (
                        <button
                          onClick={() => {
                            setActiveTab("validation");
                            if (c.validation_id) pollValidation(c.validation_id);
                          }}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          View Validation
                        </button>
                      )}
                      {c.status !== "rolled_back" && (
                        <button
                          onClick={() => handleRollback(c.change_id)}
                          className="text-xs text-red-600 hover:underline"
                        >
                          Rollback
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Validation tab */}
        {activeTab === "validation" && (
          <div>
            <h3 className="text-lg font-semibold mb-2">Validation</h3>
            {applyResult ? (
              <div className="p-3 border rounded bg-blue-50 mb-3">
                <p className="text-sm font-medium">{applyResult.message}</p>
                <p className="text-xs text-gray-600 mt-1">
                  Change ID: {applyResult.change_id} | Validation ID: {applyResult.validation_id || "pending"}
                </p>
              </div>
            ) : null}
            {validation ? (
              <div className="p-4 border rounded">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-medium">Status:</span>
                  <span
                    className={`inline-block px-2 py-0.5 rounded border text-xs ${
                      validation.status === "passed"
                        ? "bg-green-100 text-green-800"
                        : validation.status === "failed"
                        ? "bg-red-100 text-red-800"
                        : "bg-blue-100 text-blue-800"
                    }`}
                  >
                    {validation.status}
                  </span>
                </div>
                {validation.exit_code != null && (
                  <p className="text-sm">Exit code: {validation.exit_code}</p>
                )}
                {validation.duration_ms != null && (
                  <p className="text-sm">Duration: {(validation.duration_ms / 1000).toFixed(1)}s</p>
                )}
                {validation.log_ref && (
                  <p className="text-sm text-gray-600">Log ref: {validation.log_ref}</p>
                )}
                {validation.diagnosis && (
                  <div className="mt-3 p-3 border rounded bg-red-50">
                    <h4 className="font-medium text-sm text-red-800">Diagnosis</h4>
                    <p className="text-sm">{validation.diagnosis.root_cause}</p>
                    <p className="text-xs text-gray-600 mt-1">
                      {validation.diagnosis.log_excerpt}
                    </p>
                  </div>
                )}
                {validation.repair_plan && (
                  <div className="mt-3 p-3 border rounded bg-yellow-50">
                    <h4 className="font-medium text-sm text-yellow-800">Repair Plan</h4>
                    <p className="text-sm">{validation.repair_plan.summary}</p>
                    <ul className="list-disc list-inside text-sm mt-1">
                      {validation.repair_plan.detailed_steps.map((s: string, i: number) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                    <p className="text-xs text-gray-600 mt-1">
                      Confidence: {validation.repair_plan.confidence}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-gray-500">
                {applyResult
                  ? "Validation is running..."
                  : "No validation data available. Apply a change first."}
              </p>
            )}
          </div>
        )}

        {/* Repair tab */}
        {activeTab === "repair" && (
          <div>
            <h3 className="text-lg font-semibold mb-2">Repair Plan</h3>
            {validation?.repair_plan ? (
              <div className="p-4 border rounded">
                <p className="text-sm font-medium mb-2">{validation.repair_plan.summary}</p>
                <h4 className="text-sm font-medium mt-3">Steps:</h4>
                <ol className="list-decimal list-inside text-sm space-y-1 mt-1">
                  {validation.repair_plan.detailed_steps.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
                <h4 className="text-sm font-medium mt-3">Evidence Sources:</h4>
                <ul className="list-disc list-inside text-sm text-gray-600">
                  {validation.repair_plan.evidence_sources.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
                <div className="flex gap-2 mt-4">
                  {validation.repair_plan.actions_available.includes("rollback") && (
                    <button
                      onClick={() => handleRollback(validation.change_id)}
                      className="px-3 py-1 bg-red-600 text-white rounded text-sm hover:bg-red-700"
                    >
                      Rollback Change
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-gray-500">No repair plan available.</p>
            )}
          </div>
        )}

        {/* Evidence tab */}
        {activeTab === "evidence" && (
          <div>
            <h3 className="text-lg font-semibold mb-2">Evidence</h3>
            {review ? (
              <div className="space-y-3">
                <div>
                  <h4 className="font-medium text-sm">Loaded Evidence:</h4>
                  <ul className="list-disc list-inside text-sm text-gray-600">
                    {review.evidence_loaded.map((e: string, i: number) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </div>
                {review.evidence_missing.length > 0 && (
                  <div>
                    <h4 className="font-medium text-sm text-yellow-700">Missing Evidence:</h4>
                    <ul className="list-disc list-inside text-sm text-yellow-600">
                      {review.evidence_missing.map((e: string, i: number) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-gray-500">No evidence loaded.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
