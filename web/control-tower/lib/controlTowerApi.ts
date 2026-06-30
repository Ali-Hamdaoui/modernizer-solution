import type {
  ApprovalListResponse,
  ArtifactListResponse,
  Catalog,
  CommandListResponse,
  CommandOutputWindow,
  CreateDiagnosticJobFormValues,
  CreateDiagnosticJobRequest,
  FilesystemRootOption,
  JobRepresentation,
  V2MigrationJobResponse,
  V2JobEventSnapshotResponse,
  V2PipelineResponse,
  V2FailureSummaryResponse,
  V2StageEntry,
  V2StageCommandResponse,
  V2ApprovalResponse,
  V2ResumeCommandResponse,
  V2StageContinuationResponse,
  V2AssistantAskResponse,
  V2AssistantMessagesListResponse,
  V2AssistantMessageResponse,
  V2ArtifactPreviewResponse,
  V2ReviewerCritiqueResponse,
  V2ReviewerCritiquesListResponse,
  PrepareRepairApplyContextRequest,
  PrepareRepairApplyContextResponse,
  ApproveRepairReviewContextResponse,
  ApplyRepairReviewContextResponse,
  V2DraftActionResponse,
  ModelActivityRawResponse,
  ModelActivityResponse,
  PlanAmendmentPreviewRequest,
  PlanAmendmentPreviewResponse,
  PipelineOption,
  GateActionRequest,
  GateActionResponse,
  GateDetailResponse,
  GateListResponse,
  PrivilegedActionListResponse,
  ProofGatesResponse,
  ProofReportEntry,
  PublicEventReplayResponse,
  RepairProposalListResponse,
  RunnerProfileOption,
  StageChainResponse,
  OpenGateForJobResponse,
  // F14 types
  PomView,
  PomDependencyReview,
  PomChangeProposal,
  PomApplyResult,
  PomChangeRecordSummary,
  PomValidationRun,
  PomRollbackResult,
  PomProposeRequest,
  PomApplyRequest,
} from "./contracts";

export const CONTROL_TOWER_FRONTEND_CLIENT_ID = "control-tower-frontend";
export const DEFAULT_CONTROL_TOWER_API_BASE_URL = "http://127.0.0.1:8000";

export function resolveControlTowerApiBaseUrl(
  configuredValue: string | undefined = process.env.NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL
): string {
  const candidate = configuredValue ?? DEFAULT_CONTROL_TOWER_API_BASE_URL;
  const url = new URL(candidate);
  if (url.protocol !== "http:") {
    throw new Error("Control Tower API base URL must use http for local development.");
  }
  if (url.hostname !== "127.0.0.1") {
    throw new Error("Control Tower API base URL must use 127.0.0.1 and must not mix localhost.");
  }
  if (!url.port) {
    throw new Error("Control Tower API base URL must include an explicit port.");
  }
  return url.origin;
}

export const CONTROL_TOWER_API_BASE_URL = resolveControlTowerApiBaseUrl();

export const DEFAULT_V2_STAGE_CONTINUATION_POLICY = "auto_on_green" as const;

export type V2StageContinuationPolicy =
  | typeof DEFAULT_V2_STAGE_CONTINUATION_POLICY
  | "manual"
  | "manual_on_warning_or_failure";

type V2JobPolicy = {
  continue_after_warning: boolean;
  enable_runtime_gate: boolean;
  enable_endpoint_gate: boolean;
  stage_continuation_policy: V2StageContinuationPolicy;
};

export type CreateV2JobRequest = {
  setup_id: string;
  policy: V2JobPolicy;
};

export function createV2JobPayload(
  setupId: string,
  stageContinuationPolicy: V2StageContinuationPolicy = DEFAULT_V2_STAGE_CONTINUATION_POLICY,
): CreateV2JobRequest {
  return {
    setup_id: setupId,
    policy: {
      continue_after_warning: false,
      enable_runtime_gate: false,
      enable_endpoint_gate: false,
      stage_continuation_policy: stageContinuationPolicy,
    },
  };
}

export function requireJobId(jobId: string): string {
  const trimmedJobId = jobId.trim();
  if (!trimmedJobId) {
    throw new Error("Migration job id is required.");
  }
  return trimmedJobId;
}

