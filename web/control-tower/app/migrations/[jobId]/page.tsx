import { MigrationCockpit } from "./MigrationCockpit";

export const metadata = {
  title: "Migration Cockpit | Control Tower",
};

export default async function MigrationCockpitPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;

  return (
    <section className="migration-cockpit-page">
      <div className="migration-cockpit-header">
        <p className="eyebrow">V2 Migration Cockpit</p>
        <h1>Migration {jobId}</h1>
        <p className="meta">
          Stage progress, decisions, assistant, evidence, and proof.
          The backend owns all execution. This cockpit reflects state without
          taking authority.
        </p>
      </div>
      <MigrationCockpit jobId={jobId} />
    </section>
  );
}
