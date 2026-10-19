import { Fragment, useCallback, useEffect, useState } from "react";
import { ApiError, api, type Department, type Me, type Person, type PersonInput, type Room, type RoomInput } from "./api";
import { t } from "./i18n";
import { Contact, roomLabel } from "./Place";
import { KindsEditor } from "./Kinds";

type Section = "rooms" | "departments" | "people" | "kinds";

function useRun(reload: () => Promise<unknown>) {
  return (fn: () => Promise<unknown>) => async () => {
    try { await fn(); await reload(); } catch (e) { alert(t("err.generic", { msg: e instanceof ApiError ? e.message : String(e) })); }
  };
}

export function DirectoryView({ me, onKindsChanged }: { me: Me; onKindsChanged: () => void }) {
  const [section, setSection] = useState<Section>("rooms");
  const canEdit = me.role !== "viewer";
  const [hasDirectory, setHasDirectory] = useState(false);
  useEffect(() => { api.sources().then((r) => setHasDirectory(r.sources.some((x) => x.type === "ldap"))).catch(() => undefined); }, []);
  return (
    <>
      <div className="filters inline-tabs">
        {(["rooms", "departments", "people", "kinds"] as Section[]).map((s) => (
          <button key={s} className={section === s ? "chip active" : "chip"} onClick={() => setSection(s)}>{t(`dir.${s}` as const)}</button>
        ))}
        {me.role === "admin" && hasDirectory && <SyncButton />}
      </div>
      {section === "rooms" && <Rooms canEdit={canEdit} />}
      {section === "departments" && <Departments canEdit={canEdit} />}
      {section === "people" && <People canEdit={canEdit} />}
      {section === "kinds" && <KindsEditor canEdit={canEdit} onChanged={onKindsChanged} />}
    </>
  );
}

function SyncButton() {
  const [busy, setBusy] = useState(false);
  return (
    <button className="link sync" disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        const r = await api.directorySync();
        alert(r.ok ? t("dir.synced") : t("err.generic", { msg: r.error ?? "" }));
      } catch (e) { alert(t("err.generic", { msg: e instanceof ApiError ? e.message : String(e) })); }
      setBusy(false);
    }}>{t("dir.sync")}</button>
  );
}

const emptyRoom: RoomInput = { number: "", name: "", building: "", floor: "", description: "" };

function Rooms({ canEdit }: { canEdit: boolean }) {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [edit, setEdit] = useState<number | "new" | null>(null);
  const [form, setForm] = useState<RoomInput>(emptyRoom);
  const load = useCallback(() => api.rooms().then(setRooms), []);
  useEffect(() => { load(); }, [load]);
  const run = useRun(load);
  const fields: (keyof RoomInput)[] = ["number", "name", "building", "floor", "description"];
  const editor = (
    <tr className="editing">
      {fields.map((f) => <td key={f}><input value={form[f]} placeholder={t(`dir.${f}` as const)} onChange={(e) => setForm({ ...form, [f]: e.target.value })} /></td>)}
      <td className="row-actions">
        <button className="primary" disabled={!form.number.trim() && !form.name.trim()} onClick={run(async () => {
          if (edit === "new") await api.createRoom(form); else if (typeof edit === "number") await api.updateRoom(edit, form);
          setEdit(null);
        })}>{t("dir.save")}</button>
        <button onClick={() => setEdit(null)}>{t("dir.cancel")}</button>
      </td>
    </tr>
  );
  return (
    <table className="dir">
      <thead><tr>{fields.map((f) => <th key={f}>{t(`dir.${f}` as const)}</th>)}<th>{t("dir.devices")}</th></tr></thead>
      <tbody>
        {rooms.map((r) => edit === r.id ? <Fragment key={r.id}>{editor}</Fragment> : (
          <tr key={r.id}>
            <td>{r.number}</td><td>{r.name}</td><td>{r.building}</td><td>{r.floor}</td><td className="sub">{r.description}</td>
            <td>
              {r.devices ?? 0}
              {r.source === "netbox" && <span className="tag muted"> {t("dir.fromnetbox")}</span>}
              {canEdit && r.source !== "netbox" && (
                <span className="note-actions">
                  <button className="link" onClick={() => { setEdit(r.id); setForm({ number: r.number, name: r.name, building: r.building, floor: r.floor, description: r.description }); }}>{t("dir.edit")}</button>
                  <button className="link danger" onClick={() => confirm(t("dir.deleteconfirm", { name: roomLabel(r) })) && run(() => api.deleteRoom(r.id))()}>{t("dir.delete")}</button>
                </span>
              )}
            </td>
          </tr>
        ))}
        {edit === "new" && editor}
      </tbody>
      {canEdit && edit === null && (
        <tfoot><tr><td colSpan={6}><button onClick={() => { setForm(emptyRoom); setEdit("new"); }}>{t("dir.add")}</button></td></tr></tfoot>
      )}
    </table>
  );
}

