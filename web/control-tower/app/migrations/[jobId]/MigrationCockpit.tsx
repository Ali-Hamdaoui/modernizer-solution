"use client";

import { useState, useEffect } from "react";
import {
  askV2Assistant,
  applyV2RepairReviewContext,
  approveV2RepairReviewContext,
  approveV2Card,
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
  prepareV2RepairApplyContext,
  rejectV2Card,
  requestV2ReviewerCritique,
  requireJobId,
  runControlledR6RepairDemo,
  v2EventStreamUrl,
  v2RootPomDownloadUrl,
} from "../../../lib/controlTowerApi";
import type {
  V2ApprovalResponse,
  V2ArtifactPreviewResponse,
  V2AssistantMessageResponse,
  GovernedRepairProposalResponse,
  V2FailureSummaryResponse,
  V2JobEvent,
  V2MigrationJobResponse,
  V2PipelineResponse,
  GateDetailResponse,
  GateRepresentation,
  MigrationIntelligenceSummary,
  V2ReviewerCritiqueResponse,
  RepairApplyContextResponse,
  RepairApprovalResponse,
  ApplyRepairReviewContextResponse,
  V2MigrationMemoryRetrievalResponse,
  V2EvidenceBoundRepairDraftResponse,
  V2RepairDraftReviewResponse,
} from "../../../lib/contracts";
import Stage3DependencyReview from "./Stage3DependencyReview";

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

function summarizeList(values: string[] | undefined, limit: number = 3): string {
  const items = (values ?? []).filter(Boolean);
  if (items.length === 0) {
    return "None";
  }
  const preview = items.slice(0, limit);
  const extra = items.length - preview.length;
  return extra > 0 ? `${preview.join(", ")} +${extra} more` : preview.join(", ");
}

function formatCountSummary(count: number | undefined, noun: string): string {
  const value = count ?? 0;
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}

function summarizeArtifactRefs(
  refs: Record<string, string> | string[] | undefined,
  limit: number = 3,
): string {
  if (!refs) {
    return "None";
  }
  const items = Array.isArray(refs)
    ? refs.filter(Boolean).map((ref) => formatGateArtifactRefLabel(ref))
    : Object.entries(refs)
        .filter(([, ref]) => Boolean(ref))
        .map(([kind, ref]) => `${kind}: ${formatGateArtifactRefLabel(ref)}`);
  if (items.length === 0) {
    return "None";
  }
  const preview = items.slice(0, limit);
  const extra = items.length - preview.length;
  return extra > 0 ? `${preview.join(", ")} +${extra} more` : preview.join(", ");
}

function formatFlag(value: boolean | undefined | null): string {
  if (value === true) return "true";
  if (value === false) return "false";
  return "unknown";
}

export function shouldShowApprovalDecisionControls(status: string, approvalReviewOpen: boolean): boolean {
  return !approvalReviewOpen && status === "pending";
}

export function isControlledR6DemoUiEnabled(
  value: string | undefined = process.env.NEXT_PUBLIC_CONTROL_TOWER_R6_DEMO_ENABLED,
): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

export function hasUnknownNonRepairableFailure(summary: V2FailureSummaryResponse | null | undefined): boolean {
  return Boolean(
    summary?.failures?.some((failure) => {
      const repairStatus = String(failure.repair_loop_status ?? "").toUpperCase();
      const type = String(failure.type ?? "").toLowerCase();
      const message = String(failure.message ?? "").toLowerCase();
      return repairStatus === "DISABLED" && (type.includes("unknown") || message.includes("unknown"));
    }),
  );
}

function hasMigrationIntelligence(migrationIntelligence: MigrationIntelligenceSummary | null | undefined): boolean {
  if (!migrationIntelligence) {
    return false;
  }
  return [
    migrationIntelligence.runtime_contract?.status,
    migrationIntelligence.reference_delta?.status,
    migrationIntelligence.post_transform_failure_classification?.status,
  ].some((status) => status && status !== "not_available");
}

function hasVerificationFields(proposal: GovernedRepairProposalResponse): boolean {
  const artifactRefs = proposal.verification_artifact_refs;
  const artifactValues = Array.isArray(artifactRefs)
    ? artifactRefs
    : artifactRefs
      ? Object.values(artifactRefs)
      : [];
  return [
    proposal.verification_status,
    proposal.verification_build_status,
    proposal.verification_test_status,
    proposal.verification_h2_status,
    proposal.verification_failure_classification_ref,
    ...artifactValues,
  ].some(Boolean);
}

type R6RepairUiState = {
  reviewer: V2ReviewerCritiqueResponse | null;
  context: RepairApplyContextResponse | null;
  approval: RepairApprovalResponse | null;
  applyResult: ApplyRepairReviewContextResponse | null;
  approvalChecksumInput: string;
  busy: "demo" | "reviewer" | "context" | "approval" | "apply" | null;
  error: string | null;
};

export const EMPTY_R6_REPAIR_UI_STATE: R6RepairUiState = {
  reviewer: null,
  context: null,
  approval: null,
  applyResult: null,
  approvalChecksumInput: "",
  busy: null,
  error: null,
};

function latestReviewerDecision(
  proposal: GovernedRepairProposalResponse | null,
  reviewer: V2ReviewerCritiqueResponse | null,
): string {
  return reviewer?.decision ?? proposal?.reviewer_decision ?? proposal?.reviewer?.verdict ?? "";
}

function proposalPatchArtifactRef(proposal: GovernedRepairProposalResponse): string {
  return proposal.repair_artifact?.patch_path
    ?? proposal.patch_package?.repair_artifact?.patch_path
    ?? proposal.patch_package?.evidence_artifact_path
    ?? "";
}

function proposalPatchChecksum(proposal: GovernedRepairProposalResponse): string {
  return proposal.repair_artifact?.patch_checksum
    ?? proposal.patch_package?.repair_artifact?.patch_checksum
    ?? "";
}

function proposalUnifiedDiff(proposal: GovernedRepairProposalResponse): string {
  return proposal.repair_artifact?.unified_diff
    ?? proposal.patch_package?.repair_artifact?.unified_diff
    ?? "";
}

function proposalTargetPath(proposal: GovernedRepairProposalResponse): string {
  return proposal.target_files?.[0]?.relative_path
    ?? proposal.patch_package?.target_files?.[0]?.relative_path
    ?? proposal.affected_paths?.[0]
    ?? proposal.affected_files?.[0]
    ?? "";
}

function proposalSandboxReference(proposal: GovernedRepairProposalResponse): string {
  return proposal.patch_package?.sandbox_path ?? "";
}

function proposalSandboxChecksum(proposal: GovernedRepairProposalResponse): string {
  return proposal.sandbox_checksum ?? proposal.patch_package?.sandbox_checksum ?? "";
}

function proposalLegacyChecksum(proposal: GovernedRepairProposalResponse): string {
  return proposal.legacy_checksum ?? proposal.patch_package?.legacy_checksum ?? "";
}

