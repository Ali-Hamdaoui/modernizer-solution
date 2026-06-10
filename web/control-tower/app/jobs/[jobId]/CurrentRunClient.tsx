"use client";

import { useEffect, useState } from "react";
import { useRef } from "react";
import type { JobRepresentation, PublicRunEvent } from "../../../lib/contracts";
import {
  CONTROL_TOWER_API_BASE_URL,
  allowedStatusCopy,
  eventStreamUrl
} from "../../../lib/controlTowerApi";
import {
  applyPublicEvent,
  jobStatusCopy,
  latestAppliedSequence,
  shouldRefetchJobProjection
} from "../../../lib/eventReplay";
import { StartDiagnosticJobButton } from "./StartDiagnosticJobButton";

type Props = {
  initialEvents: PublicRunEvent[];
  initialJob: JobRepresentation;
};

const PUBLIC_EVENT_TYPES = ["job_created", "command_queued", "job_state_changed", "artifact_registered"];

export function CurrentRunClient({ initialEvents, initialJob }: Props) {
  const jobId = initialJob.job.job_id;
  const [job, setJob] = useState(initialJob);
  const [events, setEvents] = useState(initialEvents);
  const [connectionStatus, setConnectionStatus] = useState("Connecting");
  const lastAppliedSequenceRef = useRef(latestAppliedSequence(initialEvents));

  async function refetchJobProjection() {
    const response = await fetch(
      `${CONTROL_TOWER_API_BASE_URL}/v1/jobs/${encodeURIComponent(jobId)}`,
      { cache: "no-store" }
    );
    if (!response.ok) {
      return;
    }
    const etag = response.headers.get("etag") ?? job.etag;
    setJob({ ...((await response.json()) as JobRepresentation), etag });
  }

  useEffect(() => {
    const source = new EventSource(eventStreamUrl(jobId, lastAppliedSequenceRef.current));

    function applyMessage(message: MessageEvent<string>) {
      const event = JSON.parse(message.data) as PublicRunEvent;
      setEvents((currentEvents) => {
        const currentLastApplied = lastAppliedSequenceRef.current;
        if (event.sequence <= currentLastApplied) {
          return currentEvents;
        }
        const next = applyPublicEvent(
          {
            events: currentEvents,
            lastAppliedSequence: currentLastApplied
          },
          event
        );
        lastAppliedSequenceRef.current = next.lastAppliedSequence;
        return next.events;
      });
      if (shouldRefetchJobProjection(event)) {
        void refetchJobProjection();
      }
    }

    source.onopen = () => setConnectionStatus(allowedStatusCopy.connected);
    source.onerror = () => setConnectionStatus("Reconnecting");
    for (const eventType of PUBLIC_EVENT_TYPES) {
      source.addEventListener(eventType, applyMessage);
    }

    return () => source.close();
  }, [jobId]);

  const statusCopy = jobStatusCopy(job.job);

  return (
    <section className="panel stack">
      <div>
        <p className="eyebrow">Current run</p>
        <h1>{statusCopy}</h1>
        <p className="meta">{connectionStatus}</p>
      </div>
      <dl className="grid">
        <div>
          <dt className="meta">Job ID</dt>
          <dd>{job.job.job_id}</dd>
        </div>
        <div>
          <dt className="meta">State</dt>
          <dd className="status">{job.job.state}</dd>
        </div>
        <div>
          <dt className="meta">Version</dt>
          <dd>{job.job.version}</dd>
        </div>
        <div>
          <dt className="meta">Active command</dt>
          <dd>{job.active_command?.status ?? "None"}</dd>
        </div>
      </dl>
      {job.job.state === "CREATED" ? (
        <StartDiagnosticJobButton etag={job.etag} jobId={job.job.job_id} onStarted={refetchJobProjection} />
      ) : null}
      <section className="event-list" aria-label="Committed public events">
        {events.map((event) => (
          <article className="event-row" key={`${event.job_id}-${event.sequence}`}>
            <span className="event-sequence">#{event.sequence}</span>
            <strong>{event.event_type === "command_queued" ? allowedStatusCopy.diagnosticQueued : event.event_type}</strong>
            <span className="meta">{event.created_at}</span>
          </article>
        ))}
      </section>
    </section>
  );
}
