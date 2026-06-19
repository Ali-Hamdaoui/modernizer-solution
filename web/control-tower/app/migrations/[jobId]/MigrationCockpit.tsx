"use client";

import { useState, useEffect } from "react";
import {
  approveV2RepairProposal,
  applyV2RepairPatchToSandbox,
  askV2Assistant,
  approveV2Card,
  getV2DualModelTraces,
  getV2EvidenceBundle,
  getV2RepairProposalArtifactPreview,
  getV2RepairProposalArtifacts,
  getV2RepairLifecycle,
  getV2AssistantMessages,
  getV2FailureSummary,
  getV2JobEventSnapshot,
  getV2JobApprovals,
  getV2MigrationJob,
  getV2JobPipeline,
  getV2MigrationJobStages,
  materializeV2RepairExecutionPlan,
  materializeV2RepairPatchCandidate,
  rejectV2Card,
  rejectV2RepairProposal,
  validateV2SandboxRepair,
  requireJobId,
  v2EventStreamUrl,
} from "../../../lib/controlTowerApi";
import type {
  V2ApprovalResponse,
  V2AssistantMessageResponse,
  V2DualModelTraceListResponse,
  V2RepairExecutionPlanResponse,
  V2RepairLifecycleListResponse,
  V2RepairPatchCandidateResponse,
  V2RepairProposalArtifactListResponse,
  V2RepairProposalApprovalActionResponse,
  V2RepairProposalArtifactPreviewResponse,
  V2RepairSandboxApplyResponse,
  V2RepairSandboxValidationResponse,
  V2RunEvidenceBundleResponse,
  V2FailureSummaryResponse,
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
  dualModelTraces: V2DualModelTraceListResponse | null;
  repairLifecycle: V2RepairLifecycleListResponse | null;
  repairArtifacts: Record<string, V2RepairProposalArtifactListResponse | null>;
  repairArtifactPreviews: Record<string, V2RepairProposalArtifactPreviewResponse | null>;
  repairActionResults?: Record<string, RepairActionResult | null>;
  evidenceBundle: V2RunEvidenceBundleResponse | null;
  failureSummary: V2FailureSummaryResponse | null;
  assistantModel: { status: string; source: string; provider: string; role: string; failure_reason?: string } | null;
}

type RepairActionResult =
  | V2RepairProposalApprovalActionResponse
  | V2RepairExecutionPlanResponse
  | V2RepairPatchCandidateResponse
  | V2RepairSandboxApplyResponse
  | V2RepairSandboxValidationResponse;

type RepairMutationRefreshState<T> = Pick<CockpitData, "repairLifecycle" | "repairArtifacts" | "repairArtifactPreviews"> & {
  actionResponse: T;
};

export function cockpitEvidenceStatusLines(bundle: V2RunEvidenceBundleResponse | null): string[] {
  if (!bundle) {
    return ["Evidence bundle unavailable."];
  }
  const lines = [
    `Migration: ${bundle.migration_status}`,
    `AI supervision: ${bundle.ai_supervision_status}`,
    `Approval: ${bundle.approval_state}`,
    `Next action: ${bundle.next_operator_action}`,
  ];
  if (bundle.final_status) lines.push(`Final: ${bundle.final_status}`);
  if (bundle.build_status) lines.push(`Build: ${bundle.build_status}`);
  if (bundle.test_status) lines.push(`Test: ${bundle.test_status}`);
  if (bundle.failure_bundle?.root_cause) lines.push(`Root cause: ${bundle.failure_bundle.root_cause}`);
  return lines;
}

export async function refreshRepairLifecyclePanelState(
  jobId: string
): Promise<Pick<CockpitData, "repairLifecycle" | "repairArtifacts" | "repairArtifactPreviews">> {
  const safeJobId = requireJobId(jobId);
  const repairLifecycle = await getV2RepairLifecycle(safeJobId).catch(() => null);
  const repairArtifactState = await loadRepairArtifactState(
    safeJobId,
    repairLifecycle as V2RepairLifecycleListResponse | null,
  );
  return {
    repairLifecycle: repairLifecycle as V2RepairLifecycleListResponse | null,
    repairArtifacts: repairArtifactState.repairArtifacts,
    repairArtifactPreviews: repairArtifactState.repairArtifactPreviews,
  };
}

