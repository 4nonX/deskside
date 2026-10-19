import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";

export type Selection = { kind: "device"; id: number } | { kind: "mac"; mac: string };

export const CONNECTIONS = ["", "usb", "usb-c", "dp", "hdmi", "vga", "dvi", "dock", "network", "wifi", "bluetooth", "serial", "audio", "power", "other"];

/** "Dymo" + "Dymo LabelWriter 550" reads as "Dymo LabelWriter 550", not twice the vendor. */
export function makeModel(manufacturer?: string | null, model?: string | null): string {
  const m = (model ?? "").trim(), v = (manufacturer ?? "").trim();
  if (!v) return m;
  if (!m) return v;
  return m.toLowerCase().startsWith(v.toLowerCase()) ? m : `${v} ${m}`;
}

export function connectionLabel(c: string | null | undefined): string {
  return c ? t(`conn.${c}` as "conn.usb") : "";
}

export function ConnectionSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {CONNECTIONS.map((c) => <option key={c} value={c}>{c ? connectionLabel(c) : t("card.none")}</option>)}
    </select>
  );
}

/** Free text with suggestions from the device types already in use. */
export function KindInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [kinds, setKinds] = useState<string[]>([]);
  useEffect(() => { api.kinds().then((k) => setKinds(k.map((x) => x.kind))).catch(() => undefined); }, []);
  return (
    <>
      <input list="deskside-kinds" value={value} onChange={(e) => onChange(e.target.value)} />
      <datalist id="deskside-kinds">{kinds.map((k) => <option key={k} value={k} />)}</datalist>
    </>
  );
}
