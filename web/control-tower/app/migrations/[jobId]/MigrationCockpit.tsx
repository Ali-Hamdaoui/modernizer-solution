"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  askV2Assistant,
  approveV2Card,
  cancelV2MigrationJob,
  getV2ArtifactPreview,
  getV2RootPomPreview,
  getV2AssistantMessages,
  getV2FailureSummary,
  getV2JobEventSnapshot,
  getV2JobApprovals,
  getV2MigrationJob,
  getV2JobPipeline,
  getV2GateDetail,
  getV2JobGates,
  getV2OpenGate,
  getV2MigrationJobStages,
  getV2FinalReport,
  generateV2FinalReport,
  resolveReportDownloadUrl,
  rejectV2Card,
  updateV2ApprovalMode,
  postV2GateAction,
  requireJobId,
  v2EventStreamUrl,
  v2RootPomDownloadUrl,
  createIdempotencyKey,
} from "../../../lib/controlTowerApi";
import {
  logApprovalEvent,
  logApprovalDecisionsBefore,
  logApprovalDecisionsAfter,
  logOpenGates,
  logApproveClickPayload,
} from "../../../lib/approvalDebug";
import type {
  V2ApprovalResponse,
  V2ArtifactPreviewResponse,
  V2AssistantMessageResponse,
  V2FailureSummaryResponse,
  V2FinalReportResponse,
  V2JobEvent,
  V2MigrationJobResponse,
  V2PipelineResponse,
  V2RouteStepEntry,
  GateDetailResponse,
  GateRepresentation,
  GateEvidencePack,
  MigrationProfileId,
} from "../../../lib/contracts";
import { MIGRATION_PROFILE_OPTIONS } from "../../../lib/contracts";
import Stage3DependencyReview from "./Stage3DependencyReview";
import { RepairProposalPanel } from "./RepairProposalPanel";

export function formatGateArtifactRefLabel(ref: string): string {
  const text = ref.trim();
  if (!text) {
    return "artifact";
  }
  const label = text.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? text;
  return label === "C:" ? "artifact" : label;
}

function formatGateArtifactRefs(refs: string[]): string {
  return refs.map((ref) => formatGateArtifactRefLabel(ref)).join(", ");
}

export interface Stage {
  stage_index: number;
  pipeline_stage: string;
  chain_status: string;
  input_source_kind: string;
}