export const allowedStatusCopy = {
  cancelled: "Foundation diagnostic cancelled",
  created: "Foundation diagnostic job created",
  connected: "Event replay connected",
  completed: "Foundation diagnostic completed",
  diagnosticQueued: "Foundation diagnostic queued",
  failed: "Foundation diagnostic failed",
  running: "Foundation diagnostic running",
  queued: "Command queued"
} as const;

export function splitOptionKey(value: string): [string, string] {
  const [id, version] = value.split("@", 2);
  if (!id || !version) {
    throw new Error("Expected option key in id@version form.");
  }
  return [id, version];
}

export function createDiagnosticJobPayload(
  values: CreateDiagnosticJobFormValues
): CreateDiagnosticJobRequest {
  const [runnerProfileId, runnerProfileVersion] = splitOptionKey(values.runnerProfileKey);
  const [pipelineId, pipelineVersion] = splitOptionKey(values.pipelineKey);
  return {
    runner_profile_id: runnerProfileId,
    runner_profile_version: runnerProfileVersion,
    pipeline_id: pipelineId,
    pipeline_version: pipelineVersion,
    legacy_source_root_id: values.legacySourceRootId,
    legacy_source_relative_path: values.legacySourceRelativePath,
    output_root_id: values.outputRootId,
    output_relative_path: values.outputRelativePath,
    target_proof_level: "ANALYZED",
    enabled_gates: [],
    policy: {
      continue_after_warning: false,
      enable_runtime_gate: false,
      enable_endpoint_gate: false
    }
  };
}

export async function getCatalog(): Promise<Catalog> {
  const [runnerProfiles, pipelines, filesystemRoots] = await Promise.all([
    getJson<{ runner_profiles: RunnerProfileOption[] }>("/v1/runner-profiles"),
    getJson<{ pipelines: PipelineOption[] }>("/v1/pipelines"),
    getJson<{ filesystem_roots: FilesystemRootOption[] }>("/v1/filesystem/roots")
  ]);
  return {
    runnerProfiles: runnerProfiles.runner_profiles,
    pipelines: pipelines.pipelines,
    filesystemRoots: filesystemRoots.filesystem_roots
  };
}

export async function getJob(jobId: string): Promise<JobRepresentation & { etag: string }> {
  const response = await fetch(`${CONTROL_TOWER_API_BASE_URL}/v1/jobs/${encodeURIComponent(jobId)}`, {
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`Failed to load job ${jobId}.`);
  }
  const etag = response.headers.get("etag");
  if (!etag) {
    throw new Error("Job response did not include an ETag.");
  }
  return { ...((await response.json()) as JobRepresentation), etag };
}

export async function getCommittedEvents(
  jobId: string,
  afterSequence: number
): Promise<PublicEventReplayResponse> {
  const params = new URLSearchParams({ after_sequence: String(afterSequence) });
  return getJson<PublicEventReplayResponse>(`/v1/jobs/${encodeURIComponent(jobId)}/events?${params}`);
}

export async function getCommands(jobId: string): Promise<CommandListResponse> {
  return getJson<CommandListResponse>(`/v1/jobs/${encodeURIComponent(jobId)}/commands`);
}

export async function getCommandOutput(
  jobId: string,
  commandId: string,
  stream: "stdout" | "stderr",
  afterOffset: number
): Promise<CommandOutputWindow> {
  const params = new URLSearchParams({ after_offset: String(afterOffset), max_bytes: "65536" });
  return getJson<CommandOutputWindow>(
    `/v1/jobs/${encodeURIComponent(jobId)}/commands/${encodeURIComponent(commandId)}/logs/${stream}?${params}`
  );
}

export async function getArtifacts(jobId: string): Promise<ArtifactListResponse> {
  return getJson<ArtifactListResponse>(`/v1/jobs/${encodeURIComponent(jobId)}/artifacts`);
}

export async function getStageChain(jobId: string): Promise<StageChainResponse> {
  return getJson<StageChainResponse>(`/v1/jobs/${encodeURIComponent(jobId)}/stages`);
}

