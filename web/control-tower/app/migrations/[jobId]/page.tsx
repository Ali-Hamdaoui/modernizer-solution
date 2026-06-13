import { MigrationCockpit } from "./MigrationCockpit";

export const metadata = {
  title: "Migration Cockpit | Control Tower",
};

export default function MigrationCockpitPage({ params }: { params: { jobId: string } }) {
  return (
    <section className="stack">
      <div>
        <p className="eyebrow">V2 Migration Cockpit</p>
        <h1>Migration {params.jobId}</h1>
        <p className="meta">
          Stage progress, decisions, assistant, evidence, and proof.
          The backend owns all execution. This cockpit reflects state without
          taking authority.
        </p>
      </div>
      <MigrationCockpit jobId={params.jobId} />
    </section>
  );
}