export async function submitRepairProposalCockpitDecision(args: {
  jobId: string;
  proposalId: string;
  approvalState: string;
  approvalChecksum: string;
  operator?: string;
  reason?: string;
}): Promise<RepairMutationRefreshState<V2RepairProposalApprovalActionResponse>> {
  const safeJobId = requireJobId(args.jobId);
  if ((args.approvalState || "").trim() !== "pending_approval") {
    throw new Error(`Repair proposal ${args.proposalId} is not pending approval.`);
  }
  const actionResponse = (args.reason || "").trim()
    ? await rejectV2RepairProposal(safeJobId, args.proposalId, args.reason, args.operator)
    : await approveV2RepairProposal(safeJobId, args.proposalId, args.approvalChecksum, args.operator);
  const refreshState = await refreshRepairLifecyclePanelState(safeJobId);
  return { ...refreshState, actionResponse };
}

export function canMaterializeRepairExecutionPlan(proposal: {
  current_state: string;
  approval_state: string;
  has_execution_plan: boolean;
  has_patch_candidate: boolean;
  sandbox_apply_state: string;
  sandbox_validation_state: string;
}): boolean {
  return (
    proposal.current_state === "approved"
    && proposal.approval_state === "approved"
    && !proposal.has_execution_plan
    && !proposal.has_patch_candidate
    && proposal.sandbox_apply_state === "not_started"
    && proposal.sandbox_validation_state === "not_started"
  );
}

export async function submitRepairExecutionPlanMaterialization(args: {
  jobId: string;
  proposalId: string;
}): Promise<RepairMutationRefreshState<V2RepairExecutionPlanResponse>> {
  const safeJobId = requireJobId(args.jobId);
  const actionResponse = await materializeV2RepairExecutionPlan(safeJobId, args.proposalId);
  const refreshState = await refreshRepairLifecyclePanelState(safeJobId);
  return { ...refreshState, actionResponse };
}

export function canMaterializeRepairPatchCandidate(proposal: {
  current_state: string;
  approval_state: string;
  has_execution_plan: boolean;
  has_patch_candidate: boolean;
  sandbox_apply_state: string;
  sandbox_validation_state: string;
}): boolean {
  return (
    proposal.current_state === "execution_plan_ready"
    && proposal.approval_state === "approved"
    && proposal.has_execution_plan
    && !proposal.has_patch_candidate
    && proposal.sandbox_apply_state === "not_started"
    && proposal.sandbox_validation_state === "not_started"
  );
}

export function canApplyRepairPatchToSandbox(proposal: {
  current_state: string;
  approval_state: string;
  has_execution_plan: boolean;
  has_patch_candidate: boolean;
  sandbox_apply_state: string;
  sandbox_validation_state: string;
}): boolean {
  return (
    proposal.current_state === "patch_candidate_ready"
    && proposal.approval_state === "approved"
    && proposal.has_execution_plan
    && proposal.has_patch_candidate
    && proposal.sandbox_apply_state === "not_started"
    && proposal.sandbox_validation_state === "not_started"
  );
}

export function canValidateSandboxRepair(proposal: {
  current_state: string;
  approval_state: string;
  has_execution_plan: boolean;
  has_patch_candidate: boolean;
  sandbox_apply_state: string;
  sandbox_validation_state: string;
}): boolean {
  return (
    proposal.current_state === "applied_to_sandbox"
    && proposal.approval_state === "approved"
    && proposal.has_execution_plan
    && proposal.has_patch_candidate
    && proposal.sandbox_apply_state === "applied"
    && proposal.sandbox_validation_state === "not_started"
  );
}

export function getRepairValidationStatusMessages(currentState: string): string[] {
  switch (currentState) {
    case "validation_passed":
      return [
        "Sandbox validation passed.",
        "No source files were modified.",
        "Migration stages were not resumed.",
      ];
    case "validation_failed_rolled_back":
      return [
        "Sandbox validation failed and rollback was performed.",
        "The sandbox file was restored from backup.",
        "No source files were modified.",
        "Migration stages were not resumed.",
      ];
    case "validation_failed_rollback_error":
      return [
        "Validation failed and rollback reported an error.",
        "Manual inspection is required.",
        "No source promotion was performed.",
      ];
    default:
      return [];
  }
}

