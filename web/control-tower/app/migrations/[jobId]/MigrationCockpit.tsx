"use client";

import { useState, useEffect } from "react";
import {
  askV2Assistant,
  approveV2Card,
  getV2AssistantMessages,
  getV2JobEventSnapshot,
  getV2JobApprovals,
  getV2MigrationJob,
  getV2JobPipeline,
  getV2MigrationJobStages,
  rejectV2Card,
  requireJobId,
  v2EventStreamUrl,
} from "../../../lib/controlTowerApi";
import type {
  V2ApprovalResponse,
  V2AssistantMessageResponse,
  V2JobEvent,
  V2MigrationJobResponse,
  V2PipelineResponse,
} from "../../../lib/contracts";

interface Stage {
  stage_index: number;
  pipeline_stage: string;
  chain_status: string;
  input_source_kind: string;
}

interface CockpitData {
  job: V2MigrationJobResponse;
  stages: Stage[];
  approvals: V2ApprovalResponse[];
  messages: V2AssistantMessageResponse[];
  events: V2JobEvent[];
  pipeline: V2PipelineResponse;
  assistantModel: { status: string; source: string; provider: string; role: string } | null;
}

export function MigrationCockpit({ jobId }: { jobId?: string }) {
  const [data, setData] = useState<CockpitData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const normalizedJobId = jobId?.trim() ?? "";

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
        const [job, messagesResponse, approvalsResponse, stagesResponse, eventsResponse, pipelineResponse] = await Promise.all([
          getV2MigrationJob(safeJobId),
          getV2AssistantMessages(safeJobId),
          getV2JobApprovals(safeJobId),
          getV2MigrationJobStages(safeJobId),
          getV2JobEventSnapshot(safeJobId),
          getV2JobPipeline(safeJobId),
        ]);

        if (cancelled) return;

        setData({
          job,
          stages: stagesResponse.stages,
          approvals: approvalsResponse.approvals,
          messages: messagesResponse.messages,
          events: eventsResponse.events,
          pipeline: pipelineResponse,
          assistantModel: null,
        });
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
      "model_invocation_started",
      "model_invocation_completed",
      "model_invocation_failed",
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
        return {
          ...current,
          events: updatedEvents,
          stages: applyEventToStages(current.stages, event),
          pipeline: derivePipelineProjection(current.pipeline.job_id, updatedEvents),
        };
      });
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
    const [approvalsResponse, stagesResponse, eventsResponse, pipelineResponse] = await Promise.all([
      getV2JobApprovals(safeJobId),
      getV2MigrationJobStages(safeJobId),
      getV2JobEventSnapshot(safeJobId),
      getV2JobPipeline(safeJobId),
    ]);
    setData((current) => current ? {
      ...current,
      approvals: approvalsResponse.approvals,
      stages: stagesResponse.stages,
      events: eventsResponse.events,
      pipeline: pipelineResponse,
    } : current);
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

  if (error) return <div className="error-box">{error}</div>;
  if (!data) return <div className="info-box">Loading cockpit...</div>;

  return (
    <div className="cockpit-layout">
      {/* Stage Timeline */}
      <section className="panel">
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
      <section className="panel">
        <h2>Pipeline Status</h2>
        <p className="meta">Stream: {streamState}</p>
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

      <section className="panel">
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
      <section className="panel">
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

      {/* Assistant Panel */}
      <section className="panel">
        <h2>Assistant</h2>
        <p className="meta">
          Model: {data.assistantModel?.status ?? "unavailable"} | Source: {data.assistantModel?.source ?? "deterministic"}
        </p>
        {data.messages.length === 0 ? (
          <p className="meta">No messages yet. The assistant can explain status and draft instructions.</p>
        ) : (
          data.messages.map((m) => (
            <div key={m.message_id} className="message">
              <strong>{m.role}:</strong> {m.content}
            </div>
          ))
        )}
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

      {/* Proof & Report */}
      <section className="panel">
        <h2>Proof & Report</h2>
        <p className="meta">Final proof report generated when all three deterministic gates pass.</p>
      </section>

      <style>{`
        .cockpit-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        .panel { border: 1px solid #ccc; border-radius: 6px; padding: 1rem; }
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
      `}</style>
    </div>
  );
}