export async function getModelActivity(jobId: string): Promise<ModelActivityResponse> {
  const raw = await getJson<ModelActivityRawResponse>(
    `/v1/jobs/${encodeURIComponent(jobId)}/model-invocations`
  );

  // Normalize: backend returns { model_invocations: [...] } but
  // frontend expects { invocations: [...] }.  Accept both keys so
  // a future backend change to { invocations } works unmodified.
  const invocations: ModelActivityResponse["invocations"] = (
    raw.invocations ?? raw.model_invocations ?? []
  ).map((inv) => ({
    ...inv,
    // Backend per-job endpoint omits top-level job_id; fill from argument.
    job_id: inv.job_id ?? jobId,
    // Ensure nullable fields are null not undefined
    profile_id: inv.profile_id ?? null,
    actor_type: inv.actor_type ?? null,
    actor_id: inv.actor_id ?? null,
    correlation_id: inv.correlation_id ?? null,
    causation_id: inv.causation_id ?? null,
  }));

  return { job_id: jobId, invocations };
}

export async function getApprovals(jobId: string): Promise<ApprovalListResponse> {
  return getJson<ApprovalListResponse>(`/v1/jobs/${encodeURIComponent(jobId)}/approvals`);
}

export async function getPrivilegedActions(jobId: string): Promise<PrivilegedActionListResponse> {
  return getJson<PrivilegedActionListResponse>(`/v1/jobs/${encodeURIComponent(jobId)}/privileged-actions`);
}

export async function getRepairProposals(commandId: string): Promise<RepairProposalListResponse> {
  return getJson<RepairProposalListResponse>(`/v1/commands/${encodeURIComponent(commandId)}/fake-repair-proposals`);
}

export async function getProofGates(jobId: string): Promise<ProofGatesResponse> {
  return getJson<ProofGatesResponse>(`/v1/jobs/${encodeURIComponent(jobId)}/proof-gates`);
}

export async function getProofReport(jobId: string): Promise<ProofReportEntry> {
  return getJson<ProofReportEntry>(`/v1/jobs/${encodeURIComponent(jobId)}/proof-report`);
}

export async function previewPlanAmendment(
  jobId: string,
  payload: PlanAmendmentPreviewRequest
): Promise<PlanAmendmentPreviewResponse> {
  return postJson<PlanAmendmentPreviewResponse>(
    `/v1/jobs/${encodeURIComponent(jobId)}/plan-amendments/preview`,
    payload
  );
}

export function eventStreamUrl(jobId: string, afterSequence: number): string {
  const params = new URLSearchParams({ after_sequence: String(afterSequence) });
  return `${CONTROL_TOWER_API_BASE_URL}/v1/jobs/${encodeURIComponent(jobId)}/events/stream?${params}`;
}

export function assistantStreamUrl(jobId: string): string {
  return `${CONTROL_TOWER_API_BASE_URL}/v1/jobs/${encodeURIComponent(jobId)}/assistant/stream`;
}

// ── V2 migration cockpit API methods ──────────────────────────────────

export async function createV2Job(setupId: string): Promise<V2MigrationJobResponse> {
  return postJson<V2MigrationJobResponse>(
    "/v1/v2/migration-jobs",
    createV2JobPayload(setupId)
  );
}

export async function startV2Stage1(jobId: string, setupId: string): Promise<V2StageCommandResponse> {
  return postJson<V2StageCommandResponse>(
    "/v1/v2/migration-jobs/start-stage1",
    { job_id: jobId, setup_id: setupId }
  );
}

export async function getV2MigrationJob(jobId: string): Promise<V2MigrationJobResponse> {
  const safeJobId = requireJobId(jobId);
  return getJson<V2MigrationJobResponse>(
    `/v1/v2/migration-jobs/${encodeURIComponent(safeJobId)}`
  );
}

export async function getV2JobApprovals(jobId: string): Promise<{ approvals: V2ApprovalResponse[] }> {
  const safeJobId = requireJobId(jobId);
  return getJson<{ approvals: V2ApprovalResponse[] }>(
    `/v1/v2/jobs/${encodeURIComponent(safeJobId)}/approvals`
  );
}

export async function getV2JobEventSnapshot(
  jobId: string,
  after: number = 0
): Promise<V2JobEventSnapshotResponse> {
  const safeJobId = requireJobId(jobId);
  const params = new URLSearchParams({ after: String(after) });
  return getJson<V2JobEventSnapshotResponse>(
    `/v1/v2/migration-jobs/${encodeURIComponent(safeJobId)}/events/snapshot?${params}`
  );
}

