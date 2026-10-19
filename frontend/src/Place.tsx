import { useEffect, useState } from "react";
import { api, type Convention, type Department, type DeviceCard, type Person, type PersonLink, type Room } from "./api";
import { t } from "./i18n";
import { IconPlus, IconWarn } from "./icons";

type Wrap = (fn: () => Promise<unknown>) => () => Promise<void>;

export function roomLabel(r: Pick<Room, "number" | "name" | "building" | "floor"> | null): string {
  if (!r) return "";
  const main = [r.number, r.name].filter(Boolean).join(" ");
  const where = [r.building, r.floor].filter(Boolean).join(", ");
  return where ? `${main} (${where})` : main;
}

/** Shared lookups for rooms and departments, loaded once per card. */
function useLookups() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  useEffect(() => {
    api.rooms().then(setRooms).catch(() => undefined);
    api.departments().then(setDepartments).catch(() => undefined);
  }, []);
  return { rooms, departments };
}

export function NamingWarnings({ warnings }: { warnings: string[] }) {
  return (
    <>
      {warnings.map((w) => {
        const [kind, value] = [w.slice(0, w.indexOf(":")), w.slice(w.indexOf(":") + 1)];
        const text = kind === "ip_mismatch" ? t("warn.ip_mismatch", { ip: value }) : t("warn.name_mismatch", { pattern: value });
        return <div key={w} className="hint"><IconWarn /> {text}</div>;
      })}
    </>
  );
}

export function PlaceSection({ d, canEdit, wrap }: { d: DeviceCard; canEdit: boolean; wrap: Wrap }) {
  const { rooms, departments } = useLookups();
  if (!canEdit) {
    return (
      <section>
        <h3>{t("card.place")}</h3>
        <dl className="kv">
          <div><dt>{t("card.room")}</dt><dd>{d.room ? roomLabel(d.room) : <span className="muted">{t("card.none")}</span>}</dd></div>
          <div><dt>{t("card.department")}</dt><dd>{d.department?.name ?? <span className="muted">{t("card.none")}</span>}</dd></div>
        </dl>
      </section>
    );
  }
  return (
    <section>
      <h3>{t("card.place")}</h3>
      <dl className="kv">
        <div>
          <dt>{t("card.room")}</dt>
          <dd>
            <select value={d.room?.id ?? ""} onChange={(e) => wrap(() => e.target.value
              ? api.updateDevice(d.id, { room_id: Number(e.target.value) })
              : api.updateDevice(d.id, { clear: ["room"] }))()}>
              <option value="">{t("card.none")}</option>
              {rooms.map((r) => <option key={r.id} value={r.id}>{roomLabel(r)}</option>)}
            </select>
          </dd>
        </div>
        <div>
          <dt>{t("card.department")}</dt>
          <dd>
            <select value={d.department?.id ?? ""} onChange={(e) => wrap(() => e.target.value
              ? api.updateDevice(d.id, { department_id: Number(e.target.value) })
              : api.updateDevice(d.id, { clear: ["department"] }))()}>
              <option value="">{t("card.none")}</option>
              {departments.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </dd>
        </div>
      </dl>
    </section>
  );
}

export function Contact({ p }: { p: Pick<Person, "email" | "phone" | "mobile" | "chat"> }) {
  const items: [string, string, string | undefined][] = [
    [t("dir.phone"), p.phone ?? "", p.phone ? `tel:${p.phone.replace(/[^\d+]/g, "")}` : undefined],
    [t("dir.mobile"), p.mobile ?? "", p.mobile ? `tel:${p.mobile.replace(/[^\d+]/g, "")}` : undefined],
    [t("dir.email"), p.email ?? "", p.email ? `mailto:${p.email}` : undefined],
    [t("dir.chat"), p.chat ?? "", undefined],
  ];
  return (
    <dl className="kv contact">
      {items.filter(([, v]) => v).map(([k, v, href]) => (
        <div key={k}><dt>{k}</dt><dd>{href ? <a href={href}>{v}</a> : v}</dd></div>
      ))}
    </dl>
  );
}

export function PeopleSection({ d, canEdit, wrap }: { d: DeviceCard; canEdit: boolean; wrap: Wrap }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Person[]>([]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const h = setTimeout(() => api.people(q).then((r) => setHits(r.slice(0, 8))).catch(() => setHits([])), 200);
    return () => clearTimeout(h);
  }, [q]);
  const linked = new Set(d.people.map((p) => p.id));
  return (
    <section>
      <h3>{t("card.people")}</h3>
      {d.people.map((p: PersonLink) => (
        <div key={p.link_id} className={p.primary ? "person primary" : "person"}>
          <div className="person-head">
            <strong>{p.display_name}</strong>
            {p.primary && <span className="tag">{t("card.primary")}</span>}
            {!p.active && <span className="tag muted">{t("card.inactive")}</span>}
            {canEdit && (
              <span className="note-actions">
                {!p.primary && <button className="link" onClick={wrap(() => api.setPrimary(p.link_id))}>{t("card.makeprimary")}</button>}
                <button className="link danger" onClick={wrap(() => api.unlinkPerson(p.link_id))}>{t("card.remove")}</button>
              </span>
            )}
          </div>
          <div className="sub">{[p.title, p.department, p.username].filter(Boolean).join(" · ")}</div>
          {d.contacts_visible && <Contact p={p} />}
        </div>
      ))}
      {!d.contacts_visible && d.people.length > 0 && <div className="muted">{t("card.contactshidden")}</div>}
      {canEdit && (
        <div className="assign">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("card.addperson")} />
          {hits.filter((h) => !linked.has(h.id)).map((h) => (
            <button key={h.id} className="hit" onClick={wrap(async () => { await api.linkPerson(d.id, h.id); setQ(""); })}>
              <span><IconPlus /> {h.display_name}</span><span className="sub">{[h.department, h.username].filter(Boolean).join(" · ")}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** "Next free name" suggestion for the conventions that apply to a device kind. */
export function NextName({ kind, onUse }: { kind: string; onUse: (name: string) => void }) {
  const [conv, setConv] = useState<Convention[]>([]);
  useEffect(() => { api.naming().then(setConv).catch(() => undefined); }, []);
  const fitting = conv.filter((c) => !c.kind || !kind || c.kind.toLowerCase() === kind.toLowerCase());
  if (!fitting.length) return null;
  return (
    <div className="suggest">
      {fitting.map((c) => (
        <span key={c.key}>{t("card.nextname", { name: c.next })} <button className="link" type="button" onClick={() => onUse(c.next)}>{t("card.usename")}</button></span>
      ))}
    </div>
  );
}
