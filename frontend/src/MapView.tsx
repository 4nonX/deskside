import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background, BaseEdge, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow, useStore,
  type Edge, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, type GraphEdge, type GraphNode, type GraphRack, type NetGraph } from "./api";
import { t } from "./i18n";
import { Icon, useIconFor } from "./iconset";
import type { Selection } from "./fields";
import { portName } from "./portplace";

const W = 236, H = 52, ROW = 21, CHIP = 26;
const INDENT = 22, GAP_X = 18, GAP_Y = 10, RANK = 56, SUBTREE_GAP = 44;

type NodeData = {
  n: GraphNode; inner: GraphNode[]; hits: Set<string>; dim: boolean; hidden: number; open: boolean; port: string;
  icon: string; iconFor: (n: GraphNode) => string; onToggle: (id: string) => void; onOpen: (s: Selection) => void;
};

function haystack(n: GraphNode): string {
  return [n.name, n.ip, n.mac, n.kind, n.vendor, ...(n.members ?? []).map(haystack)].filter(Boolean).join(" ").toLowerCase();
}

function nodeHeight(d: NodeData): number {
  if (d.n.type === "group" && d.open) return H + ROW * (d.n.members?.length ?? 0) + 8;
  if (d.inner.length) return H + CHIP * d.inner.length + 8;
  return H;
}

const MapNodeView = memo(function MapNodeView({ data }: NodeProps<Node<NodeData>>) {
  const { n, inner, hits, dim, hidden, open, icon, iconFor, onToggle, onOpen } = data;
  const title = n.type === "group" ? t("map.group", { n: n.members?.length ?? 0 })
    : n.type === "internet" ? t("map.internet") : n.name || n.ip || n.mac;
  const sub = n.type === "switch"
    ? [data.port, n.managed ? t("map.managed") : n.uplink_undocumented ? t("map.noUplink") : t("map.unmanaged")]
    : n.type === "group" ? [data.port, t("map.groupHint")]
    : n.type === "vpn" ? [t("map.vpn"), data.port]
    : inner.length ? [data.port, t("map.vms", { n: inner.length }), inner.some((v) => v.gateway) ? t("map.gateway") : ""]
    : [data.port, n.ip || n.vendor || n.kind];
  return (
    <div className={`gnode ${n.type} ${inner.length ? "host" : ""} ${hits.has(n.id) ? "hit" : ""} ${dim ? "dim" : ""} ${n.online === false ? "off" : ""}`}
         title={[n.name, n.kind, n.ip, n.mac, n.vendor].filter(Boolean).join(" · ")}>
      <Handle type="target" id="top" position={Position.Top} />
      <Handle type="target" id="left" position={Position.Left} />
      <Handle type="target" id="right-in" position={Position.Right} />
      <div className="gnode-row">
        <Icon name={icon} size={n.type === "switch" || inner.length ? 24 : 20} />
        <div className="gnode-text">
          <div className="gnode-name">{title}</div>
          <div className="gnode-sub">{sub.filter(Boolean).join(" · ")}</div>
        </div>
        {n.online != null && <span className={`dot ${n.online ? "on" : ""}`} />}
        {hidden > 0 && (
          <button className="gnode-more nodrag" onClick={(e) => { e.stopPropagation(); onToggle(n.id); }}
                  title={open ? t("map.collapse") : t("map.expand")}>
            {open ? "−" : `+${hidden}`}
          </button>
        )}
      </div>
      {inner.length > 0 && (
        <div className="gnode-vms">
          {inner.map((vm) => (
            <button key={vm.id} className={`gvm nodrag ${hits.has(vm.id) ? "hit" : ""} ${vm.gateway ? "gw" : ""} ${vm.online === false ? "off" : ""}`}
                    onClick={(e) => { e.stopPropagation(); if (vm.device_id != null) onOpen({ kind: "device", id: vm.device_id }); }}
                    title={[vm.name, vm.kind, vm.ip, vm.gateway ? t("map.gateway") : ""].filter(Boolean).join(" · ")}>
              <Icon name={iconFor(vm)} size={15} />
              <span className="gvm-name">{vm.name}</span>
              <span className="gvm-ip">{vm.ip ?? ""}</span>
            </button>
          ))}
        </div>
      )}
      {n.type === "group" && open && (
        <ul className="gnode-members">
          {n.members!.map((m) => <li key={m.id}>{m.ip ?? m.mac}{m.name ? ` · ${m.name}` : m.vendor ? ` · ${m.vendor}` : ""}</li>)}
        </ul>
      )}
      <Handle type="source" id="bottom" position={Position.Bottom} />
      <Handle type="source" id="right" position={Position.Right} />
    </div>
  );
});

