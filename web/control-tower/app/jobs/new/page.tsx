import { CreateDiagnosticJobForm } from "./CreateDiagnosticJobForm";
import { getCatalog } from "../../../lib/controlTowerApi";

export default async function NewDiagnosticJobPage() {
  const catalog = await getCatalog();
  return (
    <section className="screen-page">
      <div className="screen-header">
        <p className="eyebrow">New job</p>
        <h1>Create foundation diagnostic job</h1>
        <p className="meta">Choose registered inputs only. This page does not submit executable details.</p>
      </div>
      <div className="screen-body">
        <CreateDiagnosticJobForm catalog={catalog} />
      </div>
    </section>
  );
}
