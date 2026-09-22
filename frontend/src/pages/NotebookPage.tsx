import { useEffect, useState, type ReactNode } from "react";
import { Play } from "lucide-react";
import { api, type Cell } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, ConfirmDelete, ErrorBlock, Latex, VerifiedBadge, copyCite, fmtNum } from "../components/ResultView";

const ENGINES = ["calc", "math", "units", "dates"] as const;
type Engine = (typeof ENGINES)[number];

const PLACEHOLDER_KEY: Record<Engine, DictKey> = {
  calc: "notebook_placeholder_calc",
  math: "notebook_placeholder_math",
  units: "notebook_placeholder_units",
  dates: "notebook_placeholder_dates",
};

type T = (k: DictKey) => string;

export function NotebookPage({ t }: { t: T }) {
  const [cells, setCells] = useState<Cell[]>([]);
  const [engine, setEngine] = useState<Engine>("calc");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.cells().then((r) => {
      setCells(r.cells);
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, []);

  async function addCell() {
    if (!input.trim() || busy) return;
    setBusy(true);
    try {
      const cell = await api.createCell(engine, input.trim());
      setCells((c) => [...c, cell]);
      setInput("");
    } finally {
      setBusy(false);
    }
  }

  async function removeCell(id: number) {
    setCells((c) => c.filter((x) => x.id !== id));
    try {
      await api.deleteCell(id);
    } catch {
      /* best effort */
    }
  }

  return (
    <div>
      <div className="card">
        <div className="row" style={{ marginBottom: 10, justifyContent: "space-between" }}>
          <div className="pill-select">
            {ENGINES.map((e) => (
              <button key={e} className={engine === e ? "active" : ""} onClick={() => setEngine(e)}>
                {e}
              </button>
            ))}
          </div>
          <span className="faint">{t("notebook_hint")}</span>
        </div>
        <div className="row">
          <input
            type="text"
            className="grow mono"
            placeholder={t(PLACEHOLDER_KEY[engine])}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCell()}
          />
          <button className="btn" disabled={busy || !input.trim()} onClick={addCell}>
            <Play size={14} style={{ verticalAlign: -2, marginRight: 4 }} />
            {t("notebook_add_cell")}
          </button>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        {loaded && cells.length === 0 && <div className="empty-state">{t("notebook_empty")}</div>}
        {[...cells].reverse().map((cell) => (
          <CellCard key={cell.id} cell={cell} onDelete={removeCell} t={t} />
        ))}
      </div>
    </div>
  );
}

function CellCard({ cell, onDelete, t }: { cell: Cell; onDelete: (id: number) => void; t: T }) {
  const result = cell.result as Record<string, unknown> | null;
  const isError = result && "error" in result && "message" in result;
  return (
    <div className="cell">
      <div className="cell-header">
        <div className="row">
          <span className="badge badge-muted">{cell.engine}</span>
          <code>{cell.input}</code>
        </div>
        <div className="row" style={{ gap: 4 }}>
          {result && typeof result.id === "string" && <CiteBadge id={result.id} onClick={copyCite} title={t("common_copy_cite")} />}
          <ConfirmDelete onConfirm={() => onDelete(cell.id)} label={t("common_delete")} confirmLabel={t("common_confirm_delete")} />
        </div>
      </div>
      {result && isError && <ErrorBlock message={String((result as { message?: string }).message ?? "error")} />}
      {result && !isError && <CellResult result={result} t={t} />}
    </div>
  );
}

type Solution = { values: Record<string, string>; numeric: Record<string, number | string | null>; verified: boolean };

function CellResult({ result, t }: { result: Record<string, unknown>; t: T }) {
  // math.solve: a list of solutions, each verified by substitution
  if (Array.isArray(result.result)) {
    const sols = result.result as Solution[];
    return (
      <div className="result-block">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
          <span className="faint">{sols.length} {t("notebook_solutions")}</span>
          <VerifiedBadge verified={result.verified as boolean | null} verifiedLabel={t("notebook_verified")} unverifiedLabel={t("notebook_unverified")} />
        </div>
        {sols.map((s, i) => (
          <div key={i} className="row result-value" style={{ gap: 18 }}>
            {Object.entries(s.values).map(([k, v]) => (
              <span key={k}>
                {k} = {v}
                {typeof s.numeric[k] === "number" && String(s.numeric[k]) !== v && (
                  <span className="faint"> ≈ {fmtNum(s.numeric[k], 10)}</span>
                )}
              </span>
            ))}
          </div>
        ))}
      </div>
    );
  }

  const latex = result.latex as string | null | undefined;
  const exact = result.exact as string | undefined;
  const decimal = result.decimal as string | null | undefined;
  const formatted = result.formatted as string | undefined;
  const isExact = result.is_exact as boolean | undefined;

  let main: ReactNode;
  if (formatted) main = <span>{formatted}</span>;
  else if (latex) main = <Latex tex={latex} display />;
  else if (exact !== undefined) main = <span>{exact}</span>;
  else if (typeof result.result === "string") main = <span>{result.result}</span>;
  else if (result.date) main = <span>{String(result.date)} · {String(result.weekday ?? "")}</span>;
  else main = <span>{JSON.stringify(result)}</span>;

  return (
    <div className="result-block">
      <div className="result-value" style={{ fontSize: 17 }}>{main}</div>
      {decimal !== undefined && decimal !== null && exact !== undefined && decimal !== exact && (
        <div className="muted mono" style={{ marginTop: 6, fontSize: 13 }}>
          <span className="eq">{isExact ? "=" : "≈"}</span>
          {decimal}
        </div>
      )}
    </div>
  );
}
