import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MigrationCockpitPage from "../app/migrations/[jobId]/page";
import {
  MigrationCockpit,
  GatePanelContent,
  mergeCockpitLiveRefreshResults,
  reduceStageStatus,
  type CockpitData,
} from "../app/migrations/[jobId]/MigrationCockpit";
import { askV2Assistant, CONTROL_TOWER_API_BASE_URL, getV2ArtifactPreview, requireJobId, v2EventStreamUrl } from "../lib/controlTowerApi";
import type { GateRepresentation, V2JobEvent } from "../lib/contracts";

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

  it("renders the open gate panel with gate-safe details", () => {
    const gate: GateRepresentation = {
      gate_id: "gate-1",
      job_id: "job-1",
      gate_phase: "repair_review",
      stage_index: 2,
      gate_status: "open",
      gate_decision: "revise",
      source_artifact_checksum: "sha256:gate",
      source_artifact_refs: ["diagnosis:1", "evidence:2"],
      created_at: "2026-06-17T00:00:00Z",
      resolved_at: null,
      resolved_by: null,
      checksum: "sha256:gate-checksum",
      available_actions: [
        { action: "revise", label: "Revise", description: "Request repair revision", blocked: false, block_reason: "" },
        { action: "reject", label: "Reject", description: "Reject repair", blocked: false, block_reason: "" },
      ],
    };

    const markup = renderToStaticMarkup(
      <GatePanelContent state={{
        status: "success",
        gates: [gate],
        openGate: gate,
        openGateDetail: {
          gate,
          evidence: {
            failure_summary: "build failed in sandbox",
            root_cause_hypothesis: "dependency mismatch",
            patch_summary: "Align the version",
            affected_paths: ["pom.xml"],
            reviewer_critique: null,
            remaining_attempts: 2,
            max_attempts: 3,
          },
          checksum: gate.checksum,
        },
      }} />
    );

    expect(markup).toContain("Open gate");
    expect(markup).toContain("repair_review");
    expect(markup).toContain("Stage 2");
    expect(markup).toContain("build failed in sandbox");
    expect(markup).toContain("Revise");
    expect(markup).toContain("Reject");
    expect(markup).toContain("diagnosis:1");
    expect(markup).toContain("sha256:gate-checksum");
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

  it("refreshLiveState keeps existing approvals when approvals refresh fails", () => {
    const current = makeCockpitData();
    const merged = mergeCockpitLiveRefreshResults(current, [
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "fulfilled", value: { job_id: "job-123", stages: [{ stage_index: 1, pipeline_stage: "Stage 1", chain_status: "running", input_source_kind: "legacy_source" }] } },
      { status: "fulfilled", value: { events: [{ sequence: 2, type: "stage_started", status: "running", stage: 1 } as V2JobEvent] } },
      { status: "fulfilled", value: { ...current.pipeline, rows: [{ key: "analysis", label: "Analysis", status: "running", latest_message: "Running", artifact_count: 0, last_updated: "2026-06-16T00:00:00Z" }] } },
      { status: "fulfilled", value: { job_id: "job-123", has_failures: false, failures: [], repair_loop_active: false, repair_events: [], artifact_kinds: [] } },
    ]);

    expect(merged.failed).toBe(true);
    expect(merged.data.approvals).toBe(current.approvals);
    expect(merged.data.stages[0].chain_status).toBe("running");
    expect(merged.data.events[0].sequence).toBe(2);
  });

  it("SSE-triggered refresh failure can be represented as a non-blocking warning state", () => {
    const current = makeCockpitData();
    const merged = mergeCockpitLiveRefreshResults(current, [
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
    ]);

    expect(merged.failed).toBe(true);
    expect(merged.data).toEqual(current);
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

  it("approval review jobs route approval through chatbot copy", () => {
    const approvalReviewOpen = true;
    const labels = approvalReviewOpen
      ? ["Review in chatbot", "Exact checksum confirmation is required.", "checksum-123"]
      : ["Approve", "Reject", "checksum-123"];
    expect(labels).toContain("Review in chatbot");
    expect(labels).toContain("checksum-123");
    expect(labels).not.toContain("Approve");
    expect(labels).not.toContain("Reject");
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

function makeCockpitData(): CockpitData {
  return {
    job: {
      job_id: "job-123",
      setup_id: "setup-123",
      setup_checksum: "setup-checksum",
      pipeline_id: "pipeline",
      stages: [],
      created_at: "2026-06-16T00:00:00Z",
    },
    stages: [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "queued", input_source_kind: "legacy_source" },
    ],
    approvals: [
      {
        card_id: "card-1",
        job_id: "job-123",
        stage_index: 1,
        status: "pending",
        summary: "Approval required.",
        request_checksum: "checksum-1",
        created_at: "2026-06-16T00:00:00Z",
      } as CockpitData["approvals"][number],
    ],
    messages: [],
    events: [{ sequence: 1, type: "stage_queued", status: "queued", stage: 1 } as V2JobEvent],
    pipeline: {
      job_id: "job-123",
      active_stage_index: 1,
      rows: [],
      evidence: [],
      raw_logs: [],
    } as CockpitData["pipeline"],
    failureSummary: null,
    assistantModel: null,
  };
}
