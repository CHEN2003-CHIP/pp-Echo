export type TraceTab = "overview" | "context" | "tools" | "memory" | "raw";

const tabs: Array<[TraceTab, string]> = [
  ["overview", "Overview"],
  ["context", "Context"],
  ["tools", "Tools"],
  ["memory", "Memory"],
  ["raw", "Raw JSON"]
];

export function TraceTabs({ value, onChange }: { value: TraceTab; onChange: (value: TraceTab) => void }) {
  return (
    <div className="trace-tabs" role="tablist" aria-label="Trace detail panels">
      {tabs.map(([tab, label]) => (
        <button key={tab} type="button" className={value === tab ? "active" : ""} onClick={() => onChange(tab)}>
          {label}
        </button>
      ))}
    </div>
  );
}
