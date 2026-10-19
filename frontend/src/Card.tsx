import { useCallback, useEffect, useState } from "react";
import { portName, where } from "./portplace";
import { ApiError, api, type DeviceCard, type EventItem, type Me, type NetInfo, type Row, type UnknownCard } from "./api";
import { ago, datetime, t } from "./i18n";
import { IconClose, IconEdit, IconPin, IconPlus, IconTrash, IconWarn } from "./icons";
import { ICON_NAMES, Icon, useIconFor } from "./iconset";
import { Copyable, Fact } from "./Copy";
import { NamingWarnings, NextName, PeopleSection, PlaceSection } from "./Place";
import { RemoteButton, RemoteSection } from "./Remote";
import { NetboxSection } from "./Netbox";
import { Peripherals } from "./Peripherals";
import { DeviceHistory } from "./HistoryView";
import { ConnectionSelect, KindInput, connectionLabel, makeModel, type Selection } from "./fields";

export type { Selection } from "./fields";

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
      {data?.type === "device" && (
        <DeviceView key={data.id} d={data} canEdit={canEdit} isAdmin={me.role === "admin"} wrap={wrap}
                    onDeleted={onClose} onSelect={onSelect} />
      )}
      {data?.type === "unknown" && <UnknownView u={data} canEdit={canEdit} onSelect={onSelect} />}
    </aside>
  );
}

type Wrap = (fn: () => Promise<unknown>) => () => Promise<void>;
type Tab = "details" | "notes" | "history" | "netbox";

function statusOf(d: DeviceCard): { online: boolean; since: number | null | undefined; last: number | null | undefined } {
  const live = d.interfaces.filter((i) => i.online);
  if (live.length) return { online: true, since: Math.min(...live.map((i) => i.port_since ?? i.first_seen ?? Infinity)), last: null };
  const last = Math.max(0, ...d.interfaces.map((i) => i.last_seen ?? 0));
  return { online: false, since: null, last: last || null };
}

