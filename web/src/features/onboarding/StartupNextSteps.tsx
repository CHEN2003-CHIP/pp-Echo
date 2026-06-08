import type { OnboardingStatus } from "../../api";

export function StartupNextSteps({ status, onOpenChat, onOpenTrace }: { status: OnboardingStatus | null; onOpenChat: () => void; onOpenTrace: () => void }) {
  return (
    <section className="startup-guide-section">
      <div className="startup-guide-section-head">
        <h2>下一步</h2>
      </div>
      <div className="startup-next-steps">
        {(status?.next_steps || []).map((step) => (
          <article key={step.title}>
            <strong>{step.title}</strong>
            <p>{step.description}</p>
            {step.target_view === "chat" ? <button onClick={onOpenChat}>{step.action_label || "返回会话"}</button> : null}
            {step.target_view === "traceInspect" ? <button onClick={onOpenTrace}>{step.action_label || "打开 TraceInspect"}</button> : null}
          </article>
        ))}
      </div>
    </section>
  );
}
