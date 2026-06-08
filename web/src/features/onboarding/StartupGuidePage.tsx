import { ArrowLeft, Copy, RefreshCw, Wifi } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type OnboardingCheck, type OnboardingStatus } from "../../api";
import { StartupActionCards } from "./StartupActionCards";
import { StartupChecklist } from "./StartupChecklist";
import { StartupNextSteps } from "./StartupNextSteps";
import { copyText, statusLabel, statusTone } from "./onboarding-utils";

const SAFE_FIRST_TASK = "请阅读 README，总结 pp-Echo 的核心模块，不要修改文件，不要执行 shell。";

export function StartupGuidePage({ onBack, onOpenTrace, onOpenChat }: { onBack: () => void; onOpenTrace: () => void; onOpenChat: () => void }) {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [modelCheck, setModelCheck] = useState<OnboardingCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [checkingModel, setCheckingModel] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setStatus(await api.onboardingStatus());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }

  async function checkModel() {
    setCheckingModel(true);
    try {
      setModelCheck(await api.onboardingCheckModel());
    } finally {
      setCheckingModel(false);
    }
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  const overall = status?.overall_status || "partial";
  return (
    <section className="startup-guide-page">
      <header className="startup-guide-hero">
        <div>
          <small>Startup Guide</small>
          <h2>启动指引</h2>
          <p>{status?.workspace || "正在检查当前 workspace..."}</p>
        </div>
        <div className="startup-guide-actions">
          <span className={`startup-overall startup-overall-${overall}`}>{overall}</span>
          <button className="startup-secondary-button" onClick={load} disabled={loading}><RefreshCw size={15} /><span>刷新</span></button>
          <button className="startup-secondary-button" onClick={onBack}><ArrowLeft size={15} /><span>返回会话</span></button>
        </div>
      </header>

      {error ? <div className="startup-guide-error">{error}</div> : null}
      {loading ? <div className="startup-guide-loading">正在检查启动环境...</div> : null}
      {status ? <StartupChecklist checks={modelCheck ? [...status.checks, modelCheck] : status.checks} /> : null}

      <section className="startup-guide-section">
        <div className="startup-guide-section-head">
          <h2>模型连接</h2>
        </div>
        <div className="startup-model-check">
          <p>点击后只会执行受控的模型连接检查入口；当前版本不会自动发送长 prompt 或保存密钥。</p>
          <button onClick={checkModel} disabled={checkingModel}><Wifi size={15} /><span>{checkingModel ? "检查中" : "测试模型连接"}</span></button>
          <small>提示：未来接入真实 ping 时，会发起一次轻量模型请求。</small>
          {modelCheck ? (
            <div className={`startup-model-result ${statusTone(modelCheck.status)}`}>
              <strong>{statusLabel[modelCheck.status]}：{modelCheck.summary}</strong>
              {modelCheck.detail ? <span>{modelCheck.detail}</span> : null}
            </div>
          ) : null}
        </div>
      </section>

      {status ? <StartupActionCards status={status} onOpenTrace={onOpenTrace} /> : null}

      <section className="startup-guide-section">
        <div className="startup-guide-section-head">
          <h2>安全首个任务</h2>
        </div>
        <div className="startup-safe-task">
          <p>{SAFE_FIRST_TASK}</p>
          <button onClick={() => copyText(SAFE_FIRST_TASK)}><Copy size={14} /><span>复制 prompt</span></button>
        </div>
      </section>

      <StartupNextSteps status={status} onOpenChat={onOpenChat} onOpenTrace={onOpenTrace} />
    </section>
  );
}
