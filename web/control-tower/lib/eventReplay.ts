import type { JobRepresentation, PublicRunEvent } from "./contracts";

export const STATE_CHANGING_EVENT_TYPES = new Set([
  "job_created",
  "job_state_changed",
  "command_queued",
  "artifact_registered"
]);

export type ReplayState = {
  events: PublicRunEvent[];
  lastAppliedSequence: number;
};

export function applyPublicEvent(state: ReplayState, event: PublicRunEvent): ReplayState {
  if (event.sequence <= state.lastAppliedSequence) {
    return state;
  }
  return {
    events: [...state.events, event],
    lastAppliedSequence: event.sequence
  };
}

export function shouldRefetchJobProjection(event: PublicRunEvent): boolean {
  return STATE_CHANGING_EVENT_TYPES.has(event.event_type);
}

export function latestAppliedSequence(events: PublicRunEvent[]): number {
  return events.reduce((latest, event) => Math.max(latest, event.sequence), 0);
}

export function jobStatusCopy(job: JobRepresentation["job"]): string {
  return job.state === "QUEUED" ? "Command queued" : "Foundation diagnostic job created";
}
