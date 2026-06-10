"use client";

import { useState } from "react";
import { CONTROL_TOWER_API_BASE_URL } from "../../../lib/controlTowerApi";

type Props = {
  etag: string;
  jobId: string;
  onStarted?: () => void | Promise<void>;
};

export function StartDiagnosticJobButton({ etag, jobId, onStarted }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function start() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`${CONTROL_TOWER_API_BASE_URL}/v1/jobs/${encodeURIComponent(jobId)}/start`, {
        body: JSON.stringify({}),
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
          "If-Match": etag
        },
        method: "POST"
      });
      if (!response.ok) {
        throw new Error("Could not queue command.");
      }
      await onStarted?.();
      setPending(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not queue command.");
      setPending(false);
    }
  }

  return (
    <div className="stack">
      {error ? <p role="alert">{error}</p> : null}
      <button className="button secondary" disabled={pending} onClick={start} type="button">
        {pending ? "Queueing..." : "Queue diagnostic command"}
      </button>
    </div>
  );
}
