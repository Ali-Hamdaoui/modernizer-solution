"use client";

import { useState, useEffect } from "react";
import {
  askV2Assistant,
  approveV2Card,
  getV2ArtifactPreview,
  generateV2FinalReport,
  getV2FinalReport,
  getV2RootPomPreview,
  getV2AssistantMessages,
  getV2FailureSummary,
  getV2JobEventSnapshot,
  getV2JobApprovals,
  getV2MigrationJob,
  getV2JobPipeline,
  getV2MigrationJobStages,
  rejectV2Card,
  requireJobId,
  v2EventStreamUrl,
  v2FinalReportPdfDownloadUrl,
  v2RootPomDownloadUrl,
} from "../../../lib/controlTowerApi";
import type {
  V2ApprovalResponse,
  V2ArtifactPreviewResponse,
  V2AssistantMessageResponse,
  V2FailureSummaryResponse,
  V2JobEvent,
  V2FinalReportResponse,
  V2MigrationJobResponse,
  V2PipelineResponse,
} from "../../../lib/contracts";
import Stage3DependencyReview from "./Stage3DependencyReview";
import Stage4TargetVersionComparison from "./Stage4TargetVersionComparison";

interface Stage {
  stage_index: number;
  pipeline_stage: string;
  chain_status: string;
  input_source_kind: string;
}

export interface CockpitData {
  job: V2MigrationJobResponse;
  stages: Stage[];
  approvals: V2ApprovalResponse[];
  messages: V2AssistantMessageResponse[];
  events: V2JobEvent[];
  pipeline: V2PipelineResponse;
  failureSummary: V2FailureSummaryResponse | null;
  assistantModel: { status: string; source: string; provider: string; role: string; failure_reason?: string } | null;
}

type LiveRefreshResults = [
  PromiseSettledResult<{ approvals: V2ApprovalResponse[] }>,
  PromiseSettledResult<{ job_id: string; stages: Stage[] }>,
  PromiseSettledResult<{ events: V2JobEvent[] }>,
  PromiseSettledResult<V2PipelineResponse>,
  PromiseSettledResult<V2FailureSummaryResponse>,
];

export function mergeCockpitLiveRefreshResults(
  current: CockpitData,
  results: LiveRefreshResults,
): { data: CockpitData; failed: boolean } {
  const [approvalsResult, stagesResult, eventsResult, pipelineResult, failureSummaryResult] = results;
  const failed = results.some((result) => result.status === "rejected");
  return {
    failed,
    data: {
      ...current,
      approvals: approvalsResult.status === "fulfilled" ? approvalsResult.value.approvals : current.approvals,
      stages: stagesResult.status === "fulfilled" ? stagesResult.value.stages : current.stages,
      events: eventsResult.status === "fulfilled" ? eventsResult.value.events : current.events,
      pipeline: pipelineResult.status === "fulfilled" ? pipelineResult.value : current.pipeline,
      failureSummary: failureSummaryResult.status === "fulfilled"
        ? failureSummaryResult.value
        : current.failureSummary,
    },
  };
}