function DeviceView({ d, canEdit, isAdmin, wrap, onDeleted, onSelect }:
  { d: DeviceCard; canEdit: boolean; isAdmin: boolean; wrap: Wrap; onDeleted: () => void; onSelect: (s: Selection) => void }) {
  const iconFor = useIconFor();
  const [tab, setTab] = useState<Tab>("details");
  const [editing, setEditing] = useState(false);
  const pinned = d.notes.filter((n) => n.pinned);
  const main = d.interfaces.find((i) => i.online) ?? d.interfaces[0];
  const primary = d.people.find((p) => p.primary) ?? d.people[0];
  const st = statusOf(d);
  const hasNet = d.interfaces.length > 0;
  const tabs: [Tab, string, number?][] = [["details", t("card.details")], ["notes", t("card.notes"), d.notes.length],
    ["history", t("card.timeline")]];
  if (d.netbox || d.proposals.length) tabs.push(["netbox", "NetBox", d.proposals.length || undefined]);

  return (
    <>
      {editing ? <EditHead d={d} wrap={wrap} onDone={() => setEditing(false)} /> : (
        <div className="card-head">
          <Icon name={iconFor(d.kind, d.icon)} size={26} />
          <div className="card-title">
            <div className="title-row">
              <h2>{d.name}</h2>
              {canEdit && <button className="icon" title={t("card.rename")} onClick={() => setEditing(true)}><IconEdit /></button>}
              {hasNet && (
                <span className={st.online ? "pill ok" : "pill"}>
                  {st.online ? (st.since && isFinite(st.since) ? t("status.onlinesince", { t: ago(st.since) }) : t("status.online"))
                    : st.last ? t("status.lastseen", { t: ago(st.last) }) : t("status.never")}
                </span>
              )}
            </div>
            <div className="sub">
              {[d.kind, d.room ? [d.room.number, d.room.name].filter(Boolean).join(" ") : null, d.department?.name,
                makeModel(d.manufacturer, d.model)].filter(Boolean).join(" · ")}
            </div>
            {d.parent && (
              <div className="sub">{t("card.attachedto")}{" "}
                <button className="link" onClick={() => onSelect({ kind: "device", id: d.parent!.id })}>{d.parent.name}</button>
                {d.connection && ` · ${connectionLabel(d.connection)}`}
              </div>
            )}
          </div>
        </div>
      )}

      {d.remote.length > 0 && <div className="remote-row head-remote">{d.remote.map((e) => <RemoteButton key={`${e.tool}:${e.id ?? "auto"}`} e={e} />)}</div>}

      {pinned.map((n) => (
        <div key={n.id} className="warning"><IconWarn /><div>{n.text}<div className="meta">{t("note.by", { author: n.author, t: ago(n.updated_at) })}</div></div></div>
      ))}
      <NamingWarnings warnings={d.naming_warnings} />

      {(main || primary || d.documented_ip) && (
        <div className="facts">
          {main?.ip && <Fact label={t("card.ip")} value={main.ip} mono />}
          {!main?.ip && d.documented_ip && <Fact label={`${t("card.ip")} · ${t("ip.documented")}`} value={d.documented_ip} mono />}
          {main && <Fact label={t("card.mac")} value={main.mac} mono />}
          {main?.hostname && <Fact label={t("card.hostname")} value={main.hostname} mono />}
          {primary && (
            <Fact label={t("card.primary")}>
              <span>{primary.display_name}</span>
              {primary.phone && <> · <a href={`tel:${primary.phone.replace(/[^\d+]/g, "")}`}>{primary.phone}</a></>}
            </Fact>
          )}
        </div>
      )}

      <Connection d={d} onSelect={onSelect} />
      <Peripherals d={d} canEdit={canEdit} wrap={wrap} onSelect={onSelect} />

      <div className="card-tabs" role="tablist">
        {tabs.map(([k, label, n]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "ctab active" : "ctab"} onClick={() => setTab(k)}>
            {label}{n ? <span className="count-badge">{n}</span> : null}
          </button>
        ))}
      </div>

      {tab === "details" && (
        <>
          <PeopleSection d={d} canEdit={canEdit} wrap={wrap} />
          <PlaceSection d={d} canEdit={canEdit} wrap={wrap} />
          <DeviceData d={d} canEdit={canEdit} wrap={wrap} />
          <NetworkSection d={d} canEdit={canEdit} wrap={wrap} />
          <RemoteSection d={d} canEdit={canEdit} wrap={wrap} buttons={false} />
          {isAdmin && (
            <div className="danger-zone">
              <button className="danger" onClick={() => {
                if (confirm(t("card.deleteconfirm", { name: d.name }))) wrap(async () => { await api.deleteDevice(d.id); onDeleted(); })();
              }}><IconTrash /> {t("card.delete")}</button>
            </div>
          )}
        </>
      )}
      {tab === "notes" && <Notes d={d} canEdit={canEdit} wrap={wrap} />}
      {tab === "history" && <DeviceHistory deviceId={d.id} events={d.events} />}
      {tab === "netbox" && <NetboxSection d={d} isAdmin={isAdmin} wrap={wrap} />}
    </>
  );
}

