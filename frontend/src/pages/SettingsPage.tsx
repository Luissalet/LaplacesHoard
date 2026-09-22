import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, ApiError, type BackendStatus, type HealthInfo } from "../api";
import type { Lang } from "../i18n";
import type { DictKey } from "../i18n";
import type { Theme } from "../hooks";

export function SettingsPage({
  t, lang, setLang, theme, setTheme,
}: {
  t: (k: DictKey) => string;
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
}) {
  const [health, setHealth] = useState<HealthInfo | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
  }, []);

  return (
    <div className="stack" style={{ maxWidth: 480 }}>
      <div className="card">
        <h3 className="card-title">{t("settings_language")}</h3>
        <div className="pill-select">
          <button className={lang === "en" ? "active" : ""} onClick={() => setLang("en")}>English</button>
          <button className={lang === "es" ? "active" : ""} onClick={() => setLang("es")}>Español</button>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">{t("settings_theme")}</h3>
        <div className="pill-select">
          <button className={theme === "system" ? "active" : ""} onClick={() => setTheme("system")}>{t("settings_theme_system")}</button>
          <button className={theme === "light" ? "active" : ""} onClick={() => setTheme("light")}>{t("settings_theme_light")}</button>
          <button className={theme === "dark" ? "active" : ""} onClick={() => setTheme("dark")}>{t("settings_theme_dark")}</button>
        </div>
      </div>

      <ModelsPanel t={t} />

      <div className="card">
        <h3 className="card-title">{t("settings_about")}</h3>
        {health ? (
          <div className="stack">
            <Row label={t("settings_version")} value={health.version} />
            <Row label={t("settings_datasets_registered")} value={String(health.datasets_registered)} />
            <Row label={t("settings_computations_logged")} value={String(health.computations_logged)} />
          </div>
        ) : (
          <div className="faint">{t("common_loading")}</div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="row" style={{ justifyContent: "space-between" }}>
      <span className="muted">{label}</span>
      <span className="mono">{value}</span>
    </div>
  );
}

function ModelsPanel({ t }: { t: (k: DictKey) => string }) {
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [showOverride, setShowOverride] = useState(false);
  const [faustusUrl, setFaustusUrl] = useState("");
  const [faustusToken, setFaustusToken] = useState("");
  const [capUrl, setCapUrl] = useState("");
  const [capModel, setCapModel] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.backend().then((s) => { setStatus(s); return s; }).catch(() => setStatus(null));

  useEffect(() => {
    load();
  }, []);

  async function recheck() {
    setBusy(true);
    try {
      await api.backendRecheck();
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api.backendConfig({
        faustus_url: faustusUrl || undefined,
        faustus_token: faustusToken || undefined,
        capabilities: (capUrl || capModel) ? { llm: { url: capUrl || undefined, model: capModel || undefined } } : undefined,
      });
      setFaustusToken("");
      setSaved(true);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3 className="card-title">{t("settings_models")}</h3>
        <button className="icon-btn" onClick={recheck} disabled={busy} title={t("settings_models_recheck")}>
          <RefreshCw size={15} />
        </button>
      </div>
      {!status ? (
        <div className="faint">{t("common_loading")}</div>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          {Object.entries(status.capabilities).map(([cap, res]) => (
            <div key={cap} className="stack" style={{ gap: 2 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="mono">{cap}</span>
                <span className={`badge ${res.state === "resolved" ? "badge-ok" : "badge-muted"}`}>
                  {res.state === "resolved" ? t("settings_models_state_resolved") : t("settings_models_state_unavailable")}
                </span>
              </div>
              {res.state === "resolved" && (
                <div className="faint mono" style={{ fontSize: 12 }}>{res.provider} · {res.model}</div>
              )}
              <div className="faint" style={{ fontSize: 12 }} title={res.reason}>{res.reason}</div>
            </div>
          ))}

          <button className="btn-ghost" style={{ alignSelf: "flex-start" }} onClick={() => setShowOverride((s) => !s)}>
            {t("settings_models_override")}
          </button>
          {showOverride && (
            <div className="stack" style={{ gap: 8 }}>
              <div className="col">
                <label className="field-label">{t("settings_models_faustus_url")}</label>
                <input type="text" className="mono" value={faustusUrl} onChange={(e) => setFaustusUrl(e.target.value)} placeholder="http://127.0.0.1:7000" />
              </div>
              <div className="col">
                <label className="field-label">
                  {t("settings_models_faustus_token")}
                  {status.config.token_set && <span className="faint"> ({t("settings_models_token_set")})</span>}
                </label>
                <input type="password" className="mono" value={faustusToken} onChange={(e) => setFaustusToken(e.target.value)} placeholder="ody_..." />
              </div>
              <div className="row">
                <div className="col grow">
                  <label className="field-label">llm {t("settings_models_cap_url")}</label>
                  <input type="text" className="mono" value={capUrl} onChange={(e) => setCapUrl(e.target.value)} placeholder="http://127.0.0.1:8081" style={{ width: "100%" }} />
                </div>
                <div className="col grow">
                  <label className="field-label">llm {t("settings_models_cap_model")}</label>
                  <input type="text" value={capModel} onChange={(e) => setCapModel(e.target.value)} style={{ width: "100%" }} />
                </div>
              </div>
              {error && <div className="faint" style={{ color: "var(--danger)" }}>{error}</div>}
              <button className="btn" disabled={busy} onClick={save}>
                {saved ? t("settings_models_saved") : t("settings_models_save")}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
