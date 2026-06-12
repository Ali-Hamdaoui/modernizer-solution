import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CONTROL_TOWER_FRONTEND_CLIENT_ID,
  DEFAULT_CONTROL_TOWER_API_BASE_URL,
  allowedStatusCopy,
  createDiagnosticJobPayload,
  eventStreamUrl,
  getJob,
  previewPlanAmendment,
  postJson,
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
