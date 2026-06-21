import { ArrowLeft, Copy, RefreshCw, Wifi } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type OnboardingCheck, type OnboardingStatus } from "../../api";
import { StartupActionCards } from "./StartupActionCards";
import { StartupChecklist } from "./StartupChecklist";
import { StartupNextSteps } from "./StartupNextSteps";
import { copyText, statusLabel, statusTone } from "./onboarding-utils";

const SAFE_FIRST_TASK = "Please read README and summarize pp-Echo's core modules. Do not edit files and do not run shell commands.";

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
    setError("");
    try {
      setModelCheck(await api.onboardingCheckModel());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
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
          <h2>Startup Guide</h2>
          <p>{status?.workspace || "Checking the current workspace..."}</p>
        </div>
        <div className="startup-guide-actions">
          <span className={`startup-overall startup-overall-${overall}`}>{overall}</span>
          <button className="startup-secondary-button" onClick={load} disabled={loading}><RefreshCw size={15} /><span>Refresh</span></button>
          <button className="startup-secondary-button" onClick={onBack}><ArrowLeft size={15} /><span>Back to chat</span></button>
        </div>
      </header>

      {error ? <div className="startup-guide-error">{error}</div> : null}
      {loading ? <div className="startup-guide-loading">Checking startup environment...</div> : null}
      {status ? <StartupChecklist checks={modelCheck ? [...status.checks, modelCheck] : status.checks} /> : null}

      <section className="startup-guide-section">
        <div className="startup-guide-section-head">
          <h2>Model connection</h2>
        </div>
        <div className="startup-model-check">
          <p>Clicking this runs one controlled, low-token model request. Startup checks do not run it automatically.</p>
          <button onClick={checkModel} disabled={checkingModel}><Wifi size={15} /><span>{checkingModel ? "Checking" : "Test model connection"}</span></button>
          <small>API keys are read from environment variables and are never returned to the page.</small>
          {modelCheck ? (
            <div className={`startup-model-result ${statusTone(modelCheck.status)}`}>
              <strong>{statusLabel[modelCheck.status]}: {modelCheck.summary}</strong>
              {modelCheck.detail ? <span>{modelCheck.detail}</span> : null}
            </div>
          ) : null}
        </div>
      </section>

      {status ? <StartupActionCards status={status} onOpenTrace={onOpenTrace} /> : null}

      <section className="startup-guide-section">
        <div className="startup-guide-section-head">
          <h2>Safe first task</h2>
        </div>
        <div className="startup-safe-task">
          <p>{SAFE_FIRST_TASK}</p>
          <button onClick={() => copyText(SAFE_FIRST_TASK)}><Copy size={14} /><span>Copy prompt</span></button>
        </div>
      </section>

      <StartupNextSteps status={status} onOpenChat={onOpenChat} onOpenTrace={onOpenTrace} />
    </section>
  );
}