type RackRow = { y: number; h: number; u: number | null; label?: string };
type RackData = { name: string; location: string | null; rows: RackRow[] };

/** A rack from the front: its name on top, unit numbers on the left, passive items (patch panels) as thin rows. */
const RackView = memo(function RackView({ data }: NodeProps<Node<RackData>>) {
  return (
    <div className="grack">
      <div className="grack-title">{data.name}{data.location && <span>{data.location}</span>}</div>
      {data.rows.map((r, i) => (
        <div key={i} className={r.label ? "grack-row passive" : "grack-row"} style={{ top: r.y, height: r.h }}>
          <span className="grack-u">{r.u != null ? Math.floor(r.u) : ""}</span>
          {r.label && <span className="grack-label">{r.label}</span>}
        </div>
      ))}
    </div>
  );
});

const nodeTypes = { ds: MapNodeView, rack: RackView };

type Pt = { x: number; y: number };
type Route = { points: Pt[]; labelAt?: Pt };

/** An edge along precomputed orthogonal points: trunks, rack cabling and branches all come from the layout. */
function PolyEdge({ data, style, label }: EdgeProps) {
  const route = data as Route | undefined;
  const pts = route?.points ?? [];
  if (pts.length < 2) return null;
  const path = pts.map((p, i) => `${i ? "L" : "M"} ${p.x} ${p.y}`).join(" ");
  return <BaseEdge path={path} style={style} label={label} labelX={route?.labelAt?.x} labelY={route?.labelAt?.y}
                   labelStyle={{ fontSize: 11, fontFamily: "var(--mono)", fill: "var(--muted)" }}
                   labelShowBg labelBgStyle={{ fill: "var(--panel)" }} labelBgPadding={[3, 1]} />;
}

/** A second cable between two boxes already placed (a management port): around the right side. */
function SideEdge({ sourceX, sourceY, targetX, targetY, style, label }: EdgeProps) {
  const x = Math.max(sourceX, targetX) + 26;
  return <BaseEdge path={`M ${sourceX} ${sourceY} H ${x} V ${targetY} H ${targetX}`} style={style}
                   label={label} labelX={x} labelY={(sourceY + targetY) / 2}
                   labelStyle={{ fontSize: 11, fontFamily: "var(--mono)", fill: "var(--muted)" }}
                   labelShowBg labelBgStyle={{ fill: "var(--panel)" }} labelBgPadding={[3, 1]} />;
}

const edgeTypes = { poly: PolyEdge, side: SideEdge };

function edgeStyle(e: GraphEdge): Partial<Edge> {
  const base = { stroke: "var(--map-edge)", strokeWidth: 1.4 };
  switch (e.kind) {
    case "link": case "uplink": return { style: { ...base, strokeWidth: 3, stroke: "var(--map-link)" } };
    case "wan": return { style: { ...base, strokeWidth: 3, stroke: "var(--accent)" }, animated: true };
    case "vpn": return { style: { ...base, stroke: "var(--accent)", strokeDasharray: "6 4" } };
    case "inferred": return { style: { ...base, stroke: "var(--warn-line)", strokeDasharray: "6 4" } };
    case "behind": return { style: { ...base, strokeDasharray: "4 4" } };
    case "mgmt": return { style: { ...base, strokeWidth: 1, strokeDasharray: "2 3" } };
    case "attached": return { style: { ...base, strokeWidth: 1, strokeDasharray: "1 3" } };
    default: return { style: base };
  }
}

