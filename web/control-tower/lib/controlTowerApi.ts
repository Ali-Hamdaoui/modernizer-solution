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
  ModelActivityRawResponse,
  ModelActivityResponse,
  PlanAmendmentPreviewRequest,
  PlanAmendmentPreviewResponse,
  PipelineOption,
  PrivilegedActionListResponse,
  PublicEventReplayResponse,
  RunnerProfileOption,
  StageChainResponse
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
    throw new Error(`Control Tower mutation failed for ${path}.`);
  }
  return (await response.json()) as TResponse;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${CONTROL_TOWER_API_BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Control Tower request failed for ${path}.`);
  }
  return (await response.json()) as T;
}
