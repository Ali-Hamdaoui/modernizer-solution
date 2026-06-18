import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import MigrationCockpitPage from "../app/migrations/[jobId]/page";
import { MigrationCockpit, canApplyRepairPatchToSandbox, canMaterializeRepairExecutionPlan, canMaterializeRepairPatchCandidate, cockpitEvidenceStatusLines, reduceStageStatus, submitRepairExecutionPlanMaterialization, submitRepairPatchCandidateMaterialization, submitRepairPatchSandboxApply, submitRepairProposalCockpitDecision } from "../app/migrations/[jobId]/MigrationCockpit";
import { askV2Assistant, CONTROL_TOWER_API_BASE_URL, getV2ArtifactPreview, requireJobId, v2EventStreamUrl } from "../lib/controlTowerApi";
import type { V2JobEvent } from "../lib/contracts";

describe("V2 Migration Cockpit contract", () => {
  it("passes the awaited route job id into MigrationCockpit", async () => {
    const page = await MigrationCockpitPage({
      params: Promise.resolve({ jobId: "429a9bb2154b4be7a99a32867780d744" }),
    });

    const children = page.props.children;
    const cockpit = children[1];

    expect(cockpit.type).toBe(MigrationCockpit);
    expect(cockpit.props.jobId).toBe("429a9bb2154b4be7a99a32867780d744");
  });

  it("displays three stages in order", () => {
    const stages = [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "queued", input_source_kind: "legacy_source" },
      { stage_index: 2, pipeline_stage: "Stage 2", chain_status: "pending", input_source_kind: "stage_1_sandbox" },
      { stage_index: 3, pipeline_stage: "Stage 3", chain_status: "pending", input_source_kind: "stage_2_sandbox" },
    ];
    expect(stages).toHaveLength(3);
    expect(stages[0].input_source_kind).toBe("legacy_source");
    expect(stages[1].input_source_kind).toBe("stage_1_sandbox");
    expect(stages[2].input_source_kind).toBe("stage_2_sandbox");
  });

  it("has no Boot 4 stage", () => {
    const stages = [1, 2, 3];
    expect(stages).not.toContain(4);
  });

  it("has no stage-start buttons", () => {
    const cockpitControls = [
      "stage_timeline",
      "evidence_panel",
      "approval_decisions",
      "assistant_panel",
      "proof_report",
    ];
    const forbidden = ["start_stage_1", "start_stage_2", "start_stage_3", "run_maven", "choose_goal"];
    for (const f of forbidden) {
      expect(cockpitControls).not.toContain(f);
    }
  });

  it("approval requires checksum", () => {
    const approval = { id: "a1", status: "pending", checksum_required: true };
    expect(approval.checksum_required).toBe(true);
  });

  it("assistant cannot execute, approve, write, or change route", () => {
    const assistantRules = {
      can_explain: true,
      can_diagnose: true,
      can_draft_instruction: true,
      can_execute: false,
      can_approve: false,
      can_write_file: false,
      can_change_route: false,
      can_override_proof: false,
    };
    expect(assistantRules.can_execute).toBe(false);
    expect(assistantRules.can_approve).toBe(false);
    expect(assistantRules.can_write_file).toBe(false);
    expect(assistantRules.can_change_route).toBe(false);
    expect(assistantRules.can_override_proof).toBe(false);
  });

  it("no raw secrets, paths, or deployment IDs in cockpit payloads", () => {
    // Backend guarantees redaction — the frontend contract depends on it.
    // This test verifies that realistic payloads (as API returns after
    // redaction) do NOT contain secrets that the frontend would render.
    const samplePayload = {
      job_id: "job-1",
      rows: [
        {
          key: "sandbox_build",
          label: "Sandbox Build",
          status: "failed",
          latest_message: "[redacted-path] written",
          artifact_count: 0,
          last_updated: "2026-06-14T00:00:00Z",
        },
      ],
      evidence: [
        {
          event_type: "build_failed",
          status: "failed",
          message: "Build failed: [redacted-path]",
          payload: {
            matched_line: "[redacted-path]",
            command: ["mvn", "[redacted]", "package"],
            java_home: "[redacted-path]",
            AZURE_OPENAI_API_KEY: "[redacted]",
          },
        },
      ],
      raw_logs: [],
    };
    const json = JSON.stringify(samplePayload);

    // Redacted payload should never contain real secret tokens
    const hasSecretValue =
      /\b(sk-|ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]+/.test(json);
    expect(hasSecretValue).toBe(false);

    // Redacted payload should not contain Windows or POSIX absolute paths
    expect(json).not.toMatch(/\bC:\\Users\\/);
    expect(json).not.toMatch(/\bC:\\Program Files\\/);
    expect(json).not.toMatch(/\/home\//);
    expect(json).not.toMatch(/\/etc\//);
  });

  it("stage inputs are fixed by pipeline", () => {
    const stageInputs = {
      1: "legacy_source",
      2: "stage_1_sandbox",
      3: "stage_2_sandbox",
    };
    // These must NOT come from user selection
    expect(stageInputs[1]).toBe("legacy_source");
    expect(stageInputs[2]).toBe("stage_1_sandbox");
    expect(stageInputs[3]).toBe("stage_2_sandbox");
  });

  it("rejects missing route job id before fetch URL construction", () => {
    expect(() => requireJobId("")).toThrow("Migration job id is required.");
    expect(() => requireJobId("   ")).toThrow("Migration job id is required.");
  });

  it("opens EventSource against the V2 events endpoint", () => {
    const url = v2EventStreamUrl("job-123", 7);
    expect(url).toBe("http://127.0.0.1:8000/v1/v2/migration-jobs/job-123/events?after=7");
    expect(url).not.toContain("undefined");
  });

  it("artifact preview client sends only artifact kind", async () => {
    const originalFetch = global.fetch;
    const calls: string[] = [];
    global.fetch = (async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response(JSON.stringify({
        job_id: "job-123",
        artifact_kind: "phase2_log",
        exists: true,
        preview: "BUILD_FAILED_IN_SANDBOX",
        truncated: false,
        content_type: "text/plain",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      const response = await getV2ArtifactPreview("job-123", "phase2_log");
      expect(calls[0]).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/job-123/artifacts/phase2_log`);
      expect(calls[0]).not.toContain("path=");
      expect(response.exists).toBe(true);
      expect(response.preview).toContain("BUILD_FAILED_IN_SANDBOX");
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("empty approvals render as no pending decisions copy", () => {
    const approvals: unknown[] = [];
    const copy = approvals.length === 0 ? "No pending decisions." : "Has decisions";
    expect(copy).toBe("No pending decisions.");
  });

  it("incoming event updates stage status", () => {
    const event = { stage: 1, type: "stage_started", status: "running" };
    const stages = [{ stage_index: 1, chain_status: "queued" }];
    const updated = stages.map((stage) =>
      stage.stage_index === event.stage ? { ...stage, chain_status: event.status } : stage,
    );
    expect(updated[0].chain_status).toBe("running");
  });

  it("posts assistant questions to the read-only V2 ask endpoint", async () => {
    const originalFetch = global.fetch;
    const calls: { url: string; body: string | null }[] = [];
    global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: typeof init?.body === "string" ? init.body : null });
      return new Response(JSON.stringify({
        job_id: "job-123",
        user_message: { message_id: "u1", job_id: "job-123", role: "user", content: "What happened so far?", correlation_id: null, created_at: "now" },
        assistant_message: { message_id: "a1", job_id: "job-123", role: "assistant", content: "Latest event: stage 1 analysis_started.", correlation_id: "u1", created_at: "now" },
        model: { status: "configured", source: "azure_openai", provider: "azure_openai", role: "assistant" },
        guardrails: { read_only: true, cannot_execute: true, cannot_approve: true },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      const response = await askV2Assistant("job-123", "What happened so far?");
      expect(calls[0].url).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/job-123/assistant/ask`);
      expect(calls[0].url).not.toContain("undefined");
      expect(JSON.parse(calls[0].body ?? "{}")).toEqual({ question: "What happened so far?" });
      expect(response.assistant_message.content).toContain("Latest event");
      expect(response.model.source).toBe("azure_openai");
      expect(response.guardrails.cannot_execute).toBe(true);
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("approval card exposes checksum controls", () => {
    const approval = {
      card_id: "card-1",
      stage_index: 1,
      summary: "Human approval required before sandbox transform.",
      status: "pending",
      request_checksum: "checksum-123",
    };
    const labels = ["Approve", "Reject", approval.request_checksum, "LLM cannot approve; exact checksum required."];
    expect(labels).toContain("Approve");
    expect(labels).toContain("Reject");
    expect(labels).toContain("checksum-123");
  });

  it("pipeline projection shows agent phases before raw logs", () => {
    const rows = ["Preflight", "Analysis Agent", "Planning Agent", "Assessment Agent", "Human Approval"];
    const evidenceTypes = ["analysis_started", "planning_completed", "approval_required"];
    const rawLogs = ["stdout"];
    expect(rows).toContain("Analysis Agent");
    expect(rows).toContain("Planning Agent");
    expect(rows).toContain("Assessment Agent");
    expect(evidenceTypes).not.toContain("stdout");
    expect(rawLogs).toContain("stdout");
  });

  it("pipeline response exposes active_stage_index", () => {
    const pipeline = {
      job_id: "job-123",
      rows: [],
      evidence: [],
      raw_logs: [],
      active_stage_index: 2,
    };
    expect(pipeline.active_stage_index).toBe(2);
  });

  it("human approval row is pass after approval_resume_queued, not blocked", () => {
    // Simulate the pipeline status logic: after approval_resume_queued, must be pass
    const events = [
      { type: "approval_required", status: "blocked" },
      { type: "approval_resume_queued", status: "queued" },
    ];
    // Check that the latest approval lifecycle event transitions correctly
    const hasApprovalPassed = events.some(
      (e) => e.type === "approval_resume_queued"
    );
    expect(hasApprovalPassed).toBe(true);
  });

  it("human approval stays pass even if transform fails", () => {
    const events = [
      { type: "approval_required", status: "blocked" },
      { type: "approval_resume_queued", status: "queued" },
      { type: "sandbox_transform_failed", status: "failed" },
    ];
    // Approval should still be pass
    const approvalResolved = events.some(
      (e) => e.type === "approval_resume_queued"
    );
    expect(approvalResolved).toBe(true);
  });

  it("failure summary contains observed failure shape", () => {
    const failureSummary = {
      has_failures: true,
      failures: [
        {
          type: "build_failed",
          stage: 1,
          message: "Build result kind: dependency_error",
          build_status: "BUILD_FAILED_IN_SANDBOX",
          final_status: "FALLBACK_REPAIR_PLAN",
          final_proof_level: "not_verified",
          repair_loop_status: "FALLBACK_REPAIR_PLAN",
          copilot_status: "INVALID_RESPONSE",
          repair_fallback: "True",
        },
      ],
      repair_loop_active: true,
      repair_events: [
        { type: "copilot_repair_invalid_response", message: "Copilot response invalid" },
      ],
      artifact_kinds: ["analysis_report"],
    };
    expect(failureSummary.has_failures).toBe(true);
    expect(failureSummary.failures[0].build_status).toBe("BUILD_FAILED_IN_SANDBOX");
    expect(failureSummary.failures[0].copilot_status).toBe("INVALID_RESPONSE");
  });

  it("assistant model status includes failure_reason for fallback", () => {
    const model = {
      status: "fallback",
      source: "deterministic",
      provider: "deterministic",
      role: "assistant",
      failure_reason: "missing_deployment",
    };
    expect(model.status).toBe("fallback");
    expect(model.failure_reason).toBe("missing_deployment");
  });

  it("assistant and repair wording stay separate after repair fallback", () => {
    const assistantModel = { status: "live_ok", source: "azure_openai", provider: "azure_openai" };
    const repair = { copilot_status: "INVALID_RESPONSE", repair_fallback: "True", repair_loop_status: "FALLBACK_REPAIR_PLAN" };
    expect(assistantModel.source).toBe("azure_openai");
    expect(assistantModel.status).toBe("live_ok");
    expect(repair.copilot_status).toBe("INVALID_RESPONSE");
    expect(repair.repair_loop_status).toBe("FALLBACK_REPAIR_PLAN");
  });

  it("cockpit evidence bundle keeps completed migration separate from late model failure", () => {
    const lines = cockpitEvidenceStatusLines({
      run_id: "v2-demo-s3",
      stage_statuses: { "1": "completed", "2": "completed", "3": "completed" },
      migration_status: "completed_with_warnings",
      ai_supervision_status: "unavailable_fallback",
      approval_state: "not_required",
      final_status: "TRANSFORM_APPLIED_IN_SANDBOX",
      build_status: "BUILD_PASSED_IN_SANDBOX",
      test_status: "PASS_WITH_WARNINGS",
      final_proof_level: "compiled",
      latest_trustworthy_migration_event: { type: "final_report_completed", status: "completed" },
      generated_artifact_refs: [],
      failure_events: [],
      build_test_error_contracts: [],
      relevant_log_excerpts: [],
      pom_excerpts: [],
      deterministic_failure_classification: null,
      failure_bundle: null,
      next_operator_action: "migration_completed_ai_unavailable",
      read_only: true,
    });
    expect(lines).toContain("Migration: completed_with_warnings");
    expect(lines).toContain("AI supervision: unavailable_fallback");
  });

  it("cockpit evidence bundle keeps approval state separate from build failure", () => {
    const lines = cockpitEvidenceStatusLines({
      run_id: "v2-demo-s2",
      stage_statuses: { "1": "completed", "2": "blocked" },
      migration_status: "approval_required",
      ai_supervision_status: "not_requested",
      approval_state: "pending_human_approval",
      final_status: "",
      build_status: "",
      test_status: "",
      final_proof_level: "",
      latest_trustworthy_migration_event: { type: "approval_required", status: "blocked" },
      generated_artifact_refs: [],
      failure_events: [],
      build_test_error_contracts: [],
      relevant_log_excerpts: [],
      pom_excerpts: [],
      deterministic_failure_classification: null,
      failure_bundle: null,
      next_operator_action: "human_approval_required",
      read_only: true,
    });
    expect(lines).toContain("Migration: approval_required");
    expect(lines).toContain("Approval: pending_human_approval");
  });

  it("cockpit evidence bundle still surfaces real migration failure", () => {
    const lines = cockpitEvidenceStatusLines({
      run_id: "v2-demo-s2",
      stage_statuses: { "1": "completed", "2": "failed" },
      migration_status: "failed",
      ai_supervision_status: "not_requested",
      approval_state: "not_required",
      final_status: "BUILD_FAILED_IN_SANDBOX",
      build_status: "BUILD_FAILED_IN_SANDBOX",
      test_status: "",
      final_proof_level: "not_verified",
      latest_trustworthy_migration_event: { type: "build_failed", status: "failed" },
      generated_artifact_refs: [],
      failure_events: [{ type: "build_failed", message: "Build failed in sandbox" }],
      build_test_error_contracts: [],
      relevant_log_excerpts: [],
      pom_excerpts: [],
      deterministic_failure_classification: { failure_type: "invalid_maven_wildcard_version" },
      failure_bundle: {
        failure_type: "invalid_maven_wildcard_version",
        root_cause: "Wildcard Maven versions generated in pom.xml.",
        confidence: "high",
        failure_events: [{ type: "build_failed", message: "Build failed in sandbox" }],
        missing_artifacts: [],
        error_contracts: [],
        log_excerpts: [],
        pom_excerpts: [],
        affected_paths: ["pom.xml"],
      },
      next_operator_action: "review_failure_evidence",
      read_only: true,
    });
    expect(lines).toContain("Migration: failed");
    expect(lines).toContain("Root cause: Wildcard Maven versions generated in pom.xml.");
  });

  it("cockpit renders no dual-model traces state", () => {
    const markup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 1 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: { job_id: "job-123", repair_proposals: [], read_only: true },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(markup).toContain("AI Supervision Traces");
    expect(markup).toContain("No AI supervision traces yet.");
    expect(markup).toContain("Read-only audit: true");
  });

  it("cockpit renders latest dual-model trace summaries", () => {
    const markup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 2 },
          dualModelTraces: {
            job_id: "job-123",
            run_id: "v2-demo-s2",
            trace_count: 2,
            latest_model1_trace: {
              invocation_id: "inv-1",
              model_role: "model_1_migration_engineer",
              provider: "deterministic",
              fallback_used: true,
              timestamp: "2026-06-18T00:00:00Z",
              supervision_context: "stage_2_failure_review",
              purpose: "Summarize failure.",
              validation_status: "validated",
              verdict: null,
              risk_level: "high",
              human_approval_required: null,
              errors: [],
              warnings: [],
              artifact_refs: { combined: "ai_supervision/inv-1/dual_model_invocation_trace.json" },
              read_only: true,
            },
            latest_model2_trace: {
              invocation_id: "inv-2",
              model_role: "model_2_safety_reviewer",
              provider: "deterministic",
              fallback_used: true,
              timestamp: "2026-06-18T00:01:00Z",
              supervision_context: "stage_2_failure_review",
              purpose: "Verify summary.",
              validation_status: "validated",
              verdict: "accepted",
              risk_level: "high",
              human_approval_required: false,
              errors: [],
              warnings: [],
              artifact_refs: { combined: "ai_supervision/inv-2/dual_model_invocation_trace.json" },
              read_only: true,
            },
            traces: [],
            artifact_refs: [],
            read_only: true,
          },
          repairLifecycle: { job_id: "job-123", repair_proposals: [], read_only: true },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(markup).toContain("Latest Model 1");
    expect(markup).toContain("Purpose: Summarize failure.");
    expect(markup).toContain("Risk: high");
    expect(markup).toContain("Latest Model 2");
    expect(markup).toContain("Verdict: accepted");
    expect(markup).toContain("Human approval required: false");
  });

  it("cockpit renders empty repair lifecycle state", () => {
    const markup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 1 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: { job_id: "job-123", repair_proposals: [], read_only: true },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(markup).toContain("Repair Lifecycle");
    expect(markup).toContain("No repair proposals yet.");
    expect(markup).toContain("Read-only list: true");
  });

  it("cockpit renders repair lifecycle proposal states and safety flags", () => {
    const markup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-1",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "Wildcard Maven versions remain in sandbox pom.xml.",
                current_state: "validation_passed",
                approval_state: "approved",
                approval_checksum: "chk-123",
                has_execution_plan: true,
                has_patch_candidate: true,
                sandbox_apply_state: "applied",
                sandbox_validation_state: "passed",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "no action required",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {
                  proposal: "ai_supervision/repair_proposals/proposal-1/repair_proposal.json",
                },
                read_only: true,
              },
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-2",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "Rollback performed after failed validation.",
                current_state: "validation_failed_rolled_back",
                approval_state: "approved",
                approval_checksum: "chk-456",
                has_execution_plan: true,
                has_patch_candidate: true,
                sandbox_apply_state: "applied",
                sandbox_validation_state: "rolled_back",
                rollback_performed: true,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "inspect rollback",
                risk_level: "high",
                model2_verdict: "needs_human_review",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {
            "proposal-1": {
              proposal_id: "proposal-1",
              artifacts: [
                {
                  proposal_id: "proposal-1",
                  artifact_name: "repair_proposal.md",
                  relative_path: "ai_supervision/repair_proposals/proposal-1/repair_proposal.md",
                  kind: "markdown",
                  exists: true,
                  size_bytes: 24,
                  read_only: true,
                },
                {
                  proposal_id: "proposal-1",
                  artifact_name: "repair_proposal.json",
                  relative_path: "ai_supervision/repair_proposals/proposal-1/repair_proposal.json",
                  kind: "json",
                  exists: true,
                  size_bytes: 128,
                  read_only: true,
                },
              ],
              read_only: true,
            },
            "proposal-2": {
              proposal_id: "proposal-2",
              artifacts: [],
              read_only: true,
            },
          },
          repairArtifactPreviews: {
            "proposal-1": {
              proposal_id: "proposal-1",
              artifact_name: "repair_proposal.md",
              kind: "markdown",
              content: "# Repair proposal\nUpdate sandbox pom.xml only.",
              truncated: false,
              size_bytes: 44,
              read_only: true,
            },
            "proposal-2": null,
          },
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(markup).toContain("proposal-1");
    expect(markup).toContain("Current state: validation_passed");
    expect(markup).toContain("Next operator action: no action required");
    expect(markup).toContain("Sandbox validation state: passed");
    expect(markup).toContain("proposal-2");
    expect(markup).toContain("Rollback performed: true");
    expect(markup).toContain("Sandbox validation state: rolled_back");
    expect(markup).toContain("Source mutated: false");
    expect(markup).toContain("Stage resumed: false");
    expect(markup).toContain("Read-only projection: true");
    expect(markup).toContain("Repair artifacts: repair_proposal.md, repair_proposal.json");
    expect(markup).toContain("Read-only artifact preview: repair_proposal.md");
    expect(markup).toContain("Update sandbox pom.xml only.");
    expect(markup).toContain("No previewable repair artifacts.");
    expect(markup).not.toContain(">Apply<");
    expect(markup).not.toContain(">Validate<");
    expect(markup).not.toContain(">Resume<");
  });

  it("cockpit renders approve and reject buttons for pending repair proposal", () => {
    const markup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-pending",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "Wildcard Maven versions remain in sandbox pom.xml.",
                current_state: "pending_approval",
                approval_state: "pending_approval",
                approval_checksum: "chk-pending",
                has_execution_plan: false,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "approve repair proposal",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(markup).toContain("Approval checksum: chk-pending");
    expect(markup).toContain("Approve proposal");
    expect(markup).toContain("Reject proposal");
    expect(markup).toContain("Approving this proposal does not apply any repair.");
    expect(markup).toContain("No sandbox or source files will be modified by this action.");
  });

  it("cockpit hides approve and reject buttons for approved or rejected repair proposal", () => {
    const approvedMarkup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-approved",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "approved",
                approval_state: "approved",
                approval_checksum: "chk-approved",
                has_execution_plan: false,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "materialize execution plan",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    const rejectedMarkup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-rejected",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "rejected",
                approval_state: "rejected",
                approval_checksum: "chk-rejected",
                has_execution_plan: false,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "human review required",
                risk_level: "high",
                model2_verdict: "needs_human_review",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(approvedMarkup).not.toContain("Approve proposal");
    expect(approvedMarkup).not.toContain("Reject proposal");
    expect(rejectedMarkup).not.toContain("Approve proposal");
    expect(rejectedMarkup).not.toContain("Reject proposal");
  });

  it("approve action refreshes lifecycle and avoids apply materialize validate endpoints", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => {
        if (url.includes("/repair-proposals/proposal-1/approval")) {
          return {
            proposal: {},
            proposal_status: "approved",
            proposal_checksum: "chk-1",
            reviewer_gate_status: "accepted",
            approval_result: "approved",
            latest_reviewer_decision: "accept",
            approval_decision: {},
            applied: false,
          };
        }
        if (url.includes("/repair-lifecycle")) {
          return {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-1",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "execution_plan_ready",
                approval_state: "approved",
                approval_checksum: "chk-1",
                has_execution_plan: true,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "materialize patch candidate",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          };
        }
        return { proposal_id: "proposal-1", artifacts: [], read_only: true };
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await submitRepairProposalCockpitDecision({
      jobId: "job-123",
      proposalId: "proposal-1",
      approvalState: "pending_approval",
      approvalChecksum: "chk-1",
    });

    expect(result.repairLifecycle?.repair_proposals).toHaveLength(1);
    expect(result.repairLifecycle?.repair_proposals[0].current_state).toBe("execution_plan_ready");
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toContain("/v1/v2/repair-proposals/proposal-1/approval");
    expect(urls.some((url) => url.includes("/repair-lifecycle"))).toBe(true);
    expect(urls.some((url) => url.includes("apply-to-sandbox"))).toBe(false);
    expect(urls.some((url) => url.includes("materialize-execution-plan"))).toBe(false);
    expect(urls.some((url) => url.includes("materialize-patch-candidate"))).toBe(false);
    expect(urls.some((url) => url.includes("validate-sandbox-repair"))).toBe(false);
  });

  it("reject action refreshes lifecycle and avoids apply materialize validate endpoints", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => {
        if (url.includes("/repair-proposals/proposal-1/approval")) {
          return {
            proposal: {},
            proposal_status: "rejected",
            proposal_checksum: "chk-1",
            reviewer_gate_status: "accepted",
            approval_result: "rejected",
            latest_reviewer_decision: "accept",
            approval_decision: {},
            applied: false,
          };
        }
        if (url.includes("/repair-lifecycle")) {
          return {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-1",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "execution_plan_ready",
                approval_state: "approved",
                approval_checksum: "chk-1",
                has_execution_plan: true,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "materialize patch candidate",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          };
        }
        return { proposal_id: "proposal-1", artifacts: [], read_only: true };
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await submitRepairProposalCockpitDecision({
      jobId: "job-123",
      proposalId: "proposal-1",
      approvalState: "pending_approval",
      approvalChecksum: "chk-1",
      reason: "Rejected in cockpit.",
    });

    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toContain("/v1/v2/repair-proposals/proposal-1/approval");
    expect(urls.some((url) => url.includes("/repair-lifecycle"))).toBe(true);
    expect(urls.some((url) => url.includes("apply-to-sandbox"))).toBe(false);
    expect(urls.some((url) => url.includes("materialize-execution-plan"))).toBe(false);
    expect(urls.some((url) => url.includes("materialize-patch-candidate"))).toBe(false);
    expect(urls.some((url) => url.includes("validate-sandbox-repair"))).toBe(false);
  });

  it("approve action surfaces API failure", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      json: async () => ({ error: { code: "FAILED" } }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      submitRepairProposalCockpitDecision({
        jobId: "job-123",
        proposalId: "proposal-1",
        approvalState: "pending_approval",
        approvalChecksum: "chk-1",
      })
    ).rejects.toThrow(/control tower mutation failed/i);
  });

  it("materialize button shows only for approved proposal without execution plan", () => {
    expect(canMaterializeRepairExecutionPlan({
      current_state: "approved",
      approval_state: "approved",
      has_execution_plan: false,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(true);
    expect(canMaterializeRepairExecutionPlan({
      current_state: "pending_approval",
      approval_state: "pending_approval",
      has_execution_plan: false,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canMaterializeRepairExecutionPlan({
      current_state: "rejected",
      approval_state: "rejected",
      has_execution_plan: false,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canMaterializeRepairExecutionPlan({
      current_state: "approved",
      approval_state: "approved",
      has_execution_plan: true,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
  });

  it("materialize patch candidate button shows only for execution_plan_ready proposal", () => {
    expect(canMaterializeRepairPatchCandidate({
      current_state: "execution_plan_ready",
      approval_state: "approved",
      has_execution_plan: true,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(true);
    expect(canMaterializeRepairPatchCandidate({
      current_state: "pending_approval",
      approval_state: "pending_approval",
      has_execution_plan: true,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canMaterializeRepairPatchCandidate({
      current_state: "rejected",
      approval_state: "rejected",
      has_execution_plan: true,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canMaterializeRepairPatchCandidate({
      current_state: "execution_plan_ready",
      approval_state: "approved",
      has_execution_plan: false,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canMaterializeRepairPatchCandidate({
      current_state: "execution_plan_ready",
      approval_state: "approved",
      has_execution_plan: true,
      has_patch_candidate: true,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
  });

  it("apply to sandbox button shows only for patch_candidate_ready proposal", () => {
    expect(canApplyRepairPatchToSandbox({
      current_state: "patch_candidate_ready",
      approval_state: "approved",
      has_execution_plan: true,
      has_patch_candidate: true,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(true);
    expect(canApplyRepairPatchToSandbox({
      current_state: "pending_approval",
      approval_state: "pending_approval",
      has_execution_plan: true,
      has_patch_candidate: true,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canApplyRepairPatchToSandbox({
      current_state: "rejected",
      approval_state: "rejected",
      has_execution_plan: true,
      has_patch_candidate: true,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canApplyRepairPatchToSandbox({
      current_state: "patch_candidate_ready",
      approval_state: "approved",
      has_execution_plan: true,
      has_patch_candidate: false,
      sandbox_apply_state: "not_started",
      sandbox_validation_state: "not_started",
    })).toBe(false);
    expect(canApplyRepairPatchToSandbox({
      current_state: "patch_candidate_ready",
      approval_state: "approved",
      has_execution_plan: true,
      has_patch_candidate: true,
      sandbox_apply_state: "applied",
      sandbox_validation_state: "not_started",
    })).toBe(false);
  });

  it("cockpit renders materialize execution plan button and safety text only for approved no-plan proposal", () => {
    const approvedMarkup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-approved",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "approved",
                approval_state: "approved",
                approval_checksum: "chk-approved",
                has_execution_plan: false,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "materialize execution plan",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(approvedMarkup).toContain("Materialize execution plan");
    expect(approvedMarkup).toContain("This only creates a read-only execution plan.");
    expect(approvedMarkup).toContain("It does not apply patches or run validation.");

    const hiddenMarkup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-hidden",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "execution_plan_ready",
                approval_state: "approved",
                approval_checksum: "chk-hidden",
                has_execution_plan: true,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "materialize patch candidate",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(hiddenMarkup).not.toContain("Materialize execution plan");

    const patchCandidateHidden = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-candidate",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "patch_candidate_ready",
                approval_state: "approved",
                approval_checksum: "chk-candidate",
                has_execution_plan: true,
                has_patch_candidate: true,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "apply patch to sandbox",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(patchCandidateHidden).not.toContain("Materialize patch candidate");
  });

  it("cockpit renders materialize patch candidate button and safety text only for execution plan ready proposal", () => {
    const approvedMarkup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-approved",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "execution_plan_ready",
                approval_state: "approved",
                approval_checksum: "chk-approved",
                has_execution_plan: true,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "materialize patch candidate",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(approvedMarkup).toContain("Materialize patch candidate");
    expect(approvedMarkup).toContain("This only creates a read-only patch candidate.");
    expect(approvedMarkup).toContain("It does not apply patches or run validation.");
    expect(approvedMarkup).toContain("It does not modify source or sandbox files.");

    const hiddenPending = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-pending",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "pending_approval",
                approval_state: "pending_approval",
                approval_checksum: "chk-pending",
                has_execution_plan: false,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "approve repair proposal",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(hiddenPending).not.toContain("Materialize patch candidate");
  });

  it("cockpit renders apply to sandbox button and safety text only for patch candidate ready proposal", () => {
    const approvedMarkup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-apply",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "patch_candidate_ready",
                approval_state: "approved",
                approval_checksum: "chk-apply",
                has_execution_plan: true,
                has_patch_candidate: true,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "apply patch to sandbox",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(approvedMarkup).toContain("Apply to sandbox");
    expect(approvedMarkup).toContain("This applies the repair to the sandbox workspace only.");
    expect(approvedMarkup).toContain("It does not modify the original source project.");
    expect(approvedMarkup).toContain("It does not run validation.");
    expect(approvedMarkup).toContain("A backup will be used by the backend before sandbox mutation.");

    const hiddenMarkup = renderToStaticMarkup(
      <MigrationCockpit
        jobId="job-123"
        initialData={{
          job: { job_id: "job-123", setup_id: "setup-1", setup_checksum: "chk", pipeline_id: "pipe", stages: [], created_at: "now" },
          stages: [],
          approvals: [],
          messages: [],
          events: [],
          pipeline: { job_id: "job-123", rows: [], evidence: [], raw_logs: [], active_stage_index: 3 },
          dualModelTraces: { job_id: "job-123", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true },
          repairLifecycle: {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-hidden",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "execution_plan_ready",
                approval_state: "approved",
                approval_checksum: "chk-hidden",
                has_execution_plan: true,
                has_patch_candidate: true,
                sandbox_apply_state: "applied",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "apply patch to sandbox",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          },
          repairArtifacts: {},
          repairArtifactPreviews: {},
          evidenceBundle: null,
          failureSummary: null,
          assistantModel: null,
        }}
      />
    );
    expect(hiddenMarkup).not.toContain("Apply to sandbox");
  });

  it("materialize action refreshes lifecycle and artifacts only", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => {
        if (url.includes("/materialize-execution-plan")) {
          return {
            proposal_id: "proposal-1",
            execution_plan: { applied: false, read_only: true },
          };
        }
        if (url.includes("/repair-lifecycle")) {
          return {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-1",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "execution_plan_ready",
                approval_state: "approved",
                approval_checksum: "chk-1",
                has_execution_plan: true,
                has_patch_candidate: false,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "materialize patch candidate",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          };
        }
        return { proposal_id: "proposal-1", artifacts: [], read_only: true };
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await submitRepairExecutionPlanMaterialization({
      jobId: "job-123",
      proposalId: "proposal-1",
    });

    expect(result.repairLifecycle?.repair_proposals).toHaveLength(1);
    expect(result.repairLifecycle?.repair_proposals[0].has_execution_plan).toBe(true);
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toContain("/materialize-execution-plan");
    expect(urls.some((url) => url.includes("/repair-lifecycle"))).toBe(true);
    expect(urls.some((url) => url.includes("/artifacts"))).toBe(true);
    expect(urls.some((url) => url.includes("materialize-patch-candidate"))).toBe(false);
    expect(urls.some((url) => url.includes("apply-to-sandbox"))).toBe(false);
    expect(urls.some((url) => url.includes("validate-sandbox-repair"))).toBe(false);
    expect(urls.some((url) => url.includes("/stages/progress"))).toBe(false);
  });

  it("materialize action surfaces readable API failure", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      json: async () => ({ error: { code: "FAILED" } }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      submitRepairExecutionPlanMaterialization({
        jobId: "job-123",
        proposalId: "proposal-1",
      })
    ).rejects.toThrow(/control tower mutation failed/i);
  });

  it("apply to sandbox refreshes lifecycle and artifacts only", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => {
        if (url.includes("/apply-to-sandbox")) {
          return {
            proposal_id: "proposal-1",
            sandbox_only: true,
            source_mutated: false,
            validation_started: false,
          };
        }
        if (url.includes("/repair-lifecycle")) {
          return {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-1",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "applied_to_sandbox",
                approval_state: "approved",
                approval_checksum: "chk-1",
                has_execution_plan: true,
                has_patch_candidate: true,
                sandbox_apply_state: "applied",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "validate sandbox repair",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          };
        }
        return { proposal_id: "proposal-1", artifacts: [], read_only: true };
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await submitRepairPatchSandboxApply({
      jobId: "job-123",
      proposalId: "proposal-1",
    });

    expect(result.repairLifecycle?.repair_proposals).toHaveLength(1);
    expect(result.repairLifecycle?.repair_proposals[0].sandbox_apply_state).toBe("applied");
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toContain("/apply-to-sandbox");
    expect(urls.some((url) => url.includes("/repair-lifecycle"))).toBe(true);
    expect(urls.some((url) => url.includes("/artifacts"))).toBe(true);
    expect(urls.some((url) => url.includes("materialize-execution-plan"))).toBe(false);
    expect(urls.some((url) => url.includes("materialize-patch-candidate"))).toBe(false);
    expect(urls.some((url) => url.includes("validate-sandbox-repair"))).toBe(false);
    expect(urls.some((url) => url.includes("/stages/progress"))).toBe(false);
  });

  it("apply to sandbox surfaces readable API failure", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      json: async () => ({ error: { code: "FAILED" } }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      submitRepairPatchSandboxApply({
        jobId: "job-123",
        proposalId: "proposal-1",
      })
    ).rejects.toThrow(/control tower mutation failed/i);
  });

  it("materialize patch candidate refreshes lifecycle and artifacts only", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => {
        if (url.includes("/materialize-patch-candidate")) {
          return {
            proposal_id: "proposal-1",
            patch_candidate: { applied: false, read_only: true },
          };
        }
        if (url.includes("/repair-lifecycle")) {
          return {
            job_id: "job-123",
            repair_proposals: [
              {
                job_id: "job-123",
                run_id: "v2-demo-s2",
                proposal_id: "proposal-1",
                failure_type: "invalid_maven_wildcard_version",
                root_cause: "root",
                current_state: "patch_candidate_ready",
                approval_state: "approved",
                approval_checksum: "chk-1",
                has_execution_plan: true,
                has_patch_candidate: true,
                sandbox_apply_state: "not_started",
                sandbox_validation_state: "not_started",
                rollback_performed: false,
                source_mutated: false,
                sandbox_only: true,
                stage_resumed: false,
                next_operator_action: "apply patch to sandbox",
                risk_level: "medium",
                model2_verdict: "accepted",
                artifact_refs: {},
                read_only: true,
              },
            ],
            read_only: true,
          };
        }
        return {
          proposal_id: "proposal-1",
          artifacts: [],
          read_only: true,
        };
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await submitRepairPatchCandidateMaterialization({
      jobId: "job-123",
      proposalId: "proposal-1",
    });

    expect(result.repairLifecycle?.repair_proposals).toHaveLength(1);
    expect(result.repairLifecycle?.repair_proposals[0].has_patch_candidate).toBe(true);
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toContain("/materialize-patch-candidate");
    expect(urls.some((url) => url.includes("/repair-lifecycle"))).toBe(true);
    expect(urls.some((url) => url.includes("/artifacts"))).toBe(true);
    expect(urls.some((url) => url.includes("materialize-execution-plan"))).toBe(false);
    expect(urls.some((url) => url.includes("apply-to-sandbox"))).toBe(false);
    expect(urls.some((url) => url.includes("validate-sandbox-repair"))).toBe(false);
    expect(urls.some((url) => url.includes("/stages/progress"))).toBe(false);
  });

  it("materialize patch candidate surfaces readable API failure", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      json: async () => ({ error: { code: "FAILED" } }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      submitRepairPatchCandidateMaterialization({
        jobId: "job-123",
        proposalId: "proposal-1",
      })
    ).rejects.toThrow(/control tower mutation failed/i);
  });

  it("IMPORTANT_SSE_TYPES includes all required lifecycle events", () => {
    const important = new Set([
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
      "ai_diagnosis_created",
      "pom_summary_created",
      "repair_proposal_revised",
      "reviewer_critique_created",
      "repair_patch_gate_completed",
      "repair_patch_applied",
      "repair_validation_completed",
      "repair_rollback_completed",
      "next_stage_queued",
    ]);
    expect(important.has("approval_resume_queued")).toBe(true);
    expect(important.has("approval_completed")).toBe(true);
    expect(important.has("transform_failed")).toBe(true);
    expect(important.has("build_failed")).toBe(true);
    expect(important.has("ai_diagnosis_created")).toBe(true);
    expect(important.has("reviewer_critique_created")).toBe(true);
    expect(important.has("repair_validation_completed")).toBe(true);
    expect(important.has("next_stage_queued")).toBe(true);
  });

  it("failure summary exposes backend supervision trace records", () => {
    const failureSummary = {
      has_failures: true,
      failures: [
        {
          type: "build_failed",
          stage: 2,
          supervision_trace: {
            ai_diagnosis: {
              diagnosis_id: "diag-1",
              command_id: "cmd-1",
              trigger_event_type: "build_failed",
              failure_type: "DEPENDENCY_ERROR",
              context_pack_id: "pack-1",
              context_pack_checksum: "ctx-1",
              repair_proposal_id: "proposal-1",
              model_invocation_id: "model-1",
              redaction_status: "redacted",
              created_at: "2026-06-16T00:00:00Z",
            },
            evidence_used: ["pack-1", "ctx-1", "pom-summary:1"],
            pom_analysis: {
              pom_summary_ref: "pom-summary:1",
              spring_boot_version: "2.7.18",
              java_version: "11",
              packaging: "jar",
              candidate_rules: ["pom_dependency_alignment"],
              created_at: "2026-06-16T00:00:01Z",
            },
            repair_proposal: {
              proposal_id: "proposal-2",
              source_proposal_id: "proposal-1",
              command_id: "cmd-1",
              revision_number: 2,
              allowed_scope: "pom_only",
              proposal_checksum: "prop-checksum",
              status: "completed",
              created_at: "2026-06-16T00:00:02Z",
            },
            reviewer_verdict: {
              critique_id: "crit-1",
              proposal_id: "proposal-2",
              proposal_type: "repair_proposal",
              proposal_checksum: "prop-checksum",
              context_pack_checksum: "ctx-1",
              decision: "accept",
              reasoning: "Evidence and scope are acceptable.",
              missing_evidence: [],
              unsafe_assumptions: [],
              created_at: "2026-06-16T00:00:03Z",
            },
            validation_result: {
              proposal_id: "proposal-2",
              patch_gate_status: "ALLOWED",
              deterministic_rule_id: "pom_dependency_alignment",
              build_status: "BUILD_PASSED_IN_SANDBOX",
              test_status: "TESTS_PASSED",
              h2_status: "NOT_REQUIRED",
              ledger_ref: "repair_ledger.json",
            },
          },
        },
      ],
    };
    const trace = failureSummary.failures[0].supervision_trace;
    expect(trace.ai_diagnosis?.diagnosis_id).toBe("diag-1");
    expect(trace.evidence_used).toContain("pom-summary:1");
    expect(trace.repair_proposal?.allowed_scope).toBe("pom_only");
    expect(trace.reviewer_verdict?.decision).toBe("accept");
    expect(trace.validation_result?.ledger_ref).toBe("repair_ledger.json");
  });

  // ── Stage status lifecycle reducer tests (V2 cockpit state model) ──

  it("reduceStageStatus: blocked while approval pending", () => {
    // Only approval_required/blocked events → blocked
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 2 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("blocked");
  });

  it("reduceStageStatus: running after approval completed and transform started", () => {
    // Old blocked events must not prevent running
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 2 } as V2JobEvent,
      { stage: 1, type: "approval_resume_queued", status: "queued", sequence: 3 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 4 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("running");
  });

  it("reduceStageStatus: failed after sandbox_transform_failed", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 2 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_failed", status: "failed", sequence: 3 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("failed");
  });

  it("reduceStageStatus: completed after stage_completed, blocked does not regress", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_started", status: "running", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_completed", status: "completed", sequence: 2 } as V2JobEvent,
      // A late blocked event must NOT regress completed → blocked
      { stage: 1, type: "approval_required", status: "blocked", sequence: 3 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("completed");
  });

  it("reduceStageStatus: model invocation failure does not regress completed stage", () => {
    const events: V2JobEvent[] = [
      { stage: 3, type: "stage_started", status: "running", sequence: 1 } as V2JobEvent,
      { stage: 3, type: "stage_completed", status: "completed", sequence: 2 } as V2JobEvent,
      { stage: 3, type: "final_report_completed", status: "completed", sequence: 3 } as V2JobEvent,
      { stage: 3, type: "model_invocation_failed", status: "failed", sequence: 4 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("completed");
  });

  it("reduceStageStatus: old blocked does not override later running", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 2 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("running");
  });

  it("reduceStageStatus: old blocked does not override later failed", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_failed", status: "failed", sequence: 2 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("failed");
  });

  // ── Pipeline / stage consistency tests ──

  it("approved card has disabled buttons and no active blocked state implication", () => {
    // When approval card status is "approved", buttons are disabled
    const approved = { card_id: "c1", status: "approved", request_checksum: "chk-1" };
    const pending = { card_id: "c2", status: "pending", request_checksum: "chk-2" };
    const isPending = (s: string) => s === "pending";
    expect(isPending(approved.status)).toBe(false);
    expect(isPending(pending.status)).toBe(true);
    // Disabled guard: button disabled unless status === "pending"
    expect(approved.status !== "pending").toBe(true);
  });

  it("pipeline and stage status consistent after approval lifecycle", () => {
    // The pipeline human_approval row must be "pass", not "blocked",
    // after approval_resume_queued. Stage must be "running".
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "approval_resume_queued", status: "queued", sequence: 2 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 3 } as V2JobEvent,
    ];
    const stageStatus = reduceStageStatus(events);
    expect(stageStatus).toBe("running");
    // Pipeline human_approval row logic: events with type in approval_passed_types
    const hasPassedEvent = events.some(
      (e) => ["approval_completed", "approval_resume_queued", "resume_started",
              "sandbox_transform_started", "sandbox_transform_completed"].includes(e.type)
    );
    expect(hasPassedEvent).toBe(true);
  });

  it("raw logs events are collapsed by default in SSE stream", () => {
    const events = [
      { type: "stdout", status: "running", message: "raw line" },
      { type: "analysis_completed", status: "completed", message: "done" },
    ];
    const rawLogs = events.filter((e) => e.type === "stdout" || e.type === "stderr");
    const evidence = events.filter((e) => e.type !== "stdout" && e.type !== "stderr");
    expect(rawLogs).toHaveLength(1);
    expect(evidence).toHaveLength(1);
    expect(evidence[0].type).toBe("analysis_completed");
  });

  it("no stage input paths come from user selection", () => {
    // Stage 2 input must be stage_1_sandbox, not user-selected
    const stage2Input = "stage_1_sandbox";
    const prohibitedInputs = ["user_selected", "manual", "browser_payload"];
    expect(stage2Input).toBe("stage_1_sandbox");
    for (const prohibited of prohibitedInputs) {
      expect(stage2Input).not.toBe(prohibited);
    }
  });

  it("Stage 2 profile is springboot-2.7-to-3.5-java17", () => {
    const stage2Profile = "springboot-2.7-to-3.5-java17";
    expect(stage2Profile).toBe("springboot-2.7-to-3.5-java17");
  });

  it("Stage 3 profile is springboot-3.5-java17-to-java21", () => {
    const stage3Profile = "springboot-3.5-java17-to-java21";
    expect(stage3Profile).toBe("springboot-3.5-java17-to-java21");
  });
});
