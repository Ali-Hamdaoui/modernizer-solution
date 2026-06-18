import Link from "next/link";

export default function HomePage() {
  return (
    <section className="screen-page">
      <div className="screen-header">
        <p className="eyebrow">Control Tower</p>
        <h1>Foundation diagnostic queue</h1>
        <p className="meta">
          Create a foundation diagnostic job, then queue its command.
        </p>
      </div>
      <div className="screen-body panel stack">
        <Link className="button" href="/jobs/new">
          Create diagnostic job
        </Link>
      </div>
    </section>
  );
}
