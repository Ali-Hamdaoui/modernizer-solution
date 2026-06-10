import { notFound } from "next/navigation";
import { StartDiagnosticJobButton } from "./StartDiagnosticJobButton";
import { allowedStatusCopy, getJob } from "../../../lib/controlTowerApi";

type Props = {
  params: Promise<{ jobId: string }>;
};

export default async function DiagnosticJobPage({ params }: Props) {
  const { jobId } = await params;
  let representation;
  try {
    representation = await getJob(jobId);
  } catch {
    notFound();
  }
  const statusCopy =
    representation.job.state === "QUEUED" ? allowedStatusCopy.queued : allowedStatusCopy.created;

  return (
    <section className="panel stack">
      <div>
        <p className="eyebrow">Current run</p>
        <h1>{statusCopy}</h1>
        <p className="meta">Refresh loads the persisted job state from Control Tower.</p>
      </div>
      <dl className="grid">
        <div>
          <dt className="meta">Job ID</dt>
          <dd>{representation.job.job_id}</dd>
        </div>
        <div>
          <dt className="meta">State</dt>
          <dd className="status">{representation.job.state}</dd>
        </div>
        <div>
          <dt className="meta">Version</dt>
          <dd>{representation.job.version}</dd>
        </div>
        <div>
          <dt className="meta">Active command</dt>
          <dd>{representation.active_command?.status ?? "None"}</dd>
        </div>
      </dl>
      {representation.job.state === "CREATED" ? (
        <StartDiagnosticJobButton etag={representation.etag} jobId={representation.job.job_id} />
      ) : null}
    </section>
  );
}