function portText(e: GraphEdge | undefined, self?: string | null): string {
  if (!e) return "";
  if (e.kind === "inferred") return [portName(e.label), t("map.inferred")].filter(Boolean).join(" · ");
  if (e.kind === "uplink") return [portName(e.target_label), e.alias].filter(Boolean).join(" · ");
  if (e.kind === "vpn") return e.via ? t("map.via", { name: e.via }) : "";
  if (e.kind === "attached" || e.kind === "virtual" || e.kind === "wan") return "";
  if (e.kind === "link") return [portName(e.label), e.alias].filter(Boolean).join(" · ");
  // A device on a switch port: where that port leads (room, the desk it serves), then the port.
  const p = e.place;
  if (p?.documented && p.switch && p.endpoint) return [t("place.behind", { name: p.endpoint }), portName(e.label)].join(" · ");
  if (p?.documented) {
    const at = p.endpoint && p.endpoint.toLowerCase() !== (self ?? "").toLowerCase() ? t("place.at", { name: p.endpoint }) : "";
    return [at, p.room, portName(e.label)].filter(Boolean).join(" · ");
  }
  return [portName(e.label), p && !p.documented ? t("place.unknownShort") : "", e.alias].filter(Boolean).join(" · ");
}

function natural(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

// Which edge makes a node's place in the tree, if it has several: the way traffic flows wins.
const TREE_ORDER: GraphEdge["kind"][] = ["wan", "uplink", "link", "port", "behind", "inferred", "vpn", "attached"];
const PAD = 30, TITLE = 32, ROW_GAP = 8, PASSIVE = 18, LANE0 = 18, LANE_STEP = 11, BLOCK_GAP = 120;

/**
 * Racks first: everything mounted in a rack is drawn inside it in mounting order, the cables between rack
 * devices run along its left side, and what hangs off each rack device (desks, printers, a switch in an
 * office) branches out to the right at that device's height. Anything not reached from a rack is a tree
 * from the top: children without children of their own are packed into columns on a shared trunk, the
 * others follow to the right as their own subtrees.
 */
function layout(nodes: Node<NodeData>[], edges: GraphEdge[], racks: GraphRack[]) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parent = new Map<string, string>();
  const parentEdge = new Map<string, GraphEdge>();
  const kids = new Map<string, string[]>();
  const sorted = [...edges].filter((e) => TREE_ORDER.includes(e.kind))
    .sort((a, b) => TREE_ORDER.indexOf(a.kind) - TREE_ORDER.indexOf(b.kind));
  for (const e of sorted) {
    if (!byId.has(e.source) || !byId.has(e.target) || parent.has(e.target)) continue;
    let up: string | undefined = e.source, cycle = false;
    while (up) { if (up === e.target) { cycle = true; break; } up = parent.get(up); }
    if (cycle) continue;
    parent.set(e.target, e.source);
    parentEdge.set(e.target, e);
    kids.set(e.source, [...(kids.get(e.source) ?? []), e.target]);
  }
  const rackOf = new Map<string, string>();
  for (const r of racks) for (const it of r.items) if (it.node && byId.has(it.node)) rackOf.set(it.node, r.id);
  const height = (id: string) => nodeHeight(byId.get(id)!.data);
  const label = (id: string) => byId.get(id)!.data.n.name ?? byId.get(id)!.data.n.ip ?? id;
  const order = (a: string, b: string) => {
    const ta = byId.get(a)!.data.n.type, tb = byId.get(b)!.data.n.type;
    if ((ta === "group") !== (tb === "group")) return ta === "group" ? 1 : -1;
    return natural(parentEdge.get(a)?.label ?? "~", parentEdge.get(b)?.label ?? "~") || natural(label(a), label(b));
  };
  const outside = (id: string) => [...(kids.get(id) ?? [])].filter((c) => !rackOf.has(c)).sort(order);
  // Switches and hosts are branches of the network even when nothing hangs below them in the drawing
  // (a hypervisor's VMs are inside its box), so they never end up in a column of desks.
  const branch = (c: string) => outside(c).length > 0 || byId.get(c)!.data.inner.length > 0 || byId.get(c)!.data.n.type === "switch";

  const pos = new Map<string, Pt>();
  const routes = new Map<string, Route>();
  const extra: Node[] = [];
  type Box = { w: number; h: number; place: (x: number, y: number, from: Pt[]) => void };

  /** A row of children at (x, y); `from` is the cable so far, ending where it leaves the parent. */
  const measureRow = (children: string[]): Box => {
    const leaves = children.filter((c) => !branch(c));
    const subs = children.filter(branch).map((c) => ({ id: c, box: measure(c) }));
    const cols = leaves.length ? Math.min(leaves.length, Math.max(1, Math.ceil(Math.sqrt(leaves.length / 2.5)))) : 0;
    const perCol = Math.ceil(leaves.length / Math.max(cols, 1));
    const columns = Array.from({ length: cols }, (_, i) => leaves.slice(i * perCol, (i + 1) * perCol));
    const colH = columns.map((c) => c.reduce((s, x) => s + height(x) + GAP_Y, 0) - GAP_Y);
    const gridW = cols ? cols * (INDENT + W) + (cols - 1) * GAP_X : 0;
    const subsW = subs.reduce((s, x) => s + x.box.w, 0) + Math.max(subs.length - 1, 0) * SUBTREE_GAP;
    return {
      w: gridW + (gridW && subs.length ? SUBTREE_GAP : 0) + subsW,
      h: Math.max(0, ...colH, ...subs.map((x) => x.box.h)),
      place: (x, y, from) => {
        const exit = from[from.length - 1];
        let cx = x;
        for (const col of columns) {
          const trunk = cx + INDENT / 2;
          let yy = y;
          for (const leaf of col) {
            pos.set(leaf, { x: cx + INDENT, y: yy });
            routes.set(parentEdge.get(leaf)!.id, { points: [...from, { x: exit.x, y: y - 18 }, { x: trunk, y: y - 18 },
                                                            { x: trunk, y: yy + H / 2 }, { x: cx + INDENT, y: yy + H / 2 }] });
            yy += height(leaf) + GAP_Y;
          }
          cx += INDENT + W + GAP_X;
        }
        if (cols) cx += SUBTREE_GAP - GAP_X;
        for (const sub of subs) {
          sub.box.place(cx, y, []);
          routes.set(parentEdge.get(sub.id)!.id, { points: [...from, { x: exit.x, y: y - 26 }, { x: cx + W / 2, y: y - 26 },
                                                              { x: cx + W / 2, y }] });
          cx += sub.box.w + SUBTREE_GAP;
        }
      },
    };
  };
  const measure = (id: string): Box => {
    const children = outside(id);
    const row = children.length ? measureRow(children) : null;
    const h0 = height(id);
    return {
      w: Math.max(W, row?.w ?? 0), h: h0 + (row ? RANK + row.h : 0),
      // Everything starts at the left edge of its block, so a chain runs straight down.
      place: (x, y) => {
        pos.set(id, { x, y });
        row?.place(x, y + h0 + RANK, [{ x: x + W / 2, y: y + h0 }]);
      },
    };
  };

  let top = 0, right = 0;
  const done = new Set<string>();
  for (const r of racks) {
    const members = r.items.filter((it) => it.node && byId.has(it.node));
    if (!members.length) continue;
    // Whatever feeds the rack from outside (the Internet) sits on top of it.
    const headers = nodes.map((n) => n.id).filter((id) => !parent.has(id) && !rackOf.has(id)
      && (kids.get(id) ?? []).length > 0 && (kids.get(id) ?? []).every((c) => rackOf.get(c) === r.id));
    const inside = (id: string) => rackOf.get(id) === r.id || headers.includes(id);
    const cabling = edges.filter((e) => e.kind !== "attached" && inside(e.source) && inside(e.target));
    const fx = LANE0 + LANE_STEP * cabling.length;
    let y = top;
    headers.forEach((id, i) => { pos.set(id, { x: fx + PAD + i * (W + GAP_X), y }); done.add(id); });
    if (headers.length) y += H + 44;
    const frameTop = y;
    let ry = frameTop + TITLE;
    const rows: RackRow[] = [];
    for (const it of r.items) {
      if (it.node && byId.has(it.node)) {
        pos.set(it.node, { x: fx + PAD, y: ry });
        rows.push({ y: ry - frameTop, h: height(it.node), u: it.position });
        ry += height(it.node) + ROW_GAP;
        done.add(it.node);
      } else {
        rows.push({ y: ry - frameTop, h: PASSIVE, u: it.position, label: it.name });
        ry += PASSIVE + ROW_GAP / 2;
      }
    }
    const frameW = W + 2 * PAD, frameH = ry - frameTop + PAD / 2;
    extra.push({ id: r.id, type: "rack", position: { x: fx, y: frameTop }, zIndex: -1, selectable: false, draggable: false,
                 data: { name: r.name, location: r.location, rows }, style: { width: frameW, height: frameH } });
    // Cables between rack devices along the left side; short ones on the inner lanes.
    const mid = (id: string) => pos.get(id)!.y + H / 2;
    [...cabling].sort((a, b) => Math.abs(mid(a.source) - mid(a.target)) - Math.abs(mid(b.source) - mid(b.target)))
      .forEach((e, i) => {
        const lane = fx - LANE0 - i * LANE_STEP + LANE_STEP;
        const s = pos.get(e.source)!, d = pos.get(e.target)!;
        routes.set(e.id, { points: [{ x: s.x, y: mid(e.source) }, { x: lane, y: mid(e.source) }, { x: lane, y: mid(e.target) },
                                    { x: d.x, y: mid(e.target) }],
                           labelAt: parentEdge.get(e.target) === e ? undefined : { x: lane, y: (mid(e.source) + mid(e.target)) / 2 } });
      });
    // What hangs off each rack device, to its right and at its height.
    const bx = fx + frameW + BLOCK_GAP;
    let by = frameTop, k = 0;
    for (const it of members) {
      const id = it.node!;
      const children = outside(id);
      if (!children.length) continue;
      const row = measureRow(children);
      const rowY = Math.max(pos.get(id)!.y + 40, by) + 26;
      const anchor = bx - 34 - k * 10;
      row.place(bx, rowY, [{ x: fx + PAD + W, y: mid(id) }, { x: anchor, y: mid(id) }]);
      by = rowY + row.h + 56;
      right = Math.max(right, bx + row.w);
      k++;
    }
    right = Math.max(right, fx + frameW);
    top = Math.max(frameTop + frameH, by) + 90;
  }

  const rank = (id: string) => {
    const n = byId.get(id)!.data.n;
    return n.type === "internet" ? 0 : n.type === "switch" ? (n.managed ? 1 : 2) : 3;
  };
  const roots = nodes.map((n) => n.id).filter((id) => !parent.has(id) && !done.has(id) && !rackOf.has(id))
    .sort((a, b) => rank(a) - rank(b) || (kids.get(b)?.length ?? 0) - (kids.get(a)?.length ?? 0) || natural(label(a), label(b)));
  let x = 0;
  for (const r of roots) { const box = measure(r); box.place(x, top, []); x += box.w + SUBTREE_GAP * 2; }
  for (const [child, e] of parentEdge) byId.get(child)!.data.port = portText(e, byId.get(child)!.data.n.name);
  const placed = nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? { x: 0, y: 0 } }));
  return { nodes: [...extra, ...placed] as Node[], routes, parentEdge, right };
}

