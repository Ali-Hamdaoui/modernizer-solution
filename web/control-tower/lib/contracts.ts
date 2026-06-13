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

export type PlanAmendmentPreviewChange = {
  stage_index: number;
  change_type: string;
  description: string;
  rationale?: string | null;
};

export type PlanAmendmentPreviewRequest = {
  title: string;
  summary: string;
  source_kind: "manual" | "fake_provider";
  notes: string[];
  changes: PlanAmendmentPreviewChange[];
};

export type PlanAmendmentPreviewResponse = {
  job_id: string;
  source_kind: string;
  title: string;
  summary: string;
  payload_checksum: string;
  change_count: number;
  affected_stage_indexes: number[];
  change_types: string[];
  redacted_summary: {
    source_kind: string;
    title: string;
    summary: string;
    change_count: number;
    affected_stage_indexes: number[];
    change_types: string[];
    non_authoritative: boolean;
  };
  validation_status: "PASS";
  warning_codes: string[];
  preview_persisted: false;
  preview_applied: false;
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

// ── Model activity panel types (V1-18D) ─────────────────────────────────

export type ModelInvocationEntry = {
  invocation_id: string;
  job_id: string | null;
  profile_id: string | null;
  provider_kind: string | null;
  model_name: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  redacted_summary: string | null;
  actor_type: string | null;
  actor_id: string | null;
  created_at: string;
  correlation_id: string | null;
  causation_id: string | null;
};

export type ModelActivityResponse = {
  job_id: string;
  invocations: ModelInvocationEntry[];
};

// Raw backend response shape from V1-10 GET /v1/jobs/{job_id}/model-invocations
// The live backend returns { model_invocations: [...] } without top-level job_id.
// This type models both keys for forward/backward compatibility.
export type ModelActivityRawResponse = {
  model_invocations?: ModelInvocationEntry[];
  invocations?: ModelInvocationEntry[];
};

// ── Stage timeline panel types (V1-18B) ────────────────────────────────

export type StageChainEntry = {
  ledger_id: string;
  job_id: string;
  stage_index: number;
  stage_run_id: string;
  chain_status: string;
  input_source_kind: string;
  input_checksum: string | null;
  output_artifact_id: string | null;
  output_checksum: string | null;
  output_registered_at: string | null;
  created_at: string;
};

export type StageChainResponse = {
  job_id: string;
  stages: StageChainEntry[];
};

// ── Approvals panel types (V1-18C) ────────────────────────────────

export type ApprovalEntry = {
  approval_id: string;
  interrupt_id: string;
  decision: "approved" | "rejected" | "replan_required";
  approved_by: string;
  approval_comments: string;
  created_at: string;
};

export type ApprovalListResponse = {
  job_id: string;
  approvals: ApprovalEntry[];
};

export type PrivilegedActionEntry = {
  action_id: string;
  job_id: string;
  action_type: string;
  parameters: Record<string, unknown>;
  parameters_checksum: string;
  requested_by: string;
  status: string;
  requested_at: string;
  decided_at: string | null;
  decision: string | null;
  decided_by: string | null;
};

export type PrivilegedActionListResponse = {
  job_id: string;
  actions: PrivilegedActionEntry[];
};

// ── Repair panel types (V1-18E) ───────────────────────────────────

export type RepairClassificationEntry = {
  classification_id: string;
  command_id: string;
  job_id: string;
  command_status: string;
  evidence_kind: string;
  evidence_summary: string;
  evidence_checksum: string;
  classification_code: string;
  reason_code: string;
  repairable: boolean;
  attempt_limit: number;
  actor_type: string;
  actor_id: string;
  created_at: string;
};

export type FakeRepairProposalEntry = {
  proposal_id: string;
  classification_id: string;
  command_id: string;
  job_id: string;
  proposal_order: number;
  proposal_kind: string;
  proposal_summary: string;
  proposal_checksum: string;
  recommendation_type: string;
  confidence_label: string;
  confidence_score: number;
  warning_codes: string[];
  applicable: boolean;
  context_checksum: string;
  actor_type: string;
  actor_id: string;
  created_at: string;
};

export type RepairStatusEntry = {
  command_id: string;
  job_id: string;
  classification: RepairClassificationEntry | null;
  proposals: FakeRepairProposalEntry[];
  attempts: unknown[];
  repairable: boolean;
  created_at: string;
};

export type RepairProposalListResponse = {
  command_id: string;
  proposals: FakeRepairProposalEntry[];
};

// ── Proof and final report panel types (V1-18G) ───────────────────

export type ProofGateEntry = {
  stage_index: number;
  output_checksum: string;
  proof_gate_checksum: string;
  chain_status: string;
};

export type ProofGatesResponse = {
  job_id: string;
  gates: Record<string, string>;
  gate_count: number;
  required_gates: number;
  algorithm: string;
};

export type ProofReportEntry = {
  report_id: string;
  job_id: string;
  report_version: number;
  report_checksum: string;
  gate_count: number;
  all_gates_present: boolean;
  proof_complete: boolean;
  target_proof_level: string;
  pipeline_id: string;
  summary: Record<string, unknown>;
  gates: ProofGateEntry[];
  generated_at: string;
  generated_by: string;
};

// ── V2 migration cockpit types ──────────────────────────────────────

export type V2MigrationJobResponse = {
  job_id: string;
  setup_id: string;
  setup_checksum: string;
  pipeline_id: string;
  stages: V2StageEntry[];
  created_at: string;
};

export type V2JobEvent = {
  event_id: string;
  job_id: string;
  stage: number | null;
  type: string;
  status: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
  sequence: number;
};

export type V2JobEventSnapshotResponse = {
  job_id: string;
  after: number;
  events: V2JobEvent[];
  latest_sequence: number;
};

export type V2StageEntry = {
  stage_index: number;
  stage_run_id: string;
  pipeline_stage: string;
  input_source_kind: string;
  chain_status: string;
};

export type V2StageCommandResponse = {
  command_id: string;
  job_id: string;
  stage_index: number;
  manifest_checksum: string;
  argv: string[];
  created_at: string;
};

export type V2ApprovalResponse = {
  card_id: string;
  interrupt_id: string;
  request_checksum: string;
  stage_index: number;
  summary: string;
  status: string;
  created_at: string;
};

export type V2ResumeCommandResponse = {
  resume_id: string;
  card_id: string;
  decision: string;
  job_id: string;
  stage_index: number;
  command: string[];
};

export type V2AssistantMessageResponse = {
  message_id: string;
  job_id: string;
  role: string;
  content: string;
  correlation_id: string | null;
  created_at: string;
};

export type V2AssistantMessagesListResponse = {
  job_id: string;
  messages: V2AssistantMessageResponse[];
};

export type V2DraftActionResponse = {
  action_id: string;
  job_id: string;
  action_type: string;
  reason: string;
  stage_index: number;
  payload_checksum: string;
  status: string;
  created_at: string;
};

export type V2StageContinuationResponse = {
  continuation_id: string;
  job_id: string;
  from_stage: number;
  to_stage: number;
  sandbox_path: string;
  argv: string[];
  status: string;
  reason: string;
};

export type V2SettingsResponse = {
  azure: {
    profile_id: string;
    provider: string;
    endpoint: { env_ref: string; configured: boolean };
    roles: Record<string, {
      env_ref: string;
      configured: boolean;
      deployment_label: string;
      enabled: boolean;
    }>;
  };
  local_mode: {
    enabled: boolean;
    allowed_source_roots: string[];
    allowed_output_roots: string[];
  };
};

export type V2SetupResponse = {
  setup_id: string;
  run_name: string;
  legacy_app_path: string;
  output_parent_path: string;
  ai_hub_path: string;
  java_homes: Record<string, string>;
  maven_cmd: string;
  proof_level: string;
  skip_endpoint_smoke: boolean;
  migration_flags: Record<string, unknown>;
  setup_checksum: string;
  created_at: string;
};

export type V2PreflightResponse = {
  preflight_id: string;
  setup_id: string;
  all_ready: boolean;
  readiness: Record<string, boolean>;
  warnings: string[];
  errors: string[];
  checked_at: string;
};

export type V2ReadinessResponse = {
  ready: boolean;
  setup_checksum: string;
  preflight_checksum_match: boolean;
  gates: Record<string, boolean>;
};
