import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type DeviceCard, type EventItem, type Me, type NetInfo, type Row, type UnknownCard } from "./api";
import { ago, datetime, t } from "./i18n";
import { IconClose, IconEdit, IconPin, IconPlus, IconTrash, IconWarn } from "./icons";
import { NamingWarnings, NextName, PeopleSection, PlaceSection } from "./Place";
import { RemoteSection } from "./Remote";

export type Selection = { kind: "device"; id: number } | { kind: "mac"; mac: string };

interface Props { sel: Selection; me: Me; tick: number; onClose: () => void; onSelect: (s: Selection) => void }

export function Card({ sel, me, tick, onClose, onSelect }: Props) {
  const [data, setData] = useState<DeviceCard | UnknownCard | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    try {
      if (sel.kind === "device") setData(await api.device(sel.id));
      else {
        const r = await api.mac(sel.mac);
        if (r.type === "redirect") onSelect({ kind: "device", id: r.device_id }); else setData(r);
      }
      setErr("");
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }, [sel, onSelect]);
  useEffect(() => { load(); }, [load, tick]);

  const canEdit = me.role !== "viewer";
  const wrap = (fn: () => Promise<unknown>) => async () => {
    try { await fn(); await load(); } catch (e) { alert(t("err.generic", { msg: e instanceof ApiError ? e.message : String(e) })); }
  };

  return (
    <aside className="card">
      <button className="icon close" onClick={onClose} title={t("card.close")}><IconClose /></button>
      {err && <div className="error">{err}</div>}
      {data?.type === "device" && <DeviceView d={data} canEdit={canEdit} isAdmin={me.role === "admin"} wrap={wrap} onDeleted={onClose} />}
      {data?.type === "unknown" && <UnknownView u={data} canEdit={canEdit} onSelect={onSelect} />}
    </aside>
  );
}

type Wrap = (fn: () => Promise<unknown>) => () => Promise<void>;

