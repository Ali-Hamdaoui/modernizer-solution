"use client";

import { useState, useEffect } from "react";
import {
  askV2Assistant,
  approveV2Card,
  getV2ArtifactPreview,
  getV2RootPomPreview,
  getV2AssistantMessages,
  getV2FailureSummary,
  getV2JobEventSnapshot,
  getV2JobApprovals,
  getV2MigrationJob,
  getV2JobPipeline,
  getV2OpenGate,
  getV2MigrationJobStages,
  getV2FinalReport,
  generateV2FinalReport,
  rejectV2Card,
  requireJobId,
  v2EventStreamUrl,
  v2RootPomDownloadUrl,
} from "../../../lib/controlTowerApi";
import type {
  V2ApprovalResponse,
  V2ArtifactPreviewResponse,
  V2AssistantMessageResponse,
  V2FailureSummaryResponse,
  V2FinalReportResponse,
  V2JobEvent,
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

interface AssistantPanelContentProps {
  assistantModel: CockpitData["assistantModel"];
  messages: V2AssistantMessageResponse[];
  assistantError: string | null;
  assistantQuestion: string;
  assistantBusy: boolean;
  approvalReviewOpen: boolean;
  onQuestionChange: (value: string) => void;
  onAsk: () => void;
}

export function AssistantPanelContent({
  assistantModel,
  messages,
  assistantError,
  assistantQuestion,
  assistantBusy,
  approvalReviewOpen,
  onQuestionChange,
  onAsk,
}: AssistantPanelContentProps) {
  return (
    <section className="panel cockpit-panel assistant-panel">
      <h2>Assistant</h2>
      <p className="meta">
        Model: {assistantModel?.status ?? "unavailable"} | Source: {assistantModel?.source ?? "deterministic"}
        {assistantModel?.failure_reason ? ` | Reason: ${assistantModel.failure_reason}` : ""}
        {assistantModel?.status === "live_ok" ? " | Live Azure OpenAI" : ""}
      </p>
      {assistantError && (
        <p className="assistant-error" role="alert">
          Assistant request failed: {assistantError}
        </p>
      )}
      {messages.length === 0 ? (
        <p className="meta">No messages yet. The assistant can explain status and draft instructions.</p>
      ) : (
        messages.map((m) => (
          <div key={m.message_id} className="message">
            <strong>{m.role}:</strong>
            <pre className="message-content">{m.content}</pre>
          </div>
        ))
      )}
      <div className="assistant-composer">
        <input
          aria-label="Ask assistant"
          value={assistantQuestion}
          onChange={(event) => onQuestionChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void onAsk();
          }}
          placeholder="Ask what happened so far"
        />
        <button type="button" disabled={assistantBusy || !assistantQuestion.trim()} onClick={() => void onAsk()}>
          Ask
        </button>
      </div>
      {approvalReviewOpen && (
        <p className="meta">
          Pre-transform review is open in the chatbot. Legacy Approve/Reject controls are disabled here; use the assistant to review evidence, request changes, and confirm the exact checksum.
        </p>
      )}
      <p className="meta">
        Assistant cannot execute, approve, write files, change route, or override proof.
      </p>
    </section>
  );
}