export async function getV2JobPipeline(jobId: string): Promise<V2PipelineResponse> {
  const safeJobId = requireJobId(jobId);
  return getJson<V2PipelineResponse>(
    `/v1/v2/migration-jobs/${encodeURIComponent(safeJobId)}/pipeline`
  );
}

export async function getV2FailureSummary(jobId: string): Promise<V2FailureSummaryResponse> {
  const safeJobId = requireJobId(jobId);
  return getJson<V2FailureSummaryResponse>(
    `/v1/v2/migration-jobs/${encodeURIComponent(safeJobId)}/failure-summary`
  );
}

export async function getV2ArtifactPreview(
  jobId: string,
  artifactKind: string,
  stage?: number
): Promise<V2ArtifactPreviewResponse> {
  const safeJobId = requireJobId(jobId);
  const safeKind = artifactKind.trim();
  if (!safeKind) {
    throw new Error("Artifact kind is required.");
  }
  const params = stage != null ? `?stage=${stage}` : "";
  return getJson<V2ArtifactPreviewResponse>(
    `/v1/v2/jobs/${encodeURIComponent(safeJobId)}/artifacts/${encodeURIComponent(safeKind)}${params}`
  );
}

export async function getV2RootPomPreview(
  jobId: string,
  stage: number
): Promise<V2ArtifactPreviewResponse> {
  const safeJobId = requireJobId(jobId);
  const params = new URLSearchParams({ stage: String(stage), mode: "preview" });
  return getJson<V2ArtifactPreviewResponse>(
    `/v1/v2/jobs/${encodeURIComponent(safeJobId)}/files/root-pom?${params}`
  );
}

export function v2RootPomDownloadUrl(jobId: string, stage: number): string {
  const safeJobId = requireJobId(jobId);
  const params = new URLSearchParams({ stage: String(stage), mode: "download" });
  return `${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/${encodeURIComponent(safeJobId)}/files/root-pom?${params}`;
}

export function v2EventStreamUrl(jobId: string, after: number = 0): string {
  const safeJobId = requireJobId(jobId);
  const params = new URLSearchParams({ after: String(after) });
  return `${CONTROL_TOWER_API_BASE_URL}/v1/v2/migration-jobs/${encodeURIComponent(safeJobId)}/events?${params}`;
}

export async function getV2MigrationJobStages(jobId: string): Promise<{ job_id: string; stages: V2StageEntry[] }> {
  const safeJobId = requireJobId(jobId);
  return getJson<{ job_id: string; stages: V2StageEntry[] }>(
    `/v1/v2/migration-jobs/${encodeURIComponent(safeJobId)}/stages`
  );
}

export async function getV2JobGates(jobId: string): Promise<GateListResponse> {
  const safeJobId = requireJobId(jobId);
  return getJson<GateListResponse>(`/v1/v2/jobs/${encodeURIComponent(safeJobId)}/gates`);
}

export async function getV2OpenGate(jobId: string): Promise<OpenGateForJobResponse> {
  const safeJobId = requireJobId(jobId);
  const response = await fetch(
    `${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/${encodeURIComponent(safeJobId)}/gates/open`,
    { cache: "no-store" }
  );
  if (response.status === 404) {
    return { gate: null };
  }
  if (!response.ok) {
    throw new Error(`Failed to load open gate for ${jobId}.`);
  }
  return (await response.json()) as OpenGateForJobResponse;
}

export async function getV2GateDetail(jobId: string, gateId: string): Promise<GateDetailResponse> {
  const safeJobId = requireJobId(jobId);
  const safeGateId = gateId.trim();
  if (!safeGateId) {
    throw new Error("Gate id is required.");
  }
  return getJson<GateDetailResponse>(
    `/v1/v2/jobs/${encodeURIComponent(safeJobId)}/gates/${encodeURIComponent(safeGateId)}`
  );
}

export async function postV2GateAction(
  jobId: string,
  gateId: string,
  payload: GateActionRequest
): Promise<GateActionResponse> {
  const safeJobId = requireJobId(jobId);
  const safeGateId = gateId.trim();
  if (!safeGateId) {
    throw new Error("Gate id is required.");
  }
  return postJson<GateActionResponse>(
    `/v1/v2/jobs/${encodeURIComponent(safeJobId)}/gates/${encodeURIComponent(safeGateId)}/actions`,
    payload
  );
}

