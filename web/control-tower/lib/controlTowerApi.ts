import type {
  Catalog,
  CreateDiagnosticJobFormValues,
  CreateDiagnosticJobRequest,
  FilesystemRootOption,
  JobRepresentation,
  PipelineOption,
  RunnerProfileOption
} from "./contracts";

export const CONTROL_TOWER_API_BASE_URL =
  process.env.NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL ?? "http://127.0.0.1:8000";

export const allowedStatusCopy = {
  created: "Foundation diagnostic job created",
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

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${CONTROL_TOWER_API_BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Control Tower request failed for ${path}.`);
  }
  return (await response.json()) as T;
}