function proposalRepairFamily(proposal: GovernedRepairProposalResponse): string {
  return proposal.repair_family ?? proposal.patch_package?.repair_family ?? "";
}

function proposalControlledDemoEvidence(proposal: GovernedRepairProposalResponse) {
  return proposal.failure_evidence?.controlled_demo_evidence
    ?? proposal.patch_package?.failure_evidence?.controlled_demo_evidence
    ?? null;
}

function proposalDeterministicRule(proposal: GovernedRepairProposalResponse): string {
  return proposal.deterministic_rule_id ?? proposal.patch_package?.deterministic_rule_id ?? proposalRepairFamily(proposal);
}

function proposalContextChecksum(proposal: GovernedRepairProposalResponse): string {
  return proposal.context_pack_checksum ?? proposal.patch_package?.package_checksum ?? "";
}

function proposerInvocationId(proposal: GovernedRepairProposalResponse): string {
  return proposal.proposal_model?.model_invocation_id ?? "";
}

function reviewerInvocationId(reviewer: V2ReviewerCritiqueResponse | null): string {
  return reviewer?.reviewer_model?.model_invocation_id ?? reviewer?.model_invocation_id ?? "";
}

function canPrepareR6ApplyContext(
  proposal: GovernedRepairProposalResponse | null,
  reviewer: V2ReviewerCritiqueResponse | null,
): boolean {
  if (!proposal || latestReviewerDecision(proposal, reviewer) !== "accept") {
    return false;
  }
  return [
    proposal.proposal_id,
    proposal.command_id,
    proposal.proposal_checksum,
    proposalContextChecksum(proposal),
    reviewer?.critique_id ?? proposal.reviewer_critique_id,
    proposalUnifiedDiff(proposal),
    proposalTargetPath(proposal),
    proposalSandboxReference(proposal),
    proposalSandboxChecksum(proposal),
    proposalLegacyChecksum(proposal),
  ].every((value) => String(value ?? "").trim().length > 0);
}

export function missingReviewerRequestFields(proposal: GovernedRepairProposalResponse | null): string[] {
  if (!proposal) {
    return ["proposal"];
  }
  const missing: string[] = [];
  if (!proposal.command_id) missing.push("command id");
  if (!proposal.proposal_id) missing.push("proposal id");
  if (!proposal.proposal_checksum) missing.push("proposal checksum");
  if (!proposalContextChecksum(proposal)) missing.push("context pack checksum");
  return missing;
}

function r6ApplyButtonDisabled(state: R6RepairUiState): boolean {
  const status = state.applyResult?.repair_action?.status ?? "";
  if (["failed", "rolled_back"].includes(status)) {
    return true;
  }
  return !state.context
    || !state.approval
    || state.approval.approval_status !== "recorded"
    || state.approval.approval_checksum !== state.context.proposal_checksum
    || state.busy === "apply";
}

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
  repairProposal: GovernedRepairProposalResponse | null;
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