export function MigrationCockpit({ jobId }: { jobId?: string }) {
  const [data, setData] = useState<CockpitData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [artifactPreview, setArtifactPreview] = useState<V2ArtifactPreviewResponse | null>(null);
  const [artifactPreviewBusy, setArtifactPreviewBusy] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const [liveRefreshWarning, setLiveRefreshWarning] = useState<string | null>(null);
  const [report, setReport] = useState<V2FinalReportResponse | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const normalizedJobId = jobId?.trim() ?? "";
  const reportReady = isReportReady(data?.stages ?? []);

  useEffect(() => {
    if (!normalizedJobId) {
      setData(null);
      setError("Migration job id is missing from the route.");
      return;
    }

    let cancelled = false;
    async function loadCockpit() {
      try {
        const safeJobId = requireJobId(normalizedJobId);
        const [job, messagesResponse, approvalsResponse, stagesResponse, eventsResponse, pipelineResponse, failureSummary, finalReport] = await Promise.all([
          getV2MigrationJob(safeJobId),
          getV2AssistantMessages(safeJobId),
          getV2JobApprovals(safeJobId),
          getV2MigrationJobStages(safeJobId),
          getV2JobEventSnapshot(safeJobId),
          getV2JobPipeline(safeJobId),
          getV2FailureSummary(safeJobId).catch(() => null),
          getV2FinalReport(safeJobId).catch(() => null),
        ]);

        if (cancelled) return;

        setData({
          job,
          stages: stagesResponse.stages,
          approvals: approvalsResponse.approvals,
          messages: messagesResponse.messages,
          events: eventsResponse.events,
          pipeline: pipelineResponse,
          failureSummary: failureSummary as V2FailureSummaryResponse | null,
          assistantModel: null,
        });
        setReport(finalReport as V2FinalReportResponse | null);
        setError(null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load cockpit");
        }
      }
    }
    loadCockpit();
    return () => { cancelled = true; };
  }, [normalizedJobId]);

  useEffect(() => {
    if (!normalizedJobId || typeof EventSource === "undefined") return;
    let source: EventSource | null = null;
    try {
      source = new EventSource(v2EventStreamUrl(normalizedJobId, 0));
    } catch {
      setStreamState("reconnecting");
      return;
    }

    source.onopen = () => setStreamState("connected");
    source.onerror = () => setStreamState("reconnecting");
    source.onmessage = (event) => appendEventFromSse(event.data);
    for (const type of [
      "job_created",
      "stage_queued",
      "stage_started",
      "command_started",
      "process_started",
      "stdout",
      "stderr",
      "analysis_started",
      "analysis_completed",
      "planning_started",
      "planning_completed",
      "assessment_started",
      "assessment_completed",
      "approval_blocked",
      "approval_required",
      "stage_blocked_for_approval",
      "sandbox_transform_started",
      "sandbox_transform_completed",
      "final_report_started",
      "final_report_completed",
      "artifact_written",
      "stage_completed",
      "stage_failed",
      "next_stage_queued",
      "job_completed",
      "proof_updated",
      "approval_resume_queued",
      "resume_started",
      "copilot_status_checked",
      "ai_diagnosis_created",
      "pom_summary_created",
      "repair_proposal_revised",
      "reviewer_critique_created",
      "repair_patch_gate_completed",
      "repair_patch_applied",
      "repair_validation_completed",
      "repair_rollback_completed",
      "model_invocation_started",
      "model_invocation_completed",
      "model_invocation_failed",
      "result_contract_failed",
      // F14 POM change events
      "pom_change_proposed",
      "pom_change_applied",
      "pom_validation_started",
      "pom_validation_passed",
      "pom_validation_failed",
      "pom_repair_plan_created",
      "pom_change_rolled_back",
    ]) {
      source.addEventListener(type, (event) => {
        appendEventFromSse((event as MessageEvent).data);
      });
    }

    return () => {
      source?.close();
    };
  }, [normalizedJobId]);

  function appendEventFromSse(dataText: string) {
    try {
      const event = JSON.parse(dataText) as V2JobEvent;
      setData((current) => {
        if (!current || current.events.some((existing) => existing.sequence === event.sequence)) {
          return current;
        }
        const updatedEvents = [...current.events, event].sort((a, b) => a.sequence - b.sequence);
        const updatedStages = reduceAllStageStatuses(current.stages, updatedEvents);
        return {
          ...current,
          events: updatedEvents,
          stages: updatedStages,
          // Do NOT locally derive pipeline on every SSE event.
          // Backend refresh on important events is authoritative.
        };
      });
      // On important events, refresh from backend (async, non-blocking)
      if (IMPORTANT_SSE_TYPES.has(event.type)) {
        void refreshLiveState().catch(() => {
          setLiveRefreshWarning("Live refresh temporarily failed. Retrying...");
        });
      }
    } catch {
      setStreamState("reconnecting");
    }
  }

  async function askAssistant() {
    const question = assistantQuestion.trim();
    if (!question || !normalizedJobId) return;
    setAssistantBusy(true);
    try {
      const response = await askV2Assistant(normalizedJobId, question);
      setData((current) => {
        if (!current) return current;
        return {
          ...current,
          messages: [
            ...current.messages,
            response.user_message,
            response.assistant_message,
          ],
          assistantModel: response.model,
        };
      });
      setAssistantQuestion("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Assistant request failed");
    } finally {
      setAssistantBusy(false);
    }
  }

  async function refreshLiveState() {
    if (!normalizedJobId) return;
    const safeJobId = requireJobId(normalizedJobId);
    const [approvalsResult, stagesResult, eventsResult, pipelineResult, failureSummaryResult] = await Promise.allSettled([
      getV2JobApprovals(safeJobId),
      getV2MigrationJobStages(safeJobId),
      getV2JobEventSnapshot(safeJobId),
      getV2JobPipeline(safeJobId),
      getV2FailureSummary(safeJobId),
    ]) as LiveRefreshResults;
    const failed = [approvalsResult, stagesResult, eventsResult, pipelineResult, failureSummaryResult]
      .some((result) => result.status === "rejected");
    setLiveRefreshWarning(failed ? "Live refresh temporarily failed. Retrying..." : null);
    setData((current) => {
      if (!current) return current;
      const merged = mergeCockpitLiveRefreshResults(current, [
        approvalsResult,
        stagesResult,
        eventsResult,
        pipelineResult,
        failureSummaryResult,
      ]);
      return merged.data;
    });
  }

  async function approveCard(card: V2ApprovalResponse) {
    if (!normalizedJobId) return;
    setApprovalBusy(card.card_id);
    try {
      await approveV2Card(normalizedJobId, card.card_id, card.request_checksum);
      await refreshLiveState();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApprovalBusy(null);
    }
  }

  async function rejectCard(card: V2ApprovalResponse) {
    if (!normalizedJobId) return;
    setApprovalBusy(card.card_id);
    try {
      await rejectV2Card(normalizedJobId, card.card_id);
      await refreshLiveState();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rejection failed");
    } finally {
      setApprovalBusy(null);
    }
  }

  async function previewArtifact(artifactKind: string) {
    if (!normalizedJobId) return;
    setArtifactPreviewBusy(artifactKind);
    try {
      const preview = await getV2ArtifactPreview(normalizedJobId, artifactKind);
      setArtifactPreview(preview);
    } catch (e) {
      setArtifactPreview({
        job_id: normalizedJobId,
        artifact_kind: artifactKind,
        exists: false,
        preview: "",
        truncated: false,
        content_type: "text/plain",
      });
    } finally {
      setArtifactPreviewBusy(null);
    }
  }

  async function previewRootPom(stageIndex: number) {
    if (!normalizedJobId) return;
    const busyKey = `root_pom:${stageIndex}`;
    setArtifactPreviewBusy(busyKey);
    try {
      const preview = await getV2RootPomPreview(normalizedJobId, stageIndex);
      setArtifactPreview(preview);
    } catch (e) {
      setArtifactPreview({
        job_id: normalizedJobId,
        artifact_kind: "root_pom",
        source_type: "file_alias",
        file_alias: "root_pom",
        stage_index: stageIndex,
        exists: false,
        preview: "",
        truncated: false,
        content_type: "application/xml",
        download_url: null,
        reason: "not_available",
      });
    } finally {
      setArtifactPreviewBusy(null);
    }
  }

  async function generateReport() {
    if (!normalizedJobId) return;
    setReportBusy(true);
    try {
      const generated = await generateV2FinalReport(normalizedJobId);
      setReport(generated);
      await refreshLiveState();
      triggerPdfDownload(normalizedJobId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Final report generation failed");
    } finally {
      setReportBusy(false);
    }
  }

  if (error) return <div className="error-box">{error}</div>;
  if (!data) return <div className="info-box">Loading cockpit...</div>;

  return (
    <div className="cockpit-layout">
      {/* Stage Timeline */}
      <section className="panel cockpit-panel">
        <h2>Stage Timeline</h2>
        <p className="meta">Job: {data.job.job_id}</p>
        <div className="stage-list">
          {data.stages.map((stage) => (
            <div key={stage.stage_index} className={`stage-card ${stage.chain_status}`}>
              <div className="stage-header">
                <strong>{stage.pipeline_stage}</strong>
                <span className={`status-badge ${stage.chain_status}`}>
                  {stage.chain_status.toUpperCase()}
                </span>
              </div>
              <p className="meta">Input: {stage.input_source_kind}</p>
            </div>
          ))}
        </div>
        <p className="meta">Stage inputs are fixed by pipeline. No user selection of Stage 2/3 paths.</p>
      </section>

      {/* Evidence Panel */}
      <section className="panel cockpit-panel">
        <h2>Pipeline Status</h2>
        <p className="meta">Stream: {streamState}</p>
        {liveRefreshWarning && <p className="warning-text">{liveRefreshWarning}</p>}
        <div className="pipeline-list">
          {data.pipeline.rows.map((row) => (
            <div key={row.key} className="pipeline-row">
              <span className={`status-badge ${row.status}`}>{row.status.toUpperCase()}</span>
              <strong>{row.label}</strong>
              <span>{row.latest_message}</span>
              <span className="meta">{row.artifact_count} artifacts</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel cockpit-panel">
        <h2>Evidence</h2>
        {data.pipeline.evidence.length === 0 ? (
          <div className="evidence-placeholder">
            <p>Evidence will appear as stages execute.</p>
          </div>
        ) : (
          <div className="event-list">
            {data.pipeline.evidence.map((event) => (
              <div key={event.sequence} className="event-row">
                <span className={`status-badge ${event.status}`}>{event.status.toUpperCase()}</span>
                <strong>{event.type}</strong>
                <span>{event.message}</span>
              </div>
            ))}
          </div>
        )}
        <details className="raw-logs">
          <summary>Raw logs</summary>
          {data.pipeline.raw_logs.length === 0 ? (
            <p className="meta">No raw stdout/stderr captured.</p>
          ) : (
            data.pipeline.raw_logs.map((event) => (
              <pre key={event.sequence} className="raw-log-line">{event.message}</pre>
            ))
          )}
        </details>
      </section>

      {/* Decisions Panel */}
      <section className="panel cockpit-panel">
        <h2>Approval Decisions</h2>
        {data.approvals.length === 0 ? (
          <p className="meta">No pending decisions.</p>
        ) : (
          data.approvals.map((a) => (
            <div key={a.card_id} className="approval-card">
              <div className="stage-header">
                <strong>Stage {a.stage_index}</strong>
                <span className={`status-badge ${a.status}`}>{a.status.toUpperCase()}</span>
              </div>
              <p>{a.summary}</p>
              <p className="checksum">Checksum: {a.request_checksum}</p>
              {a.reviewer_decision && (
                <p className="meta">
                  Reviewer: {a.reviewer_decision}
                  {a.reviewer_critique_id ? ` (${a.reviewer_critique_id})` : ""}
                </p>
              )}
              {a.reviewed_checksum && <p className="checksum">Reviewed checksum: {a.reviewed_checksum}</p>}
              <div className="approval-actions">
                <button type="button" disabled={a.status !== "pending" || approvalBusy === a.card_id} onClick={() => void approveCard(a)}>
                  Approve
                </button>
                <button type="button" disabled={a.status !== "pending" || approvalBusy === a.card_id} onClick={() => void rejectCard(a)}>
                  Reject
                </button>
              </div>
            </div>
          ))
        )}
        <p className="meta">LLM cannot approve; exact checksum required.</p>
      </section>

      {/* Failure Summary Panel */}
      {data.failureSummary?.has_failures && (
        <section className="panel cockpit-panel failure-panel">
          <h2>Failure & Repair</h2>
          {data.failureSummary.failures.map((f, i) => (
            <div key={i} className={`failure-card ${f.type === "result_contract_failed" ? "contract-failure-card" : ""}`}>
              <div className="stage-header">
                <strong>{f.type === "result_contract_failed" ? "Control Tower Contract Failure" : f.type}</strong>
                <span className="meta">Stage {f.stage ?? "?"}</span>
                <span className="status-badge failed">FAILED</span>
              </div>
              <p>{f.message}</p>
              {f.result_kind && f.type !== "result_contract_failed" && (
                <p className="meta">
                  <strong>Root cause:</strong>{" "}
                  {f.result_kind.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </p>
              )}
              {f.type === "result_contract_failed" && (
                <>
                  {f.exit_code != null && <p className="meta"><strong>Exit code:</strong> {f.exit_code}</p>}
                  {f.final_json_found != null && <p className="meta"><strong>Final JSON found:</strong> {String(f.final_json_found)}</p>}
                  {f.parse_strategy && <p className="meta"><strong>Parse strategy:</strong> {f.parse_strategy}</p>}
                  {f.stdout_tail && (
                    <details>
                      <summary>stdout tail</summary>
                      <pre className="raw-log-line">{f.stdout_tail}</pre>
                    </details>
                  )}
                  {f.stderr_tail && (
                    <details>
                      <summary>stderr tail</summary>
                      <pre className="raw-log-line">{f.stderr_tail}</pre>
                    </details>
                  )}
                </>
              )}
              {f.matched_line && f.type !== "result_contract_failed" && (
                <pre className="raw-log-line">{f.matched_line}</pre>
              )}
              {f.command.length > 0 && f.type !== "result_contract_failed" && (
                <p className="meta">Command: <code>{f.command.join(" ")}</code></p>
              )}
              {f.build_tool && f.type !== "result_contract_failed" && <p className="meta">Tool: {f.build_tool}</p>}
              {f.module && f.type !== "result_contract_failed" && <p className="meta">Module: {f.module}</p>}
              {f.main_class && f.type !== "result_contract_failed" && <p className="meta">Main: {f.main_class}</p>}
              {f.unit_id && f.type !== "result_contract_failed" && <p className="meta">Unit: {f.unit_id}</p>}
              {f.java_home && f.type !== "result_contract_failed" && <p className="meta">JAVA_HOME: {f.java_home}</p>}
              {(f.detected_version || f.required_minimum) && f.type !== "result_contract_failed" && (
                <p className="meta">
                  Java: {f.detected_version || "?"} {"->"} required {f.required_minimum || "?"}
                </p>
              )}
              {f.build_status && f.type !== "result_contract_failed" && <p className="meta">Build: {f.build_status}</p>}
              {f.final_status && f.type !== "result_contract_failed" && <p className="meta">Final: {f.final_status}</p>}
              {f.final_proof_level && f.type !== "result_contract_failed" && <p className="meta">Proof level: {f.final_proof_level}</p>}
              {f.repair_loop_status && f.type !== "result_contract_failed" && <p className="meta">Repair: {f.repair_loop_status}</p>}
              {f.copilot_status && f.type !== "result_contract_failed" && <p className="meta">Copilot: {f.copilot_status}</p>}
              {f.test_status && f.type !== "result_contract_failed" && <p className="meta">Test: {f.test_status}</p>}
              {f.stage != null && (
                <div className="file-alias-actions">
                  <button
                    type="button"
                    disabled={artifactPreviewBusy === `root_pom:${f.stage}`}
                    onClick={() => void previewRootPom(f.stage as number)}
                  >
                    View full POM
                  </button>
                  <a href={normalizedJobId ? v2RootPomDownloadUrl(normalizedJobId, f.stage) : "#"}>
                    Download full POM
                  </a>
                  {artifactPreviewBusy === `root_pom:${f.stage}` ? <span className="meta"> loading...</span> : null}
                </div>
              )}
              {f.next_operator_action && (
                <div className="operator-action">
                  <strong>Next action:</strong>
                  <p className="meta">{f.next_operator_action}</p>
                </div>
              )}
              {f.supervision_trace && (
                <div className="supervision-trace">
                  <h3>AI Supervision</h3>
                  {f.supervision_trace.ai_diagnosis ? (
                    <div className="trace-section">
                      <strong>AI Diagnosis</strong>
                      <p className="meta">Diagnosis: {f.supervision_trace.ai_diagnosis.diagnosis_id}</p>
                      <p className="meta">Failure: {f.supervision_trace.ai_diagnosis.failure_type}</p>
                      <p className="checksum">Context pack: {f.supervision_trace.ai_diagnosis.context_pack_checksum}</p>
                      {f.supervision_trace.ai_diagnosis.repair_proposal_id && (
                        <p className="meta">Proposal: {f.supervision_trace.ai_diagnosis.repair_proposal_id}</p>
                      )}
                      <p className="meta">Redaction: {f.supervision_trace.ai_diagnosis.redaction_status || "unknown"}</p>
                    </div>
                  ) : (
                    <p className="meta">No backend AI diagnosis record.</p>
                  )}

                  {f.supervision_trace.evidence_used.length > 0 && (
                    <div className="trace-section">
                      <strong>Evidence Used by AI</strong>
                      <ul className="meta">
                        {f.supervision_trace.evidence_used.map((ref) => <li key={ref}>{ref}</li>)}
                      </ul>
                    </div>
                  )}

                  {f.supervision_trace.pom_analysis && (
                    <div className="trace-section">
                      <strong>POM Analysis</strong>
                      <p className="meta">Summary: {f.supervision_trace.pom_analysis.pom_summary_ref}</p>
                      {f.supervision_trace.pom_analysis.spring_boot_version && (
                        <p className="meta">Spring Boot: {f.supervision_trace.pom_analysis.spring_boot_version}</p>
                      )}
                      {f.supervision_trace.pom_analysis.java_version && (
                        <p className="meta">Java: {f.supervision_trace.pom_analysis.java_version}</p>
                      )}
                      {f.supervision_trace.pom_analysis.candidate_rules.length > 0 && (
                        <p className="meta">Rules: {f.supervision_trace.pom_analysis.candidate_rules.join(", ")}</p>
                      )}
                    </div>
                  )}

                  {f.supervision_trace.repair_proposal && (
                    <div className="trace-section">
                      <strong>Repair Proposal</strong>
                      <p className="meta">Proposal: {f.supervision_trace.repair_proposal.proposal_id}</p>
                      {f.supervision_trace.repair_proposal.source_proposal_id && (
                        <p className="meta">Revision of: {f.supervision_trace.repair_proposal.source_proposal_id}</p>
                      )}
                      {f.supervision_trace.repair_proposal.allowed_scope && (
                        <p className="meta">Scope: {f.supervision_trace.repair_proposal.allowed_scope}</p>
                      )}
                      {f.supervision_trace.repair_proposal.proposal_checksum && (
                        <p className="checksum">Proposal checksum: {f.supervision_trace.repair_proposal.proposal_checksum}</p>
                      )}
                    </div>
                  )}

                  {f.supervision_trace.reviewer_verdict && (
                    <div className="trace-section">
                      <strong>Reviewer Verdict</strong>
                      <p className="meta">Decision: {f.supervision_trace.reviewer_verdict.decision}</p>
                      <p className="meta">{f.supervision_trace.reviewer_verdict.reasoning}</p>
                      <p className="checksum">Reviewed checksum: {f.supervision_trace.reviewer_verdict.proposal_checksum}</p>
                    </div>
                  )}

                  {f.supervision_trace.validation_result && (
                    <div className="trace-section">
                      <strong>Validation Result</strong>
                      {f.supervision_trace.validation_result.patch_gate_status && (
                        <p className="meta">Patch gate: {f.supervision_trace.validation_result.patch_gate_status}</p>
                      )}
                      {f.supervision_trace.validation_result.deterministic_rule_id && (
                        <p className="meta">Rule: {f.supervision_trace.validation_result.deterministic_rule_id}</p>
                      )}
                      {f.supervision_trace.validation_result.build_status && (
                        <p className="meta">Build: {f.supervision_trace.validation_result.build_status}</p>
                      )}
                      {f.supervision_trace.validation_result.test_status && (
                        <p className="meta">Test: {f.supervision_trace.validation_result.test_status}</p>
                      )}
                      {f.supervision_trace.validation_result.h2_status && (
                        <p className="meta">H2: {f.supervision_trace.validation_result.h2_status}</p>
                      )}
                      {f.supervision_trace.validation_result.rollback_status && (
                        <p className="meta">Rollback: {f.supervision_trace.validation_result.rollback_status}</p>
                      )}
                      {f.supervision_trace.validation_result.ledger_ref && (
                        <p className="checksum">Ledger: {f.supervision_trace.validation_result.ledger_ref}</p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {data.failureSummary.repair_loop_active && (
            <div className="repair-card">
              <strong>Repair Active</strong>
              {data.failureSummary.repair_events.map((r, i) => (
                <p key={i} className="meta">{r.type}: {r.message}</p>
              ))}
            </div>
          )}
          {data.failureSummary.artifact_kinds.length > 0 && (
            <div className="artifact-kinds">
              <strong>Generated artifact kinds:</strong>
              <ul className="meta">
                {data.failureSummary.artifact_kinds.map((k, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      className="artifact-kind-link"
                      disabled={artifactPreviewBusy === k}
                      onClick={() => void previewArtifact(k)}
                    >
                      {artifactKindLabel(k)}
                    </button>
                    {artifactPreviewBusy === k ? " loading..." : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {artifactPreview && (
            <div className="artifact-preview">
              <strong>
                {artifactPreview.source_type === "file_alias"
                  ? `Full POM: Stage ${artifactPreview.stage_index ?? "?"}`
                  : `Artifact Preview: ${artifactKindLabel(artifactPreview.artifact_kind)}`}
              </strong>
              {artifactPreview.exists ? (
                <>
                  <p className="meta">
                    {artifactPreview.truncated ? "Preview truncated (32 KB limit)." : "Full preview."}
                    {artifactPreview.source_ref?.command_id ? ` Source command: ${artifactPreview.source_ref.command_id}` : ""}
                    {artifactPreview.source_ref?.event_id ? ` Source event: ${artifactPreview.source_ref.event_id}` : ""}
                  </p>
                  <pre className="artifact-preview-content">{artifactPreview.content ?? artifactPreview.preview}</pre>
                  {artifactPreview.download_url && normalizedJobId && (
                    <p>
                      <a href={v2RootPomDownloadUrl(normalizedJobId, artifactPreview.stage_index ?? 1)}>
                        Download full POM
                      </a>
                    </p>
                  )}
                </>
              ) : (
                <p className="meta">
                  {artifactPreview.source_type === "file_alias"
                    ? `Full POM is not available yet${artifactPreview.reason ? `: ${artifactPreview.reason.replace(/_/g, " ")}` : "."}`
                    : "Artifact not available or not yet persisted."}
                </p>
              )}
              <button type="button" onClick={() => setArtifactPreview(null)}>Close</button>
            </div>
          )}
        </section>
      )}

      {/* Assistant Panel */}
      <section className="panel cockpit-panel assistant-panel">
        <h2>Assistant</h2>
        <p className="meta">
          Model: {data.assistantModel?.status ?? "unavailable"} | Source: {data.assistantModel?.source ?? "deterministic"}
          {data.assistantModel?.failure_reason ? ` | Reason: ${data.assistantModel.failure_reason}` : ""}
          {data.assistantModel?.status === "live_ok" ? " | Live Azure OpenAI" : ""}
        </p>
        <div className="assistant-messages">
          {data.messages.length === 0 ? (
            <p className="meta">No messages yet. The assistant can explain status and draft instructions.</p>
          ) : (
            data.messages.map((m) => (
              <div key={m.message_id} className="message">
                <strong>{m.role}:</strong> {m.content}
              </div>
            ))
          )}
        </div>
        <div className="assistant-composer">
          <input
            aria-label="Ask assistant"
            value={assistantQuestion}
            onChange={(event) => setAssistantQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void askAssistant();
            }}
            placeholder="Ask what happened so far"
          />
          <button type="button" disabled={assistantBusy || !assistantQuestion.trim()} onClick={() => void askAssistant()}>
            Ask
          </button>
        </div>
        <p className="meta">
          Assistant cannot execute, approve, write files, change route, or override proof.
        </p>
      </section>

      <Stage4TargetVersionComparison
        jobId={normalizedJobId || jobId || ""}
        stage4Completed={
          (data.stages || []).some(
            (stage) => stage.stage_index === 4 && stage.chain_status === "completed"
          )
        }
      />

      {/* Proof & Report */}
      <section className="panel cockpit-panel">
        <h2>Proof & Report</h2>
        <p className="meta">
          The final report is generated only when you request it and is stored under <code>docs/migration-reports</code>.
        </p>
        <div className="approval-actions">
          <button
            type="button"
            disabled={
              reportBusy
              || !reportReady
            }
            onClick={() => void generateReport()}
          >
            {report ? "Regenerate report" : "Generate report"}
          </button>
        </div>
        {!reportReady && (
          <p className="meta">Report generation unlocks after the latest migration stage completes successfully.</p>
        )}
        {report ? (
          <div className="artifact-preview">
            <strong>Stored report</strong>
            <p className="meta">{report.summary}</p>
            <p className="meta">
              Duration: {report.total_duration_seconds == null ? "not captured" : `${report.total_duration_seconds.toFixed(3)}s`}
            </p>
            {report.full_migration_source_stack && report.full_migration_target_stack && (
              <p className="meta">
                Journey: {formatStack(report.full_migration_source_stack)} {"->"} {formatStack(report.full_migration_target_stack)}
              </p>
            )}
            <p className="meta">Markdown: <code>{report.docs_report_markdown}</code></p>
            <p className="meta">PDF: <code>{report.docs_report_pdf}</code></p>
            {(report.pipeline_history || []).length > 0 && (
              <div className="trace-section">
                <strong>Full migration journey</strong>
                <ul className="meta">
                  {(report.pipeline_history || []).map((stage, index) => (
                    <li key={`journey-${stage.stage_index}-${index}`}>
                      Stage {stage.stage_index}: {stage.profile} | {formatStack(stage.source_stack)} {"->"} {formatStack(stage.target_stack)} | status={stage.chain_status} | duration={formatDuration(stage.duration_seconds)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {report.change_summary.length > 0 && (
              <div className="trace-section">
                <strong>What changed</strong>
                <ul className="meta">
                  {report.change_summary.map((item, index) => (
                    <li key={`change-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            {report.warnings.length > 0 && (
              <div className="trace-section">
                <strong>Warnings</strong>
                <ul className="meta">
                  {report.warnings.map((item, index) => (
                    <li key={`warning-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="meta">No generated report yet.</p>
        )}
      </section>

      {/* F14 — Stage 3 Dependency Review */}
      {data && (
        <section className="cockpit-full-span">
          <Stage3DependencyReview
            jobId={normalizedJobId || jobId || ""}
            stage3Completed={
              (data.stages || []).some(
                (s) => s.stage_index === 3 && s.chain_status === "completed"
              )
            }
            events={data.events.map((e) => ({
              type: e.type,
              payload: (e as Record<string, unknown>).payload as Record<string, unknown> | undefined,
            }))}
          />
        </section>
      )}

      <style>{`
        .cockpit-layout {
          display: grid;
          gap: 16px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          height: 100%;
          min-height: 0;
          overflow: hidden;
        }
        .cockpit-layout > .panel,
        .cockpit-full-span {
          background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 252, 251, 0.96));
          border: 1px solid #d8dfdc;
          border-radius: 18px;
          box-shadow: 0 18px 44px rgba(23, 32, 29, 0.08);
          min-height: 0;
          overflow: auto;
        }
        .cockpit-layout > .panel {
          display: flex;
          flex-direction: column;
          max-height: 420px;
          padding: 18px;
        }
        .cockpit-panel {
          scrollbar-gutter: stable;
        }
        .assistant-panel {
          max-height: 520px;
        }
        .assistant-messages {
          display: grid;
          gap: 0;
          min-height: 0;
          overflow: auto;
        }
        .cockpit-full-span {
          grid-column: 1 / -1;
        }
        .panel h2 {
          font-size: 1.08rem;
          margin-bottom: 0.45rem;
          margin-top: 0;
        }
        .stage-list,
        .pipeline-list {
          display: flex;
          flex-direction: column;
          gap: 0.65rem;
          margin-top: 0.9rem;
        }
        .stage-card,
        .approval-card,
        .failure-card,
        .repair-card,
        .artifact-kinds,
        .artifact-preview {
          background: rgba(255, 255, 255, 0.92);
          border: 1px solid #e4ebe8;
          border-radius: 14px;
          padding: 0.9rem 1rem;
        }
        .stage-card.queued { border-left: 4px solid #2b7fff; }
        .stage-card.pending { border-left: 4px solid #8a948f; }
        .stage-card.running { border-left: 4px solid #c98a00; }
        .stage-card.completed { border-left: 4px solid #0f766e; }
        .stage-card.failed,
        .failure-card { border-left: 4px solid #c6392f; }
        .stage-header {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          justify-content: space-between;
        }
        .status-badge {
          border-radius: 999px;
          display: inline-flex;
          font-size: 0.72rem;
          font-weight: 800;
          letter-spacing: 0.02em;
          padding: 0.28rem 0.62rem;
        }
        .status-badge.queued { background: #e8f1ff; color: #115bb8; }
        .status-badge.running { background: #fff5d8; color: #8a6100; }
        .status-badge.completed,
        .status-badge.pass { background: #e4f7e8; color: #146c2e; }
        .status-badge.failed { background: #ffe3e3; color: #a40000; }
        .status-badge.blocked { background: #f5e8ff; color: #5a248a; }
        .status-badge.pending { background: #edf1ef; color: #56615c; }
        .meta { color: #66736d; font-size: 0.85rem; }
        .warning-text { color: #8a5a00; font-size: 0.85rem; margin: 0.25rem 0 0.5rem; }
        .error-box,
        .info-box,
        .evidence-placeholder {
          border-radius: 14px;
          padding: 1rem;
        }
        .error-box { background: #fff0f0; border: 1px solid #e59d9d; }
        .info-box { background: #eefaf7; border: 1px solid #8ed3c5; }
        .evidence-placeholder {
          border: 1px dashed #c9d3cf;
          color: #7a8580;
          text-align: center;
        }
        .event-list { display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.8rem; }
        .event-row,
        .pipeline-row {
          align-items: center;
          border-bottom: 1px solid #eef2f0;
          display: grid;
          gap: 0.6rem;
          padding: 0.55rem 0;
        }
        .event-row { grid-template-columns: 6rem 10rem 1fr; }
        .pipeline-row { grid-template-columns: 6rem 10rem 1fr 5.5rem; }
        .approval-actions,
        .file-alias-actions {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 0.6rem;
          margin-top: 0.75rem;
        }
        .approval-actions button,
        .assistant-composer button,
        .file-alias-actions button,
        .artifact-preview button {
          background: #fff;
          border: 1px solid #b9c5c0;
          border-radius: 10px;
          color: #17201d;
          padding: 0.5rem 0.8rem;
        }
        .approval-actions button:disabled,
        .assistant-composer button:disabled,
        .file-alias-actions button:disabled {
          border-color: #d2d9d6;
          color: #777;
        }
        .checksum {
          font-family: Consolas, "Cascadia Mono", monospace;
          font-size: 0.82rem;
          overflow-wrap: anywhere;
        }
        .raw-logs { margin-top: 0.9rem; }
        .raw-log-line,
        .artifact-preview-content {
          background: #111816;
          border-radius: 12px;
          color: #d9fff8;
          margin: 0.45rem 0 0;
          overflow: auto;
          padding: 0.8rem;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .message {
          border-bottom: 1px solid #eef2f0;
          padding: 0.7rem 0;
        }
        .assistant-composer {
          display: grid;
          gap: 0.6rem;
          grid-template-columns: 1fr auto;
          margin-top: 0.85rem;
        }
        .assistant-composer input {
          background: #fff;
          border: 1px solid #c7d0cc;
          border-radius: 10px;
          min-width: 0;
          padding: 0.7rem 0.8rem;
        }
        .failure-panel {
          background: linear-gradient(180deg, rgba(255, 250, 250, 0.98), rgba(255, 244, 244, 0.94));
          border-color: #e7b4b4;
        }
        .contract-failure-card {
          background: #fff8ef;
          border-color: #ebc37e;
        }
        .supervision-trace {
          border-top: 1px solid #f1d1d1;
          margin-top: 0.85rem;
          padding-top: 0.85rem;
        }
        .supervision-trace h3 {
          font-size: 1rem;
          margin: 0 0 0.5rem 0;
        }
        .trace-section {
          border-left: 3px solid #7b8d85;
          margin-top: 0.6rem;
          padding-left: 0.7rem;
        }
        .trace-section ul {
          margin: 0.25rem 0 0 1rem;
          padding: 0;
        }
        .artifact-kind-link {
          appearance: none;
          background: none;
          border: 0;
          color: #0f766e;
          cursor: pointer;
          font: inherit;
          font-weight: 700;
          padding: 0;
          text-decoration: underline;
        }
        .artifact-kind-link:disabled {
          color: #888;
          cursor: wait;
          text-decoration: none;
        }
        .operator-action {
          background: #f7fbfa;
          border: 1px solid #dce8e3;
          border-radius: 12px;
          margin-top: 0.85rem;
          padding: 0.75rem;
        }
        @media (max-width: 980px) {
          .cockpit-layout {
            grid-template-columns: 1fr;
          }
          .event-row,
          .pipeline-row {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}

function formatStack(stack: Record<string, unknown> | undefined): string {
  if (!stack) {
    return "not captured";
  }
  const springBoot = String(stack["spring_boot"] ?? "").trim();
  const java = String(stack["java"] ?? "").trim();
  if (!springBoot && !java) {
    return "not captured";
  }
  return `Spring Boot ${springBoot || "?"} / Java ${java || "?"}`;
}

function formatDuration(value: number | null | undefined): string {
  return value == null ? "not captured" : `${value.toFixed(3)}s`;
}

function isReportReady(stages: Stage[]): boolean {
  if (stages.length === 0) {
    return false;
  }
  const highestStageIndex = stages.reduce((highest, stage) => Math.max(highest, stage.stage_index), 0);
  return stages.some((stage) => stage.stage_index === highestStageIndex && stage.chain_status === "completed");
}

function triggerPdfDownload(jobId: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const anchor = document.createElement("a");
  anchor.href = v2FinalReportPdfDownloadUrl(jobId);
  anchor.download = `${jobId}-full-migration-report.pdf`;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function artifactKindLabel(kind: string): string {
  if (kind === "rewrite_dry_run.patch") return "rewrite dry run diff/proposed changes";
  if (kind.endsWith(".patch")) return `${kind} diff/proposed changes`;
  return kind;
}

/** Recompute stage status for every stage using ALL events so far
 *  (chronological reducer), instead of deriving from a single incoming event.
 *  This guarantees the frontend never shows a contradiction. */
function reduceAllStageStatuses(stages: Stage[], allEvents: V2JobEvent[]): Stage[] {
  return stages.map((stage) => {
    const stageEvents = allEvents
      .filter((e) => e.stage === stage.stage_index)
      .sort((a, b) => a.sequence - b.sequence);
    return { ...stage, chain_status: reduceStageStatus(stageEvents) };
  });
}

/** Map a single (event.type, event.status) to a stage status *label*.
 *  This is an *input* to the chronological reducer; the label alone does
 *  NOT determine the final stage status (see reduceStageStatus). */
export function stageStatusFromEvent(event: V2JobEvent): string {
  if (event.type === "stage_failed" || event.status === "failed") return "failed";
  if (event.type === "stage_completed") return "completed";
  if (["stage_started", "command_started", "sandbox_transform_started",
       "sandbox_transform_completed", "resume_started", "approval_resume_queued",
       "approval_completed", "build_started", "test_started"].includes(event.type) || event.status === "running") {
    return "running";
  }
  if (event.type === "approval_required" || event.type === "stage_blocked_for_approval" || event.status === "blocked") return "blocked";
  if (["stage_queued", "next_stage_queued"].includes(event.type) || event.status === "queued") return "queued";
  return "pending";
}

/** State-transition helper: given current status and mapped label,
 *  return the new status respecting lifecycle rules.
 *  * failed       → terminal (highest priority)
 *  * completed    → terminal unless a later failure arrives
 *  * running      → overrides blocked/pending/queued
 *  * blocked      → applies only if not already running/completed/failed
 *  * queued       → applies only if not already past it
 *  * pending      → no change */
export function transitionStageStatus(current: string, mapped: string): string {
  if (mapped === "failed") return "failed";
  if (mapped === "completed") return "completed";
  if (mapped === "running") return "running";
  if (mapped === "blocked") {
    if (current === "running" || current === "completed" || current === "failed") return current;
    return "blocked";
  }
  if (mapped === "queued") {
    if (current === "running" || current === "completed" || current === "failed" || current === "blocked") return current;
    return "queued";
  }
  return current;
}

/** Reduce chronologically-ordered events to a single stage status. */
export function reduceStageStatus(events: V2JobEvent[]): string {
  let current = "pending";
  for (const event of events) {
    current = transitionStageStatus(current, stageStatusFromEvent(event));
  }
  return current;
}

const IMPORTANT_SSE_TYPES = new Set([
  "approval_required",
  "stage_blocked_for_approval",
  "approval_resume_queued",
  "approval_started",
  "approval_completed",
  "resume_started",
  "sandbox_transform_started",
  "sandbox_transform_completed",
  "sandbox_transform_failed",
  "stage_failed",
  "stage_completed",
  "model_invocation_completed",
  "model_invocation_failed",
  "transform_failed",
  "build_failed",
  "repair_started",
  "repair_fallback_generated",
  "copilot_repair_invalid_response",
  "ai_diagnosis_created",
  "pom_summary_created",
  "repair_proposal_revised",
  "reviewer_critique_created",
  "repair_patch_gate_completed",
  "repair_patch_applied",
  "repair_validation_completed",
  "repair_rollback_completed",
  "proof_updated",
  "next_stage_queued",
  "result_contract_failed",
  // F14 POM change events — trigger refresh on important state changes
  "pom_change_applied",
  "pom_validation_passed",
  "pom_validation_failed",
  "pom_repair_plan_created",
  "pom_change_rolled_back",
]);