function Diagram({ graph, q, onOpen, showAll }: { graph: NetGraph; q: string; onOpen: (s: Selection) => void; showAll: boolean }) {
  const iconOf = useIconFor();
  const flow = useReactFlow();
  const fitted = useRef("");
  const [inited, setInited] = useState(false);
  const paneW = useStore((st) => st.width), paneH = useStore((st) => st.height);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = useCallback((id: string) => setOpen((o) => {
    const next = new Set(o);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  }), []);
  const query = q.trim().toLowerCase();

  const { nodes, edges, focus } = useMemo(() => {
    const iconFor = (n: GraphNode) => n.type === "internet" ? "cloud" : n.type === "group" ? "stack-2"
      : n.type === "unknown" ? "question-mark" : n.type === "vpn" ? "lock"
      : iconOf(n.kind || (n.type === "switch" ? "switch" : ""), n.icon);
    // Virtual machines are drawn inside their host; peripherals stay folded into their device unless opened.
    const inner = new Map<string, string[]>();
    const attachedTo = new Map<string, string[]>();
    for (const e of graph.edges) {
      if (e.kind === "virtual") inner.set(e.source, [...(inner.get(e.source) ?? []), e.target]);
      if (e.kind === "attached") attachedTo.set(e.source, [...(attachedTo.get(e.source) ?? []), e.target]);
    }
    const contained = new Map<string, string>();
    for (const [host, vms] of inner) for (const vm of vms) contained.set(vm, host);
    const hidden = new Set<string>(contained.keys());
    const hide = (id: string) => (attachedTo.get(id) ?? []).forEach((c) => { hidden.add(c); hide(c); });
    for (const [owner] of attachedTo) if (!showAll && !open.has(owner)) hide(owner);
    for (const vm of contained.keys()) hide(vm);

    const terms = query.split(/\s+/).filter(Boolean);
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const hits = new Set(terms.length ? graph.nodes.filter((n) => terms.every((x) => haystack(n).includes(x))).map((n) => n.id) : []);
    // A hit that is folded away (a VM, a peripheral) also marks the box it is drawn in.
    const parentOf = new Map(graph.edges.filter((e) => e.kind === "attached").map((e) => [e.target, e.source]));
    const focus = new Set<string>();
    for (const id of [...hits]) {
      let p = id;
      while (hidden.has(p) && (contained.has(p) || parentOf.has(p))) p = contained.get(p) ?? parentOf.get(p)!;
      hits.add(p);
      focus.add(p);
    }
    const ns: Node<NodeData>[] = graph.nodes.filter((n) => !hidden.has(n.id)).map((n) => ({
      id: n.id, type: "ds", position: { x: 0, y: 0 },
      data: {
        n, inner: (inner.get(n.id) ?? []).map((id) => byId.get(id)!).filter(Boolean)
          .sort((a, b) => Number(!!b.gateway) - Number(!!a.gateway) || natural(a.name ?? "", b.name ?? "")),
        hits, dim: terms.length > 0 && !hits.has(n.id), open: open.has(n.id) || (n.type === "group" && hits.has(n.id)), port: "",
        hidden: n.type === "group" ? n.members?.length ?? 0 : showAll ? 0 : (attachedTo.get(n.id)?.length ?? 0),
        icon: iconFor(n), iconFor, onToggle: toggle, onOpen,
      },
    }));
    const visible = graph.edges.filter((e) => e.kind !== "virtual" && !hidden.has(e.target) && !hidden.has(e.source));
    const laid = layout(ns, visible, graph.racks ?? []);
    const es: Edge[] = visible.map((e) => {
      const route = laid.routes.get(e.id);
      const inTree = laid.parentEdge.get(e.target) === e;
      return {
        id: e.id, source: e.source, target: e.target, ...edgeStyle(e), type: route ? "poly" : "side", data: route,
        sourceHandle: "right", targetHandle: "right-in",
        label: inTree ? undefined : [portName(e.label), e.kind === "mgmt" ? t("map.mgmt") : ""].filter(Boolean).join(" · "),
      };
    });
    return { nodes: laid.nodes, edges: es, focus: [...focus] };
  }, [graph, open, showAll, query, toggle, iconOf, onOpen]);

  // Fit everything on load; on a search, fly to the hits. Live updates leave the view where the user put it.
  useEffect(() => {
    const key = focus.join("|") || "*";
    if (!inited || !paneW || !paneH || fitted.current === key || !nodes.length) return;
    const pick = focus.length ? nodes.filter((n) => focus.includes(n.id)) : nodes;
    const size = (n: Node) => n.type === "rack" ? { w: Number(n.style?.width), h: Number(n.style?.height) }
      : { w: W, h: nodeHeight(n.data as NodeData) };
    const x1 = Math.min(...pick.map((n) => n.position.x)), y1 = Math.min(...pick.map((n) => n.position.y));
    const x2 = Math.max(...pick.map((n) => n.position.x + size(n).w)), y2 = Math.max(...pick.map((n) => n.position.y + size(n).h));
    const h = setTimeout(() => {
      fitted.current = key;
      if (!focus.length) {
        void flow.fitBounds({ x: x1, y: y1, width: x2 - x1, height: y2 - y1 }, { padding: 0.04 });
        return;
      }
      // Hits: centre on them at a readable zoom, with some of their surroundings in view.
      const zoom = Math.max(0.35, Math.min(1.2, paneW / (x2 - x1 + 500), paneH / (y2 - y1 + 300)));
      void flow.setCenter((x1 + x2) / 2, (y1 + y2) / 2, { zoom, duration: 350 });
    }, 60);
    return () => clearTimeout(h);
  }, [inited, paneW, paneH, focus.join("|"), nodes, flow]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} nodesDraggable={false}
               nodesConnectable={false} elementsSelectable={false} minZoom={0.08} maxZoom={2}
               proOptions={{ hideAttribution: true }} onInit={() => setInited(true)}
               onNodeClick={(_, node) => {
                 if (node.type === "rack") return;
                 const n = (node.data as NodeData).n;
                 if (n.type === "group") toggle(n.id);
                 else if (n.device_id != null) onOpen({ kind: "device", id: n.device_id });
                 else if (n.mac) onOpen({ kind: "mac", mac: n.mac });
               }}>
      <Background gap={22} size={1} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeStrokeWidth={2} />
    </ReactFlow>
  );
}

