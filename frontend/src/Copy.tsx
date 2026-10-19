import { useState } from "react";
import { t } from "./i18n";

export function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } finally { ta.remove(); }
  return Promise.resolve();
}

/** A value that copies itself when clicked. Clicks do not bubble, so it works inside clickable rows. */
export function Copyable({ value, mono = false, className = "" }: { value: string | null | undefined; mono?: boolean; className?: string }) {
  const [done, setDone] = useState(false);
  if (!value) return null;
  return (
    <button type="button" className={`copyable ${mono ? "mono" : ""} ${className}`} title={t("remote.copy", { value })}
            onClick={(e) => {
              e.stopPropagation();
              copyText(value).then(() => { setDone(true); setTimeout(() => setDone(false), 1200); });
            }}>
      {value}
      {done && <span className="copied">{t("remote.copied")}</span>}
    </button>
  );
}

/** A labelled fact tile on the device card; the whole tile copies its value. */
export function Fact({ label, value, mono = false, children }: { label: string; value?: string | null; mono?: boolean; children?: React.ReactNode }) {
  const [done, setDone] = useState(false);
  if (!value && !children) return null;
  const body = children ?? <span className={mono ? "mono" : ""}>{value}</span>;
  if (!value || children) {
    return <div className="fact"><div className="fact-label">{label}</div><div className="fact-value">{body}</div></div>;
  }
  return (
    <button type="button" className="fact clickable" title={t("remote.copy", { value })}
            onClick={() => copyText(value).then(() => { setDone(true); setTimeout(() => setDone(false), 1200); })}>
      <div className="fact-label">{label}{done && <span className="fact-copied">{t("remote.copied")}</span>}</div>
      <div className="fact-value">{body}</div>
    </button>
  );
}
