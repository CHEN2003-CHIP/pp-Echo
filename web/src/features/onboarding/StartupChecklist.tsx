import { CheckCircle2, Copy, HelpCircle, TriangleAlert, XCircle } from "lucide-react";
import type { OnboardingCheck } from "../../api";
import { copyText, statusLabel, statusTone } from "./onboarding-utils";

const statusIcon = {
  ok: CheckCircle2,
  warning: TriangleAlert,
  error: XCircle,
  skipped: HelpCircle
};

export function StartupChecklist({ checks }: { checks: OnboardingCheck[] }) {
  return (
    <section className="startup-guide-section">
      <div className="startup-guide-section-head">
        <h2>启动检查</h2>
      </div>
      <div className="startup-checklist">
        {checks.map((check) => {
          const Icon = statusIcon[check.status];
          return (
            <article className="startup-check-item" key={check.id}>
              <div className={`startup-check-icon ${statusTone(check.status)}`}><Icon size={18} /></div>
              <div>
                <div className="startup-check-title">
                  <strong>{check.title}</strong>
                  <span className={statusTone(check.status)}>{statusLabel[check.status]}</span>
                </div>
                <p>{check.summary}</p>
                {check.detail ? <small>{check.detail}</small> : null}
                {check.action_command ? (
                  <button className="startup-copy-command" onClick={() => copyText(check.action_command || "")}>
                    <Copy size={14} />
                    <span>{check.action_label || "复制命令"}</span>
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
