import { useState } from "react";
import { api, ApiError, type StatsResult } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, copyCite } from "../components/ResultView";

const TESTS = [
  "describe", "ttest_1samp", "ttest_ind", "ttest_rel", "mannwhitneyu", "wilcoxon",
  "chi2_contingency", "fisher_exact", "pearson", "spearman", "linregress",
  "proportion_ci", "normal_ci", "binom_test",
];

// Inline mode: which tests need a second sample pasted in (`data2`).
const NEEDS_SECOND_SAMPLE = new Set(["ttest_ind", "ttest_rel", "mannwhitneyu", "wilcoxon", "pearson", "spearman", "linregress"]);
// Dataset mode: two-sample tests split by `group_by` instead of a second column.
const USES_GROUP_BY = new Set(["ttest_ind", "mannwhitneyu"]);
// Dataset mode: tests that need an explicit second column (paired/paired-like tests).
const NEEDS_COLUMN2 = new Set(["ttest_rel", "wilcoxon", "pearson", "spearman", "linregress"]);
const NEEDS_PROPORTION = new Set(["proportion_ci", "binom_test"]);

export function StatisticsPage({ t }: { t: (k: DictKey) => string }) {
  const [test, setTest] = useState("ttest_ind");
  const [source, setSource] = useState<"inline" | "dataset">("inline");
  const [data1, setData1] = useState("1, 2, 3, 4, 5");
  const [data2, setData2] = useState("2, 3, 4, 5, 9");
  const [dataset, setDataset] = useState("");
  const [column, setColumn] = useState("");
  const [column2, setColumn2] = useState("");
  const [groupBy, setGroupBy] = useState("");
  const [where, setWhere] = useState("");
  const [successes, setSuccesses] = useState(45);
  const [trials, setTrials] = useState(100);
  const [result, setResult] = useState<StatsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = { test };
      if (NEEDS_PROPORTION.has(test)) {
        payload.successes = successes;
        payload.trials = trials;
      } else if (source === "inline") {
        if (test === "chi2_contingency" || test === "fisher_exact") {
          payload.data = parseTable(data1);
        } else {
          payload.data = parseNums(data1);
          if (NEEDS_SECOND_SAMPLE.has(test)) payload.data2 = parseNums(data2);
        }
      } else {
        payload.dataset = dataset;
        payload.column = column;
        if (NEEDS_COLUMN2.has(test)) payload.column2 = column2;
        if (USES_GROUP_BY.has(test) && groupBy) payload.group_by = groupBy;
        if (where) payload.where = where;
      }
      setResult(await api.stats(payload));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 640 }}>
      <h3 className="card-title">{t("stats_title")}</h3>
      <div className="stack">
        <div className="col">
          <label className="field-label">{t("stats_test")}</label>
          <select value={test} onChange={(e) => setTest(e.target.value)}>
            {TESTS.map((tst) => <option key={tst} value={tst}>{tst}</option>)}
          </select>
        </div>

        {!NEEDS_PROPORTION.has(test) && (
          <div className="pill-select" style={{ alignSelf: "flex-start" }}>
            <button className={source === "inline" ? "active" : ""} onClick={() => setSource("inline")}>
              {t("stats_inline")}
            </button>
            <button className={source === "dataset" ? "active" : ""} onClick={() => setSource("dataset")}>
              {t("stats_dataset")}
            </button>
          </div>
        )}

        {NEEDS_PROPORTION.has(test) && (
          <div className="row">
            <div className="col grow">
              <label className="field-label">successes</label>
              <input type="number" value={successes} onChange={(e) => setSuccesses(Number(e.target.value))} />
            </div>
            <div className="col grow">
              <label className="field-label">trials</label>
              <input type="number" value={trials} onChange={(e) => setTrials(Number(e.target.value))} />
            </div>
          </div>
        )}

        {!NEEDS_PROPORTION.has(test) && source === "inline" && (
          <>
            <div className="col">
              <label className="field-label">
                {test === "chi2_contingency" || test === "fisher_exact"
                  ? "Rows of the table, one per line (e.g. 10,20)"
                  : t("stats_data1")}
              </label>
              <textarea value={data1} onChange={(e) => setData1(e.target.value)} rows={2} />
            </div>
            {NEEDS_SECOND_SAMPLE.has(test) && (
              <div className="col">
                <label className="field-label">{t("stats_data2")}</label>
                <textarea value={data2} onChange={(e) => setData2(e.target.value)} rows={2} />
              </div>
            )}
          </>
        )}

        {!NEEDS_PROPORTION.has(test) && source === "dataset" && (
          <>
            <div className="col">
              <label className="field-label">{t("stats_dataset_name")}</label>
              <input type="text" value={dataset} onChange={(e) => setDataset(e.target.value)} />
            </div>
            <div className="col">
              <label className="field-label">{t("stats_column")}</label>
              <input type="text" value={column} onChange={(e) => setColumn(e.target.value)} />
            </div>
            {NEEDS_COLUMN2.has(test) && (
              <div className="col">
                <label className="field-label">{t("stats_column2")}</label>
                <input type="text" value={column2} onChange={(e) => setColumn2(e.target.value)} />
              </div>
            )}
            {USES_GROUP_BY.has(test) && (
              <div className="col">
                <label className="field-label">{t("stats_group_by")}</label>
                <input type="text" value={groupBy} onChange={(e) => setGroupBy(e.target.value)} />
              </div>
            )}
            <div className="col">
              <label className="field-label">{t("stats_where")}</label>
              <input type="text" value={where} onChange={(e) => setWhere(e.target.value)} />
            </div>
          </>
        )}

        <button className="btn" onClick={run} disabled={busy}>{t("stats_run")}</button>
        {error && <div className="result-block" style={{ color: "var(--danger)" }}>{error}</div>}
        {result && (
          <div className="result-block">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{String(result.test)}</strong>
              <CiteBadge id={result.id} onClick={copyCite} />
            </div>
            <pre className="mono" style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>
              {JSON.stringify(omit(result, ["id", "cite", "test", "interpretation"]), null, 2)}
            </pre>
            {result.interpretation && <div className="faint" style={{ marginTop: 6 }}>{String(result.interpretation)}</div>}
          </div>
        )}
      </div>
    </div>
  );
}

function parseNums(text: string): number[] {
  return text.split(",").map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n));
}

function parseTable(text: string): number[][] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => parseNums(line));
}

function omit(obj: Record<string, unknown>, keys: string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(obj)) if (!keys.includes(k)) out[k] = obj[k];
  return out;
}
