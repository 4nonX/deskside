"""The network map as a graph, structured the way traffic flows.

The tree starts at the Internet, goes through the WAN device (modem, router) to the gateway (firewall),
and from there into the switch the gateway is plugged into. If the gateway is a virtual machine, its
host takes that place: a hypervisor carrying the firewall is upstream of the LAN, not one device among
many. From that switch, cables documented in NetBox and LLDP neighbours lead to further switches, and
each device hangs off the port the switches report it on.

What the switches report live decides where a device is. NetBox fills in what SNMP cannot see: cables
between switches, unmanaged switches and the devices behind them, hosts of virtual machines, management
interfaces (iLO, iDRAC) that must not count as a server's position, and VPN tunnels. Where neither says
how something is connected, the edge is marked as inferred or the switch as having an undocumented
uplink, instead of guessing.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .search import port_variants

GROUP_UNKNOWN_OVER = 3
_GATEWAY = re.compile(r"firewall|gateway|utm", re.I)
_ROUTER = re.compile(r"router", re.I)
_WAN = re.compile(r"modem|\bont\b|dsl|wan|fritz", re.I)


@dataclass
class Dev:
    id: int
    name: str
    kind: str = ""
    icon: str = ""
    connection: str = ""
    parent_id: int | None = None
    macs: list[str] = field(default_factory=list)
    external_id: str | None = None
    labels: dict[str, str] = field(default_factory=dict)     # mac -> interface name


@dataclass
class Seen:
    mac: str
    ip: str | None = None
    switch: str | None = None
    port: str | None = None
    hostname: str | None = None
    vendor: str | None = None
    port_mac_count: int | None = None


def _same_port(a: str, b: str) -> bool:
    return bool({v.lower() for v in port_variants(a)} & {v.lower() for v in port_variants(b)})


class Graph:
    def __init__(self, devices: list[Dev], seen: list[Seen], *, neighbors: list[Any] = (), netbox: Any = None,
                 aliases: dict[tuple[str, str], str] | None = None, options: dict[str, Any] | None = None) -> None:
        opts = options or {}
        self.devices = {d.id: d for d in devices}
        self.seen = seen
        self.neighbors = list(neighbors)
        self.nb = netbox
        self.aliases = aliases or {}
        self.switch_roles = {str(r).lower() for r in opts.get("switch_roles") or ["switch"]}
        self.gateway = opts.get("gateway")
        self.wan = opts.get("wan_device")
        self.internet = opts.get("internet", True)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._edge_keys: set[tuple[str, str, str]] = set()
        self.by_name = {d.name.lower(): d for d in self.devices.values()}
        self.mgmt_macs: set[str] = set()
        self.mgmt_doc: dict[int, tuple[str, str]] = {}

    # --- nodes -------------------------------------------------------------------------------
    def _dev_node(self, d: Dev, **extra: Any) -> str:
        nid = f"d:{d.id}"
        n = self.nodes.setdefault(nid, {"id": nid, "type": "device", "device_id": d.id, "name": d.name, "kind": d.kind,
                                        "icon": d.icon, "online": False, "ip": None})
        n.update({k: v for k, v in extra.items() if v is not None})
        return nid

    def _switch_node(self, name: str, managed: bool = False) -> str:
        d = self.by_name.get(name.lower())
        if d is not None:
            nid = self._dev_node(d)
        else:
            nid = f"sw:{name.lower()}"
            self.nodes.setdefault(nid, {"id": nid, "type": "device", "device_id": None, "name": name, "kind": "switch",
                                        "icon": "", "online": None, "ip": None})
        n = self.nodes[nid]
        n["type"] = "switch"
        n["managed"] = n.get("managed", False) or managed
        return nid

    def _edge(self, source: str, target: str, kind: str, label: str | None = None, **extra: Any) -> None:
        # A management cable runs in parallel to the data cable between the same two boxes; keep both.
        pair = (source, target) if source < target else (target, source)
        key = (*pair, "mgmt" if kind == "mgmt" else "")
        if key in self._edge_keys or source == target:
            return
        self._edge_keys.add(key)
        e = {"id": f"e{len(self.edges)}", "source": source, "target": target, "kind": kind, "label": label}
        e.update({k: v for k, v in extra.items() if v is not None})
        self.edges.append(e)

    @staticmethod
    def _is_switch_kind(kind: str) -> bool:
        return "switch" in (kind or "").lower()

    # --- NetBox ------------------------------------------------------------------------------
    def _netbox(self) -> tuple[list[tuple[str, str, str, str]], dict[int, tuple[str, str]]]:
        """Cables between switches, where NetBox says each device is plugged in, and management interfaces."""
        links: list[tuple[str, str, str, str]] = []
        documented: dict[int, tuple[str, str]] = {}
        nb = self.nb
        if nb is None or not getattr(nb, "devices", None):
            return links, documented
        nb_to_dev: dict[int, Dev] = {}
        for d in self.devices.values():
            nb_id = nb.device_for(d.name, d.macs, d.external_id)
            if nb_id is not None:
                nb_to_dev.setdefault(nb_id, d)
        nb_by_name = {(x.get("name") or "").lower(): i for i, x in nb.devices.items()}

        # Management interfaces: their MAC addresses never decide where a device is.
        for i in nb.ifaces.values():
            if not i.mgmt:
                continue
            self.mgmt_macs.update(i.macs)
            d = nb_to_dev.get(i.device_id)
            if d is not None:
                self.mgmt_macs.update(m for m in d.macs if (d.labels.get(m) or "").lower() == i.name.lower())

        def is_switch(nb_id: int) -> bool:
            x = nb.devices.get(nb_id) or {}
            if ((x.get("role") or {}).get("name") or "").lower() in self.switch_roles:
                return True
            d = nb_to_dev.get(nb_id)
            return d is not None and self._is_switch_kind(d.kind)

        def node(nb_id: int) -> str | None:
            if is_switch(nb_id):
                return self._switch_node(nb.devices[nb_id].get("name") or str(nb_id))
            d = nb_to_dev.get(nb_id)
            return f"d:{d.id}" if d is not None else None

        for i in nb.ifaces.values():
            if i.mgmt or i.device_id not in nb.devices or not is_switch(i.device_id):
                continue
            a = node(i.device_id)
            for ep in i.endpoints or []:
                dev = ep.get("device") or {}
                other = dev.get("id") or nb_by_name.get((dev.get("name") or "").lower())
                if other is None or other == i.device_id or other not in nb.devices:
                    continue
                remote = nb.ifaces.get(ep.get("id"))
                if is_switch(other):
                    links.append((a, i.name, node(other), ep.get("name") or ""))
                elif other in nb_to_dev:
                    if remote is not None and remote.mgmt:
                        self.mgmt_doc.setdefault(nb_to_dev[other].id, (a, i.name))
                    else:
                        documented.setdefault(nb_to_dev[other].id, (a, i.name))
        return links, documented

    def _gateway(self) -> tuple[Dev | None, Dev | None]:
        """The gateway (firewall, router) and the box that carries it on the wire: itself, or its VM host."""
        gw = self.by_name.get(str(self.gateway).lower()) if self.gateway else None
        ranked = sorted(self.devices.values(), key=lambda d: d.name.lower())
        if gw is None:
            gw = next((d for d in ranked if _GATEWAY.search(d.kind or "")), None) or \
                 next((d for d in ranked if _ROUTER.search(d.kind or "")), None)
        if gw is None:
            return None, None
        anchor = gw
        if gw.connection == "virtual" and gw.parent_id in self.devices:
            anchor = self.devices[gw.parent_id]
        return gw, anchor

    def _wan_device(self, gw: Dev | None, anchor: Dev | None) -> Dev | None:
        if self.wan:
            return self.by_name.get(str(self.wan).lower())
        return next((d for d in sorted(self.devices.values(), key=lambda d: d.name.lower())
                     if _WAN.search(d.kind or "") and d is not gw and d is not anchor), None)

    # --- building ----------------------------------------------------------------------------
    def build(self) -> dict[str, Any]:
        owner = {m: d.id for d in self.devices.values() for m in d.macs}
        managed = {s.switch for s in self.seen if s.switch}
        for n in self.neighbors:
            managed.add(n.switch)
        for name in sorted(managed):
            self._switch_node(name, managed=True)
        for d in self.devices.values():
            if self._is_switch_kind(d.kind):
                self._switch_node(d.name)

        links, documented = self._netbox()
        known = set(self.by_name) | {m.lower() for m in managed}
        for n in self.neighbors:
            if n.remote_name and n.remote_name.lower() in known:
                links.append((self._switch_node(n.switch), n.port, self._switch_node(n.remote_name), n.remote_port or ""))

        # Live positions: the most specific port per device (the one carrying the fewest addresses),
        # unless NetBox documents one of the ports it is seen on. Management interfaces are kept apart.
        best: dict[str, Seen] = {}
        mgmt_seen: dict[int, tuple[str, str]] = {}
        for s in self.seen:
            if s.mac in self.mgmt_macs and s.mac in owner:
                if s.switch and s.port:
                    mgmt_seen[owner[s.mac]] = (self._switch_node(s.switch, managed=True), s.port)
                continue
            key = f"d:{owner[s.mac]}" if s.mac in owner else f"u:{s.mac}"
            cur = best.get(key)
            if cur is None or (s.port and not cur.port) or (
                    s.port and cur.port and (s.port_mac_count or 0) < (cur.port_mac_count or 0)):
                best[key] = s
        for s in self.seen:
            doc = documented.get(owner.get(s.mac, -1))
            if doc and s.switch and s.port and s.mac not in self.mgmt_macs \
                    and self._switch_node(s.switch, managed=True) == doc[0] and _same_port(s.port, doc[1]):
                best[f"d:{owner[s.mac]}"] = s

        # Where the gateway (or the host carrying it) meets the LAN: the switch tree starts there.
        gw, anchor = self._gateway()
        anchor_key = f"d:{anchor.id}" if anchor else None
        anchor_at: tuple[str, str | None] | None = None
        if anchor is not None:
            if anchor.id in documented:
                anchor_at = documented[anchor.id]
            elif anchor_key in best and best[anchor_key].switch:
                s = best[anchor_key]
                anchor_at = (self._switch_node(s.switch, managed=True), s.port)

        # Spread out from there (and then from any other switch deskside reads): the first switch to
        # reach another is its upstream.
        adj: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for a, pa, b, pb in links:
            adj[a].append((pa, b, pb))
            adj[b].append((pb, a, pa))
        downstream: dict[str, list[tuple[str, str]]] = defaultdict(list)    # switch -> [(port, switch below)]
        reached: set[str] = set()
        starts = ([anchor_at[0]] if anchor_at else []) + sorted(self._switch_node(m) for m in managed)
        for start in starts:
            if start in reached:
                continue
            reached.add(start)
            queue = [start]
            while queue:
                u = queue.pop(0)
                for pu, v, pv in sorted(adj[u]):
                    if v in reached:
                        continue
                    reached.add(v)
                    queue.append(v)
                    downstream[u].append((pu, v))
                    self._edge(u, v, "link", label=pu, target_label=pv or None)
        # Cables between two switches that are both reached already, or that hang off nothing deskside reads.
        for a, pa, b, pb in links:
            self._edge(a, b, "link", label=pa, target_label=pb or None)

        def below(sw: str, port: str) -> str | None:
            for p, v in downstream.get(sw, []):
                if _same_port(p, port):
                    return v
            return None

        placed: dict[str, tuple[str, str | None, str]] = {}      # node -> (parent, port label, edge kind)
        unknown_at: dict[tuple[str, str | None], list[str]] = defaultdict(list)
        switch_seen: dict[str, tuple[str, str]] = {}           # unmanaged switch -> where its own address shows up
        for key, s in best.items():
            dev = self.devices.get(int(key[2:])) if key.startswith("d:") else None
            if dev is not None:
                self._dev_node(dev, online=True, ip=s.ip)
                if dev.parent_id in self.devices:
                    up, hops = self.devices[dev.parent_id], 0
                    while up is not None and hops < 5:            # make sure the chain up to the host is drawn
                        self._dev_node(up)
                        up, hops = self.devices.get(up.parent_id), hops + 1
                    continue
            if not s.switch or not s.port or key == anchor_key:
                continue
            sw = self._switch_node(s.switch, managed=True)
            if key in self.nodes and self.nodes[key]["type"] == "switch":
                if key != sw:
                    switch_seen[key] = (sw, s.port)
                continue                       # a switch seen on its upstream port is drawn by the switch links
            doc = documented.get(dev.id) if dev is not None else None
            down = below(sw, s.port)
            if doc and doc[0] != sw and not self.nodes[doc[0]].get("managed"):
                placed[key] = (doc[0], doc[1], "port")
            elif down:
                placed[key] = (down, None, "behind")
            else:
                placed[key] = (sw, s.port, "port")
            if dev is None:
                unknown_at[placed[key][:2]].append(key)
                self.nodes[key] = {"id": key, "type": "unknown", "device_id": None, "mac": s.mac,
                                   "name": s.hostname, "ip": s.ip, "vendor": s.vendor, "online": True}
        # Offline devices that NetBox says are cabled somewhere.
        for dev_id, (sw, port) in documented.items():
            key = f"d:{dev_id}"
            dev = self.devices[dev_id]
            if key not in placed and key not in best and key != anchor_key and dev.parent_id not in self.devices \
                    and self.nodes.get(key, {}).get("type") != "switch":
                self._dev_node(dev)
                placed[key] = (sw, port, "port")

        # Switches whose uplink nobody documented: put them where their devices are seen.
        for sw in [n for n, x in self.nodes.items() if x["type"] == "switch" and n not in reached and not adj[n]]:
            votes = Counter()
            if sw in switch_seen:
                votes[switch_seen[sw]] += 100
            for dev_id, (dsw, _) in documented.items():
                s = best.get(f"d:{dev_id}")
                if dsw == sw and s is not None and s.switch and s.port:
                    votes[(self._switch_node(s.switch), s.port)] += 1
            self.nodes[sw]["uplink_undocumented"] = True
            if votes:
                (up, port), _ = votes.most_common(1)[0]
                parent = below(up, port)
                if parent:
                    self._edge(parent, sw, "inferred")
                else:
                    self._edge(up, sw, "inferred", label=port, alias=self.aliases.get((self.nodes[up]["name"], port)))

        # The way out: Internet -> WAN device -> gateway (or its host) -> the switch it is plugged into.
        if anchor is not None:
            aid = self._dev_node(anchor)
            if gw is not anchor:
                self._dev_node(gw)
            self.nodes[f"d:{gw.id}"]["gateway"] = True
            if anchor_at:
                self._edge(aid, anchor_at[0], "uplink", target_label=anchor_at[1],
                           alias=self.aliases.get((self.nodes[anchor_at[0]]["name"], anchor_at[1] or "")))
            if self.internet:
                self.nodes["internet"] = {"id": "internet", "type": "internet", "device_id": None, "name": "Internet",
                                          "online": None}
                wan = self._wan_device(gw, anchor)
                if wan is not None:
                    wid = self._dev_node(wan)
                    self._edge("internet", wid, "wan")
                    self._edge(wid, aid, "wan")
                else:
                    self._edge("internet", aid, "wan")
            for t in getattr(self.nb, "tunnels", None) or []:
                if t.get("owner", "").lower() == gw.name.lower():
                    vid = f"vpn:{t['name'].lower()}"
                    self.nodes[vid] = {"id": vid, "type": "vpn", "device_id": None, "name": t["name"],
                                       "online": None, "ip": t.get("prefix")}
                    self._edge(aid, vid, "vpn", via=gw.name if gw is not anchor else None)

        for key, (parent, port, kind) in placed.items():
            if self.nodes[key]["type"] == "unknown" and len(unknown_at[(parent, port)]) > GROUP_UNKNOWN_OVER:
                continue
            self._edge(parent, key, kind, label=port,
                       alias=self.aliases.get((self.nodes[parent]["name"], port)) if port else None)
        for (parent, port), keys in unknown_at.items():
            if len(keys) > GROUP_UNKNOWN_OVER:
                gid = f"g:{parent}:{port or ''}"
                self.nodes[gid] = {"id": gid, "type": "group", "device_id": None, "online": True,
                                   "members": [self.nodes.pop(k) for k in keys]}
                self._edge(parent, gid, "port" if port else "behind", label=port)

        # Management interfaces: a thin second line, the device stays where its data port is.
        for dev_id in set(mgmt_seen) | set(self.mgmt_doc):
            sw, port = mgmt_seen.get(dev_id) or self.mgmt_doc[dev_id]
            if f"d:{dev_id}" in self.nodes or f"d:{dev_id}" in placed:
                self._edge(sw, self._dev_node(self.devices[dev_id]), "mgmt", label=port)

        # Peripherals and virtual machines hang off the device they belong to.
        def attach(dev: Dev, depth: int = 0) -> None:
            for child in sorted((c for c in self.devices.values() if c.parent_id == dev.id), key=lambda c: c.name.lower()):
                cid = self._dev_node(child)
                self._edge(f"d:{dev.id}", cid, "virtual" if child.connection == "virtual" else "attached",
                           label=child.connection or None)
                if depth < 4:
                    attach(child, depth + 1)

        for nid in list(self.nodes):
            if nid.startswith("d:"):
                d = self.devices[int(nid[2:])]
                if d.parent_id not in self.devices:
                    attach(d)

        connected = {e["source"] for e in self.edges} | {e["target"] for e in self.edges}
        unplaced = []
        for nid in list(self.nodes):
            n = self.nodes[nid]
            if nid not in connected and n["type"] == "device":
                unplaced.append(self.nodes.pop(nid))
        unplaced.sort(key=lambda n: (not n["online"], n["name"].lower()))
        # Devices that are neither seen nor documented anywhere stay out of the map itself.
        shown = {n["device_id"] for n in self.nodes.values()} | {n["device_id"] for n in unplaced}
        unplaced += [{"id": f"d:{d.id}", "type": "device", "device_id": d.id, "name": d.name, "kind": d.kind,
                      "icon": d.icon, "online": False, "ip": None}
                     for d in sorted(self.devices.values(), key=lambda d: d.name.lower())
                     if d.id not in shown and d.parent_id not in self.devices]
        return {"nodes": list(self.nodes.values()), "edges": self.edges, "unplaced": unplaced}
