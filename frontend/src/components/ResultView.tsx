import { useEffect, useRef } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { Check, X } from "lucide-react";

export function Latex({ tex }: { tex: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    try {
      katex.render(tex, ref.current, { throwOnError: false, displayMode: false });
    } catch {
      if (ref.current) ref.current.textContent = tex;
    }
  }, [tex]);
  return <span ref={ref} />;
}

export function CiteBadge({ id, onClick }: { id: string; onClick?: (id: string) => void }) {
  return (
    <button className="cite" title="Copy citation" onClick={() => onClick?.(id)}>
      [{id}]
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
  return (
    <div className="result-block" style={{ color: "var(--danger)" }}>
      {message}
    </div>
  );
}

export function copyCite(id: string) {
  const text = `[${id}]`;
  try {
    navigator.clipboard?.writeText(text);
  } catch {
    /* clipboard may be unavailable; not critical */
  }
}
