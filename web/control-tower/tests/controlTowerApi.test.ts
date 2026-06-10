import { afterEach, describe, expect, it, vi } from "vitest";
import { allowedStatusCopy, createDiagnosticJobPayload, eventStreamUrl, getJob } from "../lib/controlTowerApi";
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
