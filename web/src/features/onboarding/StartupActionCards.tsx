import { Activity, Copy, KeyRound, MonitorPlay, TerminalSquare } from "lucide-react";
import type { OnboardingStatus } from "../../api";
import { copyText } from "./onboarding-utils";

export function StartupActionCards({ status, onOpenTrace }: { status: OnboardingStatus | null; onOpenTrace: () => void }) {
  const hints = status?.command_hints || [];
  return (
    <section className="startup-guide-section">
      <div className="startup-guide-section-head">
        <h2>常用动作</h2>
      </div>
      <div className="startup-action-grid">
        {hints.map((hint, index) => {
          const Icon = index === 0 ? KeyRound : index === 1 ? TerminalSquare : MonitorPlay;
          return (
            <article className="startup-action-card" key={hint.title}>
              <Icon size={18} />
              <strong>{hint.title}</strong>
              <p>{hint.description}</p>
              <code>{hint.command}</code>
              <button onClick={() => copyText(hint.command)}><Copy size={14} /><span>复制命令</span></button>
            </article>
          );
        })}
        <article className="startup-action-card">
          <Activity size={18} />
          <strong>查看 Agent Trace 审计</strong>
          <p>运行一次任务后，在 TraceInspect 中查看 LLM token/cost、工具调用、审批、Memory、Checkpoint 和错误诊断。</p>
          <button onClick={onOpenTrace}><span>打开 TraceInspect</span></button>
        </article>
      </div>
    </section>
  );
}
