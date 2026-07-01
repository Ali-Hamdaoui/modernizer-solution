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

export type V2PipelineRow = {
  key: string;
  label: string;
  status: "pending" | "running" | "pass" | "blocked" | "failed" | string;
  latest_message: string;
  artifact_count: number;
  last_updated: string;
};

export type V2PipelineResponse = {
  job_id: string;
  rows: V2PipelineRow[];
  evidence: V2JobEvent[];
  raw_logs: V2JobEvent[];
  active_stage_index: number;
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
  job_id?: string;
  interrupt_id: string;
  request_checksum: string;
  stage_index: number;
  summary: string;
  status: string;
  created_at: string;
  reviewer_critique_id?: string;
  reviewer_decision?: string;
  reviewed_checksum?: string;
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

export type GovernedRepairProposalPartySummary = {
  role?: string;
  model?: string;
  provider?: string;
  status?: string;
  summary?: string;
  proposal_text?: string;
  verdict?: string;
  critique?: string;
  warnings?: string[];
  required_changes?: string[];
  reviewer_required?: boolean;
  manual_review_required?: boolean;
};

export type GovernedRepairProposalEvidenceSummary = {
  failure_classification?: FailureClassificationSummary | null;
  runtime_contract?: RuntimeContractSummary | null;
  reference_delta?: ReferenceDeltaSummary | null;
  migration_intelligence?: MigrationIntelligenceSummary | null;
  migration_intelligence_warnings?: string[];
  evidence_references?: string[];
  evidence_checksums?: string[];
};

export type GovernedRepairProposalGovernanceSummary = {
  human_approval_required?: boolean;
  no_auto_apply?: boolean;
  sandbox_only?: boolean;
  source_mutated?: boolean;
  sandbox_mutated?: boolean;
  stage_resumed?: boolean;
  backend_runner_invoked?: boolean;
  approval_bypass?: boolean;
  reviewer_required?: boolean;
  manual_review_required?: boolean;
  status?: string;
};

export type GovernedRepairTargetFile = {
  relative_path?: string;
  absolute_path?: string;
  before_checksum?: string;
  proposed_checksum?: string;
  repair_family?: string;
};

export type GovernedRepairArtifact = {
  unified_diff?: string;
  patch_path?: string;
  patch_checksum?: string;
};

export type GovernedRepairControlledDemoEvidence = {
  controlled_demo?: boolean;
  controlled_demo_id?: string;
  injected_failure?: boolean;
  sandbox_only?: boolean;
  legacy_unchanged?: boolean;
  target_file?: string;
  original_import_namespace?: string;
  injected_import_namespace?: string;
  proposed_import_namespace?: string;
  injection_before_checksum?: string;
  injection_after_checksum?: string;
  evidence_summary?: string;
  dependency_alignment?: Record<string, unknown>;
};

export type GovernedRepairFailureEvidence = {
  verification_command?: string[];
  cwd?: string;
  exit_code?: number;
  stdout_stderr_tail?: string;
  diagnostic_line?: string;
  failing_file?: string;
  controlled_demo_evidence?: GovernedRepairControlledDemoEvidence;
  dependency_alignment?: Record<string, unknown>;
};

export type GovernedRepairPatchPackage = {
  schema_version?: string;
  command_id?: string;
  job_id?: string;
  run_id?: string;
  sandbox_path?: string;
  sandbox_checksum?: string;
  legacy_checksum?: string;
  repair_family?: string;
  deterministic_rule_id?: string;
  failure_evidence?: GovernedRepairFailureEvidence;
  target_files?: GovernedRepairTargetFile[];
  repair_artifact?: GovernedRepairArtifact;
  containment?: Record<string, unknown>;
  verification_plan?: Record<string, unknown>;
  approval_apply_separate?: boolean;
  blockers?: string[];
  package_checksum?: string;
  evidence_artifact_path?: string;
};

export type GovernedRepairProposalResponse = {
  proposal_id?: string;
  command_id?: string;
  intent?: string;
  status?: string;
  title?: string;
  failure_summary?: string;
  hypothesis?: string;
  patch_summary?: string;
  summary?: string;
  proposed_action?: string;
  proposal_text?: string;
  affected_files?: string[];
  affected_components?: string[];
  affected_paths?: string[];
  proposal_checksum?: string;
  context_pack_checksum?: string;
  sandbox_checksum?: string;
  legacy_checksum?: string;
  approval_checksum?: string | null;
  reviewer_critique_id?: string;
  reviewer_decision?: string;
  repair_family?: string;
  deterministic_rule_id?: string;
  repair_artifact?: GovernedRepairArtifact;
  target_files?: GovernedRepairTargetFile[];
  failure_evidence?: GovernedRepairFailureEvidence;
  containment?: Record<string, unknown>;
  verification_plan?: Record<string, unknown>;
  patch_package?: GovernedRepairPatchPackage;
  proposal_model?: {
    model_invocation_id?: string;
    status?: string;
    source?: string;
    provider?: string;
    role?: string;
  };
  confidence?: string | number;
  risk?: string | number;
  proposer?: GovernedRepairProposalPartySummary | null;
  reviewer?: GovernedRepairProposalPartySummary | null;
  evidence?: GovernedRepairProposalEvidenceSummary | null;
  migration_intelligence?: MigrationIntelligenceSummary | null;
  migration_intelligence_warnings?: string[];
  evidence_references?: string[];
  evidence_checksums?: string[];
  governance?: GovernedRepairProposalGovernanceSummary | null;
  verification_status?: string;
  verification_build_status?: string;
  verification_test_status?: string;
  verification_h2_status?: string;
  verification_artifact_refs?: Record<string, string> | string[];
  verification_failure_classification_ref?: string;
  warnings?: string[];
};

export type V2AssistantAskResponse = {
  job_id: string;
  user_message: V2AssistantMessageResponse;
  assistant_message: V2AssistantMessageResponse;
  model: {
    status: string;
    source: string;
    provider: string;
    role: string;
    failure_reason?: string;
  };
  guardrails: Record<string, boolean>;
  repair_proposal?: GovernedRepairProposalResponse | null;
  repairProposal?: GovernedRepairProposalResponse | null;
  migration_intelligence?: MigrationIntelligenceSummary | null;
  migration_intelligence_warnings?: string[];
};

export type ControlledR6RepairDemoResponse = {
  job_id: string;
  run_id: string;
  command_id: string;
  demo_mode: string;
  repair_family: string;
  sandbox_only: boolean;
  legacy_unchanged: boolean;
  stage2_started: boolean;
  repair_proposal: GovernedRepairProposalResponse;
};

export type V2ReviewerCritiqueResponse = {
  critique_id: string;
  proposal_id: string;
  proposal_type: string;
  proposal_checksum: string;
  context_pack_checksum: string;
  decision: string;
  reasoning: string;
  missing_evidence: string[];
  unsafe_assumptions: string[];
  model_invocation_id: string | null;
  created_at: string;
  reviewer_model?: {
    model_invocation_id?: string;
    status?: string;
    source?: string;
    provider?: string;
    role?: string;
    failure_reason?: string;
    primary_failure_reason?: string;
    redacted_error_summary?: string;
    fallback_used?: boolean;
    schema_validated?: boolean;
  };
};

export type V2ReviewerCritiquesListResponse = {
  command_id: string;
  proposal_id: string;
  critiques: V2ReviewerCritiqueResponse[];
};

export type PrepareRepairApplyContextRequest = {
  proposal_checksum: string;
  context_pack_checksum: string;
  reviewer_critique_id: string;
  proposer_invocation_id: string;
  reviewer_invocation_id: string;
  approval_scope: "sandbox_only";
};

export type RepairApplyContextResponse = {
  context_id: string;
  proposal_id: string;
  command_id: string;
  reviewer_critique_id: string;
  proposer_invocation_id: string;
  reviewer_invocation_id: string;
  reviewer_decision: string;
  proposal_summary: string;
  patch_preview: string;
  patch_preview_checksum: string;
  target_path: string;
  sandbox_reference: string;
  sandbox_checksum: string;
  legacy_checksum: string;
  proposal_checksum: string;
  context_pack_checksum: string;
  evidence_refs: Record<string, string>;
  approval_eligible: boolean;
  blockers: string[];
  approval_scope: string;
  created_at: string;
  sandbox_only: boolean;
  source_mutated: boolean;
  apply_ready: boolean;
  llm_invoked: boolean;
};

export type PrepareRepairApplyContextResponse = {
  repair_review_context: RepairApplyContextResponse;
};

export type RepairApprovalResponse = {
  approval_id: string;
  context_id: string;
  proposal_id: string;
  approval_status: string;
  approval_scope: string;
  approval_note: string;
  approval_checksum: string;
  sandbox_checksum: string;
  legacy_checksum: string;
  created_at: string;
  apply_ready: boolean;
  sandbox_only: boolean;
  source_mutated: boolean;
  llm_invoked: boolean;
};

export type ApproveRepairReviewContextResponse = {
  approval: RepairApprovalResponse;
  repair_review_context: RepairApplyContextResponse | null;
};

export type RepairActionResponse = {
  action_id: string;
  proposal_id: string;
  target_path: string;
  patch_content: string;
  status: string;
  result_summary: string;
  created_at: string;
  verification_status: string;
  verification_build_status: string;
  verification_test_status: string;
  verification_h2_status: string;
  verification_artifact_refs: Record<string, string>;
  verification_failure_classification_ref: string;
  human_approved: boolean;
  sandbox_only: boolean;
  source_mutated: boolean;
  sandbox_mutated: boolean;
  stage_resumed: boolean;
  backend_runner_invoked: boolean;
  llm_invoked: boolean;
  approval_bypass: boolean;
  apply_failure?: {
    failure_stage?: string;
    failure_code?: string;
    human_readable_summary?: string;
    failed_command_id?: string;
    proposal_id?: string;
    context_id?: string;
    approval_id?: string;
    patch_artifact?: string;
    patch_checksum?: string;
    expected_sandbox_checksum?: string;
    actual_sandbox_checksum?: string;
    expected_legacy_checksum?: string;
    actual_legacy_checksum?: string;
    worktree_used?: string;
    strip_level?: number;
    git_executable?: string;
    git_apply_check_stdout?: string;
    git_apply_check_stderr?: string;
    git_apply_check_status?: string;
    patch_apply_status?: string;
    patch_apply_stdout?: string;
    patch_apply_stderr?: string;
    controlled_verification_status?: string;
    controlled_verification_code?: string;
    controlled_verification_summary?: string;
    controlled_target_repaired?: boolean;
    full_maven_verification_status?: string;
    full_maven_failure_classification?: string;
    rollback_attempted?: boolean;
    rollback_succeeded?: boolean;
    rollback_reason?: string;
    rollback_sandbox_checksum?: string;
    pre_existing_failure_detected?: boolean;
    controlled_failure_still_present?: boolean;
    verification_artifacts?: Record<string, string>;
    recommended_next_action?: string;
    assistant_followup_intent?: string;
  };
};

export type ApplyRepairReviewContextResponse = {
  context_id: string;
  approval_id: string;
  repair_action: RepairActionResponse;
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
  // F05 optional revision steering fields
  source_proposal_id?: string | null;
  failed_command_id?: string | null;
  revision_instruction?: string | null;
  context_pack_checksum?: string | null;
  revision_of?: string | null;
  revision_number?: number | null;
  allowed_scope?: string | null;
  // F05 revision binding result when revise_repair_proposal is resolved
  revision_binding?: Record<string, unknown>;
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
  azure_model_ready?: boolean;
  azure_model_failure_reason?: string;
  azure_model_response_snippet?: string;
  azure_model_checked_at?: string;
  readiness: Record<string, boolean>;
  warnings: string[];
  errors: string[];
  checked_at: string;
};

export type V2AzureSmokeResponse = {
  success: boolean;
  provider: string;
  failure_reason: string;
  redacted_summary: string;
  response_snippet: string;
  latency_ms: number;
  checked_at: string;
};

export type V2ReadinessResponse = {
  ready: boolean;
  setup_checksum: string;
  preflight_checksum_match: boolean;
  gates: Record<string, boolean>;
};

export type V2FailureSummaryItem = {
  type: string;
  stage: number | null;
  title: string;
  message: string;
  build_status: string;
  test_status: string;
  final_status: string;
  final_proof_level: string;
  repair_loop_status: string;
  copilot_status: string;
  repair_fallback: string;
  // ── SA4 diagnostic fields ──
  matched_line: string;
  command: string[];
  requested_command: string[];
  build_tool: string;
  module: string;
  main_class: string;
  unit_id: string;
  result_kind: string;
  java_home: string;
  detected_version: string;
  required_minimum: string;
  // ── Result contract diagnostic fields ──
  exit_code?: number | null;
  final_json_found?: boolean | null;
  parse_strategy?: string;
  stdout_tail?: string;
  stderr_tail?: string;
  event_types: string[];
  repair_events: { type: string; message: string }[];
  next_operator_action: string;
  supervision_trace: V2SupervisionTrace;
};

export type V2SupervisionTrace = {
  ai_diagnosis: V2AIDiagnosisResponse | null;
  evidence_used: string[];
  pom_analysis: V2PomAnalysisResponse | null;
  repair_proposal: V2RepairProposalTraceResponse | null;
  reviewer_verdict: V2ReviewerVerdictTraceResponse | null;
  validation_result: V2RepairValidationResponse | null;
};

export type V2AIDiagnosisResponse = {
  diagnosis_id: string;
  command_id: string;
  trigger_event_type: string;
  failure_type: string;
  context_pack_id: string;
  context_pack_checksum: string;
  repair_proposal_id: string;
  model_invocation_id: string;
  redaction_status: string;
  stage_evidence?: V2StageFailureEvidenceResponse | null;
  classification?: V2StageFailureClassificationResponse | null;
  created_at: string;
};

export type V2StageFailureEvidenceResponse = {
  stage_index: number | null;
  stage_name: string;
  source_boot_version: string;
  target_boot_version: string;
  source_java_version: string;
  target_java_version: string;
  input_source_kind: string;
  input_artifact_ref: string;
  output_sandbox_ref: string;
  previous_stage_ref: string;
  downstream_stage_state: {
    next_stage_index: number | null;
    state: string;
    auto_started: boolean;
  } | null;
  evidence_status: string;
  evidence_pack_id: string;
  evidence_pack_checksum: string;
  usable_artifacts: {
    kind: string;
    ref: string;
    checksum: string;
    size_bytes?: number | null;
  }[];
  missing_artifacts: string[];
  repair_enabled: boolean;
  assistant_next_action: string;
  redaction_status: string;
  failure_summary: string;
};

export type V2StageFailureClassificationResponse = {
  stage_index: number | null;
  failure_type: string;
  classification_status: string;
  repair_family_candidate: string;
  repair_enabled: boolean;
  reason: string;
  assistant_next_action: string;
  evidence_pack_id: string;
  evidence_pack_checksum: string;
};

export type V2PomAnalysisResponse = {
  pom_summary_ref: string;
  spring_boot_version: string;
  java_version: string;
  packaging: string;
  candidate_rules: string[];
  created_at: string;
};

export type V2RepairProposalTraceResponse = {
  proposal_id: string;
  source_proposal_id: string;
  command_id: string;
  revision_number: number | null;
  allowed_scope: string;
  proposal_checksum: string;
  status: string;
  created_at: string;
};

export type V2ReviewerVerdictTraceResponse = {
  critique_id: string;
  proposal_id: string;
  proposal_type: string;
  proposal_checksum: string;
  context_pack_checksum: string;
  decision: string;
  reasoning: string;
  missing_evidence: string[];
  unsafe_assumptions: string[];
  created_at: string;
};

export type V2RepairValidationResponse = {
  proposal_id: string;
  binding_checksum?: string;
  patch_gate_status?: string;
  deterministic_rule_id?: string;
  touched_paths?: string[];
  patch_ref?: string;
  patch_status?: string;
  passed?: boolean;
  build_status?: string;
  test_status?: string;
  h2_status?: string;
  artifact_refs?: Record<string, string>;
  rollback_status?: string;
  rollback_reason?: string;
  ledger_ref?: string;
  updated_at?: string;
};

export type V2FailureSummaryResponse = {
  job_id: string;
  has_failures: boolean;
  failures: V2FailureSummaryItem[];
  repair_loop_active: boolean;
  repair_events: { type: string; message: string }[];
  artifact_kinds: string[];
};

export type V2ArtifactPreviewResponse = {
  job_id: string;
  artifact_kind: string;
  source_type?: "artifact" | "file_alias";
  file_alias?: string;
  stage_index?: number;
  exists: boolean;
  preview: string;
  content?: string;
  truncated: boolean;
  content_type: string;
  download_url?: string | null;
  source_ref?: Record<string, string> | null;
  reason?: string | null;
};

// ── F14 — Stage 3 POM Dependency Review types ──────────────────────────

export type PomBaseline = {
  java_version: string;
  spring_boot_version: string;
  spring_boot_version_location: string;
  detected_from: string[];
};

export type PomDependencyFinding = {
  dependency_name: string;
  current_version: string;
  source_location: string;
  bucket: string;
  control_mode: string;
  risk: string;
  recommended_action: string;
  can_apply_now: boolean;
  reason: string;
  evidence_source: string;
};

export type PomDependencyReview = {
  job_id: string;
  stage: number;
  baseline: PomBaseline;
  buckets: Record<string, PomDependencyFinding[]>;
  findings: PomDependencyFinding[];
  evidence_loaded: string[];
  evidence_missing: string[];
  warnings: string[];
  created_at: string;
};

export type PomChangeProposal = {
  proposal_id: string;
  server_validated_plan_preview: Record<string, unknown>;
  risk: string;
  can_apply: boolean;
  warnings: string[];
  applied: boolean;
  control_mode: string;
  created_at: string;
};

export type PomApplyResult = {
  change_id: string;
  status: string;
  operation: string;
  target_desc: string;
  before_version: string;
  after_version: string;
  before_checksum: string;
  after_checksum: string;
  diff_summary: string;
  validation_id: string | null;
  rollback_available: boolean;
  idempotency_key: string | null;
  created_at: string;
  message: string;
};

export type PomValidationFailureDiagnosis = {
  failure_classification: string;
  failed_phase: string;
  exit_code: number;
  log_excerpt: string;
  log_ref: string;
  root_cause: string;
  evidence_sufficient: boolean;
  missing_evidence: string[];
};

export type PomRepairPlan = {
  repair_plan_id: string;
  change_id: string;
  summary: string;
  detailed_steps: string[];
  confidence: string;
  evidence_sources: string[];
  actions_available: string[];
  created_at: string;
};

export type PomValidationRun = {
  validation_id: string;
  change_id: string;
  status: string;
  command: string;
  build_status: string;
  test_status: string;
  exit_code: number | null;
  duration_ms: number | null;
  log_ref: string | null;
  test_log_ref: string | null;
  diagnosis: PomValidationFailureDiagnosis | null;
  repair_plan: PomRepairPlan | null;
  created_at: string;
  completed_at: string | null;
};

export type PomRollbackResult = {
  change_id: string;
  rollback_id: string;
  status: string;
  checksum_restored: boolean;
  validation_triggered: boolean;
  validation_id: string | null;
  created_at: string;
};

export type PomView = {
  job_id: string;
  stage: number;
  exists: boolean;
  content: string;
  truncated: boolean;
  content_type: string;
  redaction_applied: boolean;
  detected_baseline: PomBaseline | null;
  reason?: string | null;
};

export type PomChangeRecordSummary = {
  change_id: string;
  operation: string;
  target_desc: string;
  before_version: string;
  after_version: string;
  before_checksum: string;
  after_checksum: string;
  diff_summary: string;
  status: string;
  validation_id: string | null;
  rollback_id: string | null;
  created_at: string;
};

export type PomProposeRequest = {
  user_request: string;
  idempotency_key?: string;
};

export type PomApplyRequest = {
  proposal_id?: string;
  user_request?: string;
  idempotency_key?: string;
};

// ── F15 Gate types (jobs 101-117) ──────────────────────────────────────

export type GatePhase =
  | "analysis_review"
  | "planning_review"
  | "approval_review"
  | "repair_review"
  | "stage_completion_review";

export type GateDecision =
  | "continue"
  | "reanalyze"
  | "revise"
  | "approve"
  | "reject";

export type GateActorType =
  | "human"
  | "assistant"
  | "api"
  | "system";

export type GateStatus =
  | "open"
  | "resolved"
  | "superseded";

export type GateRepresentation = {
  gate_id: string;
  job_id: string;
  gate_phase: GatePhase;
  stage_index: number;
  gate_status: GateStatus;
  gate_decision: GateDecision;
  source_artifact_checksum: string;
  source_artifact_refs: string[];
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  checksum: string;
  available_actions: AvailableAction[];
};

export type AvailableAction = {
  action: string;
  label: string;
  description: string;
  blocked: boolean;
  block_reason: string;
};

export type GateActionRequest = {
  gate_id: string;
  job_id: string;
  action: GateDecision;
  expected_gate_checksum: string;
  idempotency_key: string;
  decided_by: string;
  actor_type: GateActorType;
  reason?: string;
  // Repair-specific fields (only for repair_review gates):
  proposal_id?: string;
  proposal_checksum?: string;
  context_pack_checksum?: string;
  user_feedback?: string;
  // No sandbox_path, argv, or env fields
};

export type GateActionResult = {
  decision_id: string;
  gate_id: string;
  job_id: string;
  action: GateDecision;
  status: string;
  result_gate_id: string | null;
  result_command_id: string | null;
  result_revision_id: string | null;
  reason: string;
};

export type RepairGateEvidence = {
  failure_summary: string;
  root_cause_hypothesis: string;
  patch_summary: string;
  affected_paths: string[];
  reviewer_critique: {
    critique_id: string;
    decision: string;
    reasoning: string;
  } | null;
  remaining_attempts: number;
  max_attempts: number;
  migration_intelligence?: MigrationIntelligenceSummary;
  migration_intelligence_warnings?: string[];
};

export type GateDetailResponse = {
  gate: GateRepresentation;
  evidence: RepairGateEvidence | null;
  checksum: string;
};

export type MigrationIntelligenceSummary = {
  runtime_contract: RuntimeContractSummary;
  reference_delta: ReferenceDeltaSummary;
  post_transform_failure_classification: FailureClassificationSummary;
};

export type RuntimeContractSummary = {
  status: string;
  detected_risks_count?: number;
  detected_risks?: string[];
  recommended_actions_count?: number;
  recommended_actions?: string[];
  jdk_requirements?: RuntimeRequirementSummary;
  maven_requirements?: RuntimeRequirementSummary;
  private_registry_requirements?: RuntimeRequirementSummary;
  internal_dependencies_count?: number;
  internal_dependencies?: string[];
  warning?: string | null;
};

export type RuntimeRequirementSummary = {
  java_version?: string;
  compiler_release?: string;
  wrapper_present?: boolean;
  settings_files?: string[];
  workflow_setup_java_versions?: string[];
  workflow_maven_versions?: string[];
  hardcoded_jdk_paths?: string[];
  hardcoded_maven_paths?: string[];
  repository_urls?: string[];
  detected_indicators?: string[];
  environment_variables?: string[];
  evidence?: string[];
};

export type ReferenceDeltaSummary = {
  status: string;
  dependency_delta?: {
    added_count?: number;
    removed_count?: number;
    version_changed_count?: number;
  };
  source_delta?: {
    added_imports_count?: number;
    removed_imports_count?: number;
    javax_to_jakarta_count?: number;
  };
  api_migration_indicators?: Record<string, boolean>;
  recommended_capability_packs?: string[];
  suspicious_artifacts_count?: number;
  suspicious_artifacts?: string[];
  warning?: string | null;
};

export type FailureClassificationSummary = {
  status: string;
  categories?: Record<string, number>;
  category_counts?: Record<string, number>;
  failed_unit?: string | null;
  failure_count?: number;
  suggested_actions?: string[];
  test_failure_summary?: {
    suite_count?: number;
    first_failure?: {
      test_class?: string;
      test_method?: string;
      outcome?: string;
      category?: string;
      exception_type?: string;
      symptom?: string;
    };
  };
  warning?: string | null;
};

export type GateListResponse = {
  gates: GateRepresentation[];
};

export type GateActionResponse = {
  result: GateActionResult;
};

export type OpenGateForJobResponse = {
  gate: GateRepresentation | null;
};
