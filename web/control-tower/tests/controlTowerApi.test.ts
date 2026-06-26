import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CONTROL_TOWER_FRONTEND_CLIENT_ID,
  DEFAULT_CONTROL_TOWER_API_BASE_URL,
  allowedStatusCopy,
  createDiagnosticJobPayload,
  createV2JobPayload,
  eventStreamUrl,
  getV2AssistantMessages,
  getV2GateDetail,
  getV2JobGates,
  getV2OpenGate,
  getV2JobApprovals,
  getV2MigrationJobStages,
  getJob,
  getV2FinalReport,
  generateV2FinalReport,
  previewPlanAmendment,
  postJson,
  postV2GateAction,
  requireJobId,
  resolveControlTowerApiBaseUrl,
  resolveReportDownloadUrl
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

  it("defaults new V2 jobs to auto_on_green stage continuation", () => {
    expect(createV2JobPayload("setup-1")).toEqual({
      setup_id: "setup-1",
      policy: {
        continue_after_warning: false,
        enable_runtime_gate: false,
        enable_endpoint_gate: false,
        stage_continuation_policy: "auto_on_green"
      }
    });
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
      getV2AssistantMessages(jobId),
    ]);

    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls).toEqual([
      expect.stringContaining(`/v1/v2/jobs/${jobId}/approvals`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/stages`),
      expect.stringContaining(`/v1/v2/jobs/${jobId}/assistant/messages`),
    ]);
    expect(urls.some((url) => url.includes("undefined"))).toBe(false);
  });

  it("calls F15 gate endpoints with safe request shapes", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/gates/open")) {
        return {
          ok: true,
          json: async () => ({ gate: null }),
        };
      }
      if (url.includes("/gates/")) {
        return {
          ok: true,
          json: async () => ({
            gate: {
              gate_id: "gate-1",
              job_id: "job-1",
              gate_phase: "approval_review",
              stage_index: 2,
              gate_status: "open",
              gate_decision: "continue",
              source_artifact_checksum: "sha256:gate",
              source_artifact_refs: ["analysis:1", "plan:1"],
              created_at: "2026-06-12T00:00:00Z",
              resolved_at: null,
              resolved_by: null,
              checksum: "sha256:gate-checksum",
              available_actions: [],
            },
            evidence: null,
            checksum: "sha256:gate-checksum",
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({ gates: [] }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([
      getV2JobGates("job-1"),
      getV2OpenGate("job-1"),
      getV2GateDetail("job-1", "gate-1"),
      postV2GateAction("job-1", "gate-1", {
        gate_id: "gate-1",
        job_id: "job-1",
        action: "reject",
        expected_gate_checksum: "sha256:gate-checksum",
        idempotency_key: "idem-1",
        decided_by: "human-1",
        actor_type: "human",
        reason: "not ready",
      }),
    ]);

    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls).toEqual(
      expect.arrayContaining([
        expect.stringContaining("/v1/v2/jobs/job-1/gates"),
        expect.stringContaining("/v1/v2/jobs/job-1/gates/open"),
        expect.stringContaining("/v1/v2/jobs/job-1/gates/gate-1"),
      ])
    );
    const actionCall = fetchMock.mock.calls.find(
      (call) => String(call[0]).includes("/actions"),
    ) as [string, RequestInit?] | undefined;
    expect(actionCall).toBeDefined();
    const body = JSON.parse(String((actionCall?.[1] as RequestInit | undefined)?.body ?? "{}"));
    expect(body).toEqual(expect.objectContaining({
      gate_id: "gate-1",
      job_id: "job-1",
      action: "reject",
      expected_gate_checksum: "sha256:gate-checksum",
      idempotency_key: "idem-1",
      decided_by: "human-1",
      actor_type: "human",
      reason: "not ready",
    }));
    expect(JSON.stringify(body)).not.toContain("sandbox_path");
    expect(JSON.stringify(body)).not.toContain("argv");
    expect(JSON.stringify(body)).not.toContain("env");
    expect(JSON.stringify(body)).not.toContain("raw_command");
    expect(JSON.stringify(body)).not.toContain("filesystem");
  });

  it("does not fetch V2 cockpit endpoints when job id is missing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    expect(() => requireJobId(" ")).toThrow(/job id is required/i);
    await expect(getV2JobApprovals("")).rejects.toThrow(/job id is required/i);
    await expect(getV2MigrationJobStages("")).rejects.toThrow(/job id is required/i);
    await expect(getV2AssistantMessages("")).rejects.toThrow(/job id is required/i);

    expect(fetchMock).not.toHaveBeenCalled();
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
    expect("provider_kind" in result.invocations[0]).toBe(false);
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
    expect(serialized).not.toContain("provider_kind");
    expect(serialized).not.toContain("azure-openai");
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

describe("F15 Final Report API contracts", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("report contracts contain no run_report_json, run_report_markdown, run_report_pdf, sandbox_path, run_dir fields", () => {
    const contractFields = {
      job_id: "",
      status: "not_generated",
      eligible: true,
      blockers: [],
      generated_at: null,
      input_checksum: null,
      redacted_summary: "",
      artifacts: [],
    };
    const serialized = JSON.stringify(contractFields);
    expect(serialized).not.toContain("run_report_json");
    expect(serialized).not.toContain("run_report_markdown");
    expect(serialized).not.toContain("run_report_pdf");
    expect(serialized).not.toContain("sandbox_path");
    expect(serialized).not.toContain("run_dir");
  });

  it("getV2FinalReport encodes job IDs properly", async () => {
    const fetchMock = vi.fn<(input: string | URL | Request, init?: RequestInit) => Promise<Response>>(async () => ({
      ok: true,
      json: async () => ({
        job_id: "job-abc",
        status: "not_generated",
        eligible: false,
        blockers: [],
        generated_at: null,
        input_checksum: null,
        redacted_summary: "",
        artifacts: [],
      }),
    } as Response));
    vi.stubGlobal("fetch", fetchMock);

    await getV2FinalReport("job+special");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain("/v1/v2/jobs/job%2Bspecial/report");
    expect(calledUrl).not.toContain("undefined");
  });

  it("generateV2FinalReport encodes job IDs properly", async () => {
    const fetchMock = vi.fn<(input: string | URL | Request, init?: RequestInit) => Promise<Response>>(async () => ({
      ok: true,
      json: async () => ({
        job_id: "job-abc",
        status: "generated",
        eligible: true,
        blockers: [],
        generated_at: "2026-06-20T00:00:00Z",
        input_checksum: "chk-1",
        redacted_summary: "report generated",
        artifacts: [],
      }),
    } as Response));
    vi.stubGlobal("fetch", fetchMock);

    await generateV2FinalReport("job+special");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain("/v1/v2/jobs/job%2Bspecial/report");
    expect(fetchMock.mock.calls[0][1]).toHaveProperty("method", "POST");
    expect(calledUrl).not.toContain("undefined");
  });

  it("download URL must be API-relative (starts with /v1/)", () => {
    expect(resolveReportDownloadUrl("/v1/reports/report-1")).toBe(
      `${resolveControlTowerApiBaseUrl(undefined)}/v1/reports/report-1`
    );
    expect(() => resolveReportDownloadUrl("http://evil.com/report")).toThrow(
      "Invalid report download URL."
    );
    expect(() => resolveReportDownloadUrl("/download/report")).toThrow(
      "Invalid report download URL."
    );
  });
});
