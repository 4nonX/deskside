import { useEffect, useMemo, useRef, useState } from "react";
import { api, type MapNode, type MapPort, type Topology } from "./api";
import { t } from "./i18n";
import { Icon, useIconFor } from "./iconset";
import { connectionLabel, type Selection } from "./fields";

function matches(n: MapNode, q: string): boolean {
  if (!q) return false;
  const hay = [n.name, n.ip, n.mac, n.kind, n.vendor].filter(Boolean).join(" ").toLowerCase();
  return q.split(/\s+/).every((term) => hay.includes(term)) || n.children.some((c) => matches(c, q));
}

function Node({ n, q, onOpen, small = false }: { n: MapNode; q: string; onOpen: (s: Selection) => void; small?: boolean }) {
  const iconFor = useIconFor();
  const hit = matches(n, q);
  const open = () => onOpen(n.type === "device" ? { kind: "device", id: n.id! } : { kind: "mac", mac: n.mac! });
  return (
    <div className={`mnode-wrap ${small ? "small" : ""}`}>
      <button className={`mnode ${n.type === "unknown" ? "unknown" : ""} ${hit ? "hit" : q ? "dim" : ""}`} onClick={open}
              title={[n.name, n.ip, n.mac, n.vendor].filter(Boolean).join(" · ")}>
        <Icon name={n.type === "unknown" ? "question-mark" : iconFor(n.kind, n.icon)} size={small ? 16 : 22} />
        <span className="mnode-text">
          <span className="mnode-name">{n.name || n.ip || n.mac}</span>
          {!small && (n.ip || n.vendor) && <span className="mnode-sub">{n.ip ?? n.vendor}</span>}
          {small && n.connection && <span className="mnode-sub">{connectionLabel(n.connection)}</span>}
        </span>
      </button>
      {n.children.length > 0 && (
        <div className="mchildren">
          {n.children.map((c) => <Node key={c.id} n={c} q={q} onOpen={onOpen} small />)}
        </div>
      )}
    </div>
  );
}

function Port({ p, q, onOpen }: { p: MapPort; q: string; onOpen: (s: Selection) => void }) {
  const short = p.port.replace(/^GigabitEthernet/i, "GE").replace(/^TenGigabitEthernet/i, "XGE").replace(/^FastEthernet/i, "FE");
  const body = p.items.map((n) => <Node key={n.type === "device" ? `d${n.id}` : `m${n.mac}`} n={n} q={q} onOpen={onOpen} />);
  return (
    <div className="mport">
      <div className="mport-label" title={p.port}>
        <span className="mport-name">{short}</span>
        {p.uplink && <span className="tag muted">{t("map.uplink")}</span>}
        {p.alias && <span className="mnode-sub">{p.alias}</span>}
      </div>
      <div className="mport-line" />
      {p.shared ? (
        <div className="msegment">
          <div className="msegment-title">{p.uplink ? t("map.uplinkgroup") : t("map.shared", { n: p.macs })}</div>
          <div className="mitems">{body}</div>
        </div>
      ) : <div className="mitems">{body}</div>}
    </div>
  );
}

export function MapView({ q, tick, onOpen }: { q: string; tick: number; onOpen: (s: Selection) => void }) {
  const [topo, setTopo] = useState<Topology | null>(null);
  const [sw, setSw] = useState<string>("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { api.topology().then(setTopo).catch(() => undefined); }, [tick]);
  const query = q.trim().toLowerCase();
  const switches = useMemo(() => (topo?.switches ?? []).filter((s) => !sw || s.name === sw), [topo, sw]);
  useEffect(() => {
    if (!query) return;
    const el = ref.current?.querySelector(".mnode.hit");
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [query, topo]);
  if (!topo) return null;
  if (!topo.switches.length && !topo.unplaced.length) return <div className="empty">{t("map.empty")}</div>;
  return (
    <div className="map" ref={ref}>
      {topo.switches.length > 1 && (
        <div className="filters inline-tabs">
          <button className={!sw ? "chip active" : "chip"} onClick={() => setSw("")}>{t("filter.all")}</button>
          {topo.switches.map((s) => <button key={s.name} className={sw === s.name ? "chip active" : "chip"} onClick={() => setSw(s.name)}>{s.name}</button>)}
        </div>
      )}
      {switches.map((s) => (
        <div key={s.name} className="mswitch">
          <div className="mswitch-head">
            <Icon name="switch-horizontal" size={26} />
            <div>
              <div className="mswitch-name">{s.name}</div>
              <div className="mnode-sub">{t("map.ports", { n: s.ports.length })}</div>
            </div>
          </div>
          <div className="mports">{s.ports.map((p) => <Port key={p.port} p={p} q={query} onOpen={onOpen} />)}</div>
        </div>
      ))}
      {topo.unplaced.length > 0 && (
        <div className="mswitch">
          <div className="mswitch-head">
            <Icon name="circle-dot" size={22} />
            <div><div className="mswitch-name">{t("map.unplaced")}</div><div className="mnode-sub">{t("map.unplacedhint")}</div></div>
          </div>
          <div className="mitems loose">{topo.unplaced.map((n) => <Node key={n.id} n={n} q={query} onOpen={onOpen} />)}</div>
        </div>
      )}
    </div>
  );
}
