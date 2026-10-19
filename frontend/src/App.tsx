import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, subscribe, type Me, type Row } from "./api";
import { ago, t } from "./i18n";
import { IconPin, IconPort, IconSearch } from "./icons";
import { Card, type Selection } from "./Card";
import { EventsView, SourcesView, UsersView } from "./Views";
import { DirectoryView } from "./Directory";
import { NetboxView } from "./Netbox";

type Tab = "devices" | "directory" | "netbox" | "events" | "sources" | "users";
type Show = "all" | "known" | "unknown" | "online";

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  if (me === undefined) return null;
  if (me === null) return <Login onDone={setMe} />;
  return <Main me={me} onSignOut={() => api.logout().finally(() => setMe(null))} />;
}

function Login({ onDone }: { onDone: (m: Me) => void }) {
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try { await api.login(user, pw); onDone(await api.me()); }
    catch (ex) { setErr(ex instanceof ApiError ? ex.message : String(ex)); }
  };
  return (
    <div className="login">
      <form onSubmit={submit} className="login-box">
        <div className="brand">deskside</div>
        <h1>{t("login.title")}</h1>
        <label>{t("login.user")}<input autoFocus autoComplete="username" value={user} onChange={(e) => setUser(e.target.value)} /></label>
        <label>{t("login.password")}<input type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
        {err && <div className="error">{err}</div>}
        <button className="primary" type="submit" disabled={!user || !pw}>{t("login.submit")}</button>
      </form>
    </div>
  );
}

function Main({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const [tab, setTab] = useState<Tab>("devices");
  const [q, setQ] = useState(() => new URLSearchParams(location.search).get("q") ?? "");
  const [show, setShow] = useState<Show>("all");
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [sel, setSel] = useState<Selection | null>(null);
  const [live, setLive] = useState(true);
  const [tick, setTick] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.devices(q, show);
      setRows(res.rows); setTotal(res.total); setLive(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onSignOut();
    }
  }, [q, show, onSignOut]);

  useEffect(() => { const h = setTimeout(load, 150); return () => clearTimeout(h); }, [load]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = subscribe((m) => {
      if (m.type === "refresh") { clearTimeout(timer); timer = setTimeout(() => setTick((x) => x + 1), 400); }
    });
    return () => { stop(); clearTimeout(timer); };
  }, []);
  useEffect(() => { if (tick) load(); }, [tick, load]);
  useEffect(() => {
    const url = new URL(location.href);
    if (q) url.searchParams.set("q", q); else url.searchParams.delete("q");
    history.replaceState(null, "", url);
  }, [q]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault(); setTab("devices"); searchRef.current?.focus();
      }
      if (e.key === "Escape") setSel(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const tabs: [Tab, string][] = [["devices", t("app.devices")], ["directory", t("app.directory")], ["netbox", "NetBox"],
    ["events", t("app.events")], ["sources", t("app.sources")]];
  if (me.role === "admin") tabs.push(["users", t("app.users")]);

  return (
    <div className={`layout ${sel && tab === "devices" ? "with-card" : ""}`}>
      <header className="top">
        <div className="brand">deskside</div>
        <div className="search">
          <IconSearch />
          <input ref={searchRef} value={q} placeholder={t("app.search")} spellCheck={false}
                 onChange={(e) => { setQ(e.target.value); setTab("devices"); }}
                 onKeyDown={(e) => { if (e.key === "Enter" && rows.length) setSel(selOf(rows[0])); }} />
        </div>
        <nav>
          {tabs.map(([k, label]) => (
            <button key={k} className={tab === k ? "tab active" : "tab"} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <div className="me">
          <span className={live ? "live on" : "live"} title={live ? t("app.live") : t("app.offline")} />
          <span>{me.username}</span>
          <button className="link" onClick={onSignOut}>{t("app.signout")}</button>
        </div>
      </header>

      {tab === "devices" && (
        <main className="list">
          <div className="filters">
            {(["all", "known", "unknown", "online"] as Show[]).map((s) => (
              <button key={s} className={show === s ? "chip active" : "chip"} onClick={() => setShow(s)}>{t(`filter.${s}`)}</button>
            ))}
            <span className="count">{t("list.count", { shown: rows.length, total })}</span>
          </div>
          <DeviceTable rows={rows} selected={sel} onSelect={setSel} />
        </main>
      )}
      {tab === "events" && <main className="page"><EventsView onOpen={(s) => { setSel(s); setTab("devices"); }} /></main>}
      {tab === "directory" && <main className="page"><DirectoryView me={me} /></main>}
      {tab === "netbox" && <main className="page"><NetboxView me={me} onOpen={(s) => { setSel(s); setTab("devices"); }} /></main>}
      {tab === "sources" && <main className="page"><SourcesView /></main>}
      {tab === "users" && <main className="page"><UsersView me={me} /></main>}

      {sel && tab === "devices" && (
        <Card key={`${sel.kind}:${sel.kind === "device" ? sel.id : sel.mac}`} sel={sel} me={me} tick={tick}
              onClose={() => setSel(null)} onSelect={setSel} />
      )}
    </div>
  );
}

function selOf(r: Row): Selection {
  return r.type === "device" && r.id != null ? { kind: "device", id: r.id } : { kind: "mac", mac: r.mac ?? r.macs[0] };
}

function DeviceTable({ rows, selected, onSelect }: { rows: Row[]; selected: Selection | null; onSelect: (s: Selection) => void }) {
  const isSel = useMemo(() => (r: Row) =>
    !!selected && (selected.kind === "device" ? r.id === selected.id : r.type === "unknown" && r.mac === selected.mac), [selected]);
  if (!rows.length) return <div className="empty">{t("list.empty")}</div>;
  return (
    <table className="devices">
      <thead>
        <tr><th>{t("col.name")}</th><th>{t("col.people")}</th><th>{t("col.room")}</th><th>{t("col.ip")}</th><th>{t("col.mac")}</th>
          <th>{t("col.location")}</th><th>{t("col.seen")}</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.type === "device" ? `d${r.id}` : `m${r.mac}`} className={isSel(r) ? "selected" : ""} onClick={() => onSelect(selOf(r))}>
            <td>
              <div className={r.type === "device" ? "name" : "name unknown"}>
                {r.name ?? r.hostname ?? t("list.unnamed")}
                {r.pinned.length > 0 && <span className="pin-flag" title={r.pinned.join("\n")}><IconPin /></span>}
              </div>
              <div className="sub">{[r.kind, r.type === "device" ? r.hostname : null, r.vendor].filter(Boolean).join(" · ")}</div>
            </td>
            <td>{r.people[0]}{r.people.length > 1 && <span className="sub"> +{r.people.length - 1}</span>}</td>
            <td>{r.room}{r.department && <div className="sub">{r.department}</div>}</td>
            <td className="mono">{r.ip}</td>
            <td className="mono">{r.mac}</td>
            <td>
              {r.port && (
                <span className={r.behind_uplink ? "port behind" : "port"}>
                  <IconPort /> {r.switch} {r.port}
                </span>
              )}
              {r.port_alias && <div className="sub">{r.port_alias}</div>}
            </td>
            <td>
              <span className={r.online ? "dot on" : "dot"} />
              {r.online ? t("status.online") : r.last_seen ? t("status.lastseen", { t: ago(r.last_seen) }) : t("status.never")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