function formatRouteStepStatusLabel(status: string): string {
  switch (status) {
    case "completed":
      return "COMPLETED";
    case "running":
      return "RUNNING";
    case "blocked":
      return "BLOCKED";
    case "queued":
      return "QUEUED";
    case "failed":
      return "FAILED";
    default:
      return "PENDING";
  }
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

type GatePanelState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | {
      status: "success";
      gates: GateRepresentation[];
      openGate: GateRepresentation | null;
      openGateDetail: GateDetailResponse | null;
    };

type LiveRefreshResults = [
  PromiseSettledResult<{ approvals: V2ApprovalResponse[] }>,
  PromiseSettledResult<{ job_id: string; stages: Stage[] }>,
  PromiseSettledResult<{ events: V2JobEvent[] }>,
  PromiseSettledResult<V2PipelineResponse>,
  PromiseSettledResult<V2FailureSummaryResponse>,
];

export function buildStageTimelineEntries(
  routeSteps: V2RouteStepEntry[] | undefined,
  stages: Stage[],
): Array<V2RouteStepEntry | Stage> {
  if (!routeSteps?.length) {
    return stages;
  }

  const stageStatusByIndex = new Map(stages.map((stage) => [stage.stage_index, stage.chain_status]));
  console.log("[route-steps-before]", routeSteps?.map((s) => ({ route_step_index: s.route_step_index, stage_index: s.stage_index, status: s.status })));
  const result = routeSteps.map((routeStep) => ({
    ...routeStep,
    status: stageStatusByIndex.get(routeStep.stage_index) ?? routeStep.status,
  }));
  console.log("[route-steps-after]", result.map((s) => ({ route_step_index: s.route_step_index, stage_index: s.stage_index, status: s.status })));
  return result;
}

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

export function GatePanelContent({
  state,
  jobId,
  job,
  onGateRefresh,
}: {
  state: GatePanelState;
  jobId?: string;
  job?: V2MigrationJobResponse;
  onGateRefresh?: () => void;
}) {
  if (state.status === "loading") {
    return (
      <section className="panel stack" aria-label="Open gate panel">
        <h2>Open gate</h2>
        <p className="meta">Loading gate state...</p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="panel stack" aria-label="Open gate panel">
        <h2>Open gate</h2>
        <p className="meta" role="alert">Failed to load gate state: {state.message}</p>
      </section>
    );
  }

  if (state.status === "empty") {
    return (
      <section className="panel stack" aria-label="Open gate panel">
        <h2>Open gate</h2>
        <p className="meta">No F15 gates are registered yet for this job.</p>
      </section>
    );
  }

  const gate = state.openGate;
  const detail = state.openGateDetail;

  return (
    <section className="panel stack" aria-label="Open gate panel">
      <h2>Open gate</h2>
      <p className="meta">All gate data comes from backend-owned, gate-bound artifacts and checksums.</p>
      {gate ? (
        <div className="table-list">
          <div className="table-row">
            <span className="meta">Type</span>
            <strong>{gate.gate_phase}</strong>
            <span className="meta">Stage {gate.stage_index}</span>
            <span className="meta">Status: {gate.gate_status}</span>
            <span className="meta">Checksum: {gate.checksum}</span>
          </div>
          <div className="table-row">
            <span className="meta">Summary</span>
            <strong>{"failure_summary" in (detail?.evidence ?? {}) ? (detail?.evidence as { failure_summary: string }).failure_summary : "Open gate awaiting decision"}</strong>
            <span className="meta">Allowed actions: {gate.available_actions.map((action) => action.label).join(", ") || "None"}</span>
          </div>
          <div className="table-row">
            <span className="meta">Safe refs</span>
            <strong>{gate.source_artifact_refs.length > 0 ? formatGateArtifactRefs(gate.source_artifact_refs) : "None"}</strong>
            <span className="meta">Gate count: {state.gates.length}</span>
          </div>
        </div>
      ) : (
        <p className="meta">No gate is currently open for this job.</p>
      )}
      {gate?.gate_phase === "analysis_review" && (
        <>
          <SourceProfileDetectionPanel gateDetail={detail} />
          {jobId && onGateRefresh && (
            <SourceProfileOverrideForm
              gateDetail={detail}
              jobId={jobId}
              job={job}
              onSuccess={onGateRefresh}
            />
          )}
        </>
      )}
    </section>
  );
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
    <section className="panel">
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

// ── F3 — Migration Route Panel ─────────────────────────────────────────

export function MigrationRoutePanel({ job }: { job: V2MigrationJobResponse }) {
  const sourceLabel =
    MIGRATION_PROFILE_OPTIONS.find((p) => p.id === job.source_profile)?.label ?? job.source_profile ?? "unspecified";
  const targetLabel =
    MIGRATION_PROFILE_OPTIONS.find((p) => p.id === job.target_profile)?.label ?? job.target_profile ?? "unspecified";

  return (
    <section className="panel" data-testid="migration-route-panel">
      <h2>Migration Route</h2>
      <div className="table-list">
        <div className="table-row">
          <span className="meta">Source profile</span>
          <strong data-testid="cockpit-source-profile">{sourceLabel}</strong>
        </div>
        <div className="table-row">
          <span className="meta">Target profile</span>
          <strong data-testid="cockpit-target-profile">{targetLabel}</strong>
        </div>
        {job.validation_status && (
          <div className="table-row">
            <span className="meta">Validation</span>
            <strong data-testid="cockpit-validation-status">{job.validation_status}</strong>
            {job.validation_reason && <span className="meta">{job.validation_reason}</span>}
          </div>
        )}
        {job.included_stages && job.included_stages.length > 0 && (
          <div className="table-row">
            <span className="meta">Included stages</span>
            <strong data-testid="cockpit-included-stages">{job.included_stages.join(", ")}</strong>
          </div>
        )}
        {job.skipped_stages && job.skipped_stages.length > 0 && (
          <div className="table-row">
            <span className="meta">Skipped stages</span>
            <strong data-testid="cockpit-skipped-stages">{job.skipped_stages.join(", ")}</strong>
          </div>
        )}
        {job.excluded_stages && job.excluded_stages.length > 0 && (
          <div className="table-row">
            <span className="meta">Excluded stages</span>
            <strong data-testid="cockpit-excluded-stages">{job.excluded_stages.join(", ")}</strong>
          </div>
        )}
        {job.run_configuration_id && (
          <div className="table-row">
            <span className="meta">Run config</span>
            <strong data-testid="cockpit-run-config-id">{job.run_configuration_id}</strong>
          </div>
        )}
        {job.stage_continuation_policy && (
          <div className="table-row">
            <span className="meta">Continuation policy</span>
            <strong data-testid="cockpit-continuation-policy">{job.stage_continuation_policy}</strong>
          </div>
        )}
      </div>
      <p className="meta">All route data is backend-returned. No local recomputation.</p>
    </section>
  );
}

// ── F4 — Source Profile Detection Panel ────────────────────────────────

function tryParseDetectionArtifact(
  evidence: GateEvidencePack | null,
): Record<string, unknown> | null {
  if (!evidence?.artifacts?.length) return null;
  const detectionArtifact = evidence.artifacts.find(
    (a) => a.kind === "source_profile_detection" || a.kind === "detection",
  );
  if (!detectionArtifact?.content) return null;
  try {
    return JSON.parse(detectionArtifact.content) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function SourceProfileDetectionPanel({
  gateDetail,
}: {
  gateDetail: GateDetailResponse | null;
}) {
  const evidence = gateDetail?.evidence;
  if (!evidence || !("pack_type" in evidence)) {
    return (
      <div className="info-box" data-testid="detection-evidence-unavailable">
        <p>Source-profile detection evidence is unavailable; refresh the gate or rerun analysis.</p>
      </div>
    );
  }

  const pack = evidence as GateEvidencePack;
  const detected = tryParseDetectionArtifact(pack);

  return (
    <section className="panel" data-testid="source-profile-detection-panel">
      <h2>Source Profile Detection</h2>
      <div className="table-list">
        <div className="table-row">
          <span className="meta">Pack type</span>
          <strong>{pack.pack_type}</strong>
        </div>
        <div className="table-row">
          <span className="meta">Summary</span>
          <strong>{pack.summary || "No summary available"}</strong>
        </div>
        <div className="table-row">
          <span className="meta">Artifacts</span>
          <strong>
            {pack.resolved_artifact_count}/{pack.total_artifact_count} resolved
          </strong>
        </div>
        {pack.missing_refs.length > 0 && (
          <div className="table-row">
            <span className="meta">Missing refs</span>
            <strong className="warning-text">{pack.missing_refs.join(", ")}</strong>
          </div>
        )}
        {pack.checksum_mismatches.length > 0 && (
          <div className="table-row">
            <span className="meta">Checksum mismatches</span>
            <strong className="warning-text">{pack.checksum_mismatches.join(", ")}</strong>
          </div>
        )}
        {pack.failure_message && (
          <div className="table-row">
            <span className="meta">Failure</span>
            <strong className="warning-text">{pack.failure_message}</strong>
          </div>
        )}
        {detected && (
          <>
            {detected.detected_source_profile && (
              <div className="table-row">
                <span className="meta">Detected source profile</span>
                <strong data-testid="detected-source-profile">{String(detected.detected_source_profile)}</strong>
              </div>
            )}
            {detected.confidence != null && (
              <div className="table-row">
                <span className="meta">Confidence</span>
                <strong>{String(detected.confidence)}</strong>
              </div>
            )}
            {detected.uncertainty_notes && (
              <div className="table-row">
                <span className="meta">Uncertainty</span>
                <strong>{String(detected.uncertainty_notes)}</strong>
              </div>
            )}
          </>
        )}
      </div>
      <p className="meta">Evidence is backend-owned. Do not use parsed content as execution input.</p>
    </section>
  );
}

// ── F4 — Source Profile Override Form ──────────────────────────────────

export type SourceProfileOverrideBlockedReason =
  | "missing_target_profile"
  | "missing_detection_artifact_ref"
  | "missing_detection_artifact_checksum"
  | "missing_reason"
  | "missing_comments"
  | "gate_phase_not_analysis_review"
  | "override_action_unavailable"
  | null;

export function getSourceProfileOverrideBlockedReason(input: {
  isAnalysisReview: boolean;
  hasOverrideAction: boolean;
  hasTargetProfile: boolean;
  hasDetectionArtifactRef: boolean;
  hasExpectedChecksum: boolean;
  reason: string;
  comments: string;
}): SourceProfileOverrideBlockedReason {
  if (!input.isAnalysisReview) {
    return "gate_phase_not_analysis_review";
  }
  if (!input.hasOverrideAction) {
    return "override_action_unavailable";
  }
  if (!input.hasTargetProfile) {
    return "missing_target_profile";
  }
  if (!input.hasDetectionArtifactRef) {
    return "missing_detection_artifact_ref";
  }
  if (!input.hasExpectedChecksum) {
    return "missing_detection_artifact_checksum";
  }
  if (input.reason.trim().length === 0) {
    return "missing_reason";
  }
  if (input.comments.trim().length === 0) {
    return "missing_comments";
  }
  return null;
}

export const SOURCE_PROFILE_OVERRIDE_BLOCKED_COPY: Record<
  Exclude<SourceProfileOverrideBlockedReason, null>,
  string
> = {
  missing_target_profile: "Missing target profile from backend job state.",
  missing_detection_artifact_ref: "Missing detection artifact reference bound to this gate.",
  missing_detection_artifact_checksum: "Missing detection artifact checksum from gate state.",
  missing_reason: "Reason is required.",
  missing_comments: "Comments are required.",
  gate_phase_not_analysis_review: "Source-profile override is only available at analysis_review gates.",
  override_action_unavailable: "The override_source_profile action is not available on this gate.",
};

export const SOURCE_PROFILE_OVERRIDE_GENERIC_COPY =
  "Source-profile detection evidence is unavailable; refresh the gate or rerun analysis.";

function findDetectionArtifactRef(sourceArtifactRefs: string[]): string {
  for (const ref of sourceArtifactRefs) {
    if (typeof ref !== "string") continue;
    const trimmed = ref.trim();
    if (!trimmed) continue;
    const normalized = trimmed.replace(/\\/g, "/");
    const filename = normalized.split("/").filter(Boolean).pop() ?? "";
    if (filename.toLowerCase().includes("source_profile_detection")) {
      return trimmed;
    }
  }
  return "";
}

function findDetectedSourceProfileFromEvidence(
  evidence: GateDetailResponse["evidence"],
): string {
  if (!evidence || !("pack_type" in evidence)) return "";
  const pack = evidence as GateEvidencePack;
  const detectionArtifact = pack.artifacts?.find(
    (a) =>
      typeof a?.kind === "string" &&
      (a.kind === "source_profile_detection" ||
        a.kind === "detection" ||
        a.kind.toLowerCase().includes("source_profile_detection")),
  );
  if (!detectionArtifact?.content) return "";
  try {
    const parsed = JSON.parse(detectionArtifact.content) as Record<string, unknown>;
    const value = parsed.detected_source_profile;
    return typeof value === "string" ? value : "";
  } catch {
    return "";
  }
}

export type SourceProfileOverrideSubmitBody = {
  gate_id: string;
  job_id: string;
  action: "override_source_profile";
  expected_gate_checksum: string;
  idempotency_key: string;
  decided_by: "human";
  actor_type: "human";
  reason: string;
  comments: string;
  override_source_profile: MigrationProfileId;
  detection_artifact_ref: string;
  detected_source_profile: MigrationProfileId | undefined;
  requested_source_profile: MigrationProfileId;
  target_profile: MigrationProfileId;
  expected_detection_artifact_checksum: string;
};

export type BuildSourceProfileOverrideBodyResult = {
  body: SourceProfileOverrideSubmitBody | null;
  blockedReason: SourceProfileOverrideBlockedReason;
  detectionArtifactRef: string;
  expectedDetectionChecksum: string;
  detectedSourceProfile: MigrationProfileId | undefined;
  targetProfile: MigrationProfileId | null;
};

export type BuildSourceProfileOverrideBodyInput = {
  gate: GateRepresentation;
  jobId: string;
  job?: V2MigrationJobResponse;
  evidence: GateDetailResponse["evidence"];
  requestedProfile: MigrationProfileId;
  reason: string;
  comments: string;
  idempotencyKey: string;
  detectedSourceProfile?: MigrationProfileId;
};

export function buildSourceProfileOverrideBody(
  input: BuildSourceProfileOverrideBodyInput,
): BuildSourceProfileOverrideBodyResult {
  const detectionArtifactRef = findDetectionArtifactRef(input.gate.source_artifact_refs);
  const expectedDetectionChecksum = input.gate.source_artifact_checksum;
  const detectedFromEvidence = findDetectedSourceProfileFromEvidence(input.evidence);
  const detectedSourceProfile: MigrationProfileId | undefined =
    detectedFromEvidence &&
    MIGRATION_PROFILE_OPTIONS.find((p) => p.id === detectedFromEvidence)
      ? (detectedFromEvidence as MigrationProfileId)
      : input.detectedSourceProfile;

  const jobTarget = input.job?.target_profile;
  const targetProfile: MigrationProfileId | null = (() => {
    if (
      jobTarget &&
      MIGRATION_PROFILE_OPTIONS.find((p) => p.id === jobTarget)?.selectableAsTarget
    ) {
      return jobTarget;
    }
    if (
      detectedSourceProfile &&
      MIGRATION_PROFILE_OPTIONS.find((p) => p.id === detectedSourceProfile)?.selectableAsTarget
    ) {
      return detectedSourceProfile;
    }
    return null;
  })();

  const isAnalysisReview = input.gate.gate_phase === "analysis_review";
  const hasOverrideAction = !!input.gate.available_actions.some(
    (a) => a.action === "override_source_profile",
  );

  const blockedReason = getSourceProfileOverrideBlockedReason({
    isAnalysisReview,
    hasOverrideAction,
    hasTargetProfile: targetProfile !== null,
    hasDetectionArtifactRef: detectionArtifactRef.length > 0,
    hasExpectedChecksum: expectedDetectionChecksum.length > 0,
    reason: input.reason,
    comments: input.comments,
  });

  if (
    blockedReason !== null ||
    targetProfile === null ||
    input.gate.checksum.length === 0
  ) {
    return {
      body: null,
      blockedReason,
      detectionArtifactRef,
      expectedDetectionChecksum,
      detectedSourceProfile,
      targetProfile,
    };
  }

  return {
    body: {
      gate_id: input.gate.gate_id,
      job_id: input.jobId,
      action: "override_source_profile",
      expected_gate_checksum: input.gate.checksum,
      idempotency_key: input.idempotencyKey,
      decided_by: "human",
      actor_type: "human",
      reason: input.reason,
      comments: input.comments,
      override_source_profile: input.requestedProfile,
      detection_artifact_ref: detectionArtifactRef,
      detected_source_profile: detectedSourceProfile,
      requested_source_profile: input.requestedProfile,
      target_profile: targetProfile,
      expected_detection_artifact_checksum: expectedDetectionChecksum,
    },
    blockedReason: null,
    detectionArtifactRef,
    expectedDetectionChecksum,
    detectedSourceProfile,
    targetProfile,
  };
}

export function SourceProfileOverrideForm({
  gateDetail,
  jobId,
  job,
  onSuccess,
}: {
  gateDetail: GateDetailResponse | null;
  jobId: string;
  job?: V2MigrationJobResponse;
  onSuccess: () => void;
}) {
  const [requestedProfile, setRequestedProfile] = useState<MigrationProfileId>("springboot-2.7-java11");
  const [reason, setReason] = useState("");
  const [comments, setComments] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const gate = gateDetail?.gate;
  const evidence = gateDetail?.evidence;
  const isAnalysisReview = gate?.gate_phase === "analysis_review";
  const hasOverrideAction = !!gate?.available_actions.some(
    (a) => a.action === "override_source_profile",
  );

  // Backend-bound target profile: prefer job.target_profile, fall back to
  // detected_source_profile from the detection evidence artifact only when
  // the job target is unavailable. Never derive from gate_phase.
  const detectedFromEvidence = findDetectedSourceProfileFromEvidence(evidence ?? null);
  const targetProfile: MigrationProfileId | null = (() => {
    const jobTarget = job?.target_profile;
    if (jobTarget && (MIGRATION_PROFILE_OPTIONS.find((p) => p.id === jobTarget)?.selectableAsTarget ?? false)) {
      return jobTarget;
    }
    if (
      detectedFromEvidence &&
      (MIGRATION_PROFILE_OPTIONS.find((p) => p.id === detectedFromEvidence)?.selectableAsTarget ?? false)
    ) {
      return detectedFromEvidence as MigrationProfileId;
    }
    return null;
  })();

  // Backend-bound detection artifact ref: must come from gate.source_artifact_refs.
  // Select the ref whose filename contains "source_profile_detection".
  const detectionArtifactRef = findDetectionArtifactRef(gate?.source_artifact_refs ?? []);

  // Backend-bound detection checksum: use gate.source_artifact_checksum
  // (the canonical gate-bound checksum), never pack_id or pack metadata.
  const expectedDetectionChecksum = gate?.source_artifact_checksum ?? "";

  const requestedProfileValid =
    MIGRATION_PROFILE_OPTIONS.find((p) => p.id === requestedProfile)?.selectableAsSource ?? false;
  const detectedSourceProfile: MigrationProfileId | undefined =
    detectedFromEvidence &&
    (MIGRATION_PROFILE_OPTIONS.find((p) => p.id === detectedFromEvidence) !== undefined)
      ? (detectedFromEvidence as MigrationProfileId)
      : undefined;

  const blockedReason = getSourceProfileOverrideBlockedReason({
    isAnalysisReview,
    hasOverrideAction,
    hasTargetProfile: targetProfile !== null,
    hasDetectionArtifactRef: detectionArtifactRef.length > 0,
    hasExpectedChecksum: expectedDetectionChecksum.length > 0,
    reason,
    comments,
  });
  const canSubmit =
    blockedReason === null && gate?.checksum !== undefined && gate.checksum.length > 0 && requestedProfileValid;

  if (!isAnalysisReview || !hasOverrideAction) {
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!gate) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = buildSourceProfileOverrideBody({
        gate,
        jobId,
        job,
        evidence: evidence ?? null,
        requestedProfile,
        reason,
        comments,
        idempotencyKey: createIdempotencyKey(),
        detectedSourceProfile,
      });
      if (result.body === null) {
        setSubmitError(
          result.blockedReason !== null
            ? SOURCE_PROFILE_OVERRIDE_BLOCKED_COPY[result.blockedReason]
            : SOURCE_PROFILE_OVERRIDE_GENERIC_COPY,
        );
        return;
      }
      await postV2GateAction(jobId, gate.gate_id, result.body);
      onSuccess();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Override submission failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel" data-testid="source-profile-override-form">
      <h2>Override Source Profile</h2>
      <p className="meta">
        Only a human checksum-bound gate action can override source profile.
      </p>
      {!canSubmit && (
        <div className="info-box" data-testid="override-submit-disabled">
          <p data-testid="override-blocked-reason">
            {blockedReason !== null
              ? SOURCE_PROFILE_OVERRIDE_BLOCKED_COPY[blockedReason]
              : SOURCE_PROFILE_OVERRIDE_GENERIC_COPY}
          </p>
        </div>
      )}
      <form onSubmit={(e) => void handleSubmit(e)}>
        <div className="field-row">
          <label>Requested Profile *</label>
          <select
            value={requestedProfile}
            onChange={(e) => setRequestedProfile(e.target.value as MigrationProfileId)}
            data-testid="override-profile-select"
          >
            {MIGRATION_PROFILE_OPTIONS.filter((p) => p.selectableAsSource).map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field-row">
          <label>Reason *</label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why override the detected source profile?"
            required
            aria-required="true"
            data-testid="override-reason-input"
          />
        </div>
        <div className="field-row">
          <label>Comments *</label>
          <textarea
            rows={3}
            value={comments}
            onChange={(e) => setComments(e.target.value)}
            placeholder="Required additional context for the override"
            required
            aria-required="true"
            data-testid="override-comments-input"
          />
        </div>
        {submitError && (
          <p className="error-box" role="alert" data-testid="override-submit-error">
            {submitError}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting || !canSubmit}
          data-testid="override-submit-button"
        >
          {submitting ? "Submitting..." : "Submit Override"}
        </button>
      </form>
    </section>
  );
}

export function ApprovalModePanel({
  enabled,
  busy,
  error,
  onToggle,
}: {
  enabled: boolean;
  busy: boolean;
  error: string | null;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <section className="panel" aria-label="Approval mode">
      <h2>Approval Mode</h2>
      <div className="approval-mode-row">
        <div>
          <strong>{enabled ? "Auto Approval ON" : "Manual"}</strong>
          <p className="meta">{enabled ? "Successful approval gates are approved automatically." : "Approval gates wait for manual Approve or Reject."}</p>
        </div>
        <label className="toggle-control">
          <input
            type="checkbox"
            checked={enabled}
            disabled={busy}
            onChange={(event) => onToggle(event.target.checked)}
          />
          <span>{busy ? "Updating..." : enabled ? "On" : "Off"}</span>
        </label>
      </div>
      {error && <p className="warning-text" role="alert">{error}</p>}
    </section>
  );
}

export function ApprovalDecisionsPanel({
  approvals,
  approvalReviewOpen,
  approvalBusy,
  onApprove,
  onReject,
}: {
  approvals: V2ApprovalResponse[];
  approvalReviewOpen: boolean;
  approvalBusy: string | null;
  onApprove: (card: V2ApprovalResponse) => void;
  onReject: (card: V2ApprovalResponse) => void;
}) {
  // Approval rendering is driven entirely by backend-owned approval decisions.
  // Every pending gate renders its own active Approve/Reject buttons.
  // An approved/rejected gate only disables its own buttons; it must never
  // hide buttons for a different pending gate (later stages included).
  return (
    <section className="panel">
      <h2>Approval Decisions</h2>
      {approvalReviewOpen && (
        <p className="meta">
          A pre-transform review gate is open. Approve/Reject buttons are enabled below for each pending gate; the chatbot can also confirm the exact checksum.
        </p>
      )}
      {approvals.length === 0 ? (
        <p className="meta">No pending decisions.</p>
      ) : (
        approvals.map((a) => (
          <div key={a.card_id} className="approval-card">
            <div className="stage-header">
              <strong>Stage {a.stage_index}</strong>
              <span className={`status-badge ${a.status}`}>{a.status.replace(/_/g, " ").toUpperCase()}</span>
            </div>
            <p>{a.summary}</p>
            <p className="checksum">Checksum: {a.request_checksum}</p>
            {a.status === "auto_approved" && <p className="meta">Mode: Auto Approval | Timestamp: {a.created_at}</p>}
            {a.reviewer_decision && (
              <p className="meta">
                Reviewer: {a.reviewer_decision}
                {a.reviewer_critique_id ? ` (${a.reviewer_critique_id})` : ""}
              </p>
            )}
            {a.reviewed_checksum && <p className="checksum">Reviewed checksum: {a.reviewed_checksum}</p>}
            {a.status === "pending" ? (
              <div className="approval-actions">
                <button
                  type="button"
                  disabled={approvalBusy === a.card_id}
                  onClick={() => onApprove(a)}
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={approvalBusy === a.card_id}
                  onClick={() => onReject(a)}
                >
                  Reject
                </button>
              </div>
            ) : (
              <p className="meta">Decision recorded.</p>
            )}
          </div>
        ))
      )}
      <p className="meta">LLM cannot approve; exact checksum required.</p>
    </section>
  );
}

export function MigrationCockpit({ jobId }: { jobId?: string }) {
  const router = useRouter();
  const [data, setData] = useState<CockpitData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantError, setAssistantError] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [approvalModeBusy, setApprovalModeBusy] = useState(false);
  const [approvalModeError, setApprovalModeError] = useState<string | null>(null);
  const [artifactPreview, setArtifactPreview] = useState<V2ArtifactPreviewResponse | null>(null);
  const [artifactPreviewBusy, setArtifactPreviewBusy] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const [liveRefreshWarning, setLiveRefreshWarning] = useState<string | null>(null);
  const [gateState, setGateState] = useState<GatePanelState>({ status: "loading" });
  const [report, setReport] = useState<V2FinalReportResponse | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const normalizedJobId = jobId?.trim() ?? "";
  const approvalReviewOpen = gateState.status === "success" && gateState.openGate?.gate_phase === "approval_review";

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
    if (!normalizedJobId || !report?.eligible) return;
    setReportBusy(true);
    try {
      setReport(await generateV2FinalReport(normalizedJobId));
    } finally {
      setReportBusy(false);
    }
  }

  useEffect(() => {
    if (!normalizedJobId) {
      setGateState({ status: "loading" });
      return;
    }

    let cancelled = false;
    async function loadGateState() {
      try {
        const safeJobId = requireJobId(normalizedJobId);
        const [gateList, openGateResponse] = await Promise.all([
          getV2JobGates(safeJobId),
          getV2OpenGate(safeJobId),
        ]);
        if (cancelled) return;
        const openGate = openGateResponse.gate ?? null;
        const openGateDetail = openGate
          ? await getV2GateDetail(safeJobId, openGate.gate_id).catch(() => null)
          : null;
        if (cancelled) return;
        setGateState({
          status: gateList.gates.length === 0 ? "empty" : "success",
          gates: gateList.gates,
          openGate,
          openGateDetail,
        });
      } catch (e) {
        if (!cancelled) {
          setGateState({
            status: "error",
            message: e instanceof Error ? e.message : "Failed to load gate state.",
          });
        }
      }
    }
    loadGateState();
    return () => {
      cancelled = true;
    };
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
      "approval_mode_updated",
      "approval_required",
      "approval_auto_approved",
      "stage_blocked_for_approval",
      "sandbox_transform_started",
      "sandbox_transform_completed",
      "final_report_started",
      "final_report_completed",
      "artifact_written",
      "stage_completed",
      "migration_completed",
      "stage_failed",
      "next_stage_queued",
      "job_completed",
      "proof_updated",
      "approval_resume_queued",
      "resume_started",
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
      "migration_cancelling",
      "stage_cancelled",
      "migration_cancelled",
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
      logApprovalEvent(event);
      if (event.type === "approval_mode_updated") {
        const enabled = Boolean(event.payload?.auto_approval_enabled);
        setData((current) => current ? {
          ...current,
          job: { ...current.job, auto_approval_enabled: enabled },
        } : current);
      }
      console.log("[migration-event]", {
        type: event.type,
        stage: event.stage,
        status: event.status,
        sequence: event.sequence,
        payload: event.payload,
      });
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
      // On important events, refresh from backend (async, non-blocking).
      // Gate state is refreshed too so the open-gate slot and approvalReviewOpen
      // stay current as later-stage gates open/resolve (not just on mount).
      if (IMPORTANT_SSE_TYPES.has(event.type)) {
        void refreshLiveState().catch(() => {
          setLiveRefreshWarning("Live refresh temporarily failed. Retrying...");
        });
        void refreshGateState().catch(() => {
          // keep existing gate state on refresh failure
        });
      }
    } catch {
      setStreamState("reconnecting");
    }
  }

  async function handleCancelMigration() {
    if (!normalizedJobId || cancelBusy) return;
    setCancelBusy(true);
    setCancelError(null);
    try {
      await cancelV2MigrationJob(normalizedJobId);
      setStreamState("reconnecting");
      router.push("/migrations/new");
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : "Cancel migration failed");
    } finally {
      setCancelBusy(false);
    }
  }

  async function updateApprovalMode(nextEnabled: boolean) {
    if (!normalizedJobId || approvalModeBusy) return;
    if (nextEnabled) {
      const confirmed = window.confirm(
        "Auto Approval will automatically approve future successful analysis/planning/assessment gates for this migration job. You can turn it off at any time. Failed or unsafe gates will not be auto-approved. Do you want to enable it?"
      );
      if (!confirmed) return;
    }
    setApprovalModeBusy(true);
    setApprovalModeError(null);
    try {
      const response = await updateV2ApprovalMode(normalizedJobId, nextEnabled);
      setData((current) => {
        if (!current) return current;
        return {
          ...current,
          job: response.job ?? {
            ...current.job,
            auto_approval_enabled: response.auto_approval_enabled,
          },
        };
      });
      // When the backend auto-approved the currently open gate, proactively
      // refresh approvals, pipeline status, and the open-gate panel so the UI
      // reflects AUTO APPROVED + Transform running without waiting for SSE.
      if (response.auto_approved) {
        console.log("[approval-mode-auto-approved]", {
          jobId: normalizedJobId,
          gateId: response.auto_approved.gate_id,
          stageId: response.auto_approved.stage_index,
          decisionSource: "auto_approval",
        });
        void refreshLiveState().catch(() => {
          setLiveRefreshWarning("Live refresh temporarily failed. Retrying...");
        });
        void refreshGateState().catch(() => {
          // keep existing gate state on refresh failure
        });
      }
    } catch (e) {
      console.error("[approval-mode-error]", e);
      setApprovalModeError(
        e instanceof Error
          ? `Could not update approval mode. Please check backend connection or CORS configuration. ${e.message}`
          : "Could not update approval mode. Please check backend connection or CORS configuration."
      );
    } finally {
      setApprovalModeBusy(false);
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
      logApprovalDecisionsBefore(current.approvals);
      const merged = mergeCockpitLiveRefreshResults(current, [
        approvalsResult,
        stagesResult,
        eventsResult,
        pipelineResult,
        failureSummaryResult,
      ]);
      logApprovalDecisionsAfter(merged.data.approvals);
      return merged.data;
    });
  }

  // Best-effort refresh of the gate panel state. Called on important SSE
  // events so that a newly opened later-stage approval_review gate is
  // reflected (and a resolved earlier-stage gate no longer occupies the
  // open-gate slot). Silent on failure: keeps the existing gate state.
  async function refreshGateState() {
    if (!normalizedJobId) return;
    const safeJobId = requireJobId(normalizedJobId);
    try {
      const [gateList, openGateResponse] = await Promise.all([
        getV2JobGates(safeJobId),
        getV2OpenGate(safeJobId),
      ]);
      const openGate = openGateResponse.gate ?? null;
      const openGateDetail = openGate
        ? await getV2GateDetail(safeJobId, openGate.gate_id).catch(() => null)
        : null;
      setGateState({
        status: gateList.gates.length === 0 ? "empty" : "success",
        gates: gateList.gates,
        openGate,
        openGateDetail,
      });
      logOpenGates({ openGate, gateCount: gateList.gates.length });
    } catch {
      // keep existing gate state on refresh failure
    }
  }

  async function approveCard(card: V2ApprovalResponse) {
    if (!normalizedJobId) return;
    setApprovalBusy(card.card_id);
    const payload = {
      jobId: normalizedJobId,
      cardId: card.card_id,
      stageId: card.stage_index,
      checksum: card.request_checksum,
      decision: "approve",
    };
    logApproveClickPayload(payload);
    try {
      await approveV2Card(normalizedJobId, card.card_id, card.request_checksum);
      await refreshLiveState();
      await refreshGateState();
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

  const stageTimelineEntries = buildStageTimelineEntries(data.job.route_steps, data.stages);

  return (
    <div className="cockpit-layout">
      <section className="panel cockpit-actions" data-testid="migration-cancel-panel">
        <div>
          <h2>Migration Controls</h2>
          <p className="meta">Job: {data.job.job_id}</p>
        </div>
        <button
          type="button"
          className="cancel-button"
          disabled={cancelBusy}
          onClick={() => void handleCancelMigration()}
        >
          {cancelBusy ? "Cancelling..." : "Cancel Migration"}
        </button>
        {cancelError && <p className="cancel-error" role="alert">{cancelError}</p>}
      </section>

      {/* Stage Timeline */}
      <section className="panel">
        <h2>Stage Timeline</h2>
        <p className="meta">Job: {data.job.job_id}</p>
        <div className="stage-list">
          {stageTimelineEntries.map((entry) => {
            if ("route_step_index" in entry) {
              const routeStep = entry as V2RouteStepEntry;
              return (
                <div key={routeStep.route_step_index} className={`stage-card ${routeStep.status}`}>
                  <div className="stage-header">
                    <strong>
                      Route step {routeStep.route_step_index}: {routeStep.source_profile} → {routeStep.target_profile}
                    </strong>
                    <span className={`status-badge ${routeStep.status}`}>
                      {formatRouteStepStatusLabel(routeStep.status)}
                    </span>
                    {routeStep.route_step_index === data.job.route_steps?.length && routeStep.status === "completed" && (
                      <span className="status-badge completed">MIGRATION COMPLETED</span>
                    )}
                  </div>
                  <p className="meta">Runtime profile: {routeStep.runtime_profile}</p>
                  <p className="meta">Catalog: {routeStep.catalog}</p>
                  <p className="meta">Execution JDK: {routeStep.execution_jdk}</p>
                  {routeStep.approval_gate_id && <p className="meta">Approval gate: {routeStep.approval_gate_id}</p>}
                  <p className="meta">
                    Artifacts: {routeStep.artifact_refs.length > 0 ? routeStep.artifact_refs.join(", ") : "None yet"}
                  </p>
                  <p className="meta">
                    Evidence: {routeStep.evidence_refs.length > 0 ? routeStep.evidence_refs.join(", ") : "None yet"}
                  </p>
                </div>
              );
            }

            const stage = entry as Stage;
            const isSkipped = data.job.skipped_stages?.includes(String(stage.stage_index));
            const isExcluded = data.job.excluded_stages?.includes(String(stage.stage_index));
            const isIncluded = data.job.included_stages?.includes(String(stage.stage_index));
            return (
              <div key={stage.stage_index} className={`stage-card ${stage.chain_status}`}>
                <div className="stage-header">
                  <strong>{stage.pipeline_stage}</strong>
                  <span className={`status-badge ${stage.chain_status}`}>
                    {formatStageStatusLabel(stage.chain_status)}
                  </span>
                  {isSkipped && (
                    <span className="status-badge skipped" data-testid={`stage-${stage.stage_index}-skipped`}>
                      SKIPPED BY SOURCE
                    </span>
                  )}
                  {isExcluded && (
                    <span className="status-badge excluded" data-testid={`stage-${stage.stage_index}-excluded`}>
                      EXCLUDED BY TARGET
                    </span>
                  )}
                  {isIncluded && (
                    <span className="meta" data-testid={`stage-${stage.stage_index}-included`}>
                      included
                    </span>
                  )}
                </div>
                <p className="meta">Input: {stage.input_source_kind}</p>
                {stage.stage_index === 4 && (
                  <p className="meta">
                    Stage 4 is the Spring Boot 4 migration stage and follows the same approval and evidence flow as the earlier stages.
                  </p>
                )}
              </div>
            );
          })}
        </div>
        {data.job.route_steps?.length ? (
          <p className="meta">
            Executable route steps are backend-projected from the selected source/target pair. Skipped and excluded stages remain metadata only.
          </p>
        ) : (
          <p className="meta">Stage inputs are fixed by pipeline. No user selection of Stage 2/3 paths.</p>
        )}
      </section>

      {/* F3 — Migration Route Panel */}
      <MigrationRoutePanel job={data.job} />

      {gateState.status !== "loading" ? (
        <GatePanelContent
          state={gateState}
          jobId={normalizedJobId}
          job={data?.job}
          onGateRefresh={() => {
            void refreshGateState();
          }}
        />
      ) : null}

      {/* Evidence Panel */}
      <section className="panel">
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
      <ApprovalModePanel
        enabled={Boolean(data.job.auto_approval_enabled)}
        busy={approvalModeBusy}
        error={approvalModeError}
        onToggle={(enabled) => void updateApprovalMode(enabled)}
      />
      <ApprovalDecisionsPanel
        approvals={data.approvals}
        approvalReviewOpen={approvalReviewOpen}
        approvalBusy={approvalBusy}
        onApprove={(card) => void approveCard(card)}
        onReject={(card) => void rejectCard(card)}
      />

      {/* Failure Summary Panel */}
      {data.failureSummary?.has_failures && (
        <section className="panel failure-panel">
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

      {/* PR-C — Repair Proposal Panel */}
      {normalizedJobId && (
        <RepairProposalPanel jobId={normalizedJobId} />
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

      {/* Proof & Report */}
      <section className="panel">
        <h2>Proof & Report</h2>
        <p className="meta">Final proof report generated when all three deterministic gates pass.</p>
      </section>

      {/* Final Report Panel */}
      <section className="panel">
        <h2>Final Report</h2>
        {report && report.blockers.length > 0 && report.blockers.map((blocker) => (
          <p className="warning-text" key={blocker}>{blocker}</p>
        ))}
        {report && !report.eligible && (
          <p className="meta">Report generation not yet available for this job.</p>
        )}
        <button
          type="button"
          disabled={reportBusy || !report?.eligible}
          onClick={() => void handleGenerateReport()}
        >
          {report?.status === "generated" ? "Regenerate report" : "Generate report"}
        </button>
        {reportBusy && <span className="meta"> Generating...</span>}
        {report?.artifacts.map((artifact) => (
          <div key={artifact.artifact_id} className="report-artifact-row">
            <span className="meta">{artifact.kind}</span>
            <span className="checksum">{artifact.checksum_sha256.slice(0, 16)}...</span>
            <a
              href={resolveReportDownloadUrl(artifact.download_url)}
              download
            >
              Download
            </a>
          </div>
        ))}
      </section>

      {/* F14 — Stage 3 Dependency Review */}
      {data && (
        <section style={{ gridColumn: "1 / -1" }}>
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
        .cockpit-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        .cockpit-actions { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
        .cancel-button { border: 1px solid #a40000; background: #a40000; color: #fff; border-radius: 4px; padding: 0.65rem 1rem; font-weight: 600; }
        .cancel-button:disabled { background: #b66; border-color: #b66; cursor: not-allowed; }
        .cancel-error { color: #a40000; margin: 0; }
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
        .status-badge.auto_approved { background: #e4f7e8; color: #146c2e; }
        .status-badge.pass { background: #e4f7e8; color: #146c2e; }
        .status-badge.failed { background: #ffe3e3; color: #a40000; }
        .status-badge.cancelled { background: #f4d8d8; color: #7a0000; }
        .status-badge.blocked { background: #f5e8ff; color: #5a248a; }
        .status-badge.pending { background: #eee; color: #666; }
        .status-badge.skipped { background: #e8f4ff; color: #005599; }
        .status-badge.excluded { background: #ffe8e8; color: #990000; }
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
        .approval-mode-row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
        .toggle-control { display: inline-flex; align-items: center; gap: 0.5rem; font-weight: 600; }
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
        .artifact-preview { border: 1px solid #0066cc; background: #f0f6ff; padding: 1rem; margin: 0.75rem 0; border-radius: 4px; }
        .artifact-preview-content { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 400px; overflow-y: auto; background: #fff; padding: 0.5rem; border: 1px solid #ddd; font-size: 0.8rem; }
        .report-artifact-row { display: flex; gap: 0.5rem; align-items: center; padding: 0.35rem 0; border-bottom: 1px solid #eee; }
        .report-artifact-row a { color: #0066cc; text-decoration: underline; font-size: 0.85rem; }
      `}</style>
    </div>
  );
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
      .filter((event) => eventAppliesToStage(event, stage.stage_index))
      .sort((a, b) => a.sequence - b.sequence);
    return { ...stage, chain_status: reduceStageStatus(stageEvents, stage.stage_index) };
  });
}

function eventAppliesToStage(event: V2JobEvent, stageIndex: number): boolean {
  if (event.type !== "next_stage_queued") {
    return event.stage === stageIndex;
  }

  const payload = event.payload ?? {};
  const fromStage = Number(payload.from_stage ?? 0);
  const toStage = Number(payload.to_stage ?? event.stage ?? 0);
  return fromStage === stageIndex || toStage === stageIndex;
}

/** Map a single (event.type, event.status) to a stage status *label*.
 *  This is an *input* to the chronological reducer; the label alone does
 *  NOT determine the final stage status (see reduceStageStatus). */
export function stageStatusFromEvent(event: V2JobEvent): string {
  if (event.type === "stage_cancelled" || event.status === "cancelled") return "cancelled";
  if (event.type === "stage_failed" || event.status === "failed") return "failed";
  if (event.type === "stage_completed") return "completed";
  if (["stage_started", "command_started", "sandbox_transform_started",
       "sandbox_transform_completed", "resume_started", "approval_resume_queued",
       "approval_completed", "build_started", "test_started"].includes(event.type) || event.status === "running") {
    return "running";
  }
  if (event.type === "approval_auto_approved") return "completed";
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
  if (current === "cancelled") return "cancelled";
  if (mapped === "cancelled") return "cancelled";
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

export function formatStageStatusLabel(status: string): string {
  return status.replace(/_/g, " ").toUpperCase();
}

/** Reduce chronologically-ordered events to a single stage status. */
export function reduceStageStatus(events: V2JobEvent[], stageIndex?: number): string {
  let current = "pending";
  for (const event of events) {
    if (event.type === "next_stage_queued" && stageIndex != null) {
      const payload = event.payload ?? {};
      const fromStage = Number(payload.from_stage ?? 0);
      const toStage = Number(payload.to_stage ?? event.stage ?? 0);
      if (fromStage === stageIndex) {
        current = transitionStageStatus(current, "completed");
        continue;
      }
      if (toStage === stageIndex) {
        current = transitionStageStatus(current, "queued");
        continue;
      }
    }
    current = transitionStageStatus(current, stageStatusFromEvent(event));
  }
  return current;
}

const IMPORTANT_SSE_TYPES = new Set([
  "approval_mode_updated",
  "approval_required",
  "approval_auto_approved",
  "stage_blocked_for_approval",
  "approval_resume_queued",
  "approval_started",
  "approval_completed",
  "resume_started",
  "sandbox_transform_started",
  "sandbox_transform_completed",
  "sandbox_transform_failed",
  "analysis_started",
  "analysis_completed",
  "analysis_failed",
  "planning_started",
  "planning_completed",
  "planning_failed",
  "assessment_started",
  "assessment_completed",
  "assessment_failed",
  "final_report_started",
  "final_report_completed",
  "final_report_failed",
  "stage_failed",
  "stage_completed",
  "model_invocation_completed",
  "model_invocation_failed",
  "transform_failed",
  "build_failed",
  "repair_started",
  "repair_fallback_generated",
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
