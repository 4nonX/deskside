import { useEffect, useState } from "react";
import { ApiError, api, type EventItem, type Me, type Role, type SourcesInfo, type UserItem } from "./api";
import { ago, datetime, t } from "./i18n";
import type { Selection } from "./Card";

export function EventsView({ onOpen }: { onOpen: (s: Selection) => void }) {
  const [items, setItems] = useState<EventItem[] | null>(null);
  useEffect(() => {
    const load = () => api.events().then(setItems).catch(() => setItems([]));
    load();
    const h = setInterval(load, 30000);
    return () => clearInterval(h);
  }, []);
  if (!items) return null;
  if (!items.length) return <div className="empty">{t("events.empty")}</div>;
  return (
    <ul className="events">
      {items.map((e) => (
        <li key={e.id} className={e.mac || e.device_id ? "clickable" : ""}
            onClick={() => e.device_id ? onOpen({ kind: "device", id: e.device_id }) : e.mac && onOpen({ kind: "mac", mac: e.mac })}>
          <span className={`ev ${e.kind}`}>{e.kind}</span><span className="when">{datetime(e.ts)}</span><span>{e.message}</span>
        </li>
      ))}
    </ul>
  );
}

export function SourcesView() {
  const [info, setInfo] = useState<SourcesInfo | null>(null);
  useEffect(() => {
    const load = () => api.sources().then(setInfo).catch(() => undefined);
    load();
    const h = setInterval(load, 10000);
    return () => clearInterval(h);
  }, []);
  if (!info) return null;
  return (
    <>
      <h2>{t("sources.title")}</h2>
      <div className="sources">
        {info.sources.map((s) => (
          <div key={s.name} className={s.error ? "source bad" : "source"}>
            <div className="source-head">
              <strong>{s.name}</strong> <span className="sub">{s.type} · {t("sources.every", { n: s.interval })}</span>
              <span className={s.error ? "badge bad" : s.last_ok ? "badge ok" : "badge"}>
                {s.error ? t("sources.error") : s.last_ok ? t("sources.ok") : t("sources.never")}
              </span>
            </div>
            {s.error && <div className="error">{s.error}</div>}
            <div className="sub">
              {s.last_ok && t("sources.lastok", { t: ago(s.last_ok) })}
              {s.duration != null && ` · ${t("sources.took", { n: s.duration })}`}
              {Object.entries(s.counts).filter(([, v]) => v).map(([k, v]) => ` · ${k}: ${v}`).join("")}
            </div>
          </div>
        ))}
      </div>
      {info.suspect_ports.length > 0 && (
        <>
          <h3>{t("sources.busy")}</h3>
          <p className="muted">{t("sources.busyhint")}</p>
          <ul className="plain">
            {info.suspect_ports.map((p) => <li key={p.switch + p.port}>{p.switch} {p.port}: {p.macs}</li>)}
          </ul>
        </>
      )}
    </>
  );
}

export function UsersView({ me }: { me: Me }) {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const load = () => api.users().then(setUsers).catch(() => undefined);
  useEffect(() => { load(); }, []);
  const run = (fn: () => Promise<unknown>) => async () => {
    try { await fn(); await load(); } catch (e) { alert(t("err.generic", { msg: e instanceof ApiError ? e.message : String(e) })); }
  };
  const roles: Role[] = ["viewer", "editor", "admin"];
  return (
    <>
      <h2>{t("users.title")}</h2>
      <table className="users">
        <thead><tr><th>{t("login.user")}</th><th>{t("users.role")}</th><th>{t("users.lastlogin")}</th><th /></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td>
              <td>
                <select value={u.role} disabled={u.id === undefined} onChange={(e) => run(() => api.updateUser(u.id, { role: e.target.value as Role }))()}>
                  {roles.map((r) => <option key={r} value={r}>{t(`role.${r}` as const)}</option>)}
                </select>
              </td>
              <td>{u.last_login ? datetime(u.last_login) : t("users.never")}</td>
              <td className="row-actions">
                <button className="link" onClick={() => {
                  const p = prompt(t("users.password"));
                  if (p) run(() => api.updateUser(u.id, { password: p }))();
                }}>{t("users.setpassword")}</button>
                {u.username !== me.username && <button className="link danger" onClick={run(() => api.deleteUser(u.id))}>{t("users.delete")}</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>{t("users.add")}</h3>
      <form className="inline" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.createUser({ username: name, password: pw, role }); setName(""); setPw(""); })(); }}>
        <input placeholder={t("login.user")} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
        <input type="password" placeholder={t("users.password")} value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
        <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {roles.map((r) => <option key={r} value={r}>{t(`role.${r}` as const)}</option>)}
        </select>
        <button className="primary" disabled={!name || pw.length < 12}>{t("users.add")}</button>
      </form>
    </>
  );
}
