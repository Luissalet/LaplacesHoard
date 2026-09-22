import { useEffect, useState } from "react";
import { Play, Trash2 } from "lucide-react";
import { api, type Cell } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, ErrorBlock, Latex, VerifiedBadge, copyCite } from "../components/ResultView";

const ENGINES = ["calc", "math", "units", "dates"] as const;
type Engine = (typeof ENGINES)[number];

const PLACEHOLDER_KEY: Record<Engine, DictKey> = {
  calc: "notebook_placeholder_calc",
  math: "notebook_placeholder_math",
  units: "notebook_placeholder_units",
  dates: "notebook_placeholder_dates",
};

export function NotebookPage({ t }: { t: (k: DictKey) => string }) {
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
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="pill-select">
            {ENGINES.map((e) => (
              <button key={e} className={engine === e ? "active" : ""} onClick={() => setEngine(e)}>
                {e}
              </button>
            ))}
          </div>
        </div>
        <div className="row">
          <input
            type="text"
            className="grow"
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
          <CellCard key={cell.id} cell={cell} onDelete={removeCell} />
        ))}
      </div>
    </div>
  );
}

function CellCard({ cell, onDelete }: { cell: Cell; onDelete: (id: number) => void }) {
  const result = cell.result as Record<string, unknown> | null;
  const isError = result && "error" in result;
  return (
    <div className="cell">
      <div className="cell-header">
        <div className="row">
          <span className="badge badge-muted">{cell.engine}</span>
          <code>{cell.input}</code>
        </div>
        <button className="icon-btn" onClick={() => onDelete(cell.id)} title="Delete">
          <Trash2 size={14} />
        </button>
      </div>
      {result && isError && <ErrorBlock message={String((result as { message?: string }).message ?? "error")} />}
      {result && !isError && <CellResult result={result} />}
    </div>
  );
}

function CellResult({ result }: { result: Record<string, unknown> }) {
  const id = result.id as string | undefined;
  const exact = result.exact as string | undefined;
  const latex = result.latex as string | null | undefined;
  const formatted = result.formatted as string | undefined;
  const decimal = result.decimal;
  const verified = (result as { verified?: boolean | null }).verified;

  return (
    <div className="result-block">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="result-value">
          {latex ? <Latex tex={latex} /> : <span>{exact ?? formatted ?? formatFallback(result)}</span>}
        </div>
        <div className="row">
          <VerifiedBadge verified={verified} verifiedLabel="verified" unverifiedLabel="unverified" />
          {id && <CiteBadge id={id} onClick={copyCite} />}
        </div>
      </div>
      {decimal !== undefined && decimal !== null && exact !== undefined && String(decimal) !== exact && (
        <div className="faint" style={{ marginTop: 4 }}>≈ {String(decimal)}</div>
      )}
      {formatted && exact !== undefined && (
        <div className="faint" style={{ marginTop: 4 }}>{formatted}</div>
      )}
    </div>
  );
}

function formatFallback(result: Record<string, unknown>): string {
  if (typeof result.result === "string") return result.result;
  if (result.date) return String(result.date);
  return JSON.stringify(result);
}
