import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type DeviceCard, type Me, type ProposalItem } from "./api";
import { datetime, t } from "./i18n";
import { IconLink } from "./icons";
import type { Selection } from "./Card";

type Wrap = (fn: () => Promise<unknown>) => () => Promise<void>;

/** The proposal as a sentence in the interface language; falls back to the server's English summary. */
export function proposalText(p: ProposalItem): string {
  const key = `nb.summary.${p.kind}` as "nb.summary.mac";
  return p.display && Object.keys(p.display).length ? t(key, p.display) : p.summary;
}

/** NetBox block on the device card: link, location, cable path, and this device's open proposals. */
export function NetboxSection({ d, isAdmin, wrap }: { d: DeviceCard; isAdmin: boolean; wrap: Wrap }) {
  if (!d.netbox && !d.proposals.length) return null;
  return (
    <section>
      <h3>NetBox</h3>
      {d.netbox ? (
        <dl className="kv">
          <div><dt>{t("nb.device")}</dt><dd><a href={d.netbox.url} target="_blank" rel="noreferrer">{d.netbox.name} <IconLink /></a></dd></div>
          {d.netbox.location && <div><dt>{t("nb.location")}</dt><dd>{d.netbox.location}</dd></div>}
          {d.netbox.interfaces.map((i) => (
            <div key={i.name}><dt>{i.name}</dt><dd>{i.endpoint ? t("nb.path", { endpoint: i.endpoint }) : <span className="muted">{t("nb.nopath")}</span>}</dd></div>
          ))}
        </dl>
      ) : <div className="muted">{t("nb.notfound")}</div>}
      {d.proposals.map((p) => (
        <div key={p.id} className="proposal">
          <span className={`ev ${p.status === "failed" ? "offline" : "new"}`}>{t(`nb.kind.${p.kind}` as "nb.kind.mac")}</span>
          <span>{proposalText(p)}</span>
          {isAdmin && d.netbox_writable && (
            <span className="note-actions">
              <button className="link" onClick={wrap(() => api.applyProposal(p.id))}>{t("nb.apply")}</button>
              <button className="link danger" onClick={wrap(() => api.dismissProposal(p.id))}>{t("nb.dismiss")}</button>
            </span>
          )}
        </div>
      ))}
    </section>
  );
}

export function NetboxView({ me, onOpen }: { me: Me; onOpen: (s: Selection) => void }) {
  const [status, setStatus] = useState("open");
  const [data, setData] = useState<{ configured: boolean; read_only: boolean; rows: ProposalItem[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.proposals(status).then(setData).catch(() => undefined), [status]);
  useEffect(() => { load(); const h = setInterval(load, 30000); return () => clearInterval(h); }, [load]);
  const run = (fn: () => Promise<unknown>) => async () => {
    setBusy(true);
    try { await fn(); } catch (e) { alert(t("err.generic", { msg: e instanceof ApiError ? e.message : String(e) })); }
    setBusy(false);
    await load();
  };
  if (!data) return null;
  if (!data.configured) return <div className="empty">{t("nb.notconfigured")}</div>;
  const admin = me.role === "admin";
  return (
    <>
      <div className="filters inline-tabs">
        {["open", "applied", "dismissed", "resolved", "all"].map((s) => (
          <button key={s} className={status === s ? "chip active" : "chip"} onClick={() => setStatus(s)}>{t(`nb.status.${s}` as "nb.status.open")}</button>
        ))}
        {admin && <button className="link sync" disabled={busy} onClick={run(() => api.netboxSync())}>{t("nb.sync")}</button>}
      </div>
      {data.read_only && <div className="hint">{t("nb.readonly")}</div>}
      <p className="muted">{t("nb.explain")}</p>
      {!data.rows.length && <div className="empty">{t("nb.none")}</div>}
      <ul className="events proposals">
        {data.rows.map((p) => (
          <li key={p.id}>
            <span className={`ev ${p.status === "failed" ? "offline" : p.status === "applied" ? "online" : "new"}`}>{t(`nb.kind.${p.kind}` as "nb.kind.mac")}</span>
            <span className="when">{datetime(p.updated_at)}</span>
            <span>
              {proposalText(p)}
              {p.device && <> · <button className="link" onClick={() => onOpen({ kind: "device", id: p.device_id! })}>{p.device}</button></>}
              {p.error && <div className="error">{p.error}</div>}
              {p.decided_by && <div className="sub">{t(`nb.status.${p.status}` as "nb.status.open")} · {p.decided_by}</div>}
            </span>
            {admin && (p.status === "open" || p.status === "failed") && !data.read_only && (
              <span className="row-actions">
                <button className="primary" disabled={busy} onClick={run(() => api.applyProposal(p.id))}>{t("nb.apply")}</button>
                <button disabled={busy} onClick={run(() => api.dismissProposal(p.id))}>{t("nb.dismiss")}</button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