function applyEventToStages(stages: Stage[], event: V2JobEvent): Stage[] {
  if (!event.stage) return stages;
  return stages.map((stage) => {
    if (stage.stage_index !== event.stage) return stage;
    return { ...stage, chain_status: stageStatusFromEvent(event) };
  });
}

function stageStatusFromEvent(event: V2JobEvent): string {
  if (event.type === "stage_failed" || event.status === "failed") return "failed";
  if (event.type === "approval_required" || event.type === "stage_blocked_for_approval" || event.status === "blocked") return "blocked";
  if (event.type === "stage_completed") return "completed";
  if (["stage_started", "command_started", "stdout", "stderr"].includes(event.type) || event.status === "running") {
    return "running";
  }
  if (["stage_queued", "next_stage_queued"].includes(event.type) || event.status === "queued") return "queued";
  return "pending";
}

const PHASES = [
  { key: "preflight", label: "Preflight", events: ["job_created", "stage_queued"] },
  { key: "analysis", label: "Analysis Agent", events: ["analysis_started", "analysis_completed", "analysis_failed"] },
  { key: "planning", label: "Planning Agent", events: ["planning_started", "planning_completed", "planning_failed"] },
  { key: "assessment", label: "Assessment Agent", events: ["assessment_started", "assessment_completed", "assessment_failed"] },
  { key: "human_approval", label: "Human Approval", events: ["approval_blocked", "approval_required", "stage_blocked_for_approval", "approval_resume_queued", "resume_started"] },
  { key: "sandbox_transform", label: "Transform Agent", events: ["sandbox_transform_started", "sandbox_transform_completed", "sandbox_transform_failed"] },
  { key: "build_validation", label: "Build Agent", events: ["build_started", "build_completed", "build_failed"] },
  { key: "test_validation", label: "Test Validation", events: ["test_started", "test_completed", "test_failed"] },
  { key: "final_report", label: "Final Report", events: ["final_report_started", "final_report_completed", "final_report_failed", "proof_updated", "stage_completed"] },
];

function derivePipelineProjection(jobId: string, events: V2JobEvent[]): V2PipelineResponse {
  const rows = PHASES.map((phase) => {
    const matching = events.filter((event) => phase.events.includes(event.type));
    const latest = matching[matching.length - 1];
    return {
      key: phase.key,
      label: phase.label,
      status: pipelineStatus(matching),
      latest_message: latest?.message ?? "Waiting for backend-owned evidence.",
      artifact_count: events.filter((event) => event.type === "artifact_written").length,
      last_updated: latest?.created_at ?? "",
    };
  });
  const evidence = events.filter((event) =>
    event.type !== "stdout" &&
    event.type !== "stderr" &&
    (event.status === "blocked" || event.status === "failed" || event.type.endsWith("_started") || event.type.endsWith("_completed") || [
      "approval_required",
      "stage_blocked_for_approval",
      "approval_resume_queued",
      "artifact_written",
      "proof_updated",
      "copilot_status_checked",
    ].includes(event.type))
  );
  return {
    job_id: jobId,
    rows,
    evidence: evidence.slice(-100),
    raw_logs: events.filter((event) => event.type === "stdout" || event.type === "stderr").slice(-200),
  };
}

function pipelineStatus(events: V2JobEvent[]): string {
  if (events.length === 0) return "pending";
  if (events.some((event) => event.status === "failed" || event.type.endsWith("_failed"))) return "failed";
  const latest = events[events.length - 1];
  if (latest.status === "blocked") return "blocked";
  if (latest.status === "running" || latest.type.endsWith("_started")) return "running";
  if (latest.type === "approval_resume_queued") return "pass";
  if (events.some((event) => event.status === "completed" || event.type.endsWith("_completed"))) return "pass";
  return "pending";
}
