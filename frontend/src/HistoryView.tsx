import { useCallback, useEffect, useState } from "react";
import { api, type EventItem, type HistoryItem } from "./api";
import { ago, datetime, t } from "./i18n";
import type { Selection } from "./fields";

export const EVENT_KINDS = ["new", "online", "offline", "moved", "ip_changed", "scheme", "busy_port", "discovery", "netbox"];

export function kindLabel(kind: string): string {
  return t(`evk.${kind}` as "evk.new");
}

function duration(start: number, end: number | null): string {
  const s = (end ?? Date.now() / 1000) - start;
  if (s < 3600) return t("dur.min", { n: Math.max(1, Math.round(s / 60)) });
  if (s < 86400 * 2) return t("dur.h", { n: Math.round(s / 3600) });
  return t("dur.d", { n: Math.round(s / 86400) });
}

/** Device card tab: where the device was plugged in and which address it had, then its events. */
export function DeviceHistory({ deviceId, events }: { deviceId: number; events: EventItem[] }) {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  useEffect(() => { api.history(deviceId).then(setItems).catch(() => setItems([])); }, [deviceId]);
  const ports = (items ?? []).filter((h) => h.kind === "port");
  const ips = (items ?? []).filter((h) => h.kind === "ip");
  return (
    <section>
      {items && !items.length && !events.length && <div className="muted">{t("events.empty")}</div>}
      {ports.length > 0 && (
        <>
          <h3>{t("hist.ports")}</h3>
          <ul className="timeline">
            {ports.map((h, i) => (
              <li key={i} className={h.end ? "" : "current"}>
                <span className="tl-value">{h.switch} {h.value}</span>
                <span className="tl-when">{datetime(h.start)} – {h.end ? datetime(h.end) : t("hist.now")}</span>
                <span className="tl-dur">{duration(h.start, h.end)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {ips.length > 0 && (
        <>
          <h3>{t("hist.ips")}</h3>
          <ul className="timeline">
            {ips.map((h, i) => (
              <li key={i} className={h.end ? "" : "current"}>
                <span className="tl-value mono">{h.value}</span>
                <span className="tl-when">{datetime(h.start)} – {h.end ? datetime(h.end) : t("hist.now")}</span>
                <span className="tl-dur">{duration(h.start, h.end)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {events.length > 0 && (
        <>
          <h3>{t("card.history")}</h3>
          <ul className="events compact">
            {events.map((e, i) => (
              <li key={i}><span className={`ev ${e.kind}`}>{kindLabel(e.kind)}</span><span className="when">{datetime(e.ts)}</span><span>{e.message}</span></li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/** The events page: filter by kind and text, newest first, with "load older". */
export function EventsPage({ onOpen }: { onOpen: (s: Selection) => void }) {
  const [kinds, setKinds] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [items, setItems] = useState<EventItem[]>([]);
  const [more, setMore] = useState(false);
  const load = useCallback(async (before?: number) => {
    const page = await api.events({ limit: 200, kind: kinds.join(","), q, before });
    setItems((cur) => (before ? [...cur, ...page] : page));
    setMore(page.length === 200);
  }, [kinds, q]);
  useEffect(() => { const h = setTimeout(() => load().catch(() => undefined), 200); return () => clearTimeout(h); }, [load]);
  useEffect(() => { const h = setInterval(() => load().catch(() => undefined), 30000); return () => clearInterval(h); }, [load]);
  const toggle = (k: string) => setKinds((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]));
  return (
    <>
      <div className="filters inline-tabs wrap">
        <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("events.search")} />
        {EVENT_KINDS.map((k) => (
          <button key={k} className={kinds.includes(k) ? "chip active" : "chip"} onClick={() => toggle(k)}>{kindLabel(k)}</button>
        ))}
      </div>
      {!items.length && <div className="empty">{t("events.empty")}</div>}
      <ul className="events">
        {items.map((e) => (
          <li key={e.id} className={e.mac || e.device_id ? "clickable" : ""}
              onClick={() => e.device_id ? onOpen({ kind: "device", id: e.device_id }) : e.mac && onOpen({ kind: "mac", mac: e.mac })}>
            <span className={`ev ${e.kind}`}>{kindLabel(e.kind)}</span>
            <span className="when" title={datetime(e.ts)}>{ago(e.ts)}</span>
            <span>{e.message}</span>
          </li>
        ))}
      </ul>
      {more && <button className="more" onClick={() => load(items[items.length - 1]?.id)}>{t("events.older")}</button>}
    </>
  );
}