export async function approveV2Card(
  jobId: string,
  cardId: string,
  expectedChecksum: string
): Promise<V2ResumeCommandResponse> {
  return postJson<V2ResumeCommandResponse>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/approvals/${encodeURIComponent(cardId)}/approve`,
    { expected_checksum: expectedChecksum }
  );
}

export async function rejectV2Card(
  jobId: string,
  cardId: string
): Promise<V2ApprovalResponse> {
  return postJson<V2ApprovalResponse>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/approvals/${encodeURIComponent(cardId)}/reject`,
    {}
  );
}

export async function progressV2Stage(
  jobId: string,
  setupId: string,
  currentStage: number,
  sandboxPath: string
): Promise<V2StageContinuationResponse> {
  return postJson<V2StageContinuationResponse>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stages/progress`,
    {
      setup_id: setupId,
      current_stage: currentStage,
      sandbox_path: sandboxPath,
    }
  );
}

export async function getV2AssistantMessages(jobId: string): Promise<V2AssistantMessagesListResponse> {
  const safeJobId = requireJobId(jobId);
  return getJson<V2AssistantMessagesListResponse>(
    `/v1/v2/jobs/${encodeURIComponent(safeJobId)}/assistant/messages`
  );
}

export async function addV2AssistantMessage(
  jobId: string,
  role: string,
  content: string
): Promise<V2AssistantMessageResponse> {
  return postJson<V2AssistantMessageResponse>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/assistant/messages`,
    { job_id: jobId, role, content }
  );
}

export async function askV2Assistant(
  jobId: string,
  question: string
): Promise<V2AssistantAskResponse> {
  const safeJobId = requireJobId(jobId);
  return postJson<V2AssistantAskResponse>(
    `/v1/v2/jobs/${encodeURIComponent(safeJobId)}/assistant/ask`,
    { question }
  );
}

export async function draftV2Action(
  jobId: string,
  actionType: string,
  reason: string,
  stageIndex: number = 1,
  // F05 optional revision steering fields
  options?: {
    source_proposal_id?: string;
    failed_command_id?: string;
    revision_instruction?: string;
    context_pack_checksum?: string;
    revision_of?: string;
    revision_number?: number;
    allowed_scope?: string;
  }
): Promise<V2DraftActionResponse> {
  const body: Record<string, unknown> = {
    job_id: jobId,
    action_type: actionType,
    reason,
    stage_index: stageIndex,
  };
  if (options?.source_proposal_id) body.source_proposal_id = options.source_proposal_id;
  if (options?.failed_command_id) body.failed_command_id = options.failed_command_id;
  if (options?.revision_instruction) body.revision_instruction = options.revision_instruction;
  if (options?.context_pack_checksum) body.context_pack_checksum = options.context_pack_checksum;
  if (options?.revision_of) body.revision_of = options.revision_of;
  if (options?.revision_number) body.revision_number = options.revision_number;
  if (options?.allowed_scope) body.allowed_scope = options.allowed_scope;
  return postJson<V2DraftActionResponse>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/assistant/actions/draft`,
    body
  );
}

export async function requestV2ReviewerCritique(
  commandId: string,
  proposalId: string,
  payload: {
    proposal_type: string;
    proposal_checksum: string;
    context_pack_checksum: string;
    model_invocation_id?: string | null;
  }
): Promise<V2ReviewerCritiqueResponse> {
  // F07: NEVER sends decision/reasoning from client.
  // The backend calls the reviewer model, validates output, and persists.
  return postJson<V2ReviewerCritiqueResponse>(
    `/v1/v2/commands/${encodeURIComponent(commandId)}/repair/proposal/${encodeURIComponent(proposalId)}/reviewer-critique`,
    { proposal_id: proposalId, ...payload }
  );
}

export async function getV2ReviewerCritiques(
  commandId: string,
  proposalId: string
): Promise<V2ReviewerCritiquesListResponse> {
  return getJson<V2ReviewerCritiquesListResponse>(
    `/v1/v2/commands/${encodeURIComponent(commandId)}/repair/proposal/${encodeURIComponent(proposalId)}/reviewer-critiques`
  );
}

export async function prepareV2RepairApplyContext(
  commandId: string,
  proposalId: string,
  payload: PrepareRepairApplyContextRequest
): Promise<PrepareRepairApplyContextResponse> {
  return postJson<PrepareRepairApplyContextResponse>(
    `/v1/v2/commands/${encodeURIComponent(commandId)}/repair/proposal/${encodeURIComponent(proposalId)}/prepare-apply-context`,
    payload
  );
}

export async function approveV2RepairReviewContext(
  contextId: string,
  payload: {
    approval_checksum: string;
    approval_note: string;
    approval_scope: "sandbox_only";
  }
): Promise<ApproveRepairReviewContextResponse> {
  return postJson<ApproveRepairReviewContextResponse>(
    `/v1/v2/repair-review/${encodeURIComponent(contextId)}/approve`,
    payload
  );
}

export async function applyV2RepairReviewContext(
  contextId: string,
  payload: {
    approval_id: string;
    expected_approval_checksum: string;
    expected_sandbox_checksum: string;
    expected_legacy_checksum: string;
    idempotency_key?: string;
  }
): Promise<ApplyRepairReviewContextResponse> {
  return postJson<ApplyRepairReviewContextResponse>(
    `/v1/v2/repair-review/${encodeURIComponent(contextId)}/apply`,
    payload
  );
}

// ── F14 — Stage 3 POM Dependency Editor API ──────────────────────────────

export async function getStage3Pom(jobId: string): Promise<PomView> {
  return getJson<PomView>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom`
  );
}