function DeviceView({ d, canEdit, isAdmin, wrap, onDeleted }:
  { d: DeviceCard; canEdit: boolean; isAdmin: boolean; wrap: Wrap; onDeleted: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(d.name);
  const [kind, setKind] = useState(d.kind);
  const [desc, setDesc] = useState(d.description);
  const [newMac, setNewMac] = useState("");
  useEffect(() => { setName(d.name); setKind(d.kind); setDesc(d.description); }, [d]);
  const pinned = d.notes.filter((n) => n.pinned);

  return (
    <>
      {editing ? (
        <div className="edit-head">
          <input className="title-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <NextName kind={kind} onUse={setName} />
          <label>{t("card.kind")}<input value={kind} onChange={(e) => setKind(e.target.value)} /></label>
          <label>{t("card.description")}<textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
          <div className="row-actions">
            <button className="primary" disabled={!name.trim()}
                    onClick={wrap(async () => { await api.updateDevice(d.id, { name, kind, description: desc }); setEditing(false); })}>
              {t("card.save")}
            </button>
            <button onClick={() => setEditing(false)}>{t("card.cancel")}</button>
          </div>
        </div>
      ) : (
        <div className="head">
          <h2>{d.name}</h2>
          {canEdit && <button className="icon" title={t("card.rename")} onClick={() => setEditing(true)}><IconEdit /></button>}
          {(d.kind || d.description) && <div className="sub">{[d.kind, d.description].filter(Boolean).join(" · ")}</div>}
        </div>
      )}

      {pinned.map((n) => (
        <div key={n.id} className="warning"><IconWarn /><div>{n.text}<div className="meta">{t("note.by", { author: n.author, t: ago(n.updated_at) })}</div></div></div>
      ))}
      <NamingWarnings warnings={d.naming_warnings} />

      <RemoteSection d={d} canEdit={canEdit} wrap={wrap} />

      <PeopleSection d={d} canEdit={canEdit} wrap={wrap} />
      <PlaceSection d={d} canEdit={canEdit} wrap={wrap} />

      <section>
        <h3>{t("card.network")}</h3>
        {d.interfaces.length === 0 && <div className="muted">{t("card.nointerfaces")}</div>}
        {d.interfaces.map((i) => (
          <div key={i.id} className="iface">
            <NetTable n={i} mac={i.mac} />
            {canEdit && (
              <button className="link danger" onClick={wrap(() => api.removeInterface(i.id))}>{t("card.removemac")}</button>
            )}
          </div>
        ))}
        {canEdit && (
          <form className="inline" onSubmit={(e) => { e.preventDefault(); wrap(async () => { await api.addInterface(d.id, newMac); setNewMac(""); })(); }}>
            <input className="mono" placeholder="00:11:22:33:44:55" value={newMac} onChange={(e) => setNewMac(e.target.value)} />
            <button disabled={!newMac.trim()}><IconPlus /> {t("card.addmac")}</button>
          </form>
        )}
      </section>

      <Notes d={d} canEdit={canEdit} wrap={wrap} />
      <History events={d.events} />

      {isAdmin && (
        <div className="danger-zone">
          <button className="danger" onClick={() => {
            if (confirm(t("card.deleteconfirm", { name: d.name }))) wrap(async () => { await api.deleteDevice(d.id); onDeleted(); })();
          }}><IconTrash /> {t("card.delete")}</button>
        </div>
      )}
    </>
  );
}

function NetTable({ n, mac }: { n: NetInfo; mac: string }) {
  const rows: [string, React.ReactNode][] = [
    [t("card.ip"), n.ip && <span className="mono">{n.ip}</span>],
    [t("card.mac"), <span className="mono">{mac}</span>],
    [t("card.hostname"), n.hostname],
    [t("card.vendor"), n.vendor],
    [t("card.port"), n.port && <>{n.switch} {n.port}{n.port_alias ? ` (${n.port_alias})` : ""}</>],
    [t("card.vlan"), n.vlan],
    [t("card.addressing"), n.ip ? (n.dhcp ? t("card.dhcp") : t("card.fixed")) : null],
    [t("col.seen"), <><span className={n.online ? "dot on" : "dot"} />
      {n.online ? t("status.online") : n.last_seen ? t("status.lastseen", { t: ago(n.last_seen) }) : t("status.never")}</>],
    [t("card.portsince"), n.port_since ? datetime(n.port_since) : null],
    [t("card.firstseen"), n.first_seen ? datetime(n.first_seen) : null],
    [t("card.sources"), n.sources?.length ? n.sources.join(", ") : null],
  ];
  return (
    <>
      {n.behind_uplink && n.port && <div className="hint">{t("card.behind", { n: n.port_mac_count ?? "?" })}</div>}
      <dl className="kv">
        {rows.filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
    </>
  );
}

function Notes({ d, canEdit, wrap }: { d: DeviceCard; canEdit: boolean; wrap: Wrap }) {
  const [text, setText] = useState("");
  const [pin, setPin] = useState(false);
  return (
    <section>
      <h3>{t("card.notes")}</h3>
      {canEdit && (
        <form className="note-form" onSubmit={(e) => { e.preventDefault(); wrap(async () => { await api.addNote(d.id, text, pin); setText(""); setPin(false); })(); }}>
          <textarea rows={2} placeholder={t("note.placeholder")} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row-actions">
            <label className="check"><input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} /> {t("note.pin")}</label>
            <button className="primary" disabled={!text.trim()}>{t("note.add")}</button>
          </div>
        </form>
      )}
      {d.notes.map((n) => (
        <div key={n.id} className={n.pinned ? "note pinned" : "note"}>
          <div className="note-text">{n.text}</div>
          <div className="meta">
            {n.pinned && <span className="tag"><IconPin /> {t("note.pinned")}</span>}
            {t("note.by", { author: n.author, t: datetime(n.created_at) })}
            {canEdit && (
              <span className="note-actions">
                <button className="link" onClick={wrap(() => api.updateNote(n.id, { pinned: !n.pinned }))}>{n.pinned ? t("note.unpin") : t("note.pin")}</button>
                <button className="link danger" onClick={wrap(() => api.deleteNote(n.id))}>{t("note.delete")}</button>
              </span>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

function History({ events }: { events: EventItem[] }) {
  if (!events.length) return null;
  return (
    <section>
      <h3>{t("card.history")}</h3>
      <ul className="events compact">
        {events.map((e, i) => <li key={i}><span className={`ev ${e.kind}`}>{e.kind}</span><span className="when">{datetime(e.ts)}</span><span>{e.message}</span></li>)}
      </ul>
    </section>
  );
}

function UnknownView({ u, canEdit, onSelect }: { u: UnknownCard; canEdit: boolean; onSelect: (s: Selection) => void }) {
  const suggested = u.suggested_name ?? (u.hostname ?? "").split(".")[0];
  const [name, setName] = useState(suggested);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Row[]>([]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const h = setTimeout(() => api.devices(q, "known").then((r) => setHits(r.rows.slice(0, 8))).catch(() => setHits([])), 200);
    return () => clearTimeout(h);
  }, [q]);
  const fail = (e: unknown) => alert(t("err.generic", { msg: e instanceof ApiError ? e.message : String(e) }));
  return (
    <>
      <div className="head">
        <h2 className="unknown">{u.hostname ?? t("list.unnamed")}</h2>
        <div className="sub">{t("card.unknown")}</div>
      </div>
      {canEdit && (
        <section className="adopt">
          <form className="inline" onSubmit={async (e) => {
            e.preventDefault();
            try { const r = await api.createDevice({ name: name.trim(), mac: u.mac }); onSelect({ kind: "device", id: r.id }); } catch (ex) { fail(ex); }
          }}>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("col.name")} />
            <button className="primary" disabled={!name.trim()}><IconPlus /> {t("card.create")}</button>
          </form>
          <NextName kind="" onUse={setName} />
          <div className="assign">
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("card.assignsearch")} aria-label={t("card.assign")} />
            {hits.map((h) => (
              <button key={h.id} className="hit" onClick={async () => {
                try { await api.addInterface(h.id!, u.mac); onSelect({ kind: "device", id: h.id! }); } catch (ex) { fail(ex); }
              }}>{h.name} <span className="sub">{h.ip}</span></button>
            ))}
          </div>
        </section>
      )}
      <section>
        <h3>{t("card.network")}</h3>
        <NetTable n={u} mac={u.mac} />
      </section>
      <History events={u.events} />
    </>
  );
}