function Departments({ canEdit }: { canEdit: boolean }) {
  const [deps, setDeps] = useState<Department[]>([]);
  const [edit, setEdit] = useState<number | "new" | null>(null);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const load = useCallback(() => api.departments().then(setDeps), []);
  useEffect(() => { load(); }, [load]);
  const run = useRun(load);
  const editor = (
    <tr className="editing">
      <td><input value={name} placeholder={t("dir.name")} onChange={(e) => setName(e.target.value)} /></td>
      <td><input value={desc} placeholder={t("dir.description")} onChange={(e) => setDesc(e.target.value)} /></td>
      <td colSpan={2} className="row-actions">
        <button className="primary" disabled={!name.trim()} onClick={run(async () => {
          if (edit === "new") await api.createDepartment({ name, description: desc });
          else if (typeof edit === "number") await api.updateDepartment(edit, { name, description: desc });
          setEdit(null);
        })}>{t("dir.save")}</button>
        <button onClick={() => setEdit(null)}>{t("dir.cancel")}</button>
      </td>
    </tr>
  );
  return (
    <table className="dir">
      <thead><tr><th>{t("dir.name")}</th><th>{t("dir.description")}</th><th>{t("dir.devices")}</th><th>{t("dir.persons")}</th></tr></thead>
      <tbody>
        {deps.map((d) => edit === d.id ? <Fragment key={d.id}>{editor}</Fragment> : (
          <tr key={d.id}>
            <td>{d.name} {d.source === "directory" && <span className="tag muted">{t("dir.fromdirectory")}</span>}</td>
            <td className="sub">{d.description}</td>
            <td>{d.devices ?? 0}</td>
            <td>
              {d.people ?? 0}
              {canEdit && (
                <span className="note-actions">
                  <button className="link" onClick={() => { setEdit(d.id); setName(d.name); setDesc(d.description); }}>{t("dir.edit")}</button>
                  {d.source !== "directory" && (
                    <button className="link danger" onClick={() => confirm(t("dir.deleteconfirm", { name: d.name })) && run(() => api.deleteDepartment(d.id))()}>{t("dir.delete")}</button>
                  )}
                </span>
              )}
            </td>
          </tr>
        ))}
        {edit === "new" && editor}
      </tbody>
      {canEdit && edit === null && (
        <tfoot><tr><td colSpan={4}><button onClick={() => { setName(""); setDesc(""); setEdit("new"); }}>{t("dir.add")}</button></td></tr></tfoot>
      )}
    </table>
  );
}

const emptyPerson: PersonInput = { display_name: "", username: "", email: "", phone: "", mobile: "", chat: "", title: "", department_id: null };

function People({ canEdit }: { canEdit: boolean }) {
  const [people, setPeople] = useState<Person[]>([]);
  const [deps, setDeps] = useState<Department[]>([]);
  const [q, setQ] = useState("");
  const [inactive, setInactive] = useState(false);
  const [edit, setEdit] = useState<number | "new" | null>(null);
  const [form, setForm] = useState<PersonInput>(emptyPerson);
  const load = useCallback(() => api.people(q, inactive).then(setPeople), [q, inactive]);
  useEffect(() => { const h = setTimeout(load, 150); return () => clearTimeout(h); }, [load]);
  useEffect(() => { api.departments().then(setDeps).catch(() => undefined); }, []);
  const run = useRun(load);
  const text: (keyof PersonInput)[] = ["display_name", "title", "username", "email", "phone", "mobile", "chat"];
  const label = (k: keyof PersonInput) => t(k === "display_name" ? "dir.displayname" : (`dir.${k}` as "dir.email"));
  return (
    <>
      <div className="filters inline-tabs">
        <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("dir.search")} />
        <label className="check"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> {t("dir.showinactive")}</label>
        {canEdit && edit === null && <button onClick={() => { setForm(emptyPerson); setEdit("new"); }}>{t("dir.add")}</button>}
      </div>
      {edit !== null && (
        <div className="person-form">
          {text.map((k) => (
            <label key={k}>{label(k)}<input value={form[k] as string} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
          ))}
          <label>{t("card.department")}
            <select value={form.department_id ?? ""} onChange={(e) => setForm({ ...form, department_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">{t("card.none")}</option>
              {deps.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
          <div className="row-actions">
            <button className="primary" disabled={!form.display_name.trim()} onClick={run(async () => {
              if (edit === "new") await api.createPerson(form); else await api.updatePerson(edit, form);
              setEdit(null);
            })}>{t("dir.save")}</button>
            <button onClick={() => setEdit(null)}>{t("dir.cancel")}</button>
          </div>
        </div>
      )}
      <div className="people">
        {people.map((p) => (
          <div key={p.id} className={p.active ? "person" : "person inactive"}>
            <div className="person-head">
              <strong>{p.display_name}</strong>
              <span className="tag muted">{p.source === "directory" ? t("dir.fromdirectory") : t("dir.manual")}</span>
              {!p.active && <span className="tag muted">{t("card.inactive")}</span>}
              {canEdit && p.source !== "directory" && (
                <span className="note-actions">
                  <button className="link" onClick={() => {
                    setForm({ display_name: p.display_name, username: p.username, email: p.email ?? "", phone: p.phone ?? "",
                      mobile: p.mobile ?? "", chat: p.chat ?? "", title: p.title, department_id: p.department_id });
                    setEdit(p.id);
                  }}>{t("dir.edit")}</button>
                  <button className="link danger" onClick={() => confirm(t("dir.deleteconfirm", { name: p.display_name })) && run(() => api.deletePerson(p.id))()}>{t("dir.delete")}</button>
                </span>
              )}
            </div>
            <div className="sub">{[p.title, p.department, p.username, p.devices ? `${t("dir.devices")}: ${p.devices}` : null].filter(Boolean).join(" · ")}</div>
            <Contact p={p} />
          </div>
        ))}
      </div>
    </>
  );
}