export async function getStage3DependencyReview(jobId: string): Promise<PomDependencyReview> {
  return getJson<PomDependencyReview>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/dependency-review`
  );
}

export async function proposePomChange(
  jobId: string,
  request: PomProposeRequest
): Promise<PomChangeProposal> {
  return postJson<PomChangeProposal>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom/propose-change`,
    request
  );
}

export async function applyPomChange(
  jobId: string,
  request: PomApplyRequest
): Promise<PomApplyResult> {
  return postJson<PomApplyResult>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom/apply-change`,
    request
  );
}

export async function listPomChanges(
  jobId: string
): Promise<{ job_id: string; changes: PomChangeRecordSummary[] }> {
  return getJson<{ job_id: string; changes: PomChangeRecordSummary[] }>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom/changes`
  );
}

export async function getPomChange(
  jobId: string,
  changeId: string
): Promise<PomChangeRecordSummary> {
  return getJson<PomChangeRecordSummary>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom/changes/${encodeURIComponent(changeId)}`
  );
}

export async function getPomValidationResult(
  jobId: string,
  validationId: string
): Promise<PomValidationRun> {
  return getJson<PomValidationRun>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom/validation/${encodeURIComponent(validationId)}`
  );
}

export async function applyPomRepairPlan(
  jobId: string,
  repairPlanId: string,
  idempotencyKey: string
): Promise<PomApplyResult> {
  return postJson<PomApplyResult>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom/repair`,
    { repair_plan_id: repairPlanId, idempotency_key: idempotencyKey }
  );
}

export async function rollbackPomChange(
  jobId: string,
  changeId: string,
  idempotencyKey: string
): Promise<PomRollbackResult> {
  return postJson<PomRollbackResult>(
    `/v1/v2/jobs/${encodeURIComponent(jobId)}/stage/3/pom/rollback`,
    { change_id: changeId, idempotency_key: idempotencyKey }
  );
}


export async function postJson<TResponse>(
  path: string,
  body: unknown,
  headers: HeadersInit = {}
): Promise<TResponse> {
  const response = await fetch(`${CONTROL_TOWER_API_BASE_URL}${path}`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: {
      "Content-Type": "application/json",
      "X-Control-Tower-Client": CONTROL_TOWER_FRONTEND_CLIENT_ID,
      ...headers
    }
  });
  if (!response.ok) {
    throw new Error(
      `Control Tower mutation failed for ${path}: ${response.status} ${response.statusText || "HTTP error"}.`
    );
  }
  return (await response.json()) as TResponse;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${CONTROL_TOWER_API_BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(
      `Control Tower request failed for ${path}: ${response.status} ${response.statusText || "HTTP error"}.`
    );
  }
  return (await response.json()) as T;
}