export function GatePanelContent({ state }: { state: GatePanelState }) {
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
  const migrationIntelligence = detail?.evidence?.migration_intelligence ?? null;
  const migrationWarnings = [
    ...(detail?.evidence?.migration_intelligence_warnings ?? []),
    migrationIntelligence?.runtime_contract?.warning ?? "",
    migrationIntelligence?.reference_delta?.warning ?? "",
    migrationIntelligence?.post_transform_failure_classification?.warning ?? "",
  ].filter(Boolean);

  return (
    <section className="panel stack" aria-label="Open gate panel">
      <h2>Open gate</h2>
      <p className="meta">All gate data comes from backend-owned, gate-bound artifacts and checksums.</p>
      {gate ? (
        <>
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
            <strong>{detail?.evidence?.failure_summary ?? "Open gate awaiting decision"}</strong>
            <span className="meta">Allowed actions: {gate.available_actions.map((action) => action.label).join(", ") || "None"}</span>
          </div>
          <div className="table-row">
            <span className="meta">Safe refs</span>
            <strong>{gate.source_artifact_refs.length > 0 ? formatGateArtifactRefs(gate.source_artifact_refs) : "None"}</strong>
            <span className="meta">Gate count: {state.gates.length}</span>
          </div>
        </div>
        <div className="migration-intelligence stack">
          <strong>Migration Intelligence</strong>
          {hasMigrationIntelligence(migrationIntelligence) || migrationWarnings.length > 0 ? (
            <>
              <div className="trace-section">
                <strong>Runtime Contract</strong>
                <p className="meta">Status: {migrationIntelligence?.runtime_contract?.status ?? "not_available"}</p>
                <p className="meta">
                  {formatCountSummary(migrationIntelligence?.runtime_contract?.detected_risks_count, "risk")}
                  {migrationIntelligence?.runtime_contract?.detected_risks?.length
                    ? ` · ${summarizeList(migrationIntelligence.runtime_contract.detected_risks)}`
                    : ""}
                </p>
                <p className="meta">
                  {formatCountSummary(migrationIntelligence?.runtime_contract?.recommended_actions_count, "recommended action")}
                  {migrationIntelligence?.runtime_contract?.recommended_actions?.length
                    ? ` · ${summarizeList(migrationIntelligence.runtime_contract.recommended_actions)}`
                    : ""}
                </p>
                <p className="meta">
                  JDK: {migrationIntelligence?.runtime_contract?.jdk_requirements?.java_version || "?"}
                  {migrationIntelligence?.runtime_contract?.jdk_requirements?.compiler_release
                    ? ` / release ${migrationIntelligence.runtime_contract.jdk_requirements.compiler_release}`
                    : ""}
                </p>
                <p className="meta">
                  Maven: {migrationIntelligence?.runtime_contract?.maven_requirements?.wrapper_present ? "wrapper present" : "wrapper absent"}
                  {migrationIntelligence?.runtime_contract?.private_registry_requirements?.repository_urls?.length
                    ? ` · private registry ${summarizeList(migrationIntelligence.runtime_contract.private_registry_requirements.repository_urls)}`
                    : " · no private registry"}
                </p>
                <p className="meta">
                  Internal deps: {formatCountSummary(migrationIntelligence?.runtime_contract?.internal_dependencies_count, "item")}
                  {migrationIntelligence?.runtime_contract?.internal_dependencies?.length
                    ? ` · ${summarizeList(migrationIntelligence.runtime_contract.internal_dependencies)}`
                    : ""}
                </p>
              </div>

              <div className="trace-section">
                <strong>Reference Delta</strong>
                <p className="meta">Status: {migrationIntelligence?.reference_delta?.status ?? "not_available"}</p>
                <p className="meta">
                  Dependency delta: +{migrationIntelligence?.reference_delta?.dependency_delta?.added_count ?? 0}
                  / -{migrationIntelligence?.reference_delta?.dependency_delta?.removed_count ?? 0}
                  / version {migrationIntelligence?.reference_delta?.dependency_delta?.version_changed_count ?? 0}
                </p>
                <p className="meta">
                  Source delta: imports +{migrationIntelligence?.reference_delta?.source_delta?.added_imports_count ?? 0}
                  / -{migrationIntelligence?.reference_delta?.source_delta?.removed_imports_count ?? 0}
                  / javax→jakarta {migrationIntelligence?.reference_delta?.source_delta?.javax_to_jakarta_count ?? 0}
                </p>
                <p className="meta">
                  API indicators: {formatCountSummary(Object.keys(migrationIntelligence?.reference_delta?.api_migration_indicators ?? {}).length, "flag")}
                  {Object.keys(migrationIntelligence?.reference_delta?.api_migration_indicators ?? {}).length > 0
                    ? ` · ${Object.entries(migrationIntelligence?.reference_delta?.api_migration_indicators ?? {})
                        .filter(([, value]) => value)
                        .map(([key]) => key)
                        .slice(0, 3)
                        .join(", ")}`
                    : ""}
                </p>
                <p className="meta">
                  Capability packs: {summarizeList(migrationIntelligence?.reference_delta?.recommended_capability_packs)}
                </p>
                <p className="meta">
                  Suspicious artifacts: {formatCountSummary(migrationIntelligence?.reference_delta?.suspicious_artifacts_count, "item")}
                  {migrationIntelligence?.reference_delta?.suspicious_artifacts?.length
                    ? ` · ${summarizeList(migrationIntelligence.reference_delta.suspicious_artifacts)}`
                    : ""}
                </p>
              </div>

              <div className="trace-section">
                <strong>Failure Classification</strong>
                <p className="meta">Status: {migrationIntelligence?.post_transform_failure_classification?.status ?? "not_available"}</p>
                <p className="meta">
                  Categories: {formatCountSummary(Object.keys(migrationIntelligence?.post_transform_failure_classification?.categories ?? {}).length, "kind")}
                  {Object.keys(migrationIntelligence?.post_transform_failure_classification?.categories ?? {}).length > 0
                    ? ` · ${Object.entries(migrationIntelligence?.post_transform_failure_classification?.categories ?? {})
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 3)
                        .map(([key, value]) => `${key}=${value}`)
                        .join(", ")}`
                    : ""}
                </p>
                <p className="meta">Failed unit: {migrationIntelligence?.post_transform_failure_classification?.failed_unit ?? "n/a"}</p>
                <p className="meta">
                  Suggested actions: {summarizeList(migrationIntelligence?.post_transform_failure_classification?.suggested_actions)}
                </p>
                <p className="meta">
                  Test failures: {migrationIntelligence?.post_transform_failure_classification?.test_failure_summary?.suite_count ?? 0}
                  {migrationIntelligence?.post_transform_failure_classification?.test_failure_summary?.first_failure?.test_class
                    ? ` · ${migrationIntelligence.post_transform_failure_classification.test_failure_summary.first_failure.test_class}`
                    : ""}
                </p>
              </div>

              {migrationWarnings.length > 0 && (
                <div className="trace-section">
                  <strong>Warnings</strong>
                  <ul className="meta">
                    {migrationWarnings.slice(0, 5).map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <p className="meta">No migration intelligence artifacts available yet.</p>
          )}
        </div>
        </>
      ) : (
        <p className="meta">No gate is currently open for this job.</p>
      )}
    </section>
  );
}

export function GovernedRepairProposalCard({ proposal }: { proposal: GovernedRepairProposalResponse | null }) {
  if (!proposal) {
    return null;
  }

  const proposer = proposal.proposer ?? null;
  const reviewer = proposal.reviewer ?? null;
  const evidence = proposal.evidence ?? null;
  const runtimeContract = evidence?.runtime_contract ?? proposal.migration_intelligence?.runtime_contract ?? null;
  const referenceDelta = evidence?.reference_delta ?? proposal.migration_intelligence?.reference_delta ?? null;
  const failureClassification = evidence?.failure_classification ?? proposal.migration_intelligence?.post_transform_failure_classification ?? null;
  const verificationStatus = proposal.verification_status ?? "not_available";
  const verificationArtifactRefs = proposal.verification_artifact_refs;
  const warnings = [
    ...(proposal.warnings ?? []),
    ...(proposal.migration_intelligence_warnings ?? []),
    ...(evidence?.migration_intelligence_warnings ?? []),
  ].filter(Boolean);

  return (
    <div className="repair-proposal-card">
      <h3>Governed Repair Proposal</h3>
      <p className="meta">Status: Awaiting human approval</p>
      {proposal.proposal_id && <p className="meta">Proposal: {proposal.proposal_id}</p>}
      {proposal.intent && <p className="meta">Intent: {proposal.intent}</p>}
      {proposal.status && <p className="meta">Proposal status: {proposal.status}</p>}
      {proposal.title && <p className="meta">Title: {proposal.title}</p>}
      {proposal.summary && <p className="meta">Summary: {proposal.summary}</p>}
      {proposal.proposed_action && <p className="meta">Proposed action: {proposal.proposed_action}</p>}
      {(proposal.affected_files?.length ?? 0) > 0 && (
        <p className="meta">Affected files: {summarizeList(proposal.affected_files)}</p>
      )}
      {(proposal.affected_components?.length ?? 0) > 0 && (
        <p className="meta">Affected components: {summarizeList(proposal.affected_components)}</p>
      )}
      {proposal.confidence != null && <p className="meta">Confidence: {String(proposal.confidence)}</p>}
      {proposal.risk != null && <p className="meta">Risk: {String(proposal.risk)}</p>}

      <div className="trace-section">
        <strong>Proposer</strong>
        <p className="meta">
          Role: {proposer?.role ?? "n/a"} | Model: {proposer?.model ?? "n/a"} | Provider: {proposer?.provider ?? "n/a"} | Status: {proposer?.status ?? "n/a"}
        </p>
        <p className="meta">
          {proposer?.proposal_text ?? proposer?.summary ?? proposal.proposal_text ?? proposal.summary ?? "No proposer summary available."}
        </p>
      </div>

      <div className="trace-section">
        <strong>Reviewer</strong>
        <p className="meta">
          Role: {reviewer?.role ?? "n/a"} | Model: {reviewer?.model ?? "n/a"} | Provider: {reviewer?.provider ?? "n/a"} | Status: {reviewer?.status ?? "n/a"}
        </p>
        <p className="meta">
          Verdict: {reviewer?.verdict ?? "n/a"}
        </p>
        <p className="meta">
          {reviewer?.critique ?? reviewer?.summary ?? "No reviewer critique available."}
        </p>
        {(reviewer?.warnings?.length ?? 0) > 0 && (
          <p className="meta">Warnings: {summarizeList(reviewer?.warnings)}</p>
        )}
        {(reviewer?.required_changes?.length ?? 0) > 0 && (
          <p className="meta">Required changes: {summarizeList(reviewer?.required_changes)}</p>
        )}
        <p className="meta">
          Reviewer required: {formatFlag(reviewer?.reviewer_required ?? proposal.governance?.reviewer_required)} | Manual review required: {formatFlag(reviewer?.manual_review_required ?? proposal.governance?.manual_review_required)}
        </p>
      </div>

      <div className="trace-section">
        <strong>Evidence</strong>
        <p className="meta">
          Failure classification: {failureClassification?.status ?? "not_available"}
          {failureClassification?.failed_unit ? ` · failed unit ${failureClassification.failed_unit}` : ""}
        </p>
        <p className="meta">
          Runtime contract: {runtimeContract?.status ?? "not_available"}
          {runtimeContract?.detected_risks?.length ? ` · ${summarizeList(runtimeContract.detected_risks)}` : ""}
        </p>
        <p className="meta">
          Reference delta: {referenceDelta?.status ?? "not_available"}
          {referenceDelta?.recommended_capability_packs?.length ? ` · ${summarizeList(referenceDelta.recommended_capability_packs)}` : ""}
        </p>
        {(proposal.evidence_references?.length ?? 0) > 0 && (
          <p className="meta">Evidence refs: {summarizeList(proposal.evidence_references)}</p>
        )}
        {(proposal.evidence_checksums?.length ?? 0) > 0 && (
          <p className="meta">Evidence checksums: {summarizeList(proposal.evidence_checksums)}</p>
        )}
        {(warnings.length > 0) && (
          <p className="meta">Warnings: {summarizeList(warnings)}</p>
        )}
      </div>

      {hasVerificationFields(proposal) && (
        <div className="trace-section">
          <strong>Post-Apply Verification</strong>
          <p className="meta">Status: {verificationStatus}</p>
          <p className="meta">Build: {proposal.verification_build_status ?? "not_available"}</p>
          <p className="meta">Test: {proposal.verification_test_status ?? "not_available"}</p>
          <p className="meta">H2: {proposal.verification_h2_status ?? "not_available"}</p>
          <p className="meta">Artifact refs: {summarizeArtifactRefs(verificationArtifactRefs)}</p>
          <p className="meta">
            Failure classification ref: {proposal.verification_failure_classification_ref ?? "not_available"}
          </p>
          {verificationStatus === "passed" ? (
            <p className="meta">Verification passed in sandbox. No automatic production promotion happened.</p>
          ) : verificationStatus === "failed" ? (
            <p className="meta">Verification failed in sandbox. Use Solve This again to generate a new governed proposal.</p>
          ) : (
            <p className="meta">Verification not available yet.</p>
          )}
        </div>
      )}

      <div className="trace-section">
        <strong>Governance</strong>
        <p className="meta">Human approval required: {formatFlag(proposal.governance?.human_approval_required)}</p>
        <p className="meta">No auto apply: {formatFlag(proposal.governance?.no_auto_apply)}</p>
        <p className="meta">Sandbox only: {formatFlag(proposal.governance?.sandbox_only)}</p>
        <p className="meta">Source mutated: {formatFlag(proposal.governance?.source_mutated)}</p>
        <p className="meta">Sandbox mutated: {formatFlag(proposal.governance?.sandbox_mutated)}</p>
        <p className="meta">Stage resumed: {formatFlag(proposal.governance?.stage_resumed)}</p>
        <p className="meta">Backend runner invoked: {formatFlag(proposal.governance?.backend_runner_invoked)}</p>
        <p className="meta">Approval bypass: {formatFlag(proposal.governance?.approval_bypass)}</p>
        <p className="meta">Status: {proposal.governance?.status ?? "Awaiting human approval"}</p>
        <p className="meta">No automatic changes have been applied.</p>
      </div>
    </div>
  );
}

export function R6GovernedRepairPanel({
  proposal,
  state,
  onApprovalChecksumChange,
  onRequestReviewer,
  onPrepareContext,
  onApproveRepair,
  onOfficialApply,
}: {
  proposal: GovernedRepairProposalResponse | null;
  state: R6RepairUiState;
  onApprovalChecksumChange: (value: string) => void;
  onRequestReviewer: () => void;
  onPrepareContext: () => void;
  onApproveRepair: () => void;
  onOfficialApply: () => void;
}) {
  if (!proposal) {
    return null;
  }

  const commandId = proposal.command_id ?? "";
  const proposalId = proposal.proposal_id ?? "";
  const proposalChecksum = proposal.proposal_checksum ?? "";
  const contextChecksum = proposalContextChecksum(proposal);
  const missingReviewerFields = missingReviewerRequestFields(proposal);
  const reviewerDecision = latestReviewerDecision(proposal, state.reviewer);
  const patchArtifact = proposalPatchArtifactRef(proposal);
  const patchChecksum = proposalPatchChecksum(proposal);
  const sandboxChecksum = state.context?.sandbox_checksum ?? proposalSandboxChecksum(proposal);
  const legacyChecksum = state.context?.legacy_checksum ?? proposalLegacyChecksum(proposal);
  const approvalChecksumMatches = state.approvalChecksumInput.trim() === proposalChecksum;
  const prepareEnabled = canPrepareR6ApplyContext(proposal, state.reviewer) && state.busy !== "context";
  const approvalEnabled = Boolean(state.context)
    && approvalChecksumMatches
    && !state.approval
    && state.busy !== "approval";
  const applyDisabled = r6ApplyButtonDisabled(state);
  const action = state.applyResult?.repair_action ?? null;
  const applyFailure = action?.apply_failure ?? null;
  const controlledDemoEvidence = proposalControlledDemoEvidence(proposal);
  const gitApplyCheckStatus = applyFailure?.git_apply_check_status
    ?? (action ? (action.status === "applied" || action.status === "idempotent" ? "passed" : applyFailure?.failure_stage === "git_apply_check" ? "failed" : "not completed") : "not run");
  const patchApplyStatus = applyFailure?.patch_apply_status ?? action?.status ?? "not run";
  const rollbackStatus = applyFailure?.rollback_attempted
    ? (applyFailure.rollback_succeeded ? "succeeded" : "failed")
    : action?.status === "rolled_back"
      ? "succeeded"
      : "not attempted";
  const controlledVerificationStatus = applyFailure?.controlled_verification_status ?? "not_applicable";
  const fullMavenStatus = applyFailure?.full_maven_verification_status ?? action?.verification_status ?? "not run";

  return (
    <section className="panel stack r6-repair-panel" aria-label="Governed R6 repair flow">
      <h2>Governed R6 Repair</h2>
      <p className="meta">Stage2 disabled during R6. LLM can propose and reviewer can critique; human approves; backend applies and verifies in sandbox.</p>
      {state.error && <p className="assistant-error" role="alert">{state.error}</p>}

      <div className="trace-section">
        <strong>Repair Proposal</strong>
        <p className="meta">Failed command: {commandId || "n/a"}</p>
        <p className="meta">Failure evidence: {proposal.failure_evidence?.diagnostic_line ?? proposal.patch_package?.failure_evidence?.diagnostic_line ?? proposal.failure_summary ?? "n/a"}</p>
        <p className="meta">Repair family: {proposalRepairFamily(proposal) || "n/a"}</p>
        <p className="meta">Proposal: {proposalId || "n/a"}</p>
        <p className="checksum">Proposal checksum: {proposalChecksum || "n/a"}</p>
        <p className="meta">Patch artifact: {patchArtifact ? formatGateArtifactRefLabel(patchArtifact) : "n/a"}</p>
        <p className="checksum">Patch checksum: {patchChecksum || "n/a"}</p>
        <p className="meta">Pre-validation: {patchArtifact && patchChecksum ? "passed before proposal became actionable" : "not available"}</p>
        {controlledDemoEvidence?.injected_failure && (
          <div className="trace-subsection">
            <p className="meta">Controlled demo: injected local/dev failure; not the real Stage1 UNKNOWN failure.</p>
            <p className="meta">
              Namespace proof: {controlledDemoEvidence.injected_import_namespace || "n/a"} was injected and proposal restores {controlledDemoEvidence.proposed_import_namespace || "n/a"} from pre-injection evidence.
            </p>
            <p className="checksum">Injection before checksum: {controlledDemoEvidence.injection_before_checksum || "n/a"}</p>
            <p className="checksum">Injection after checksum: {controlledDemoEvidence.injection_after_checksum || "n/a"}</p>
          </div>
        )}
      </div>

      <div className="trace-section">
        <strong>Reviewer</strong>
        <p className="meta">Decision: {reviewerDecision || "not requested"}</p>
        <p className="meta">Critique: {state.reviewer?.critique_id ?? proposal.reviewer_critique_id ?? "n/a"}</p>
        <p className="meta">Model invocation: {reviewerInvocationId(state.reviewer) || "n/a"}</p>
        <p className="meta">
          Reviewer source: {state.reviewer?.reviewer_model?.provider ?? "n/a"} / {state.reviewer?.reviewer_model?.source ?? "n/a"} / {state.reviewer?.reviewer_model?.status ?? "n/a"}
        </p>
        {state.reviewer?.reasoning && <p className="meta">{state.reviewer.reasoning}</p>}
        {missingReviewerFields.length > 0 && (
          <p className="meta">Reviewer request disabled: missing {missingReviewerFields.join(", ")}.</p>
        )}
        <button
          type="button"
          disabled={missingReviewerFields.length > 0 || state.busy === "reviewer"}
          onClick={onRequestReviewer}
        >
          Request reviewer critique
        </button>
      </div>

      <div className="trace-section">
        <strong>Apply Context &amp; Human Approval</strong>
        <p className="meta">Context: {state.context?.context_id ?? "not prepared"}</p>
        <p className="checksum">Sandbox checksum: {sandboxChecksum || "n/a"}</p>
        <p className="checksum">Legacy checksum: {legacyChecksum || "n/a"}</p>
        <p className="meta">Approval scope: sandbox_only</p>
        <button type="button" disabled={!prepareEnabled} onClick={onPrepareContext}>
          Prepare apply context
        </button>
        <label className="checksum-input">
          Exact approval checksum
          <input
            value={state.approvalChecksumInput}
            onChange={(event) => onApprovalChecksumChange(event.target.value)}
            placeholder={proposalChecksum || "proposal checksum"}
            aria-label="Exact approval checksum"
          />
        </label>
        <button type="button" disabled={!approvalEnabled} onClick={onApproveRepair}>
          Record human repair approval
        </button>
        <p className="meta">Approval: {state.approval?.approval_id ?? "not recorded"}</p>
      </div>

      <div className="trace-section">
        <strong>Official Apply &amp; Verification</strong>
        <button type="button" disabled={applyDisabled} onClick={onOfficialApply}>
          Run official apply
        </button>
        <p className="meta">Patch gate: {action ? "accepted by backend before apply" : "not run"}</p>
        <p className="meta">git apply --check: {gitApplyCheckStatus}</p>
        <p className="meta">Patch apply: {patchApplyStatus}</p>
        {applyFailure && (
          <div className="trace-subsection">
            <p className="meta">Failure stage: {applyFailure.failure_stage || "n/a"}</p>
            <p className="meta">Failure code: {applyFailure.failure_code || "n/a"}</p>
            <p className="meta">Failure detail: {applyFailure.human_readable_summary || action?.result_summary || "n/a"}</p>
            <p className="meta">git apply --check stderr: {applyFailure.git_apply_check_stderr || "n/a"}</p>
            <p className="meta">Controlled target verification: {controlledVerificationStatus}</p>
            <p className="meta">Controlled verification detail: {applyFailure.controlled_verification_summary || "n/a"}</p>
            <p className="meta">Full Maven verification: {fullMavenStatus}</p>
            <p className="meta">Maven failure classification: {applyFailure.full_maven_failure_classification || "n/a"}</p>
            {applyFailure.full_maven_failure_classification === "unrelated_preexisting_failure" && (
              <p className="meta">Controlled repair passed; full Maven remains blocked by unrelated pre-existing sandbox failures.</p>
            )}
            <p className="checksum">Expected sandbox checksum: {applyFailure.expected_sandbox_checksum || "n/a"}</p>
            <p className="checksum">Actual sandbox checksum: {applyFailure.actual_sandbox_checksum || "n/a"}</p>
            <p className="meta">Worktree used: {formatGateArtifactRefLabel(applyFailure.worktree_used || "") || "n/a"}</p>
            <p className="meta">Strip level: {applyFailure.strip_level ?? "n/a"}</p>
            <p className="meta">Recommended next action: {applyFailure.recommended_next_action || "n/a"}</p>
          </div>
        )}
        <p className="meta">Maven verification: {fullMavenStatus}</p>
        <p className="meta">Build: {action?.verification_build_status || "not run"}</p>
        <p className="meta">Test: {action?.verification_test_status || "not run"}</p>
        <p className="meta">Rollback: {rollbackStatus}</p>
        <p className="meta">Sandbox-only: {action ? formatFlag(action.sandbox_only) : "unknown"}</p>
        <p className="meta">Legacy unchanged: {action ? formatFlag(!action.source_mutated) : "unknown"}</p>
        <p className="meta">Verification artifacts: {summarizeArtifactRefs(action?.verification_artifact_refs)}</p>
      </div>

      <details>
        <summary>Guardrails</summary>
        <ul className="meta">
          <li>LLM cannot approve.</li>
          <li>LLM cannot apply.</li>
          <li>UI cannot mutate files directly.</li>
          <li>Backend owns execution, patch gates, git apply --check, and Maven verification.</li>
          <li>No browser-chosen shell commands, Maven goals, argv, env, model deployments, or patch editor.</li>
          <li>Stage2 remains disabled for R6.</li>
        </ul>
      </details>
    </section>
  );
}

export function ControlledR6RepairDemoPanel({
  enabled,
  hasProposal,
  unknownFailure,
  busy,
  onRun,
}: {
  enabled: boolean;
  hasProposal: boolean;
  unknownFailure: boolean;
  busy: boolean;
  onRun: () => void;
}) {
  if (!enabled && !unknownFailure) {
    return null;
  }

  return (
    <section className="panel stack" aria-label="Controlled R6 repair demo">
      <h2>Controlled R6 Repair Demo</h2>
      {unknownFailure && (
        <p className="meta">
          Failure is not eligible for governed R6 repair. Use controlled R6 repair demo scenario.
        </p>
      )}
      <p className="meta">
        Local/dev only. Backend injects known sandbox-only Jakarta/javax failure and creates durable governed proposal.
      </p>
      {enabled ? (
        <button type="button" disabled={busy || hasProposal} onClick={onRun}>
          Run controlled R6 repair demo
        </button>
      ) : (
        <p className="meta">Controlled demo action disabled outside explicit local/dev demo mode.</p>
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
  repairProposal?: GovernedRepairProposalResponse | null;
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
  repairProposal = null,
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
      <GovernedRepairProposalCard proposal={repairProposal} />
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

export function StageFailureEvidenceDetails({
  diagnosis,
  stage,
}: {
  diagnosis: NonNullable<V2FailureSummaryResponse["failures"][number]["supervision_trace"]["ai_diagnosis"]>;
  stage?: number | null;
}) {
  const stageEvidence = diagnosis.stage_evidence;
  const classification = diagnosis.classification;
  const classificationHelp = classification ? stageClassificationHelp(classification.classification_status) : "";
  return (
    <>
      {stageEvidence && (
        <div className="trace-section">
          <strong>Stage Evidence</strong>
          <p className="meta">Failed stage: Stage {stageEvidence.stage_index ?? stage ?? "?"}</p>
          <p className="meta">
            Stage target: {stageEvidence.source_boot_version || "unknown"}/Java {stageEvidence.source_java_version || "unknown"}
            {" -> "}
            {stageEvidence.target_boot_version || "unknown"}/Java {stageEvidence.target_java_version || "unknown"}
          </p>
          <p className="meta">Evidence: {stageEvidence.evidence_status || "unknown"}</p>
          <p className="checksum">Evidence pack: {stageEvidence.evidence_pack_id || "n/a"} · {stageEvidence.evidence_pack_checksum || "n/a"}</p>
          <p className="meta">
            Usable artifacts: {summarizeList(stageEvidence.usable_artifacts.map((artifact) => artifact.kind))}
          </p>
          <p className="meta">Missing artifacts: {summarizeList(stageEvidence.missing_artifacts)}</p>
          {stageEvidence.downstream_stage_state && (
            <p className="meta">
              Downstream stages: {stageEvidence.downstream_stage_state.state || "pending"}
            </p>
          )}
        </div>
      )}
      {classification && (
        <div className="trace-section">
          <strong>Stage Classification</strong>
          <p className="meta">Classification: {classification.classification_status || "unknown"}</p>
          <p className="meta">Failure: {classification.failure_type || "unknown"}</p>
          {classification.repair_family_candidate && (
            <p className="meta">Candidate family: {classification.repair_family_candidate}</p>
          )}
          {classification.governance_gate_type && (
            <p className="meta">Governance gate: {classification.governance_gate_type}</p>
          )}
          {classification.stage_relevance && (
            <p className="meta">Stage relevance: {classification.stage_relevance}</p>
          )}
          <p className="meta">Confidence: {classification.confidence || "unknown"}</p>
          <p className="meta">Confidence reason: {classification.confidence_reason || "n/a"}</p>
          <p className="meta">Matched signals: {summarizeList(classification.matched_signals)}</p>
          <p className="meta">Missing required evidence: {summarizeList(classification.missing_required_evidence)}</p>
          <p className="meta">Repair: {classification.repair_enabled ? "enabled" : "disabled"}</p>
          <p className="meta">Repair blocked reason: {classification.repair_blocked_reason || classification.reason || "n/a"}</p>
          <p className="meta">Next action: {classification.assistant_next_action || "n/a"}</p>
          {classificationHelp && <p className="meta">{classificationHelp}</p>}
          <MigrationMemoryDetails memory={classification.migration_memory ?? null} />
          <RepairDraftDetails draft={classification.repair_proposal_draft ?? null} />
          <RepairDraftReviewDetails review={classification.repair_draft_review ?? null} />
        </div>
      )}
    </>
  );
}

function RepairDraftDetails({ draft }: { draft: V2EvidenceBoundRepairDraftResponse | null }) {
  if (!draft) {
    return (
      <div className="trace-section">
        <strong>Repair Draft</strong>
        <p className="meta">No repair draft available.</p>
      </div>
    );
  }
  const noDraft = draft.proposal_status === "unavailable" || !draft.proposal_status;
  return (
    <div className="trace-section">
      <strong>Repair Draft</strong>
      {noDraft ? (
        <p className="meta">No repair draft available.</p>
      ) : (
        <>
          <p className="meta">Draft status: {draft.proposal_status}</p>
          <p className="meta">Supported family: {draft.supported_family || "none"}</p>
          {draft.blocked_reason && <p className="meta">Reason: {draft.blocked_reason}</p>}
          {draft.evidence_pack_checksum && <p className="checksum">Evidence pack checksum: {draft.evidence_pack_checksum}</p>}
          {draft.memory_query_signature && <p className="checksum">Memory query signature: {draft.memory_query_signature}</p>}
          <p className="meta">Target file: {summarizeList(draft.target_files)}</p>
          {draft.proposed_diff_checksum && <p className="checksum">Proposed diff checksum: {draft.proposed_diff_checksum}</p>}
          <p className="meta">Apply: {draft.apply_enabled ? "enabled" : "disabled"}</p>
          <p className="meta">Human approval: {draft.approval_enabled ? "enabled" : "disabled"}</p>
          <p className="meta">Reviewer: required later, not active</p>
          <p className="meta">Backend apply required later: {draft.backend_apply_required ? "yes" : "no"}</p>
          <p className="meta">Draft is non-actionable in R7D. It can be reviewed later but cannot be applied.</p>
        </>
      )}
    </div>
  );
}

function RepairDraftReviewDetails({ review }: { review: V2RepairDraftReviewResponse | null }) {
  if (!review) {
    return (
      <div className="trace-section">
        <strong>Repair Draft Review</strong>
        <p className="meta">No repair draft review available.</p>
      </div>
    );
  }
  const firstTarget = review.target_files[0] ?? "";
  const targetChecksum = firstTarget ? review.target_file_checksums[firstTarget] : "";
  const notReviewable = review.review_status === "not_reviewable_blocked_human_gate";
  return (
    <div className="trace-section">
      <strong>Repair Draft Review</strong>
      {notReviewable ? (
        <>
          <p className="meta">Reviewer status: not_reviewable_blocked_human_gate</p>
          <p className="meta">Reviewer verdict: {review.verdict || "blocked"}</p>
          <p className="meta">Reason: {summarizeList(review.reasons) || "human review gate / no supported draft"}</p>
          <p className="meta">Apply: disabled</p>
          <p className="meta">Human approval: disabled</p>
          <p className="meta">Reviewer verdict is non-actionable in R7E.</p>
        </>
      ) : (
        <>
          <p className="meta">Reviewer status: {review.review_status || "unavailable"}</p>
          <p className="meta">Reviewer verdict: {review.verdict || "rejected"}</p>
          <p className="meta">Reviewer kind: {review.reviewer_kind || "deterministic_local"}</p>
          <p className="meta">Reviewed family: {review.reviewed_family || "none"}</p>
          {review.evidence_pack_checksum && <p className="checksum">Evidence pack checksum: {review.evidence_pack_checksum}</p>}
          {review.memory_query_signature && <p className="checksum">Memory query signature: {review.memory_query_signature}</p>}
          {targetChecksum && <p className="checksum">Target file checksum: {firstTarget} · {targetChecksum}</p>}
          {review.proposed_diff_checksum && <p className="checksum">Proposed diff checksum: {review.proposed_diff_checksum}</p>}
          {review.proposal_checksum && <p className="checksum">Proposal checksum: {review.proposal_checksum}</p>}
          {review.review_checksum && <p className="checksum">Review checksum: {review.review_checksum}</p>}
          <p className="meta">Apply: {review.apply_enabled ? "enabled" : "disabled"}</p>
          <p className="meta">Human approval: {review.approval_enabled ? "enabled" : "disabled"}</p>
          <p className="meta">Future LLM reviewer compatible: {review.future_llm_reviewer_compatible ? "yes" : "no"}</p>
          <p className="meta">Reviewer verdict is non-actionable in R7E.</p>
          {review.reasons.length > 0 && <p className="meta">Reason: {summarizeList(review.reasons)}</p>}
        </>
      )}
    </div>
  );
}

function MigrationMemoryDetails({
  memory,
}: {
  memory: V2MigrationMemoryRetrievalResponse | null;
}) {
  if (!memory) {
    return null;
  }
  const top = memory.top_match;
  return (
    <div className="trace-section">
      <strong>Migration Memory</strong>
      <p className="meta">Retrieval status: {memory.retrieval_status || "unavailable"}</p>
      {memory.retrieval_status === "available" && top ? (
        <>
          <p className="meta">Top match: {top.title || "n/a"}</p>
          <p className="meta">Memory case: {top.memory_case_id || "n/a"}</p>
          <p className="meta">Trust level: {top.trust_level || "unknown"}</p>
          <p className="meta">Authority level: {memory.authority_level || top.authority_level || "advisory_only"}</p>
          <p className="meta">Matched memory signals: {summarizeList(top.matched_signals)}</p>
          <p className="meta">Advisory summary: {memory.advisory_summary || top.summary || "n/a"}</p>
          <p className="meta">Missing evidence suggestions: {summarizeList(memory.missing_evidence_suggestions)}</p>
          <p className="meta">Repair authority: none</p>
          <p className="meta">Memory cannot approve/apply/start downstream</p>
          <p className="meta">Recommended use: {memory.recommended_use || "human review gate / future RAG seed"}</p>
        </>
      ) : memory.retrieval_status === "no_matches" ? (
        <p className="meta">No relevant memory cases found.</p>
      ) : (
        <p className="meta">Migration memory unavailable.</p>
      )}
      <p className="meta">Memory match is advisory only. It can inform future proposer/reviewer prompts, but it cannot approve, apply, or override backend gates.</p>
    </div>
  );
}

function stageClassificationHelp(status: string): string {
  if (status === "known_family_candidate") {
    return "Candidate deterministic rule detected, but real repair proposal/apply is not enabled in R7C.2.";
  }
  if (status === "blocked_pending_evidence") {
    return "Additional build/test artifacts are required before classifier can select a subtype.";
  }
  if (status === "unsupported_known_failure") {
    return "Failure signal recognized as a migration review gate. No automatic repair is enabled.";
  }
  if (status === "unknown") {
    return "Failure remains unknown after evidence review.";
  }
  return "";
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
  const [gateState, setGateState] = useState<GatePanelState>({ status: "loading" });
  const [r6RepairState, setR6RepairState] = useState<R6RepairUiState>(EMPTY_R6_REPAIR_UI_STATE);
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
          repairProposal: null,
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
          repairProposal: response.repair_proposal ?? response.repairProposal ?? null,
        };
      });
      setR6RepairState(EMPTY_R6_REPAIR_UI_STATE);
      setAssistantQuestion("");
    } catch (e) {
      setAssistantError(e instanceof Error ? e.message : "Assistant request failed");
    } finally {
      setAssistantBusy(false);
    }
  }

  async function runControlledR6Demo() {
    if (!normalizedJobId) return;
    setR6RepairState((current) => ({ ...current, busy: "demo", error: null }));
    try {
      const response = await runControlledR6RepairDemo(normalizedJobId);
      setData((current) => {
        if (!current) return current;
        return {
          ...current,
          repairProposal: response.repair_proposal,
        };
      });
      setR6RepairState(EMPTY_R6_REPAIR_UI_STATE);
      await refreshLiveState();
    } catch (e) {
      setR6RepairState((current) => ({
        ...current,
        busy: null,
        error: e instanceof Error ? e.message : "Controlled R6 repair demo failed.",
      }));
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

  async function requestReviewerForCurrentProposal() {
    const proposal = data?.repairProposal ?? null;
    const missing = missingReviewerRequestFields(proposal);
    if (!proposal || missing.length > 0) {
      setR6RepairState((current) => ({ ...current, error: `Reviewer request missing: ${missing.join(", ")}.` }));
      return;
    }
    const contextChecksum = proposalContextChecksum(proposal);
    const commandId = proposal.command_id ?? "";
    const proposalId = proposal.proposal_id ?? "";
    const proposalChecksum = proposal.proposal_checksum ?? "";
    setR6RepairState((current) => ({ ...current, busy: "reviewer", error: null }));
    try {
      const critique = await requestV2ReviewerCritique(commandId, proposalId, {
        proposal_type: "repair_proposal",
        proposal_checksum: proposalChecksum,
        context_pack_checksum: contextChecksum,
      });
      setR6RepairState((current) => ({ ...current, reviewer: critique, busy: null }));
    } catch (e) {
      setR6RepairState((current) => ({
        ...current,
        busy: null,
        error: e instanceof Error ? e.message : "Reviewer request failed.",
      }));
    }
  }

  async function prepareCurrentRepairApplyContext() {
    const proposal = data?.repairProposal ?? null;
    const reviewer = r6RepairState.reviewer;
    if (!proposal?.command_id || !proposal.proposal_id || !canPrepareR6ApplyContext(proposal, reviewer)) {
      setR6RepairState((current) => ({ ...current, error: "Apply context requires reviewer accept plus proposal patch, target, sandbox, legacy, and checksums from backend." }));
      return;
    }
    setR6RepairState((current) => ({ ...current, busy: "context", error: null }));
    try {
      const response = await prepareV2RepairApplyContext(proposal.command_id, proposal.proposal_id, {
        proposal_checksum: proposal.proposal_checksum ?? "",
        context_pack_checksum: proposalContextChecksum(proposal),
        reviewer_critique_id: reviewer?.critique_id ?? proposal.reviewer_critique_id ?? "",
        proposer_invocation_id: proposerInvocationId(proposal),
        reviewer_invocation_id: reviewerInvocationId(reviewer),
        approval_scope: "sandbox_only",
      });
      setR6RepairState((current) => ({ ...current, context: response.repair_review_context, busy: null }));
    } catch (e) {
      setR6RepairState((current) => ({
        ...current,
        busy: null,
        error: e instanceof Error ? e.message : "Apply context preparation failed.",
      }));
    }
  }

  async function approveCurrentRepair() {
    const context = r6RepairState.context;
    const checksum = r6RepairState.approvalChecksumInput.trim();
    if (!context || checksum !== context.proposal_checksum) {
      setR6RepairState((current) => ({ ...current, error: "Human approval requires exact proposal checksum." }));
      return;
    }
    setR6RepairState((current) => ({ ...current, busy: "approval", error: null }));
    try {
      const response = await approveV2RepairReviewContext(context.context_id, {
        approval_checksum: checksum,
        approval_note: "Human approved exact repair checksum from Control Tower UI.",
        approval_scope: "sandbox_only",
      });
      setR6RepairState((current) => ({
        ...current,
        approval: response.approval,
        context: response.repair_review_context ?? current.context,
        busy: null,
      }));
    } catch (e) {
      setR6RepairState((current) => ({
        ...current,
        busy: null,
        error: e instanceof Error ? e.message : "Repair approval failed.",
      }));
    }
  }

  async function applyCurrentRepair() {
    const context = r6RepairState.context;
    const approval = r6RepairState.approval;
    if (!context || !approval) {
      setR6RepairState((current) => ({ ...current, error: "Official apply requires prepared context and recorded human approval." }));
      return;
    }
    setR6RepairState((current) => ({ ...current, busy: "apply", error: null }));
    try {
      const response = await applyV2RepairReviewContext(context.context_id, {
        approval_id: approval.approval_id,
        expected_approval_checksum: approval.approval_checksum,
        expected_sandbox_checksum: context.sandbox_checksum,
        expected_legacy_checksum: context.legacy_checksum,
      });
      setR6RepairState((current) => ({ ...current, applyResult: response, busy: null }));
      await refreshLiveState();
    } catch (e) {
      setR6RepairState((current) => ({
        ...current,
        busy: null,
        error: e instanceof Error ? e.message : "Official repair apply failed.",
      }));
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

      {gateState.status !== "loading" ? <GatePanelContent state={gateState} /> : null}

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
      <section className="panel">
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
              ) : shouldShowApprovalDecisionControls(a.status, approvalReviewOpen) ? (
                <div className="approval-actions">
                  <button type="button" disabled={approvalBusy === a.card_id} onClick={() => void approveCard(a)}>
                    Approve
                  </button>
                  <button type="button" disabled={approvalBusy === a.card_id} onClick={() => void rejectCard(a)}>
                    Reject
                  </button>
                </div>
              ) : (
                <p className="meta">
                  Decision recorded: {a.status.toUpperCase()}. No further approval actions available.
                </p>
              )}
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
                      <StageFailureEvidenceDetails diagnosis={f.supervision_trace.ai_diagnosis} stage={f.stage} />
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
        repairProposal={data.repairProposal}
        onQuestionChange={setAssistantQuestion}
        onAsk={() => void askAssistant()}
      />

      <ControlledR6RepairDemoPanel
        enabled={isControlledR6DemoUiEnabled()}
        hasProposal={Boolean(data.repairProposal)}
        unknownFailure={hasUnknownNonRepairableFailure(data.failureSummary)}
        busy={r6RepairState.busy === "demo"}
        onRun={() => void runControlledR6Demo()}
      />

      <R6GovernedRepairPanel
        proposal={data.repairProposal}
        state={r6RepairState}
        onApprovalChecksumChange={(value) => setR6RepairState((current) => ({ ...current, approvalChecksumInput: value }))}
        onRequestReviewer={() => void requestReviewerForCurrentProposal()}
        onPrepareContext={() => void prepareCurrentRepairApplyContext()}
        onApproveRepair={() => void approveCurrentRepair()}
        onOfficialApply={() => void applyCurrentRepair()}
      />

      {/* Proof & Report */}
      <section className="panel">
        <h2>Proof & Report</h2>
        <p className="meta">Final proof report generated when all three deterministic gates pass.</p>
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
        .repair-proposal-card { border: 1px solid #c9ab4b; background: #fffdf5; padding: 0.75rem; margin-top: 0.75rem; border-radius: 4px; }
        .r6-repair-panel { grid-column: 1 / -1; }
        .r6-repair-panel button { padding: 0.45rem 0.7rem; border: 1px solid #333; border-radius: 4px; background: #fff; width: fit-content; }
        .r6-repair-panel button:disabled { color: #777; border-color: #bbb; }
        .checksum-input { display: grid; gap: 0.25rem; max-width: 42rem; font-size: 0.85rem; color: #666; }
        .checksum-input input { min-width: 0; padding: 0.5rem; border: 1px solid #aaa; border-radius: 4px; font-family: monospace; }
        .failure-panel { border-color: #a40000; background: #fffafa; }
        .failure-card { border: 1px solid #ffcccc; padding: 0.75rem; margin: 0.5rem 0; border-radius: 4px; }
        .failure-card .meta { margin: 0.2rem 0; }
        .contract-failure-card { border: 1px solid #cc8800; background: #fffaf0; }
        .contract-failure-card .meta { margin: 0.2rem 0; }
        .supervision-trace { border-top: 1px solid #f1c0c0; margin-top: 0.75rem; padding-top: 0.75rem; }
        .supervision-trace h3 { margin: 0 0 0.5rem 0; font-size: 1rem; }
        .trace-section { border-left: 3px solid #6b7a90; padding-left: 0.6rem; margin-top: 0.6rem; }
        .trace-section ul { margin: 0.25rem 0 0 1rem; padding: 0; }
        .migration-intelligence { border-top: 1px solid #ddd; margin-top: 0.75rem; padding-top: 0.75rem; }
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
