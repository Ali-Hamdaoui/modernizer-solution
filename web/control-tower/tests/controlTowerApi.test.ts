import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CONTROL_TOWER_FRONTEND_CLIENT_ID,
  DEFAULT_CONTROL_TOWER_API_BASE_URL,
  allowedStatusCopy,
  createDiagnosticJobPayload,
  eventStreamUrl,
  getV2AssistantMessages,
  getV2EvidenceBundle,
  getV2DualModelTraces,
  approveV2RepairProposal,
  applyV2RepairPatchToSandbox,
  getV2RepairProposalArtifactPreview,
  getV2RepairProposalArtifacts,
  getV2RepairLifecycle,
  getV2JobApprovals,
  getV2MigrationJobStages,
  getJob,
  materializeV2RepairExecutionPlan,
  materializeV2RepairPatchCandidate,
  previewPlanAmendment,
  postJson,
  rejectV2RepairProposal,
  requireJobId,
  validateV2SandboxRepair,
  resolveControlTowerApiBaseUrl
} from "../lib/controlTowerApi";
import { applyPublicEvent, latestAppliedSequence, shouldRefetchJobProjection } from "../lib/eventReplay";

describe("M2-01 frontend diagnostic contracts", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("submits only allowed create-job fields", () => {
    const payload = createDiagnosticJobPayload({
      runnerProfileKey: "runner-default@2026.06",
      pipelineKey: "pipeline-default@2026.06",
      legacySourceRootId: "source-root",
      legacySourceRelativePath: "src",
      outputRootId: "output-root",
      outputRelativePath: "out"
    });

    expect(payload).toEqual({
      runner_profile_id: "runner-default",
      runner_profile_version: "2026.06",
      pipeline_id: "pipeline-default",
      pipeline_version: "2026.06",
      legacy_source_root_id: "source-root",
      legacy_source_relative_path: "src",
      output_root_id: "output-root",
      output_relative_path: "out",
      target_proof_level: "ANALYZED",
      enabled_gates: [],
      policy: {
        continue_after_warning: false,
        enable_runtime_gate: false,
        enable_endpoint_gate: false
      }
    });
    expect(JSON.stringify(payload)).not.toContain("actor");
    expect(JSON.stringify(payload)).not.toContain("command");
    expect(JSON.stringify(payload)).not.toContain("executable");
  });

  it("uses only approved diagnostic wording", () => {
    const copy = Object.values(allowedStatusCopy).join(" ");
    expect(copy).toContain("Foundation diagnostic job created");
    expect(copy).toContain("Command queued");
    expect(copy).not.toContain("Migration completed");
    expect(copy).not.toContain("Build verified");
    expect(copy).not.toContain("Spring Boot upgraded");
    expect(copy).not.toContain("Proof achieved");
  });

  it("opens event replay from the last applied sequence", () => {
    expect(eventStreamUrl("job-1", 7)).toContain("/v1/jobs/job-1/events/stream?after_sequence=7");
  });

  it("uses canonical 127.0.0.1 api base url", () => {
    expect(DEFAULT_CONTROL_TOWER_API_BASE_URL).toBe("http://127.0.0.1:8000");
    expect(resolveControlTowerApiBaseUrl(undefined)).toBe("http://127.0.0.1:8000");
    expect(() => resolveControlTowerApiBaseUrl("http://localhost:8000")).toThrow(/127\.0\.0\.1/);
  });

  it("keeps initial job projection fetch non-cached", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      headers: {
        get: (name: string) => (name.toLowerCase() === "etag" ? '"job-job-1-v1"' : null)
      },
      json: async () => ({
        job: {
          job_id: "job-1",
          version: 1,
          state: "CREATED",
          created_at: "2026-06-10T00:00:00Z",
          updated_at: "2026-06-10T00:00:00Z"
        },
        active_command: null
      })
    }));
    vi.stubGlobal("fetch", fetchMock);

    await getJob("job-1");

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/v1/jobs/job-1"), {
      cache: "no-store"
    });
  });

  it("mutation helper sends required client header and json content type", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true })
    }));
    vi.stubGlobal("fetch", fetchMock);

    await postJson("/v1/jobs", { value: "ok" }, { "Idempotency-Key": "key-1" });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/jobs"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-Control-Tower-Client": CONTROL_TOWER_FRONTEND_CLIENT_ID,
          "Idempotency-Key": "key-1"
        })
      })
    );
  });

  it("calls V2 cockpit endpoints with the actual migration route job id", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => {
        if (url.includes("/assistant/messages")) {
          return { job_id: "429a9bb2154b4be7a99a32867780d744", messages: [] };
        }
        if (url.includes("/dual-model-traces")) {
          return { job_id: "429a9bb2154b4be7a99a32867780d744", run_id: "v2-demo-s2", trace_count: 0, latest_model1_trace: null, latest_model2_trace: null, traces: [], artifact_refs: [], read_only: true };
        }
        if (url.includes("/repair-lifecycle")) {
          return { job_id: "429a9bb2154b4be7a99a32867780d744", repair_proposals: [], read_only: true };
        }
        if (url.includes("/repair-proposals/") && url.includes("/artifacts/")) {
          return {
            proposal_id: "proposal-1",
            artifact_name: "repair_proposal.md",
            kind: "markdown",
            content: "# Repair proposal",
            truncated: false,
            size_bytes: 18,
            read_only: true,
          };
        }
        if (url.includes("/repair-proposals/") && url.endsWith("/artifacts")) {
          return {
            proposal_id: "proposal-1",
            artifacts: [
              {
                proposal_id: "proposal-1",
                artifact_name: "repair_proposal.md",
                relative_path: "ai_supervision/repair_proposals/proposal-1/repair_proposal.md",
                kind: "markdown",
                exists: true,
                size_bytes: 18,
                read_only: true,
              },
            ],
            read_only: true,
          };
        }
        if (url.includes("/approvals")) {
          return { approvals: [] };
        }
        return { job_id: "429a9bb2154b4be7a99a32867780d744", stages: [] };
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const jobId = "429a9bb2154b4be7a99a32867780d744";
    await Promise.all([
      getV2JobApprovals(jobId),
      getV2MigrationJobStages(jobId),
      getV2EvidenceBundle(jobId),
      getV2DualModelTraces(jobId),
      getV2RepairLifecycle(jobId),
      getV2RepairProposalArtifacts(jobId, "proposal-1"),
      getV2RepairProposalArtifactPreview(jobId, "proposal-1", "repair_proposal.md"),
      getV2AssistantMessages(jobId),
    ]);

    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([
      expect.stringContaining(`/v1/v2/jobs/${jobId}/approvals`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/stages`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/evidence-bundle`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/dual-model-traces`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/repair-lifecycle`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/repair-proposals/proposal-1/artifacts`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/repair-proposals/proposal-1/artifacts/repair_proposal.md`),
      expect.stringContaining(`/v1/v2/jobs/${jobId}/assistant/messages`),
    ]);
    expect(urls.some((url) => url.includes("undefined"))).toBe(false);
  });

  it("does not fetch V2 cockpit endpoints when job id is missing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    expect(() => requireJobId(" ")).toThrow(/job id is required/i);
    await expect(getV2JobApprovals("")).rejects.toThrow(/job id is required/i);
    await expect(getV2MigrationJobStages("")).rejects.toThrow(/job id is required/i);
    await expect(getV2EvidenceBundle("")).rejects.toThrow(/job id is required/i);
    await expect(getV2DualModelTraces("")).rejects.toThrow(/job id is required/i);
    await expect(getV2RepairLifecycle("")).rejects.toThrow(/job id is required/i);
    await expect(getV2RepairProposalArtifacts("", "proposal-1")).rejects.toThrow(/job id is required/i);
    await expect(getV2RepairProposalArtifactPreview("", "proposal-1", "repair_proposal.md")).rejects.toThrow(/job id is required/i);
    await expect(getV2AssistantMessages("")).rejects.toThrow(/job id is required/i);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("approve repair proposal sends expected checksum only to approval endpoint", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        job_id: "job-123",
        run_id: "v2-demo-s2",
        proposal_id: "proposal-1",
        proposal: {},
        proposal_status: "approved",
        proposal_checksum: "chk-123",
        reviewer_gate_status: "accepted",
        approval_result: "approved",
        approval_state: {
          state: "approved",
          checksum: "chk-123",
          approved_at: "2026-06-19T00:00:00Z",
          read_only_until_apply: true,
          no_auto_apply: true,
        },
        latest_reviewer_decision: "accept",
        approval_decision: {},
        applied: false,
        read_only: true,
        source_mutated: false,
        stage_resumed: false,
        sandbox_only: true,
        validation_started: false,
        rollback_performed: false,
      })
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await approveV2RepairProposal("job-123", "proposal-1", "chk-123", "architect");

    expect(fetchMock).toHaveBeenCalledWith(
      `${DEFAULT_CONTROL_TOWER_API_BASE_URL}/v1/v2/repair-proposals/proposal-1/approval`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          decision: "approve",
          approval_checksum: "chk-123",
          note: "Approved by architect",
        }),
      })
    );
    expect(result.applied).toBe(false);
    expect(result.read_only).toBe(true);
    expect(result.source_mutated).toBe(false);
    expect(result.stage_resumed).toBe(false);
    expect(result.sandbox_only).toBe(true);
    expect(result.validation_started).toBe(false);
    expect(result.approval_state?.state).toBe("approved");
  });

  it("reject repair proposal sends reject request without execution endpoint", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        job_id: "job-123",
        run_id: "v2-demo-s2",
        proposal_id: "proposal-1",
        proposal: {},
        proposal_status: "rejected",
        proposal_checksum: "chk-123",
        reviewer_gate_status: "accepted",
        approval_result: "rejected",
        approval_state: {
          state: "rejected",
          checksum: "chk-123",
          rejected_at: "2026-06-19T00:00:00Z",
          read_only_until_apply: true,
          no_auto_apply: true,
        },
        latest_reviewer_decision: "accept",
        approval_decision: {},
        applied: false,
        read_only: true,
        source_mutated: false,
        stage_resumed: false,
        sandbox_only: true,
        validation_started: false,
        rollback_performed: false,
      })
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await rejectV2RepairProposal("job-123", "proposal-1", "Needs human review", "architect");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${DEFAULT_CONTROL_TOWER_API_BASE_URL}/v1/v2/repair-proposals/proposal-1/approval`);
    expect(String(url)).not.toContain("apply");
    expect(String(url)).not.toContain("materialize");
    expect(String(url)).not.toContain("validate");
    expect(JSON.parse(String(init.body))).toEqual({
      decision: "reject",
      approval_checksum: "reject",
      note: "Operator: architect - Needs human review",
    });
    expect(result.applied).toBe(false);
    expect(result.read_only).toBe(true);
    expect(result.source_mutated).toBe(false);
    expect(result.stage_resumed).toBe(false);
    expect(result.sandbox_only).toBe(true);
    expect(result.validation_started).toBe(false);
    expect(result.approval_state?.state).toBe("rejected");
  });

  it("materialize repair execution plan calls read-write execution-plan endpoint only", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        proposal_id: "proposal-1",
        run_id: "v2-demo-s2",
        approval_checksum: "chk-1",
        failure_type: "invalid_maven_wildcard_version",
        root_cause: "root",
        affected_paths: ["pom.xml"],
        planned_operations: [{ kind: "update_property" }],
        validation_commands: ["mvn -q -DskipTests package"],
        rollback_plan: { restore: ["pom.xml"] },
        source_artifact_refs: { proposal: "ai_supervision/repair_proposals/proposal-1/repair_proposal.json" },
        approved: true,
        human_approved: true,
        requires_sandbox_apply: true,
        requires_validation: true,
        applied: false,
        read_only: true,
        source_mutated: false,
        stage_resumed: false,
      })
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await materializeV2RepairExecutionPlan("job-123", "proposal-1");

    expect(fetchMock).toHaveBeenCalledWith(
      `${DEFAULT_CONTROL_TOWER_API_BASE_URL}/v1/v2/migration-jobs/job-123/repair-proposals/proposal-1/materialize-execution-plan`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      })
    );
    expect(result.applied).toBe(false);
    expect(result.read_only).toBe(true);
    expect(result.requires_sandbox_apply).toBe(true);
    expect(result.requires_validation).toBe(true);
  });

  it("materialize patch candidate calls read-write patch-candidate endpoint only", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        proposal_id: "proposal-1",
        run_id: "v2-demo-s2",
        approval_checksum: "chk-1",
        execution_plan_ref: "ai_supervision/repair_proposals/proposal-1/repair_execution_plan.json",
        failure_type: "invalid_maven_wildcard_version",
        root_cause: "root",
        affected_paths: ["pom.xml"],
        planned_operations: [{ kind: "update_property" }],
        patch_strategy: "bounded_maven_property_update",
        patch_operations: [{ kind: "update_property", path: "pom.xml" }],
        validation_commands: ["mvn -q -DskipTests package"],
        rollback_plan: { restore: ["pom.xml"] },
        requires_sandbox_apply: true,
        requires_validation: true,
        human_approved: true,
        applied: false,
        read_only: true,
        no_source_mutation: true,
        source_mutated: false,
        stage_resumed: false,
      })
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await materializeV2RepairPatchCandidate("job-123", "proposal-1");

    expect(fetchMock).toHaveBeenCalledWith(
      `${DEFAULT_CONTROL_TOWER_API_BASE_URL}/v1/v2/migration-jobs/job-123/repair-proposals/proposal-1/materialize-patch-candidate`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      })
    );
    expect(result.applied).toBe(false);
    expect(result.read_only).toBe(true);
    expect(result.no_source_mutation).toBe(true);
  });

  it("apply repair patch to sandbox calls sandbox apply endpoint only", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        proposal_id: "proposal-1",
        run_id: "v2-demo-s2",
        target_workspace: "sandbox",
        modified_files: ["pom.xml"],
        operations_applied: [{ kind: "update_property" }],
        backup_refs: { "pom.xml": "ai_supervision/repair_proposals/proposal-1/backups/pom.xml.before-repair" },
        applied: true,
        validation_required: true,
        validation_started: false,
        sandbox_only: true,
        source_mutated: false,
        read_only: true,
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await applyV2RepairPatchToSandbox("job-123", "proposal-1");

    expect(fetchMock).toHaveBeenCalledWith(
      `${DEFAULT_CONTROL_TOWER_API_BASE_URL}/v1/v2/migration-jobs/job-123/repair-proposals/proposal-1/apply-to-sandbox`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      })
    );
    expect(result.applied).toBe(true);
    expect(result.sandbox_only).toBe(true);
    expect(result.source_mutated).toBe(false);
    expect(result.validation_started).toBe(false);
  });

  it("validate sandbox repair calls validation endpoint only", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        proposal_id: "proposal-1",
        run_id: "v2-demo-s2",
        target_workspace: "sandbox",
        commands_run: ["mvn -q test"],
        exit_code: 0,
        status: "passed",
        stdout_excerpt: "ok",
        stderr_excerpt: "",
        validation_started_at: "2026-06-19T00:00:00Z",
        validation_finished_at: "2026-06-19T00:01:00Z",
        rollback_performed: false,
        rollback_reason: null,
        rollback_error: null,
        sandbox_only: true,
        source_mutated: false,
        stage_resumed: false,
        read_only: true,
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await validateV2SandboxRepair("job-123", "proposal-1");

    expect(fetchMock).toHaveBeenCalledWith(
      `${DEFAULT_CONTROL_TOWER_API_BASE_URL}/v1/v2/migration-jobs/job-123/repair-proposals/proposal-1/validate-sandbox-repair`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      })
    );
    expect(result.status).toBe("passed");
    expect(result.rollback_performed).toBe(false);
    expect(result.sandbox_only).toBe(true);
    expect(result.source_mutated).toBe(false);
    expect(result.stage_resumed).toBe(false);
  });

  it("preview helper uses preview endpoint and safe preview contract", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        job_id: "job-1",
        source_kind: "manual",
        title: "Safe preview",
        summary: "Planning only",
        payload_checksum: "chk-1",
        change_count: 1,
        affected_stage_indexes: [1],
        change_types: ["documentation"],
        redacted_summary: {
          source_kind: "manual",
          title: "Safe preview",
          summary: "Planning only",
          change_count: 1,
          affected_stage_indexes: [1],
          change_types: ["documentation"],
          non_authoritative: true
        },
        validation_status: "PASS",
        warning_codes: [],
        preview_persisted: false,
        preview_applied: false
      })
    }));
    vi.stubGlobal("fetch", fetchMock);

    const body = await previewPlanAmendment("job-1", {
      title: "Safe preview",
      summary: "Planning only",
      source_kind: "manual",
      notes: ["safe"],
      changes: [
        {
          stage_index: 1,
          change_type: "documentation",
          description: "Clarify plan text"
        }
      ]
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/jobs/job-1/plan-amendments/preview"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-Control-Tower-Client": CONTROL_TOWER_FRONTEND_CLIENT_ID
        })
      })
    );
    expect(body.validation_status).toBe("PASS");
    expect(body.preview_persisted).toBe(false);
    expect(body.preview_applied).toBe(false);
    expect(body.redacted_summary.non_authoritative).toBe(true);
  });

  // ── V1-18D model activity normalization ────────────────────────────

  it("normalizes backend { model_invocations } into { invocations }", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        model_invocations: [
          {
            invocation_id: "inv-001",
            profile_id: "profile-azure",
            provider_kind: "azure-openai",
            model_name: "gpt-4o",
            prompt_tokens: 150,
            completion_tokens: 42,
            total_tokens: 192,
            redacted_summary: "Analyzed stage 1 output",
            created_at: "2026-06-12T00:00:00Z",
          },
        ],
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { getModelActivity } = await import("../lib/controlTowerApi");
    const result = await getModelActivity("job-1");

    expect(result).toEqual({
      job_id: "job-1",
      invocations: [
        {
          invocation_id: "inv-001",
          job_id: "job-1",
          profile_id: "profile-azure",
          provider_kind: "azure-openai",
          model_name: "gpt-4o",
          prompt_tokens: 150,
          completion_tokens: 42,
          total_tokens: 192,
          redacted_summary: "Analyzed stage 1 output",
          actor_type: null,
          actor_id: null,
          correlation_id: null,
          causation_id: null,
          created_at: "2026-06-12T00:00:00Z",
        },
      ],
    });
  });

  it("preserves { invocations } key if backend already uses it", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        invocations: [
          {
            invocation_id: "inv-002",
            job_id: "job-2",
            provider_kind: "openai",
            model_name: "gpt-4o-mini",
            prompt_tokens: 80,
            completion_tokens: 20,
            total_tokens: 100,
            redacted_summary: "Patch review",
            created_at: "2026-06-12T01:00:00Z",
          },
        ],
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { getModelActivity } = await import("../lib/controlTowerApi");
    const result = await getModelActivity("job-2");

    expect(result.invocations).toHaveLength(1);
    expect(result.invocations[0].invocation_id).toBe("inv-002");
    expect(result.invocations[0].job_id).toBe("job-2");
  });

  it("handles empty { model_invocations: [] } gracefully", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ model_invocations: [] }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { getModelActivity } = await import("../lib/controlTowerApi");
    const result = await getModelActivity("job-3");

    expect(result).toEqual({ job_id: "job-3", invocations: [] });
  });

  it("handles empty { invocations: [] } gracefully", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ invocations: [] }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { getModelActivity } = await import("../lib/controlTowerApi");
    const result = await getModelActivity("job-4");

    expect(result).toEqual({ job_id: "job-4", invocations: [] });
  });

  it("normalized response exposes no raw prompts, secrets, or deployment IDs", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        model_invocations: [
          {
            invocation_id: "inv-003",
            provider_kind: "azure-openai",
            model_name: "gpt-4o",
            prompt_tokens: 99,
            completion_tokens: 10,
            total_tokens: 109,
            redacted_summary: "Analyzed output",
            created_at: "2026-06-12T02:00:00Z",
          },
        ],
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { getModelActivity } = await import("../lib/controlTowerApi");
    const result = await getModelActivity("job-5");
    const serialized = JSON.stringify(result);

    expect(result.invocations).toHaveLength(1);
    // Raw prompt content must not leak
    expect(serialized).not.toContain("raw prompt");
    expect(serialized).not.toContain("secret");
    expect(serialized).not.toContain("deployment-id");
    expect(serialized).not.toContain("my-secret");
  });

  it("applies public events idempotently and refetches state-changing projections", () => {
    const event = {
      actor_id: "tester",
      actor_type: "user",
      causation_id: null,
      correlation_id: null,
      created_at: "2026-06-10T00:00:00Z",
      event_id: "event-1",
      event_type: "command_queued",
      job_id: "job-1",
      payload: {},
      payload_checksum: "abc",
      sequence: 2
    };
    const applied = applyPublicEvent({ events: [], lastAppliedSequence: 1 }, event);
    const duplicate = applyPublicEvent(applied, event);

    expect(applied.events).toHaveLength(1);
    expect(applied.lastAppliedSequence).toBe(2);
    expect(duplicate).toBe(applied);
    expect(latestAppliedSequence(applied.events)).toBe(2);
    expect(shouldRefetchJobProjection(event)).toBe(true);
  });
});