function EditHead({ d, wrap, onDone }: { d: DeviceCard; wrap: Wrap; onDone: () => void }) {
  const [name, setName] = useState(d.name);
  const [kind, setKind] = useState(d.kind);
  const [desc, setDesc] = useState(d.description);
  const [icon, setIcon] = useState(d.icon);
  const iconFor = useIconFor();
  const fromNetbox = d.source === "netbox";
  return (
    <div className="edit-head">
      <input className="title-input" value={name} disabled={fromNetbox} onChange={(e) => setName(e.target.value)} autoFocus />
      {!fromNetbox && <NextName kind={kind} onUse={setName} />}
      <label>{t("card.kind")}<KindInput value={kind} onChange={setKind} /></label>
      <label>{t("card.description")}<textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
      <label>{t("card.icon")}
        <span className="icon-select">
          <Icon name={iconFor(kind, icon)} size={22} />
          <select value={icon} onChange={(e) => setIcon(e.target.value)}>
            <option value="">{t("card.icontype")}</option>
            {ICON_NAMES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </span>
      </label>
      <div className="row-actions">
        <button className="primary" disabled={!name.trim()} onClick={wrap(async () => {
          await api.updateDevice(d.id, fromNetbox ? { kind, description: desc, icon } : { name, kind, description: desc, icon });
          onDone();
        })}>{t("card.save")}</button>
        <button onClick={onDone}>{t("card.cancel")}</button>
      </div>
    </div>
  );
}

/** Where the device is plugged in: switch port, patch panel, a shared segment, and who else is there. */
function Connection({ d, onSelect }: { d: DeviceCard; onSelect: (s: Selection) => void }) {
  const iconFor = useIconFor();
  const seg = d.segment;
  if (!seg) return null;
  const via = d.netbox?.interfaces.find((i) => i.via)?.via;
  const shared = seg.behind_uplink || seg.peers.length > 0;
  return (
    <section className="tight">
      <h3>{t("card.connection")}</h3>
      <div className="chain">
        <span className="node" title={`${seg.switch} ${seg.port}`}><Icon name="switch-horizontal" size={15} /> {seg.switch} · {portName(seg.port)}{seg.alias ? ` · ${seg.alias}` : ""}</span>
        {(via || seg.place?.panel) && <><span className="arrow">→</span><span className="node">{via || seg.place?.panel}</span></>}
        {seg.place?.room && <><span className="arrow">→</span><span className="node"><Icon name="door" size={15} /> {seg.place.room}</span></>}
        {seg.place && !seg.place.documented && <><span className="arrow">→</span><span className="node dashed">{t("place.unknown")}</span></>}
        {(seg.behind_uplink || seg.peers.length > 0) && (
          <><span className="arrow">→</span><span className="node dashed">{t("card.unmanaged", { n: seg.port_mac_count ?? seg.peers.length + 1 })}</span></>
        )}
        <span className="arrow">→</span>
        <span className="node self"><Icon name={iconFor(d.kind, d.icon)} size={15} /> {d.name}</span>
      </div>
      {shared && seg.peers.length > 0 && (
        <div className="peers">
          <span className="sub">{t("card.sameport")}</span>
          {seg.peers.map((p, i) => p.type === "device" ? (
            <button key={i} className="chip small" onClick={() => onSelect({ kind: "device", id: p.id! })}>
              <Icon name={iconFor(p.kind, p.icon)} size={14} /> {p.name}
            </button>
          ) : (
            <button key={i} className="chip small unknown" onClick={() => onSelect({ kind: "mac", mac: p.mac! })}>
              <Icon name="question-mark" size={14} /> {p.name ?? p.ip ?? p.mac}{p.vendor ? ` · ${p.vendor}` : ""}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function DeviceData({ d, canEdit, wrap }: { d: DeviceCard; canEdit: boolean; wrap: Wrap }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ manufacturer: d.manufacturer, model: d.model, serial: d.serial, connection: d.connection });
  const fromNetbox = d.source === "netbox";
  if (!edit) {
    const rows: [string, React.ReactNode][] = [
      [t("dev.manufacturer"), d.manufacturer], [t("dev.model"), d.model],
      [t("dev.serial"), d.serial && <Copyable value={d.serial} mono />],
      [t("dev.connection"), d.connection && (connectionLabel(d.connection))],
      [t("dev.source"), fromNetbox ? t("dir.fromnetbox") : null],
    ];
    const shown = rows.filter(([, v]) => v);
    return (
      <section>
        <h3>{t("dev.title")} {canEdit && <button className="link small" onClick={() => setEdit(true)}>{t("dir.edit")}</button>}</h3>
        {shown.length ? <dl className="kv">{shown.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
          : <div className="muted">{t("card.none")}</div>}
      </section>
    );
  }
  return (
    <section>
      <h3>{t("dev.title")}</h3>
      <div className="person-form compact">
        {(["manufacturer", "model", "serial"] as const).map((k) => (
          <label key={k}>{t(`dev.${k}`)}<input value={f[k]} disabled={fromNetbox} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
        ))}
        <label>{t("dev.connection")}<ConnectionSelect value={f.connection} onChange={(v) => setF({ ...f, connection: v })} /></label>
        <div className="row-actions">
          <button className="primary" onClick={wrap(async () => {
            await api.updateDevice(d.id, fromNetbox ? { connection: f.connection } : f);
            setEdit(false);
          })}>{t("dir.save")}</button>
          <button onClick={() => setEdit(false)}>{t("dir.cancel")}</button>
        </div>
      </div>
    </section>
  );
}

function NetworkSection({ d, canEdit, wrap }: { d: DeviceCard; canEdit: boolean; wrap: Wrap }) {
  const [newMac, setNewMac] = useState("");
  return (
    <section>
      <h3>{t("card.network")}</h3>
      {d.interfaces.length === 0 && <div className="muted">{t("card.nointerfaces")}</div>}
      {d.interfaces.map((i) => (
        <div key={i.id} className="iface">
          <NetTable n={i} mac={i.mac} />
          {canEdit && <button className="link danger small" onClick={wrap(() => api.removeInterface(i.id))}>{t("card.removemac")}</button>}
        </div>
      ))}
      {canEdit && (
        <form className="inline" onSubmit={(e) => { e.preventDefault(); wrap(async () => { await api.addInterface(d.id, newMac); setNewMac(""); })(); }}>
          <input className="mono" placeholder="00:11:22:33:44:55" value={newMac} onChange={(e) => setNewMac(e.target.value)} />
          <button disabled={!newMac.trim()}><IconPlus /> {t("card.addmac")}</button>
        </form>
      )}
    </section>
  );
}

function NetTable({ n, mac }: { n: NetInfo; mac: string }) {
  const rows: [string, React.ReactNode][] = [
    [t("card.ip"), n.ip && <Copyable value={n.ip} mono />],
    [t("card.mac"), <Copyable value={mac} mono />],
    [t("card.hostname"), n.hostname && <Copyable value={n.hostname} mono />],
    [t("card.vendor"), n.vendor],
    [t("card.port"), n.port && (() => {
      const w = where(n.switch, n.port, n.port_place, null, n.port_alias, n.behind_uplink);
      return <>{w.main}{w.sub && <span className="sub"> · {w.sub}</span>}</>;
    })()],
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
      {canEdit && (
        <form className="note-form" onSubmit={(e) => { e.preventDefault(); wrap(async () => { await api.addNote(d.id, text, pin); setText(""); setPin(false); })(); }}>
          <textarea rows={2} placeholder={t("note.placeholder")} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row-actions">
            <label className="check"><input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} /> {t("note.pin")}</label>
            <button className="primary" disabled={!text.trim()}>{t("note.add")}</button>
          </div>
        </form>
      )}
      {!d.notes.length && !canEdit && <div className="muted">{t("card.none")}</div>}
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
  if (!events.length) return <section><div className="muted">{t("events.empty")}</div></section>;
  return (
    <section>
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
      <div className="card-head">
        <Icon name="question-mark" size={26} />
        <div className="card-title">
          <div className="title-row">
            <h2 className="unknown">{u.hostname ?? t("list.unnamed")}</h2>
            <span className={u.online ? "pill ok" : "pill"}>{u.online ? t("status.online") : u.last_seen ? t("status.lastseen", { t: ago(u.last_seen) }) : t("status.never")}</span>
          </div>
          <div className="sub">{[t("card.unknown"), u.vendor].filter(Boolean).join(" · ")}</div>
        </div>
      </div>
      <div className="facts">
        {u.ip && <Fact label={t("card.ip")} value={u.ip} mono />}
        <Fact label={t("card.mac")} value={u.mac} mono />
        {u.hostname && <Fact label={t("card.hostname")} value={u.hostname} mono />}
        {u.port && <Fact label={t("card.portplace")} value={where(u.switch, u.port, u.port_place, null, null, u.behind_uplink).main} />}
        {u.port && <Fact label={t("card.port")} value={`${u.switch} · ${portName(u.port)}`} />}
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
      <section><h3>{t("card.history")}</h3></section>
      <History events={u.events} />
    </>
  );
}
