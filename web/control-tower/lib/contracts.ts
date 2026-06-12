export type RunnerProfileOption = {
  runner_profile_id: string;
  runner_profile_version: string;
  display_name: string;
};

export type PipelineOption = {
  pipeline_id: string;
  pipeline_version: string;
  display_name: string;
};

export type FilesystemRootOption = {
  runner_profile_id: string;
  runner_profile_version: string;
  root_id: string;
  kind: "source" | "output" | string;
  display_name: string;
};

export type Catalog = {
  runnerProfiles: RunnerProfileOption[];
  pipelines: PipelineOption[];
  filesystemRoots: FilesystemRootOption[];
};

export type CreateDiagnosticJobFormValues = {
  runnerProfileKey: string;
  pipelineKey: string;
  legacySourceRootId: string;
  legacySourceRelativePath: string;
  outputRootId: string;
  outputRelativePath: string;
};

export type CreateDiagnosticJobRequest = {
  runner_profile_id: string;
  runner_profile_version: string;
  pipeline_id: string;
  pipeline_version: string;
  legacy_source_root_id: string;
  legacy_source_relative_path: string;
  output_root_id: string;
  output_relative_path: string;
  target_proof_level: "ANALYZED";
  enabled_gates: string[];
  policy: {
    continue_after_warning: boolean;
    enable_runtime_gate: boolean;
    enable_endpoint_gate: boolean;
  };
};

export type JobRepresentation = {
  job: {
    job_id: string;
    version: number;
    state: string;
    created_at: string;
    updated_at: string;
  };
  active_command: null | {
    command_id: string;
    job_id: string;
      operation: string;
      status: string;
      created_at: string;
      updated_at: string;
      command_manifest_artifact_id?: string | null;
      working_directory_root_id?: string | null;
      working_directory_relative_path?: string | null;
      worker_id?: string | null;
      launch_attempt?: number | null;
    };
  etag: string;
};

export type CommandRepresentation = NonNullable<JobRepresentation["active_command"]>;

export type CommandListResponse = {
  job_id: string;
  commands: CommandRepresentation[];
};

export type CommandOutputWindow = {
  command_id: string;
  job_id: string;
  stream: "stdout" | "stderr";
  requested_offset: number;
  start_offset: number;
  next_offset: number;
  data: string;
  encoding: string;
  replacement_characters_used: number;
  truncated: boolean;
  terminal: boolean;
  max_bytes: number;
};

export type ArtifactMetadata = {
  artifact_id: string;
  job_id: string;
  stage_run_id: string | null;
  artifact_type: string;
  registered_root_id: string;
  relative_path: string;
  normalized_relative_path: string;
  content_type: string | null;
  size_bytes: number;
  checksum_algorithm: string;
  checksum: string;
  created_at: string;
  created_by: string;
};

export type ArtifactListResponse = {
  job_id: string;
  artifacts: ArtifactMetadata[];
};

export type PublicRunEvent = {
  event_id: string;
  job_id: string;
  sequence: number;
  event_type: string;
  actor_type: string;
  actor_id: string;
  correlation_id: string | null;
  causation_id: string | null;
  payload: Record<string, unknown>;
  payload_checksum: string;
  created_at: string;
};

export type PublicEventReplayResponse = {
  job_id: string;
  after_sequence: number;
  next_after_sequence: number;
  latest_sequence: number;
  events: PublicRunEvent[];
};

// ── Assistant panel types (V1-18F) ─────────────────────────────────

export type AssistantStreamEvent = {
  event_type: "message" | "tool_call" | "tool_result" | "error" | "done";
  data_json: string;
  sequence: number;
};

export type AssistantMessageData = {
  message_id: string;
  role: "user" | "assistant" | "tool_result";
  content: string;
  tool_call_id?: string;
};

export type AssistantToolResultData = {
  tool_call_id: string;
  tool_name: string;
  result: string;
  truncated: boolean;
  duration_ms: number;
};

export type AssistantToolCallData = {
  tool_call_id: string;
  tool_name: string;
  parameters: Record<string, unknown>;
};

export type AssistantErrorData = {
  tool_call_id: string;
  error: string;
};

export type AssistantDoneData = {
  status: string;
};
