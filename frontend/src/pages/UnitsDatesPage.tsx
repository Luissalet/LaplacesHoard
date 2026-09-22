import { useState } from "react";
import { api, ApiError, type DateResult, type UnitsResult } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, copyCite } from "../components/ResultView";

const DATE_OPS = ["diff", "add", "business_days", "weekday", "iso_week", "age", "convert_tz", "parse"] as const;

export function UnitsDatesPage({ t }: { t: (k: DictKey) => string }) {
  return (
    <div className="two-col">
      <UnitsCard t={t} />
      <DatesCard t={t} />
    </div>
  );
}

function UnitsCard({ t }: { t: (k: DictKey) => string }) {
  const [quantity, setQuantity] = useState("3.5 km/h");
  const [to, setTo] = useState("m/s");
  const [result, setResult] = useState<UnitsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.unitsConvert(quantity, to));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h3 className="card-title">{t("units_title")}</h3>
      <div className="stack">
        <div className="col">
          <label className="field-label">{t("units_quantity")}</label>
          <input type="text" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </div>
        <div className="col">
          <label className="field-label">{t("units_to")}</label>
          <input type="text" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <button className="btn" onClick={run} disabled={busy}>{t("units_convert")}</button>
        {error && <div className="result-block" style={{ color: "var(--danger)" }}>{error}</div>}
        {result && (
          <div className="result-block">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="result-value">{result.formatted}</span>
              <CiteBadge id={result.id} onClick={copyCite} />
            </div>
            <div className="faint" style={{ marginTop: 4 }}>
              {result.from_magnitude} {result.from_unit} → {result.to_magnitude.toLocaleString()} {result.to_unit}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DatesCard({ t }: { t: (k: DictKey) => string }) {
  const [op, setOp] = useState<(typeof DATE_OPS)[number]>("diff");
  const [start, setStart] = useState("2026-01-01");
  const [end, setEnd] = useState("2026-09-22");
  const [value, setValue] = useState("2026-09-22");
  const [birthDate, setBirthDate] = useState("1990-05-15");
  const [days, setDays] = useState(10);
  const [country, setCountry] = useState("ES");
  const [subdivision, setSubdivision] = useState("MD");
  const [fromTz, setFromTz] = useState("Europe/Madrid");
  const [toTz, setToTz] = useState("America/New_York");
  const [result, setResult] = useState<DateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = { operation: op, country, subdivision };
      if (op === "diff" || op === "business_days") { payload.start = start; payload.end = end; }
      if (op === "add") { payload.start = start; payload.days = days; }
      if (op === "weekday" || op === "iso_week" || op === "parse") payload.value = value;
      if (op === "age") { payload.birth_date = birthDate; }
      if (op === "convert_tz") { payload.value = value; payload.from_tz = fromTz; payload.to_tz = toTz; }
      setResult(await api.dateCalc(payload));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h3 className="card-title">{t("dates_title")}</h3>
      <div className="stack">
        <div className="col">
          <label className="field-label">{t("dates_operation")}</label>
          <select value={op} onChange={(e) => setOp(e.target.value as (typeof DATE_OPS)[number])}>
            {DATE_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
        {(op === "diff" || op === "business_days") && (
          <div className="row">
            <div className="col grow">
              <label className="field-label">{t("dates_start")}</label>
              <input type="text" value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
            <div className="col grow">
              <label className="field-label">{t("dates_end")}</label>
              <input type="text" value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>
        )}
        {op === "add" && (
          <div className="row">
            <div className="col grow">
              <label className="field-label">{t("dates_start")}</label>
              <input type="text" value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
            <div className="col">
              <label className="field-label">days</label>
              <input type="number" value={days} onChange={(e) => setDays(Number(e.target.value))} />
            </div>
          </div>
        )}
        {(op === "weekday" || op === "iso_week" || op === "parse") && (
          <div className="col">
            <label className="field-label">value</label>
            <input type="text" value={value} onChange={(e) => setValue(e.target.value)} />
          </div>
        )}
        {op === "age" && (
          <div className="col">
            <label className="field-label">birth date</label>
            <input type="text" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
          </div>
        )}
        {op === "convert_tz" && (
          <>
            <div className="col">
              <label className="field-label">value</label>
              <input type="text" value={value} onChange={(e) => setValue(e.target.value)} />
            </div>
            <div className="row">
              <div className="col grow">
                <label className="field-label">from tz</label>
                <input type="text" value={fromTz} onChange={(e) => setFromTz(e.target.value)} />
              </div>
              <div className="col grow">
                <label className="field-label">to tz</label>
                <input type="text" value={toTz} onChange={(e) => setToTz(e.target.value)} />
              </div>
            </div>
          </>
        )}
        {op === "business_days" && (
          <div className="row">
            <div className="col grow">
              <label className="field-label">country</label>
              <input type="text" value={country} onChange={(e) => setCountry(e.target.value)} />
            </div>
            <div className="col grow">
              <label className="field-label">subdivision</label>
              <input type="text" value={subdivision} onChange={(e) => setSubdivision(e.target.value)} />
            </div>
          </div>
        )}
        <button className="btn" onClick={run} disabled={busy}>{t("dates_run")}</button>
        {error && <div className="result-block" style={{ color: "var(--danger)" }}>{error}</div>}
        {result && (
          <div className="result-block">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(omit(result, ["id", "cite"]), null, 2)}
              </pre>
              <CiteBadge id={result.id} onClick={copyCite} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function omit(obj: Record<string, unknown>, keys: string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(obj)) if (!keys.includes(k)) out[k] = obj[k];
  return out;
}
