import { NewMigrationForm } from "./NewMigrationForm";

export const metadata = {
  title: "New Migration | Control Tower",
};

export default function NewMigrationPage() {
  return (
    <section className="stack">
      <div>
        <p className="eyebrow">V2 Local Migration</p>
        <h1>New Migration</h1>
        <p className="meta">
          Set up a local migration. Paste your terminal-style env block or enter
          fields manually. The backend validates all paths before any command is queued.
        </p>
      </div>
      <NewMigrationForm />
    </section>
  );
}
