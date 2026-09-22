import { useEffect, useRef, useState, type ReactNode } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { Check, Trash2, X } from "lucide-react";

export function Latex({ tex, display = false }: { tex: string; display?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    try {
      katex.render(tex, ref.current, { throwOnError: false, displayMode: display });
    } catch {
      if (ref.current) ref.current.textContent = tex;
    }
  }, [tex, display]);
  return <span ref={ref} />;
}

export function CiteBadge({ id, onClick, title }: { id: string; onClick?: (id: string) => void; title?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="cite"
      title={title ?? "Copy citation"}
      onClick={() => {
        onClick?.(id);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? <Check size={11} style={{ verticalAlign: -1 }} /> : null} [{id}]
    </button>
  );
}

export function VerifiedBadge({ verified, verifiedLabel, unverifiedLabel }: { verified: boolean | null | undefined; verifiedLabel: string; unverifiedLabel: string }) {
  if (verified === null || verified === undefined) return null;
  return verified ? (
    <span className="badge badge-ok">
      <Check size={12} /> {verifiedLabel}
    </span>
  ) : (
    <span className="badge badge-error">
      <X size={12} /> {unverifiedLabel}
    </span>
  );
}

export function ErrorBlock({ message }: { message: string }) {
  return <div className="error-block">{message}</div>;
}

export function copyCite(id: string) {
  const text = `[${id}]`;
  try {
    navigator.clipboard?.writeText(text);
  } catch {
    /* clipboard may be unavailable; not critical */
  }
}

/** Numbers for people: up to 6 significant digits, full value on hover. */
export function fmtNum(v: unknown, digits = 6): string {
  if (typeof v !== "number") return v === null || v === undefined ? "–" : String(v);
  if (Number.isInteger(v)) return v.toLocaleString();
  const abs = Math.abs(v);
  if (abs !== 0 && (abs < 1e-4 || abs >= 1e9)) return v.toExponential(3);
  return Number(v.toPrecision(digits)).toLocaleString(undefined, { maximumFractionDigits: 8 });
}

function fmtValue(v: unknown): ReactNode {
  if (typeof v === "number") return <span title={String(v)}>{fmtNum(v)}</span>;
  if (typeof v === "boolean") return v ? "true" : "false";
  if (v === null || v === undefined) return "–";
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x !== "object")) return v.map((x) => fmtNum(x)).join(", ");
    return JSON.stringify(v);
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Every remaining field of a result, as a tidy two-column list. */
export function KeyValues({ data, skip = [] }: { data: Record<string, unknown>; skip?: string[] }) {
  const hidden = new Set(["id", "cite", ...skip]);
  const entries = Object.entries(data).filter(([k]) => !hidden.has(k));
  if (entries.length === 0) return null;
  return (
    <dl className="kv">
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd>{fmtValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Headline({ value, unit, label }: { value: ReactNode; unit?: ReactNode; label?: ReactNode }) {
  return (
    <div>
      {label && <div className="headline-label">{label}</div>}
      <div className="headline">
        <span className="headline-value">{value}</span>
        {unit && <span className="headline-unit">{unit}</span>}
      </div>
    </div>
  );
}

/** Two-step delete: the first click arms it, the second (within 4 s) confirms. No browser dialogs. */
export function ConfirmDelete({ onConfirm, label, confirmLabel }: { onConfirm: () => void; label: string; confirmLabel: string }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  return armed ? (
    <button className="icon-btn confirm-danger" onClick={onConfirm} title={confirmLabel}>
      {confirmLabel}
    </button>
  ) : (
    <button className="icon-btn" onClick={() => setArmed(true)} title={label}>
      <Trash2 size={14} />
    </button>
  );
}