export function MigrationCockpit({ jobId }: { jobId?: string }) {
  const [data, setData] = useState<CockpitData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantError, setAssistantError] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [artifactPreview, setArtifactPreview] = useState<V2ArtifactPreviewResponse | null>(null);
  const [artifactPreviewBusy, setArtifactPreviewBusy] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const [liveRefreshWarning, setLiveRefreshWarning] = useState<string | null>(null);
  const [approvalReviewOpen, setApprovalReviewOpen] = useState(false);
  const [report, setReport] = useState<V2FinalReportResponse | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const normalizedJobId = jobId?.trim() ?? "";
  const reportReady = isReportReady(data?.stages ?? []);

  async function refreshApprovalReviewState(safeJobId: string) {
    try {
      const openGate = (await getV2OpenGate(safeJobId)).gate;
      setApprovalReviewOpen(openGate?.gate_phase === "approval_review");
    } catch {
      setApprovalReviewOpen(false);
    }
  }

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
        const [job, messagesResponse, approvalsResponse, stagesResponse, eventsResponse, pipelineResponse, failureSummary] = await Promise.all([
          getV2MigrationJob(safeJobId),
          getV2AssistantMessages(safeJobId),
          getV2JobApprovals(safeJobId),
          getV2MigrationJobStages(safeJobId),
          getV2JobEventSnapshot(safeJobId),
          getV2JobPipeline(safeJobId),
          getV2FailureSummary(safeJobId).catch(() => null),
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
        setError(null);
        void refreshReport();
        void refreshApprovalReviewState(safeJobId);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load cockpit");
        }
      }
    }
    loadCockpit();
    return () => { cancelled = true; };
  }, [normalizedJobId]);

  async function refreshReport() {
    if (!normalizedJobId) return;
    try {
      setReport(await getV2FinalReport(normalizedJobId));
    } catch {
      // report state stays null if not available
    }
  }

  async function handleGenerateReport() {
    if (!normalizedJobId || !reportReady) return;
    setReportBusy(true);
    try {
      setReport(await generateV2FinalReport(normalizedJobId));
      await refreshLiveState();
      triggerPdfDownload(normalizedJobId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Final report generation failed");
    } finally {
      setReportBusy(false);
    }
  }

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
    setAssistantError(null);
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
      setAssistantError(e instanceof Error ? e.message : "Assistant request failed");
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
    await refreshApprovalReviewState(safeJobId);
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
        {approvalReviewOpen && (
          <p className="meta">
            Pre-transform review is open in the chatbot. Legacy Approve/Reject controls are disabled here; use the assistant to review evidence, request changes, and confirm the exact checksum.
          </p>
        )}
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
              {approvalReviewOpen ? (
                <p className="meta">
                  Review in chatbot. Exact checksum confirmation is required before transform resumes.
                </p>
              ) : (
                <div className="approval-actions">
                  <button type="button" disabled={a.status !== "pending" || approvalBusy === a.card_id} onClick={() => void approveCard(a)}>
                    Approve
                  </button>
                  <button type="button" disabled={a.status !== "pending" || approvalBusy === a.card_id} onClick={() => void rejectCard(a)}>
                    Reject
                  </button>
                </div>
              )}
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
                  Java: {f.detected_version || "?"} → required {f.required_minimum || "?"}
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
      <AssistantPanelContent
        assistantModel={data.assistantModel}
        messages={data.messages}
        assistantError={assistantError}
        assistantQuestion={assistantQuestion}
        assistantBusy={assistantBusy}
        approvalReviewOpen={approvalReviewOpen}
        onQuestionChange={setAssistantQuestion}
        onAsk={() => void askAssistant()}
      />
      {/* Final Report Panel */}
      <section className="panel preview-panel">
        <h2>Final Report</h2>
        <button
          type="button"
          disabled={reportBusy || !reportReady}
          onClick={() => void handleGenerateReport()}
        >
          {report ? "Regenerate report" : "Generate report"}
        </button>
        {reportBusy && <span className="meta"> Generating...</span>}
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

      <section className="preview-full-span">
        <Stage4TargetVersionComparison
          jobId={normalizedJobId || jobId || ""}
        stage4Completed={
          (data.stages || []).some(
            (s) => s.stage_index === 4 && s.chain_status === "completed"
          )
        }
        />
      </section>

      {/* F14 ? Stage 3 Dependency Review */}
      {data && (
        <section className="preview-full-span">
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
        .cockpit-layout { display: grid; gap: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); height: 100%; min-height: 0; }
        .cockpit-layout > .panel,
        .preview-full-span { min-height: 0; }
        .panel { border: 1px solid #ccc; border-radius: 6px; padding: 1rem; overflow: auto; }
        .cockpit-layout > .panel { display: flex; flex-direction: column; max-height: 420px; }
        .cockpit-panel { scrollbar-gutter: stable; }
        .assistant-panel { max-height: 520px; }
        .preview-panel { max-height: 520px; scrollbar-gutter: stable; }
        .preview-full-span { grid-column: 1 / -1; max-height: 560px; overflow: auto; }
        .preview-full-span > section { max-height: none; }
        .panel h2 { margin-top: 0; font-size: 1.1rem; }
        .stage-list { display: flex; flex-direction: column; gap: 0.5rem; }
        .stage-card { border: 1px solid #ddd; border-radius: 4px; padding: 0.75rem; }
        .stage-card.queued { border-left: 3px solid #0066cc; }
        .stage-card.pending { border-left: 3px solid #888; }
        .stage-header { display: flex; justify-content: space-between; align-items: center; }
        .status-badge { font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 3px; }
        .status-badge.queued { background: #e0f0ff; color: #0066cc; }
        .status-badge.running { background: #fff4cc; color: #886600; }
        .status-badge.completed { background: #e4f7e8; color: #146c2e; }
        .status-badge.pass { background: #e4f7e8; color: #146c2e; }
        .status-badge.failed { background: #ffe3e3; color: #a40000; }
        .status-badge.blocked { background: #f5e8ff; color: #5a248a; }
        .status-badge.pending { background: #eee; color: #666; }
        .meta { font-size: 0.85rem; color: #666; }
        .warning-text { font-size: 0.85rem; color: #8a5a00; margin: 0.25rem 0 0.5rem; }
        .error-box { border: 1px solid #cc0000; background: #fff0f0; padding: 1rem; border-radius: 6px; }
        .info-box { border: 1px solid #0066cc; background: #f0f6ff; padding: 1rem; border-radius: 6px; }
        .evidence-placeholder { border: 1px dashed #ccc; padding: 1rem; text-align: center; color: #888; }
        .event-list { display: flex; flex-direction: column; gap: 0.4rem; }
        .event-row { display: grid; grid-template-columns: 6rem 10rem 1fr; gap: 0.5rem; align-items: center; border-bottom: 1px solid #eee; padding: 0.35rem 0; }
        .pipeline-list { display: flex; flex-direction: column; gap: 0.45rem; }
        .pipeline-row { display: grid; grid-template-columns: 6rem 10rem 1fr 5rem; gap: 0.5rem; align-items: center; border-bottom: 1px solid #eee; padding: 0.45rem 0; }
        .approval-card { border: 1px solid #eee; padding: 0.5rem; margin: 0.25rem 0; }
        .approval-actions { display: flex; gap: 0.5rem; }
        .approval-actions button { padding: 0.45rem 0.7rem; border: 1px solid #333; border-radius: 4px; background: #fff; }
        .approval-actions button:disabled { color: #777; border-color: #bbb; }
        .checksum { font-family: monospace; overflow-wrap: anywhere; font-size: 0.82rem; }
        .raw-logs { margin-top: 0.75rem; }
        .raw-log-line { white-space: pre-wrap; overflow-wrap: anywhere; border-bottom: 1px solid #eee; margin: 0; padding: 0.35rem 0; }
        .message { border-bottom: 1px solid #eee; padding: 0.5rem 0; }
        .assistant-composer { display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; margin-top: 0.75rem; }
        .assistant-composer input { min-width: 0; padding: 0.5rem; border: 1px solid #aaa; border-radius: 4px; }
        .assistant-composer button { padding: 0.5rem 0.75rem; border: 1px solid #333; border-radius: 4px; background: #fff; }
        .assistant-composer button:disabled { color: #777; border-color: #bbb; }
        .assistant-error { border: 1px solid #c98300; background: #fff8ea; color: #7a4a00; padding: 0.65rem 0.75rem; border-radius: 4px; margin: 0.5rem 0 0.75rem; }
        .message-content { margin: 0.25rem 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
        .failure-panel { border-color: #a40000; background: #fffafa; }
        .failure-card { border: 1px solid #ffcccc; padding: 0.75rem; margin: 0.5rem 0; border-radius: 4px; }
        .failure-card .meta { margin: 0.2rem 0; }
        .contract-failure-card { border: 1px solid #cc8800; background: #fffaf0; }
        .contract-failure-card .meta { margin: 0.2rem 0; }
        .supervision-trace { border-top: 1px solid #f1c0c0; margin-top: 0.75rem; padding-top: 0.75rem; }
        .supervision-trace h3 { margin: 0 0 0.5rem 0; font-size: 1rem; }
        .trace-section { border-left: 3px solid #6b7a90; padding-left: 0.6rem; margin-top: 0.6rem; }
        .trace-section ul { margin: 0.25rem 0 0 1rem; padding: 0; }
        .repair-card { border: 1px solid #ffcc66; background: #fffdf0; padding: 0.75rem; margin: 0.5rem 0; border-radius: 4px; }
        .file-alias-actions { display: flex; align-items: center; gap: 0.6rem; margin: 0.5rem 0; }
        .file-alias-actions button { padding: 0.35rem 0.6rem; border: 1px solid #333; border-radius: 4px; background: #fff; }
        .file-alias-actions button:disabled { color: #777; border-color: #bbb; }
        .artifact-kinds { border: 1px solid #ddd; padding: 0.5rem; margin: 0.5rem 0; }
        .artifact-kind-link { background: none; border: none; color: #0066cc; cursor: pointer; text-decoration: underline; font-size: 0.85rem; padding: 0; }
        .artifact-kind-link:hover { color: #004499; }
        .artifact-kind-link:disabled { color: #888; cursor: wait; text-decoration: none; }
        .preview-panel {
          background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 252, 251, 0.96));
          border-color: #d8dfdc;
          border-radius: 18px;
          box-shadow: 0 18px 44px rgba(23, 32, 29, 0.08);
          overflow: auto;
        }
        .preview-full-span {
          grid-column: 1 / -1;
        }
        .preview-full-span > section {
          background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 252, 251, 0.96));
          border: 1px solid #d8dfdc;
          border-radius: 18px;
          box-shadow: 0 18px 44px rgba(23, 32, 29, 0.08);
        }
        .artifact-preview {
          background: rgba(255, 255, 255, 0.92);
          border: 1px solid #e4ebe8;
          border-radius: 14px;
          margin: 0.75rem 0;
          padding: 0.9rem 1rem;
        }
        .artifact-preview-content {
          background: #111816;
          border-radius: 12px;
          color: #d9fff8;
          font-size: 0.8rem;
          margin: 0.45rem 0 0;
          max-height: 400px;
          overflow: auto;
          overflow-wrap: anywhere;
          padding: 0.8rem;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .trace-section {
          border-left: 3px solid #7b8d85;
          margin-top: 0.6rem;
          padding-left: 0.7rem;
        }
        .trace-section ul { margin: 0.25rem 0 0 1rem; padding: 0; }
        .artifact-preview button,
        .file-alias-actions button {
          background: #fff;
          border: 1px solid #b9c5c0;
          border-radius: 10px;
          color: #17201d;
          padding: 0.5rem 0.8rem;
        }
        .file-alias-actions button:disabled {
          border-color: #d2d9d6;
          color: #777;
        }
        @media (max-width: 980px) {
          .cockpit-layout {
            grid-template-columns: 1fr;
          }
          .cockpit-layout > .panel,
          .preview-full-span {
            max-height: none;
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
  if (!stack) return "not captured";
  const springBoot = String(stack["spring_boot"] ?? "").trim();
  const java = String(stack["java"] ?? "").trim();
  if (!springBoot && !java) return "not captured";
  return `Spring Boot ${springBoot || "?"} / Java ${java || "?"}`;
}

function formatDuration(value: number | null | undefined): string {
  return value == null ? "not captured" : `${value.toFixed(3)}s`;
}

function isReportReady(stages: Stage[]): boolean {
  if (stages.length === 0) return false;
  const highestStageIndex = stages.reduce((highest, stage) => Math.max(highest, stage.stage_index), 0);
  return stages.some((stage) => stage.stage_index === highestStageIndex && stage.chain_status === "completed");
}

function triggerPdfDownload(jobId: string): void {
  if (typeof document === "undefined") return;
  const anchor = document.createElement("a");
  anchor.href = `/api/control-tower/v1/v2/migration-jobs/${encodeURIComponent(jobId)}/final-report.pdf`;
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
