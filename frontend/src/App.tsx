import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, subscribe, type Me, type Row } from "./api";
import { ago, t } from "./i18n";
import { IconPin, IconSearch } from "./icons";
import { Card } from "./Card";
import type { Selection } from "./fields";
import { where } from "./portplace";
import { SourcesView, UsersView } from "./Views";
import { EventsPage } from "./HistoryView";
import { DirectoryView } from "./Directory";
import { NetboxView } from "./Netbox";
import { RoomsView } from "./RoomsView";
import { Copyable } from "./Copy";
import { Icon, KindIcons, useIconFor } from "./iconset";

const MapView = lazy(() => import("./MapView").then((m) => ({ default: m.MapView })));

type Tab = "devices" | "directory" | "netbox" | "events" | "admin";
type View = "list" | "map" | "rooms";
type Show = "all" | "known" | "unknown" | "online" | "peripherals" | "leases";

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
  const [err, setErr] = useState(() => new URLSearchParams(location.search).get("login_error") ?? "");
  const [cfg, setCfg] = useState<{ local_login: boolean; sso: string | null } | null>(null);
  useEffect(() => { api.authConfig().then(setCfg).catch(() => setCfg({ local_login: true, sso: null })); }, []);
  const sso = () => { location.href = `/api/auth/start?next=${encodeURIComponent(location.pathname + location.search.replace(/[?&]login_error=[^&]*/, ""))}`; };
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
        {cfg?.sso && <button type="button" className="primary" onClick={sso}>{t("login.sso", { name: cfg.sso })}</button>}
        {cfg?.local_login && <>
          {cfg.sso && <div className="sub login-or">{t("login.or")}</div>}
          <label>{t("login.user")}<input autoFocus={!cfg.sso} autoComplete="username" value={user} onChange={(e) => setUser(e.target.value)} /></label>
          <label>{t("login.password")}<input type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
          <button className={cfg.sso ? "" : "primary"} type="submit" disabled={!user || !pw}>{t("login.submit")}</button>
        </>}
        {err && <div className="error">{err}</div>}
      </form>
    </div>
  );
}

function readView(): View {
  const v = new URLSearchParams(location.search).get("view");
  return v === "map" || v === "rooms" ? v : "list";
}

function Main({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const [tab, setTab] = useState<Tab>("devices");
  const [view, setView] = useState<View>(readView);
  const [admin, setAdmin] = useState<"sources" | "users">("sources");
  const [q, setQ] = useState(() => new URLSearchParams(location.search).get("q") ?? "");
  const [show, setShow] = useState<Show>("all");
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [leaseOnly, setLeaseOnly] = useState(0);
  const [sel, setSel] = useState<Selection | null>(null);
  const [live, setLive] = useState(true);
  const [tick, setTick] = useState(0);
  const [kindIcons, setKindIcons] = useState<Record<string, string>>({});
  const searchRef = useRef<HTMLInputElement>(null);

  const loadKinds = useCallback(() => api.kinds()
    .then((k) => setKindIcons(Object.fromEntries(k.filter((x) => x.icon).map((x) => [x.kind, x.icon])))).catch(() => undefined), []);
  const load = useCallback(async () => {
    try {
      // Rooms need every device (including peripherals) to build the tree; the list filters on the client.
      const res = await api.devices(view === "rooms" ? "" : q, show === "peripherals" ? "known" : show);
      setRows(res.rows); setTotal(res.total); setLeaseOnly(res.lease_only ?? 0); setLive(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onSignOut();
    }
  }, [q, show, view, onSignOut]);

  useEffect(() => { const h = setTimeout(load, 150); return () => clearTimeout(h); }, [load]);
  useEffect(() => { loadKinds(); }, [loadKinds, tick]);
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
    if (view !== "list") url.searchParams.set("view", view); else url.searchParams.delete("view");
    history.replaceState(null, "", url);
  }, [q, view]);
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

  // Peripherals clutter the list; they appear when searched for or when the peripherals filter is on.
  const listRows = useMemo(() => {
    if (show === "peripherals") return rows.filter((r) => r.parent_id);
    if (q.trim()) return rows;
    return rows.filter((r) => !r.parent_id);
  }, [rows, show, q]);

  const open = (s: Selection) => { setSel(s); setTab("devices"); if (view === "rooms") setView("list"); };
  const tabs: [Tab, string][] = [["devices", t("app.devices")], ["directory", t("app.directory")], ["netbox", "NetBox"],
    ["events", t("app.events")], ["admin", t("app.admin")]];
  const withCard = !!sel && tab === "devices";

  return (
    <KindIcons.Provider value={kindIcons}>
      <div className={`layout ${withCard ? "with-card" : ""}`}>
        <header className="top">
          <div className="brand">deskside</div>
          <div className="search">
            <IconSearch />
            <input ref={searchRef} value={q} placeholder={t("app.search")} spellCheck={false}
                   onChange={(e) => { setQ(e.target.value); setTab("devices"); }}
                   onKeyDown={(e) => { if (e.key === "Enter" && listRows.length) setSel(selOf(listRows[0])); }} />
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
          <main className={view === "list" ? "list" : "page"}>
            <div className={view === "list" ? "filters" : "filters inline-tabs"}>
              <div className="segmented" role="tablist">
                {(["list", "map", "rooms"] as View[]).map((v) => (
                  <button key={v} role="tab" aria-selected={view === v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
                    <Icon name={v === "list" ? "stack-2" : v === "map" ? "topology-star-3" : "door"} size={15} /> {t(`view.${v}` as "view.list")}
                  </button>
                ))}
              </div>
              {view === "list" && (
                <>
                  {(["all", "known", "unknown", "online", "peripherals", ...(leaseOnly ? ["leases"] : [])] as Show[]).map((s) => (
                    <button key={s} className={show === s ? "chip active" : "chip"} onClick={() => setShow(s)}>{t(`filter.${s}` as "filter.all")}</button>
                  ))}
                  <span className="count" title={show === "all" && leaseOnly ? t("list.leasehint") : undefined}>
                    {t("list.count", { shown: listRows.length, total })}
                  </span>
                </>
              )}
            </div>
            {view === "list" && <DeviceTable rows={listRows} selected={sel} onSelect={setSel} />}
            {view === "map" && <Suspense fallback={null}><MapView q={q} tick={tick} onOpen={setSel} /></Suspense>}
            {view === "rooms" && <RoomsView rows={rows} onOpen={open} />}
          </main>
        )}
        {tab === "events" && <main className="page"><EventsPage onOpen={open} /></main>}
        {tab === "directory" && <main className="page"><DirectoryView me={me} onKindsChanged={loadKinds} /></main>}
        {tab === "netbox" && <main className="page"><NetboxView me={me} onOpen={open} /></main>}
        {tab === "admin" && (
          <main className="page">
            {me.role === "admin" && (
              <div className="filters inline-tabs">
                <button className={admin === "sources" ? "chip active" : "chip"} onClick={() => setAdmin("sources")}>{t("app.sources")}</button>
                <button className={admin === "users" ? "chip active" : "chip"} onClick={() => setAdmin("users")}>{t("app.users")}</button>
              </div>
            )}
            {(admin === "sources" || me.role !== "admin") ? <SourcesView isAdmin={me.role === "admin"} /> : <UsersView me={me} />}
          </main>
        )}

        {withCard && (
          <Card key={`${sel!.kind}:${sel!.kind === "device" ? sel!.id : sel!.mac}`} sel={sel!} me={me} tick={tick}
                onClose={() => setSel(null)} onSelect={setSel} />
        )}
      </div>
    </KindIcons.Provider>
  );
}

