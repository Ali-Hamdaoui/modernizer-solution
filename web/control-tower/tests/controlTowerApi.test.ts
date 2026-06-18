import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CONTROL_TOWER_API_BASE_URL,
  CONTROL_TOWER_FRONTEND_CLIENT_ID,
  DEFAULT_CONTROL_TOWER_API_BASE_URL,
  allowedStatusCopy,
  createDiagnosticJobPayload,
  eventStreamUrl,
  generateV2FinalReport,
  getV2AssistantMessages,
  getV2FinalReport,
  getV2JobApprovals,
  getV2MigrationJobStages,
  getJob,
  previewPlanAmendment,
  postJson,
  requireJobId,
  resolveControlTowerApiBaseUrl,
  v2FinalReportPdfDownloadUrl,
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

    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([
      expect.stringContaining(`/v1/v2/jobs/${jobId}/approvals`),
      expect.stringContaining(`/v1/v2/migration-jobs/${jobId}/stages`),
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
    await expect(getV2AssistantMessages("")).rejects.toThrow(/job id is required/i);
    await expect(getV2FinalReport("")).rejects.toThrow(/job id is required/i);
    await expect(generateV2FinalReport("")).rejects.toThrow(/job id is required/i);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("calls the V2 final report endpoints with the route job id", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => ({
      ok: true,
      json: async () => ({
        job_id: "job-123",
        status: "generated",
        generated_at: "2026-06-18T00:00:00Z",
        docs_report_json: "docs/migration-reports/job-123/migration_report.json",
        docs_report_markdown: "docs/migration-reports/job-123/full_migration_report.md",
        docs_report_pdf: "docs/migration-reports/job-123/full_migration_report.pdf",
        run_report_json: "C:/tmp/run/final/migration_report.json",
        run_report_markdown: "C:/tmp/run/final/migration_summary.md",
        run_report_pdf: "C:/tmp/run/final/full_migration_report.pdf",
        report_context: "docs/migration-reports/job-123/report_context.json",
        total_duration_seconds: 42.25,
        summary: "summary",
        change_summary: ["Java changed from 17 to 21."],
        warnings: [],
        full_migration_source_stack: { spring_boot: "2.1.6", java: "11" },
        full_migration_target_stack: { spring_boot: "4.0.7", java: "21" },
        pipeline_history: [
          {
            stage_index: 1,
            pipeline_stage: "baseline",
            input_source_kind: "legacy",
            profile: "springboot-2.1.6-to-2.7-java11",
            source_stack: { spring_boot: "2.1.6", java: "11" },
            target_stack: { spring_boot: "2.7.18", java: "11" },
            chain_status: "completed",
            build_status: "BUILD_PASSED_IN_SANDBOX",
            test_status: "TEST_PASSED",
            transform_status: "TRANSFORM_APPLIED_IN_SANDBOX",
            run_id: "run-1",
            run_dir: "C:/tmp/run-1",
            duration_seconds: 12.5,
            artifact_refs: {},
          },
        ],
      }),
      status: 200,
      headers: { get: () => null },
      init,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const jobId = "job-123";
    await getV2FinalReport(jobId);
    await generateV2FinalReport(jobId);

    expect(fetchMock.mock.calls[0][0]).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/${jobId}/report`);
    expect(fetchMock.mock.calls[1][0]).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/${jobId}/report`);
    expect(v2FinalReportPdfDownloadUrl(jobId)).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/${jobId}/report.pdf`);
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        method: "POST",
      }),
    );
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