export function MapView({ q, tick, onOpen }: { q: string; tick: number; onOpen: (s: Selection) => void }) {
  const iconFor = useIconFor();
  const [graph, setGraph] = useState<NetGraph | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showUnplaced, setShowUnplaced] = useState(false);
  useEffect(() => { api.graph().then(setGraph).catch(() => undefined); }, [tick]);
  if (!graph) return null;
  if (!graph.nodes.length) return <div className="empty">{t("map.empty")}</div>;
  const peripherals = graph.edges.some((e) => e.kind === "attached");
  return (
    <div className="gmap">
      <div className="gmap-bar">
        <div className="gmap-legend">
          <span><i className="lg wan" />{t("map.lg.wan")}</span>
          <span><i className="lg link" />{t("map.lg.link")}</span>
          <span><i className="lg port" />{t("map.lg.port")}</span>
          <span><i className="lg behind" />{t("map.lg.behind")}</span>
          <span><i className="lg inferred" />{t("map.lg.inferred")}</span>
          <span><i className="lg mgmt" />{t("map.lg.mgmt")}</span>
        </div>
        <div className="gmap-actions">
          {peripherals && (
            <label className="check"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> {t("map.showPeripherals")}</label>
          )}
          {graph.unplaced.length > 0 && (
            <button onClick={() => setShowUnplaced((v) => !v)}>{t("map.unplacedCount", { n: graph.unplaced.length })}</button>
          )}
        </div>
      </div>
      <div className="gmap-body">
        <div className="gmap-canvas">
          <ReactFlowProvider><Diagram graph={graph} q={q} onOpen={onOpen} showAll={showAll} /></ReactFlowProvider>
        </div>
        {showUnplaced && (
          <aside className="gmap-side">
            <h3>{t("map.unplaced")}</h3>
            <p className="muted">{t("map.unplacedhint")}</p>
            <ul className="plain">
              {graph.unplaced.map((n) => (
                <li key={n.id}>
                  <button className="link gmap-item" onClick={() => n.device_id != null && onOpen({ kind: "device", id: n.device_id })}>
                    <Icon name={iconFor(n.kind, n.icon)} size={16} /> {n.name}
                    {n.online && <span className="dot on" />}
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        )}
      </div>
    </div>
  );
}