function selOf(r: Row): Selection {
  return r.type === "device" && r.id != null ? { kind: "device", id: r.id } : { kind: "mac", mac: r.mac ?? r.macs[0] };
}

function DeviceTable({ rows, selected, onSelect }: { rows: Row[]; selected: Selection | null; onSelect: (s: Selection) => void }) {
  const iconFor = useIconFor();
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
              <div className="name-cell">
                <Icon name={iconFor(r.kind, r.icon, r.type === "unknown")} size={20} />
                <div>
                  <div className={r.type === "device" ? "name" : "name unknown"}>
                    {r.name ?? r.hostname ?? t("list.unnamed")}
                    {r.pinned.length > 0 && <span className="pin-flag" title={r.pinned.join("\n")}><IconPin /></span>}
                    {r.children > 0 && <span className="tag muted">+{r.children}</span>}
                  </div>
                  <div className="sub">
                    {r.type === "device" && r.hostname ? <Copyable value={r.hostname} /> : null}
                    {r.type === "device" && r.hostname && r.kind ? " · " : null}
                    {[r.kind, r.type === "unknown" ? r.vendor : null].filter(Boolean).join(" · ")}
                  </div>
                </div>
              </div>
            </td>
            <td>{r.people[0]}{r.people.length > 1 && <span className="sub"> +{r.people.length - 1}</span>}</td>
            <td>{r.room}{r.department && <div className="sub">{r.department}</div>}</td>
            <td><Copyable value={r.ip} mono />{r.ip_documented && <div className="sub">{t("ip.documented")}</div>}</td>
            <td><Copyable value={r.mac} mono /></td>
            <td>
              {r.parent ? <span className="sub">{t("card.attachedto")} {r.parent}</span> : r.port && (() => {
                const w = where(r.switch, r.port, r.port_place, r.name, r.port_alias, r.behind_uplink);
                return <>
                  <span className={r.behind_uplink ? "port behind" : "port"} title={`${r.switch} ${r.port}`}>{w.main}</span>
                  {w.sub && <div className="sub">{w.sub}</div>}
                </>;
              })()}
            </td>
            <td>
              {r.macs.length > 0 && (
                <>
                  <span className={r.online ? "dot on" : "dot"} />
                  {r.online ? t("status.online") : r.last_seen ? t("status.lastseen", { t: ago(r.last_seen) }) : t("status.never")}
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
