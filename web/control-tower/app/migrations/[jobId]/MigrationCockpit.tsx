"use client";

import { useState, useCallback, useEffect } from "react";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

interface Stage {
  stage_index: number;
  pipeline_stage: string;
  chain_status: string;
  input_source_kind: string;
}

interface CockpitData {
  job_id: string;
  stages: Stage[];
  approvals: Array<{ card_id: string; status: string; summary: string; request_checksum: string }>;
  messages: Array<{ message_id: string; role: string; content: string }>;
}

export function MigrationCockpit({ jobId }: { jobId: string }) {
  const [data, setData] = useState<CockpitData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadCockpit() {
      try {
        // Fetch real V2 data
        const [messagesRes, approvalsRes, commandsRes] = await Promise.allSettled([
          fetch(`${API_BASE}/v1/v2/jobs/${encodeURIComponent(jobId)}/assistant/messages`, {
            headers: { Host: "127.0.0.1:8000" },
          }),
          fetch(`${API_BASE}/v1/v2/jobs/${encodeURIComponent(jobId)}/approvals`, {
            headers: { Host: "127.0.0.1:8000" },
          }),
          fetch(`${API_BASE}/v1/v2/migration-jobs/${encodeURIComponent(jobId)}/stages`, {
            headers: { Host: "127.0.0.1:8000" },
          }),
        ]);

        if (cancelled) return;

        // Parse responses (gracefully handle missing endpoints)
        let messages: Array<{ message_id: string; role: string; content: string }> = [];
        let approvals: Array<{ card_id: string; status: string; summary: string; request_checksum: string }> = [];
        let stages: Stage[] = [
          { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "queued", input_source_kind: "legacy_source" },
          { stage_index: 2, pipeline_stage: "Stage 2", chain_status: "pending", input_source_kind: "stage_1_sandbox" },
          { stage_index: 3, pipeline_stage: "Stage 3", chain_status: "pending", input_source_kind: "stage_2_sandbox" },
        ];

        if (messagesRes.status === "fulfilled" && messagesRes.value.ok) {
          const body = await messagesRes.value.json();
          messages = body.messages || [];
        }
        if (approvalsRes.status === "fulfilled" && approvalsRes.value.ok) {
          const body = await approvalsRes.value.json();
          approvals = body.approvals || [];
        }

        setData({ job_id: jobId, stages, approvals, messages });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load cockpit");
        }
      }
    }
    loadCockpit();
    return () => { cancelled = true; };
  }, [jobId]);

  if (error) return <div className="error-box">{error}</div>;
  if (!data) return <div className="info-box">Loading cockpit...</div>;

  return (
    <div className="cockpit-layout">
      {/* Stage Timeline */}
      <section className="panel">
        <h2>Stage Timeline</h2>
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
        <h2>Evidence</h2>
        <p className="meta">Evidence from command execution, Maven tests, and proof gates.</p>
        <div className="evidence-placeholder">
          <p>Evidence will appear as stages execute.</p>
        </div>
      </section>

      {/* Decisions Panel */}
      <section className="panel">
        <h2>Approval Decisions</h2>
        {data.approvals.length === 0 ? (
          <p className="meta">No pending decisions.</p>
        ) : (
          data.approvals.map((a) => (
            <div key={a.card_id} className="approval-card">
              <span>Status: {a.status}</span>
            </div>
          ))
        )}
        <p className="meta">Exact checksum required for approval. LLM cannot approve.</p>
      </section>

      {/* Assistant Panel */}
      <section className="panel">
        <h2>Assistant</h2>
        {data.messages.length === 0 ? (
          <p className="meta">No messages yet. The assistant can explain status and draft instructions.</p>
        ) : (
          data.messages.map((m) => (
            <div key={m.message_id} className="message">
              <strong>{m.role}:</strong> {m.content}
            </div>
          ))
        )}
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
        .status-badge.pending { background: #eee; color: #666; }
        .meta { font-size: 0.85rem; color: #666; }
        .error-box { border: 1px solid #cc0000; background: #fff0f0; padding: 1rem; border-radius: 6px; }
        .info-box { border: 1px solid #0066cc; background: #f0f6ff; padding: 1rem; border-radius: 6px; }
        .evidence-placeholder { border: 1px dashed #ccc; padding: 1rem; text-align: center; color: #888; }
        .approval-card { border: 1px solid #eee; padding: 0.5rem; margin: 0.25rem 0; }
        .message { border-bottom: 1px solid #eee; padding: 0.5rem 0; }
      `}</style>
    </div>
  );
}
