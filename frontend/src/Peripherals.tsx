import { useEffect, useState } from "react";
import { api, type DeviceCard, type Row } from "./api";
import { t } from "./i18n";
import { IconPlus } from "./icons";
import { Icon, useIconFor } from "./iconset";
import { ConnectionSelect, KindInput, connectionLabel, makeModel, type Selection } from "./fields";

type Wrap = (fn: () => Promise<unknown>) => () => Promise<void>;

export function Peripherals({ d, canEdit, wrap, onSelect }:
  { d: DeviceCard; canEdit: boolean; wrap: Wrap; onSelect: (s: Selection) => void }) {
  const iconFor = useIconFor();
  const [mode, setMode] = useState<"" | "new" | "attach">("");
  // Virtual machines run on this host; they are not attached hardware and get their own list.
  const vms = d.children.filter((c) => c.connection === "virtual");
  const attached = d.children.filter((c) => c.connection !== "virtual");
  return (
    <>
    {vms.length > 0 && (
      <section className="tight">
        <h3>{t("vm.title")}</h3>
        <div className="peripherals">
          {vms.map((c) => (
            <div key={c.id} className="periph" role="button" tabIndex={0}
                 onClick={() => onSelect({ kind: "device", id: c.id })}
                 onKeyDown={(e) => e.key === "Enter" && onSelect({ kind: "device", id: c.id })}>
              <Icon name={iconFor(c.kind, c.icon)} size={20} />
              <div className="periph-text">
                <div className="periph-name">{c.name}</div>
                <div className="sub">{c.kind}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
    )}
    {(attached.length > 0 || canEdit) && (
    <section className="tight">
      <h3>{t("per.title")}</h3>
      {attached.length > 0 && (
        <div className="peripherals">
          {attached.map((c) => (
            <div key={c.id} className="periph" role="button" tabIndex={0}
                 onClick={() => onSelect({ kind: "device", id: c.id })}
                 onKeyDown={(e) => e.key === "Enter" && onSelect({ kind: "device", id: c.id })}>
              <Icon name={iconFor(c.kind, c.icon)} size={20} />
              <div className="periph-text">
                <div className="periph-name">{c.name}</div>
                <div className="sub">
                  {[connectionLabel(c.connection), makeModel(c.manufacturer, c.model),
                    c.children ? t("per.more", { n: c.children }) : null].filter(Boolean).join(" · ") || c.kind}
                </div>
              </div>
              {canEdit && (
                <button className="link danger small" title={t("per.detach")}
                        onClick={(e) => { e.stopPropagation(); wrap(() => api.updateDevice(c.id, { clear: ["parent"] }))(); }}>
                  {t("per.detach")}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {canEdit && mode === "" && (
        <div className="row-actions">
          <button className="link small" onClick={() => setMode("new")}><IconPlus /> {t("per.new")}</button>
          <button className="link small" onClick={() => setMode("attach")}>{t("per.attach")}</button>
        </div>
      )}
      {mode === "new" && <NewPeripheral d={d} wrap={wrap} onDone={() => setMode("")} />}
      {mode === "attach" && <AttachExisting d={d} wrap={wrap} onDone={() => setMode("")} />}
    </section>
    )}
    </>
  );
}

function NewPeripheral({ d, wrap, onDone }: { d: DeviceCard; wrap: Wrap; onDone: () => void }) {
  const [f, setF] = useState({ name: "", kind: "", connection: "usb", manufacturer: "", model: "", serial: "" });
  return (
    <div className="person-form compact">
      <label>{t("col.name")}<input autoFocus value={f.name} placeholder={`${d.name} Monitor`} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label>{t("card.kind")}<KindInput value={f.kind} onChange={(v) => setF({ ...f, kind: v })} /></label>
      <label>{t("dev.connection")}<ConnectionSelect value={f.connection} onChange={(v) => setF({ ...f, connection: v })} /></label>
      <label>{t("dev.manufacturer")}<input value={f.manufacturer} onChange={(e) => setF({ ...f, manufacturer: e.target.value })} /></label>
      <label>{t("dev.model")}<input value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} /></label>
      <label>{t("dev.serial")}<input value={f.serial} onChange={(e) => setF({ ...f, serial: e.target.value })} /></label>
      <div className="row-actions">
        <button className="primary" disabled={!f.name.trim()} onClick={wrap(async () => {
          await api.createDevice({ ...f, name: f.name.trim(), parent_id: d.id });
          onDone();
        })}>{t("dir.save")}</button>
        <button onClick={onDone}>{t("dir.cancel")}</button>
      </div>
    </div>
  );
}

function AttachExisting({ d, wrap, onDone }: { d: DeviceCard; wrap: Wrap; onDone: () => void }) {
  const iconFor = useIconFor();
  const [q, setQ] = useState("");
  const [conn, setConn] = useState("usb");
  const [hits, setHits] = useState<Row[]>([]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const h = setTimeout(() => api.devices(q, "known")
      .then((r) => setHits(r.rows.filter((x) => x.id !== d.id && x.parent_id !== d.id).slice(0, 8))).catch(() => setHits([])), 200);
    return () => clearTimeout(h);
  }, [q, d.id]);
  return (
    <div className="assign">
      <div className="inline">
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("card.assignsearch")} />
        <ConnectionSelect value={conn} onChange={setConn} />
        <button onClick={onDone}>{t("dir.cancel")}</button>
      </div>
      {hits.map((h) => (
        <button key={h.id} className="hit" onClick={wrap(async () => { await api.updateDevice(h.id!, { parent_id: d.id, connection: conn }); onDone(); })}>
          <span><Icon name={iconFor(h.kind, h.icon)} size={16} /> {h.name}</span>
          <span className="sub">{h.parent ? t("per.currently", { name: h.parent }) : h.kind}</span>
        </button>
      ))}
    </div>
  );
}
