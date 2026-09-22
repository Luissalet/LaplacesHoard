import { useEffect, useState } from "react";
import { api, type HealthInfo } from "../api";
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