function parseSandboxValidationPreview(
  preview: V2RepairProposalArtifactPreviewResponse | null
): Record<string, unknown> | null {
  if (!preview || preview.artifact_name !== "sandbox_validation_result.json") {
    return null;
  }
  try {
    const parsed = JSON.parse(preview.content);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function repairActionResponseLines(action: RepairActionResult | null | undefined): string[] {
  if (!action) {
    return [];
  }
  const lines: string[] = [];
  if ("approval_result" in action && action.approval_result) lines.push(`Approval result: ${action.approval_result}`);
  if ("proposal_status" in action && action.proposal_status) lines.push(`Proposal status: ${action.proposal_status}`);
  if ("status" in action && action.status) lines.push(`Status: ${action.status}`);
  if ("approval_state" in action && action.approval_state && typeof action.approval_state === "object") {
    if (action.approval_state.state) lines.push(`Approval state: ${action.approval_state.state}`);
    if (action.approval_state.checksum) lines.push(`Approval checksum: ${action.approval_state.checksum}`);
    if (action.approval_state.read_only_until_apply != null) {
      lines.push(`Read-only until apply: ${String(action.approval_state.read_only_until_apply)}`);
    }
    if (action.approval_state.no_auto_apply != null) {
      lines.push(`No auto apply: ${String(action.approval_state.no_auto_apply)}`);
    }
  }
  if ("applied" in action && typeof action.applied === "boolean") lines.push(`Applied: ${String(action.applied)}`);
  if ("read_only" in action && typeof action.read_only === "boolean") lines.push(`Read-only: ${String(action.read_only)}`);
  if ("sandbox_only" in action && typeof action.sandbox_only === "boolean") lines.push(`Sandbox only: ${String(action.sandbox_only)}`);
  if ("source_mutated" in action && typeof action.source_mutated === "boolean") lines.push(`Source mutated: ${String(action.source_mutated)}`);
  if ("validation_started" in action && typeof action.validation_started === "boolean") {
    lines.push(`Validation started: ${String(action.validation_started)}`);
  }
  if ("stage_resumed" in action && typeof action.stage_resumed === "boolean") lines.push(`Stage resumed: ${String(action.stage_resumed)}`);
  if ("rollback_performed" in action && typeof action.rollback_performed === "boolean") {
    lines.push(`Rollback performed: ${String(action.rollback_performed)}`);
  }
  if ("requires_sandbox_apply" in action && typeof action.requires_sandbox_apply === "boolean") {
    lines.push(`Requires sandbox apply: ${String(action.requires_sandbox_apply)}`);
  }
  if ("requires_validation" in action && typeof action.requires_validation === "boolean") {
    lines.push(`Requires validation: ${String(action.requires_validation)}`);
  }
  if ((action as { human_approved?: boolean }).human_approved != null) {
    lines.push(`Human approved: ${String((action as { human_approved?: boolean }).human_approved)}`);
  }
  if ((action as { patch_operations?: unknown[] }).patch_operations) {
    lines.push(`Patch operations: ${(action as { patch_operations?: unknown[] }).patch_operations?.length ?? 0}`);
  }
  return lines;
}

export async function submitRepairPatchCandidateMaterialization(args: {
  jobId: string;
  proposalId: string;
}): Promise<RepairMutationRefreshState<V2RepairPatchCandidateResponse>> {
  const safeJobId = requireJobId(args.jobId);
  const actionResponse = await materializeV2RepairPatchCandidate(safeJobId, args.proposalId);
  const refreshState = await refreshRepairLifecyclePanelState(safeJobId);
  return { ...refreshState, actionResponse };
}

export async function submitRepairPatchSandboxApply(args: {
  jobId: string;
  proposalId: string;
}): Promise<RepairMutationRefreshState<V2RepairSandboxApplyResponse>> {
  const safeJobId = requireJobId(args.jobId);
  const actionResponse = await applyV2RepairPatchToSandbox(safeJobId, args.proposalId);
  const refreshState = await refreshRepairLifecyclePanelState(safeJobId);
  return { ...refreshState, actionResponse };
}

export async function submitRepairSandboxValidation(args: {
  jobId: string;
  proposalId: string;
}): Promise<RepairMutationRefreshState<V2RepairSandboxValidationResponse>> {
  const safeJobId = requireJobId(args.jobId);
  const actionResponse = await validateV2SandboxRepair(safeJobId, args.proposalId);
  const refreshState = await refreshRepairLifecyclePanelState(safeJobId);
  return { ...refreshState, actionResponse };
}

const REPAIR_ARTIFACT_PREFERRED_PREVIEW_ORDER = [
  "repair_proposal.md",
  "repair_proposal.json",
  "repair_verification.json",
  "approval_state.json",
  "repair_execution_plan.json",
  "repair_patch_candidate.json",
  "sandbox_validation_result.json",
  "sandbox_apply_result.json",
  "backups/pom.xml.before-repair",
] as const;

async function loadRepairArtifactState(
  jobId: string,
  repairLifecycle: V2RepairLifecycleListResponse | null
): Promise<{
  repairArtifacts: Record<string, V2RepairProposalArtifactListResponse | null>;
  repairArtifactPreviews: Record<string, V2RepairProposalArtifactPreviewResponse | null>;
}> {
  if (!repairLifecycle || repairLifecycle.repair_proposals.length === 0) {
    return { repairArtifacts: {}, repairArtifactPreviews: {} };
  }
  const artifactEntries = await Promise.all(
    repairLifecycle.repair_proposals.map(async (proposal) => {
      try {
        const artifacts = await getV2RepairProposalArtifacts(jobId, proposal.proposal_id);
        return [proposal.proposal_id, artifacts] as const;
      } catch {
        return [proposal.proposal_id, null] as const;
      }
    })
  );
  const repairArtifacts = Object.fromEntries(artifactEntries);
  const previewEntries = await Promise.all(
    artifactEntries.map(async ([proposalId, artifactList]) => {
      if (!artifactList) {
        return [proposalId, null] as const;
      }
      const selected = REPAIR_ARTIFACT_PREFERRED_PREVIEW_ORDER.find((artifactName) =>
        artifactList.artifacts.some((artifact) => artifact.exists && artifact.artifact_name === artifactName)
      );
      if (!selected) {
        return [proposalId, null] as const;
      }
      try {
        const preview = await getV2RepairProposalArtifactPreview(jobId, proposalId, selected);
        return [proposalId, preview] as const;
      } catch {
        return [proposalId, null] as const;
      }
    })
  );
  return {
    repairArtifacts,
    repairArtifactPreviews: Object.fromEntries(previewEntries),
  };
}

export function MigrationCockpit({ jobId, initialData }: { jobId?: string; initialData?: CockpitData | null }) {
  const [data, setData] = useState<CockpitData | null>(initialData ?? null);
  const [error, setError] = useState<string | null>(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [repairApprovalBusy, setRepairApprovalBusy] = useState<string | null>(null);
  const [repairExecutionBusy, setRepairExecutionBusy] = useState<string | null>(null);
  const [repairPatchBusy, setRepairPatchBusy] = useState<string | null>(null);
  const [repairApplyBusy, setRepairApplyBusy] = useState<string | null>(null);
  const [repairValidateBusy, setRepairValidateBusy] = useState<string | null>(null);
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
        const [job, messagesResponse, approvalsResponse, stagesResponse, eventsResponse, pipelineResponse, failureSummary, evidenceBundle, dualModelTraces] = await Promise.all([
          getV2MigrationJob(safeJobId),
          getV2AssistantMessages(safeJobId),
          getV2JobApprovals(safeJobId),
          getV2MigrationJobStages(safeJobId),
          getV2JobEventSnapshot(safeJobId),
          getV2JobPipeline(safeJobId),
          getV2FailureSummary(safeJobId).catch(() => null),
          getV2EvidenceBundle(safeJobId).catch(() => null),
          getV2DualModelTraces(safeJobId).catch(() => null),
        ]);
        const repairArtifactState = await refreshRepairLifecyclePanelState(safeJobId);

        if (cancelled) return;

        setData({
          job,
          stages: stagesResponse.stages,
          approvals: approvalsResponse.approvals,
          messages: messagesResponse.messages,
          events: eventsResponse.events,
          pipeline: pipelineResponse,
          dualModelTraces: dualModelTraces as V2DualModelTraceListResponse | null,
          repairLifecycle: repairArtifactState.repairLifecycle,
          repairArtifacts: repairArtifactState.repairArtifacts,
          repairArtifactPreviews: repairArtifactState.repairArtifactPreviews,
          evidenceBundle: evidenceBundle as V2RunEvidenceBundleResponse | null,
          failureSummary: failureSummary as V2FailureSummaryResponse | null,
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
        void refreshLiveState();
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
          evidenceBundle: response.evidence_bundle ?? current.evidenceBundle,
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
    const [approvalsResponse, stagesResponse, eventsResponse, pipelineResponse, failureSummary, evidenceBundle, dualModelTraces] = await Promise.all([
      getV2JobApprovals(safeJobId),
      getV2MigrationJobStages(safeJobId),
      getV2JobEventSnapshot(safeJobId),
      getV2JobPipeline(safeJobId),
      getV2FailureSummary(safeJobId).catch(() => null),
      getV2EvidenceBundle(safeJobId).catch(() => null),
      getV2DualModelTraces(safeJobId).catch(() => null),
    ]);
    const repairArtifactState = await refreshRepairLifecyclePanelState(safeJobId);
    setData((current) => current ? {
      ...current,
      approvals: approvalsResponse.approvals,
      stages: stagesResponse.stages,
      events: eventsResponse.events,
      pipeline: pipelineResponse,
      dualModelTraces: dualModelTraces as V2DualModelTraceListResponse | null,
      repairLifecycle: repairArtifactState.repairLifecycle,
      repairArtifacts: repairArtifactState.repairArtifacts,
      repairArtifactPreviews: repairArtifactState.repairArtifactPreviews,
      evidenceBundle: evidenceBundle as V2RunEvidenceBundleResponse | null,
      failureSummary: failureSummary as V2FailureSummaryResponse | null,
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

  async function approveRepairProposal(proposalId: string, approvalChecksum: string) {
    if (!normalizedJobId) return;
    setRepairApprovalBusy(proposalId);
    try {
      const refreshState = await submitRepairProposalCockpitDecision({
        jobId: normalizedJobId,
        proposalId,
        approvalState: "pending_approval",
        approvalChecksum,
      });
      setData((current) => current ? {
        ...current,
        repairLifecycle: refreshState.repairLifecycle,
        repairArtifacts: refreshState.repairArtifacts,
        repairArtifactPreviews: refreshState.repairArtifactPreviews,
        repairActionResults: {
          ...(current.repairActionResults ?? {}),
          [proposalId]: refreshState.actionResponse,
        },
      } : current);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Repair proposal approval failed");
    } finally {
      setRepairApprovalBusy(null);
    }
  }

  async function rejectRepairProposal(proposalId: string) {
    if (!normalizedJobId) return;
    setRepairApprovalBusy(proposalId);
    try {
      const refreshState = await submitRepairProposalCockpitDecision({
        jobId: normalizedJobId,
        proposalId,
        approvalState: "pending_approval",
        approvalChecksum: "reject",
        reason: "Rejected in cockpit.",
      });
      setData((current) => current ? {
        ...current,
        repairLifecycle: refreshState.repairLifecycle,
        repairArtifacts: refreshState.repairArtifacts,
        repairArtifactPreviews: refreshState.repairArtifactPreviews,
        repairActionResults: {
          ...(current.repairActionResults ?? {}),
          [proposalId]: refreshState.actionResponse,
        },
      } : current);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Repair proposal rejection failed");
    } finally {
      setRepairApprovalBusy(null);
    }
  }

  async function materializeRepairExecutionPlan(proposalId: string) {
    if (!normalizedJobId) return;
    setRepairExecutionBusy(proposalId);
    try {
      const refreshState = await submitRepairExecutionPlanMaterialization({
        jobId: normalizedJobId,
        proposalId,
      });
      setData((current) => current ? {
        ...current,
        repairLifecycle: refreshState.repairLifecycle,
        repairArtifacts: refreshState.repairArtifacts,
        repairArtifactPreviews: refreshState.repairArtifactPreviews,
        repairActionResults: {
          ...(current.repairActionResults ?? {}),
          [proposalId]: refreshState.actionResponse,
        },
      } : current);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Execution plan materialization failed");
    } finally {
      setRepairExecutionBusy(null);
    }
  }

  async function materializeRepairPatchCandidate(proposalId: string) {
    if (!normalizedJobId) return;
    setRepairPatchBusy(proposalId);
    try {
      const refreshState = await submitRepairPatchCandidateMaterialization({
        jobId: normalizedJobId,
        proposalId,
      });
      setData((current) => current ? {
        ...current,
        repairLifecycle: refreshState.repairLifecycle,
        repairArtifacts: refreshState.repairArtifacts,
        repairArtifactPreviews: refreshState.repairArtifactPreviews,
        repairActionResults: {
          ...(current.repairActionResults ?? {}),
          [proposalId]: refreshState.actionResponse,
        },
      } : current);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Patch candidate materialization failed");
    } finally {
      setRepairPatchBusy(null);
    }
  }

  async function applyRepairPatchToSandbox(proposalId: string) {
    if (!normalizedJobId) return;
    setRepairApplyBusy(proposalId);
    try {
      const refreshState = await submitRepairPatchSandboxApply({
        jobId: normalizedJobId,
        proposalId,
      });
      setData((current) => current ? {
        ...current,
        repairLifecycle: refreshState.repairLifecycle,
        repairArtifacts: refreshState.repairArtifacts,
        repairArtifactPreviews: refreshState.repairArtifactPreviews,
        repairActionResults: {
          ...(current.repairActionResults ?? {}),
          [proposalId]: refreshState.actionResponse,
        },
      } : current);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sandbox apply failed");
    } finally {
      setRepairApplyBusy(null);
    }
  }

  async function validateSandboxRepair(proposalId: string) {
    if (!normalizedJobId) return;
    setRepairValidateBusy(proposalId);
    try {
      const refreshState = await submitRepairSandboxValidation({
        jobId: normalizedJobId,
        proposalId,
      });
      setData((current) => current ? {
        ...current,
        repairLifecycle: refreshState.repairLifecycle,
        repairArtifacts: refreshState.repairArtifacts,
        repairArtifactPreviews: refreshState.repairArtifactPreviews,
      } : current);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sandbox validation failed");
    } finally {
      setRepairValidateBusy(null);
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
        <h2>Run Evidence</h2>
        {cockpitEvidenceStatusLines(data.evidenceBundle).map((line) => (
          <p key={line} className="meta">{line}</p>
        ))}
        {data.evidenceBundle?.generated_artifact_refs?.length ? (
          <p className="meta">
            Artifacts: {data.evidenceBundle.generated_artifact_refs.map((ref) => ref.label || ref.path).join(", ")}
          </p>
        ) : null}
        {data.evidenceBundle?.failure_bundle?.missing_artifacts?.length ? (
          <p className="meta">
            Missing artifacts: {data.evidenceBundle.failure_bundle.missing_artifacts.join(", ")}
          </p>
        ) : null}
        <p className="meta">
          Read-only: {data.evidenceBundle?.read_only === false ? "false" : "true"}
        </p>
      </section>

      <section className="panel">
        <h2>AI Supervision Traces</h2>
        {!data.dualModelTraces || data.dualModelTraces.trace_count === 0 ? (
          <p className="meta">No AI supervision traces yet.</p>
        ) : (
          <>
            <p className="meta">Trace count: {data.dualModelTraces.trace_count}</p>
            {data.dualModelTraces.latest_model1_trace ? (
              <div className="trace-section">
                <strong>Latest Model 1</strong>
                <p className="meta">Provider: {data.dualModelTraces.latest_model1_trace.provider}</p>
                <p className="meta">Fallback: {String(data.dualModelTraces.latest_model1_trace.fallback_used)}</p>
                <p className="meta">Purpose: {data.dualModelTraces.latest_model1_trace.purpose}</p>
                <p className="meta">Risk: {data.dualModelTraces.latest_model1_trace.risk_level ?? "n/a"}</p>
              </div>
            ) : (
              <p className="meta">No Model 1 trace yet.</p>
            )}
            {data.dualModelTraces.latest_model2_trace ? (
              <div className="trace-section">
                <strong>Latest Model 2</strong>
                <p className="meta">Provider: {data.dualModelTraces.latest_model2_trace.provider}</p>
                <p className="meta">Fallback: {String(data.dualModelTraces.latest_model2_trace.fallback_used)}</p>
                <p className="meta">Verdict: {data.dualModelTraces.latest_model2_trace.verdict ?? "n/a"}</p>
                <p className="meta">
                  Human approval required: {String(data.dualModelTraces.latest_model2_trace.human_approval_required ?? false)}
                </p>
              </div>
            ) : (
              <p className="meta">No Model 2 trace yet.</p>
            )}
          </>
        )}
        <p className="meta">
          Read-only audit: {data.dualModelTraces?.read_only === false ? "false" : "true"}
        </p>
      </section>

      <section className="panel">
        <h2>Repair Lifecycle</h2>
        {!data.repairLifecycle || data.repairLifecycle.repair_proposals.length === 0 ? (
          <p className="meta">No repair proposals yet.</p>
        ) : (
          <>
            {data.repairLifecycle.repair_proposals.map((proposal) => (
              <div key={proposal.proposal_id} className="trace-section">
                <strong>{proposal.proposal_id}</strong>
                <p className="meta">Current state: {proposal.current_state}</p>
                <p className="meta">Approval state: {proposal.approval_state}</p>
                {proposal.approval_checksum ? (
                  <p className="checksum">Approval checksum: {proposal.approval_checksum}</p>
                ) : null}
                <p className="meta">Next operator action: {proposal.next_operator_action}</p>
                <p className="meta">Failure type: {proposal.failure_type}</p>
                <p className="meta">Root cause: {proposal.root_cause}</p>
                <p className="meta">Risk level: {proposal.risk_level ?? "n/a"}</p>
                <p className="meta">Model 2 verdict: {proposal.model2_verdict ?? "n/a"}</p>
                <p className="meta">Sandbox apply state: {proposal.sandbox_apply_state}</p>
                <p className="meta">Sandbox validation state: {proposal.sandbox_validation_state}</p>
                <p className="meta">Rollback performed: {String(proposal.rollback_performed)}</p>
                <p className="meta">Has execution plan: {String(proposal.has_execution_plan)}</p>
                <p className="meta">Has patch candidate: {String(proposal.has_patch_candidate)}</p>
                <p className="meta">Source mutated: {String(proposal.source_mutated)}</p>
                <p className="meta">Sandbox only: {String(proposal.sandbox_only)}</p>
                <p className="meta">Stage resumed: {String(proposal.stage_resumed)}</p>
                <p className="meta">Read-only projection: {String(proposal.read_only)}</p>
                {getRepairValidationStatusMessages(proposal.current_state).map((line) => (
                  <p key={`${proposal.proposal_id}-${line}`} className="meta">
                    {line}
                  </p>
                ))}
                {data.repairArtifacts[proposal.proposal_id]?.artifacts?.some((artifact) => artifact.exists) ? (
                  <p className="meta">
                    Repair artifacts: {data.repairArtifacts[proposal.proposal_id]?.artifacts
                      .filter((artifact) => artifact.exists)
                      .map((artifact) => artifact.artifact_name)
                      .join(", ")}
                  </p>
                ) : (
                  <p className="meta">No previewable repair artifacts.</p>
                )}
                {data.repairArtifacts[proposal.proposal_id]?.artifacts?.some(
                  (artifact) => artifact.exists && artifact.artifact_name === "sandbox_validation_result.json"
                ) ? (
                  <p className="meta">Validation artifact: sandbox_validation_result.json</p>
                ) : null}
                {data.repairArtifactPreviews[proposal.proposal_id] ? (
                  <details className="raw-logs">
                    <summary>
                      Read-only artifact preview: {data.repairArtifactPreviews[proposal.proposal_id]?.artifact_name}
                    </summary>
                    {parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id]) ? (
                      <div className="meta">
                        <p className="meta">
                          Parsed validation status:{" "}
                          {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.status ?? "n/a")}
                        </p>
                        <p className="meta">
                          Exit code:{" "}
                          {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.exit_code ?? "n/a")}
                        </p>
                        <p className="meta">
                          Commands run:{" "}
                          {Array.isArray(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.commands_run)
                            ? (parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.commands_run as unknown[])
                                .map((command) => String(command))
                                .join(", ")
                            : String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.commands_run ?? "n/a")}
                        </p>
                        <p className="meta">
                          Rollback performed:{" "}
                          {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.rollback_performed ?? "n/a")}
                        </p>
                        {parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.rollback_reason ? (
                          <p className="meta">
                            Rollback reason:{" "}
                            {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.rollback_reason)}
                          </p>
                        ) : null}
                        {parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.rollback_error ? (
                          <p className="meta">
                            Rollback error:{" "}
                            {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.rollback_error)}
                          </p>
                        ) : null}
                        {parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.stdout_excerpt ? (
                          <p className="meta">
                            Stdout excerpt:{" "}
                            {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.stdout_excerpt)}
                          </p>
                        ) : null}
                        {parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.stderr_excerpt ? (
                          <p className="meta">
                            Stderr excerpt:{" "}
                            {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.stderr_excerpt)}
                          </p>
                        ) : null}
                        <p className="meta">
                          Source mutated:{" "}
                          {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.source_mutated ?? "n/a")}
                        </p>
                        <p className="meta">
                          Sandbox only:{" "}
                          {String(parseSandboxValidationPreview(data.repairArtifactPreviews[proposal.proposal_id])?.sandbox_only ?? "n/a")}
                        </p>
                      </div>
                    ) : null}
                    <pre className="raw-log-line">
                      {data.repairArtifactPreviews[proposal.proposal_id]?.content}
                    </pre>
                  </details>
                ) : null}
                {data.repairActionResults?.[proposal.proposal_id] ? (
                  <div className="trace-section">
                    <strong>Latest action response</strong>
                    {repairActionResponseLines(data.repairActionResults[proposal.proposal_id]).map((line) => (
                      <p key={`${proposal.proposal_id}-${line}`} className="meta">
                        {line}
                      </p>
                    ))}
                  </div>
                ) : null}
                {proposal.approval_state === "pending_approval" && proposal.approval_checksum ? (
                  <>
                    <div className="approval-actions">
                      <button
                        type="button"
                        disabled={repairApprovalBusy === proposal.proposal_id}
                        onClick={() => void approveRepairProposal(proposal.proposal_id, proposal.approval_checksum ?? "")}
                      >
                        Approve proposal
                      </button>
                      <button
                        type="button"
                        disabled={repairApprovalBusy === proposal.proposal_id}
                        onClick={() => void rejectRepairProposal(proposal.proposal_id)}
                      >
                        Reject proposal
                      </button>
                    </div>
                    <p className="meta">Approving this proposal does not apply any repair.</p>
                    <p className="meta">No sandbox or source files will be modified by this action.</p>
                  </>
                ) : null}
                {canMaterializeRepairExecutionPlan(proposal) ? (
                  <>
                    <div className="approval-actions">
                      <button
                        type="button"
                        disabled={repairExecutionBusy === proposal.proposal_id}
                        onClick={() => void materializeRepairExecutionPlan(proposal.proposal_id)}
                      >
                        Materialize execution plan
                      </button>
                    </div>
                    <p className="meta">This only creates a read-only execution plan.</p>
                    <p className="meta">It does not apply patches or run validation.</p>
                  </>
                ) : null}
                {canMaterializeRepairPatchCandidate(proposal) ? (
                  <>
                    <div className="approval-actions">
                      <button
                        type="button"
                        disabled={repairPatchBusy === proposal.proposal_id}
                        onClick={() => void materializeRepairPatchCandidate(proposal.proposal_id)}
                      >
                        Materialize patch candidate
                      </button>
                    </div>
                    <p className="meta">This only creates a read-only patch candidate.</p>
                    <p className="meta">It does not apply patches or run validation.</p>
                    <p className="meta">It does not modify source or sandbox files.</p>
                  </>
                ) : null}
                {canApplyRepairPatchToSandbox(proposal) ? (
                  <>
                    <div className="approval-actions">
                      <button
                        type="button"
                        disabled={repairApplyBusy === proposal.proposal_id}
                        onClick={() => void applyRepairPatchToSandbox(proposal.proposal_id)}
                      >
                        Apply to sandbox
                      </button>
                    </div>
                    <p className="meta">This applies the repair to the sandbox workspace only.</p>
                    <p className="meta">It does not modify the original source project.</p>
                    <p className="meta">It does not run validation.</p>
                    <p className="meta">A backup will be used by the backend before sandbox mutation.</p>
                  </>
                ) : null}
                {canValidateSandboxRepair(proposal) ? (
                  <>
                    <div className="approval-actions">
                      <button
                        type="button"
                        disabled={repairValidateBusy === proposal.proposal_id}
                        onClick={() => void validateSandboxRepair(proposal.proposal_id)}
                      >
                        Validate sandbox repair
                      </button>
                    </div>
                    <p className="meta">This validates the sandbox repair only.</p>
                    <p className="meta">If validation fails, the backend may roll back the sandbox change.</p>
                    <p className="meta">It does not modify the original source project.</p>
                    <p className="meta">It does not resume migration stages.</p>
                  </>
                ) : null}
                {Object.keys(proposal.artifact_refs ?? {}).length > 0 ? (
                  <p className="meta">
                    Artifacts: {Object.entries(proposal.artifact_refs).map(([label, path]) => `${label}: ${path}`).join(", ")}
                  </p>
                ) : null}
              </div>
            ))}
          </>
        )}
        <p className="meta">
          Read-only list: {data.repairLifecycle?.read_only === false ? "false" : "true"}
        </p>
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
              {f.copilot_status && f.type !== "result_contract_failed" && <p className="meta">Copilot: {f.copilot_status}</p>}
              {f.test_status && f.type !== "result_contract_failed" && <p className="meta">Test: {f.test_status}</p>}
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
                {data.failureSummary.artifact_kinds.map((k, i) => <li key={i}>{k}</li>)}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* Assistant Panel */}
      <section className="panel">
        <h2>Assistant</h2>
        <p className="meta">
          Model: {data.assistantModel?.status ?? "unavailable"} | Source: {data.assistantModel?.source ?? "deterministic"}
          {data.assistantModel?.failure_reason ? ` | Reason: ${data.assistantModel.failure_reason}` : ""}
          {data.assistantModel?.status === "live_ok" ? " | Live Azure OpenAI" : ""}
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
        .artifact-kinds { border: 1px solid #ddd; padding: 0.5rem; margin: 0.5rem 0; }
      `}</style>
    </div>
  );
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
  if ([
    "model_invocation_started",
    "model_invocation_completed",
    "model_invocation_failed",
  ].includes(event.type)) return "pending";
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
]);
