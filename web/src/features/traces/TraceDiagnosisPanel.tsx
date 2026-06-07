import type { TraceDiagnosis } from "../../api";

export function TraceDiagnosisPanel({ diagnosis, warnings }: { diagnosis: TraceDiagnosis[]; warnings: string[] }) {
  return (
    <section className="trace-inspect-section">
      <h3>Diagnosis</h3>
      {[...diagnosis, ...warnings.map((message) => ({ code: message, severity: "warning" as const, title: "Trace warning", message }))].map((item) => (
        <div className={`trace-diagnosis trace-diagnosis-${item.severity}`} key={`${item.code}-${item.message}`}>
          <strong>{item.title}</strong>
          <span>{item.message}</span>
        </div>
      ))}
      {diagnosis.length === 0 && warnings.length === 0 ? <p className="muted">No diagnosis.</p> : null}
    </section>
  );
}
