"""The engine: runs sources, merges their snapshots and records what changed.

Merge rules, in short:

* A MAC's location is the switch port where it is learned. When it is learned
  on several ports (several switches in a chain), the port that is not an
  uplink and carries the fewest MACs wins, because that is the port closest
  to the device.
* A port is an uplink when a neighbour is known on it (LLDP, Netdisco or
  configuration). A port that carries more MACs than ``uplink_mac_threshold``
  without being a known uplink is flagged as "probably an unmanaged switch".
* The IP comes from ARP when available (it reflects what the device uses
  right now), otherwise from DHCP or Netdisco. The hostname comes from DHCP,
  then Netdisco, then reverse DNS.
* Snapshots older than three intervals of their source are ignored, so one
  failing source does not freeze old data in place.
* Only switch tables and ARP count as proof that a device is online. DHCP
  leases outlive the device being switched on by days, so they only add
  addresses and names.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import socket
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from .config import Settings
from . import naming
from .db import Database, Device, EventLog, History, Interface, Sighting, now
from .directory import Directory, DirectoryError
from .netbox import Netbox, NetboxError
from .notify import Notifier
from .netaddr import is_locally_administered, oui
from .sources import AddressEntry, PortEntry, Snapshot, Source, SourceError, build_sources

log = logging.getLogger("deskside.engine")

ORIGIN_RANK = {"arp": 0, "dhcp": 1, "netdisco": 2}


@dataclass
class SourceState:
    name: str
    type: str
    interval: int
    last_run: float | None = None
    last_ok: float | None = None
    duration: float | None = None
    error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class Observed:
    mac: str
    switch: str | None = None
    port: str | None = None
    vlan: int | None = None
    port_mac_count: int | None = None
    behind_uplink: bool = False
    ip: str | None = None
    hostname: str | None = None
    hostname_source: str | None = None
    dhcp: bool = False
    vendor: str | None = None
    live: bool = False              # seen in a switch table or ARP right now, not just in a lease
    sources: set[str] = field(default_factory=set)


class Oui:
    """Vendor lookup from the IEEE registry CSV (https://standards-oui.ieee.org/oui/oui.csv)."""

    def __init__(self, path: str | None) -> None:
        self.table: dict[str, str] = {}
        if path and Path(path).exists():
            with open(path, encoding="utf-8", errors="replace", newline="") as fh:
                for row in csv.DictReader(fh):
                    a = (row.get("Assignment") or "").upper()
                    if len(a) == 6:
                        self.table[f"{a[0:2]}:{a[2:4]}:{a[4:6]}"] = (row.get("Organization Name") or "").strip()
            log.info("loaded %d vendor prefixes from %s", len(self.table), path)

    def lookup(self, mac: str) -> str | None:
        if is_locally_administered(mac):
            return "randomised MAC"
        return self.table.get(oui(mac))


class Engine:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.sources: list[Source] = build_sources(settings.sources)
        self.state = {s.name: SourceState(s.name, s.type, s.interval) for s in self.sources}
        self.snapshots: dict[str, Snapshot] = {}
        self.oui = Oui(settings.raw.get("oui_file"))
        dns = settings.raw.get("dns") or {}
        self.reverse_dns = bool(dns.get("reverse", True))
        self._dns_cache: dict[str, tuple[float, str | None]] = {}
        self.port_aliases: dict[tuple[str, str], str] = {}
        self.suspect_ports: dict[tuple[str, str], int] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._merge_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._dns_task: asyncio.Task[None] | None = None
        self._new_events: list[dict[str, Any]] = []
        self._known_busy: set[tuple[str, str]] = set()
        self._busy_ready = False
        self.conventions = naming.load(settings.naming)
        notif = settings.raw.get("notifications") or []
        self.notifier = Notifier(notif if isinstance(notif, list) else [],
                                 (settings.raw.get("server") or {}).get("public_url"),
                                 int((settings.raw.get("live") or {}).get("notify_batch_seconds", 60)))
        self.last_merge: float | None = None
        self.directory: Directory | None = None
        self.netbox: Netbox | None = None
        if settings.raw.get("netbox"):
            try:
                self.netbox = Netbox(settings.raw["netbox"], db)
            except NetboxError as exc:
                from .config import ConfigError
                raise ConfigError(str(exc)) from exc
        if settings.directory:
            try:
                self.directory = Directory(settings.directory, db)
            except DirectoryError as exc:
                from .config import ConfigError
                raise ConfigError(str(exc)) from exc

    # --- lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        for src in self.sources:
            self._tasks.append(asyncio.create_task(self._loop(src), name=f"source:{src.name}"))
        self._tasks.append(asyncio.create_task(self._housekeeping(), name="housekeeping"))
        if self.directory:
            self._tasks.append(asyncio.create_task(self._directory_loop(), name="directory"))
        if self.netbox:
            self._tasks.append(asyncio.create_task(self._netbox_loop(), name="netbox"))

    async def _netbox_loop(self) -> None:
        assert self.netbox
        await asyncio.sleep(20)  # let the collectors deliver a first picture before comparing
        while True:
            await self.netbox.sync()
            self.publish({"type": "refresh"})
            self.publish({"type": "sources"})
            await asyncio.sleep(self.netbox.state.interval)

    async def _directory_loop(self) -> None:
        assert self.directory
        while True:
            if await self.directory.sync():
                self.publish({"type": "refresh"})
            self.publish({"type": "sources"})
            await asyncio.sleep(self.directory.state.interval)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _loop(self, src: Source) -> None:
        while True:
            await self.run_source(src)
            await asyncio.sleep(src.interval)

    async def run_source(self, src: Source) -> None:
        st = self.state[src.name]
        start = time.time()
        st.last_run = start
        try:
            snap = await asyncio.wait_for(src.collect(), timeout=max(30, src.interval * 2))
        except SourceError as exc:
            st.error = str(exc)
            log.warning("%s", exc)
        except TimeoutError:
            st.error = f"source {src.name}: no result within {max(30, src.interval * 2)} seconds"
            log.warning("%s", st.error)
        except Exception as exc:  # a broken source must never stop the others
            st.error = f"source {src.name}: unexpected error: {exc!r}"
            log.exception("source %s failed", src.name)
        else:
            st.error = None
            st.last_ok = time.time()
            st.counts = {"ports": len(snap.ports), "addresses": len(snap.addresses), "neighbors": len(snap.neighbors)}
            self.snapshots[src.name] = snap
            await self.merge()
        finally:
            st.duration = round(time.time() - start, 2)
            self.publish({"type": "sources"})

    async def _housekeeping(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.merge()
                cutoff = now() - self.settings.retention_days * 86400
                with self.db.session() as s:
                    s.execute(delete(EventLog).where(EventLog.ts < cutoff))
                    s.execute(delete(History).where(History.end.is_not(None), History.end < cutoff))
            except Exception:
                log.exception("housekeeping failed")

    # --- live updates ------------------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def publish(self, msg: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    # --- merging -----------------------------------------------------------------------------
    def _fresh_snapshots(self) -> list[tuple[str, Snapshot]]:
        t = time.time()
        return [(name, snap) for name, snap in self.snapshots.items()
                if t - snap.taken_at <= 3 * self.state[name].interval + 60]

    def compute(self) -> dict[str, Observed]:
        """Merge the current snapshots into one record per MAC. Pure, no I/O except DNS cache reads."""
        fresh = self._fresh_snapshots()
        port_macs: dict[tuple[str, str], set[str]] = defaultdict(set)
        entries: dict[str, list[tuple[PortEntry, str]]] = defaultdict(list)
        uplinks: set[tuple[str, str]] = set()
        addrs: dict[str, list[tuple[AddressEntry, str]]] = defaultdict(list)
        vendors: dict[str, str] = {}
        aliases: dict[tuple[str, str], str] = {}
        for name, snap in fresh:
            for p in snap.ports:
                port_macs[(p.switch, p.port)].add(p.mac)
                entries[p.mac].append((p, name))
            for n in snap.neighbors:
                uplinks.add((n.switch, n.port))
            for a in snap.addresses:
                addrs[a.mac].append((a, name))
            vendors.update(snap.vendors)
            aliases.update(snap.port_names)
        self.port_aliases = aliases
        threshold = self.settings.uplink_mac_threshold
        self.suspect_ports = {k: len(v) for k, v in port_macs.items() if len(v) > threshold and k not in uplinks}

        out: dict[str, Observed] = {}
        for mac in set(entries) | set(addrs):
            o = Observed(mac)
            cands = entries.get(mac, [])
            if cands:
                def rank(c: tuple[PortEntry, str]) -> tuple[int, int]:
                    key = (c[0].switch, c[0].port)
                    return (1 if key in uplinks else 0, len(port_macs[key]))
                best, src = min(cands, key=rank)
                key = (best.switch, best.port)
                o.switch, o.port, o.vlan = best.switch, best.port, best.vlan
                o.port_mac_count = len(port_macs[key])
                o.behind_uplink = key in uplinks or o.port_mac_count > threshold
                o.sources.update(s for _, s in cands)
                o.live = True
            alist = sorted(addrs.get(mac, []), key=lambda a: ORIGIN_RANK.get(a[0].origin, 9))
            if alist:
                o.ip = alist[0][0].ip
                o.live = o.live or any(a.origin == "arp" for a, _ in alist)
                o.sources.update(s for _, s in alist)
                for a, _ in alist:
                    if a.origin == "dhcp" and a.ip == o.ip and a.dynamic:
                        o.dhcp = True
                for origin in ("dhcp", "netdisco"):
                    host = next((a.hostname for a, _ in alist if a.origin == origin and a.hostname and a.ip == o.ip), None)
                    if host:
                        o.hostname, o.hostname_source = host, origin
                        break
            if not o.hostname and o.ip and o.live:
                cached = self._dns_cache.get(o.ip)
                if cached and cached[1]:
                    o.hostname, o.hostname_source = cached[1], "dns"
            o.vendor = vendors.get(mac) or self.oui.lookup(mac)
            out[mac] = o
        return out

    async def _resolve_missing(self, ips: list[str]) -> bool:
        """Reverse-resolve addresses without a hostname. Returns True if new names were found."""
        t = time.time()

        def lookup(ip: str) -> str | None:
            try:
                return socket.gethostbyaddr(ip)[0]
            except OSError:
                return None

        found = False
        for i in range(0, len(ips), 32):
            batch = ips[i:i + 32]
            names = await asyncio.gather(*(asyncio.to_thread(lookup, ip) for ip in batch))
            for ip, n in zip(batch, names):
                found = found or (n is not None and self._dns_cache.get(ip, (0, None))[1] != n)
                self._dns_cache[ip] = (t, n)
        return found

    def _schedule_dns(self, observed: dict[str, Observed]) -> None:
        """Look up missing names in the background; slow or failing DNS must not delay the merge."""
        if not self.reverse_dns or (self._dns_task and not self._dns_task.done()):
            return
        t = time.time()
        todo = sorted({o.ip for o in observed.values() if o.ip and o.live and not o.hostname
                       and (o.ip not in self._dns_cache or t - self._dns_cache[o.ip][0] > 3600)})
        if not todo:
            return

        async def run() -> None:
            if await self._resolve_missing(todo):
                await self.merge()

        self._dns_task = asyncio.create_task(run(), name="reverse-dns")

    async def merge(self) -> None:
        async with self._merge_lock:
            observed = self.compute()
            changed = await asyncio.to_thread(self._persist, observed)
            self.last_merge = time.time()
            events = self.drain_events()
        self.notifier.submit(events)
        self._schedule_dns(observed)
        if changed:
            self.publish({"type": "refresh"})

    def _persist(self, observed: dict[str, Observed]) -> bool:
        t = now()
        changed = False
        fresh: list[dict[str, Any]] = []
        with self.db.session() as s:
            existing = {x.mac: x for x in s.scalars(select(Sighting))}
            known = dict(s.execute(select(Interface.mac, Interface.device_id)).all())
            devices = {d.id: d for d in s.scalars(select(Device))}
            open_hist = {(h.mac, h.kind): h for h in s.scalars(select(History).where(History.end.is_(None)))}
            first_run = not existing

            def label(mac: str, dev: int | None) -> str:
                d = devices.get(dev) if dev else None
                return f"{d.name} ({mac})" if d else mac

            def event(kind: str, mac: str | None, dev: int | None, message: str, data: dict[str, Any] | None = None) -> None:
                s.add(EventLog(kind=kind, mac=mac, device_id=dev, message=message, data=data or {}))
                d = devices.get(dev) if dev else None
                fresh.append({"ts": t, "kind": kind, "mac": mac, "device_id": dev, "device": d.name if d else None,
                              "message": message, "data": data or {}})

            def period(mac: str, kind: str, value: str | None, switch: str | None = None) -> None:
                cur = open_hist.get((mac, kind))
                if cur is not None and (cur.value, cur.switch) == (value, switch):
                    return
                if cur is not None:
                    cur.end = t
                    del open_hist[(mac, kind)]
                if value:
                    h = History(mac=mac, kind=kind, switch=switch, value=value, start=t)
                    s.add(h)
                    open_hist[(mac, kind)] = h

            if first_run and observed:
                event("discovery", None, None, f"Initial discovery: {len(observed)} MAC addresses")
            for mac, o in observed.items():
                row = existing.get(mac)
                dev = known.get(mac)
                who = label(mac, dev)
                if row is None:
                    row = Sighting(mac=mac, first_seen=t, last_seen=t if o.live else 0, online=o.live,
                                   port_since=t if o.port else None)
                    s.add(row)
                    changed = True
                    if o.live and not first_run:
                        what = "Known device back on the network" if dev else "New device on the network"
                        event("online" if dev else "new", mac, dev, f"{what}: {who} {o.ip or ''} {_where(o)}".strip(), _ev(o))
                elif o.live:
                    if not row.online:
                        changed = True
                        event("online", mac, dev, f"Back online: {who} {o.ip or ''} {_where(o)}".strip(), _ev(o))
                    if o.port and (row.switch, row.port) != (o.switch, o.port):
                        if row.port:
                            event("moved", mac, dev, f"Moved: {who} from {row.switch} {row.port} to {_where(o)}",
                                  {**_ev(o), "from_switch": row.switch, "from_port": row.port})
                        row.port_since = t
                        changed = True
                    if o.ip and row.ip and o.ip != row.ip:
                        event("ip_changed", mac, dev, f"New address: {who} {row.ip} -> {o.ip}", {**_ev(o), "from_ip": row.ip})
                        changed = True
                        self._check_scheme(event, devices.get(dev) if dev else None, mac, o.ip)
                before = (row.ip, row.hostname, row.switch, row.port, row.online, row.vendor, row.dhcp)
                if o.port:
                    row.switch, row.port, row.vlan = o.switch, o.port, o.vlan
                    row.port_mac_count, row.behind_uplink = o.port_mac_count, o.behind_uplink
                row.ip = o.ip or row.ip
                if o.hostname:
                    row.hostname, row.hostname_source = o.hostname, o.hostname_source
                elif row.hostname_source == "dns" and not o.live:
                    row.hostname, row.hostname_source = None, None     # a stale PTR name, see compute()
                row.vendor = o.vendor or row.vendor
                row.dhcp = o.dhcp
                row.sources = sorted(o.sources)
                if o.live:
                    row.online = True
                    row.last_seen = t
                    if o.port:
                        period(mac, "port", o.port, o.switch)
                    if o.ip:
                        period(mac, "ip", o.ip)
                if before != (row.ip, row.hostname, row.switch, row.port, row.online, row.vendor, row.dhcp):
                    changed = True
            for mac, row in existing.items():
                o = observed.get(mac)
                if row.online and not (o and o.live) and t - row.last_seen > self.settings.offline_after:
                    row.online = False
                    changed = True
                    dev = known.get(mac)
                    event("offline", mac, dev,
                          f"Offline: {label(mac, dev)} {row.ip or ''}, last seen on {row.switch or '?'} {row.port or ''}".strip(),
                          {"ip": row.ip, "switch": row.switch, "port": row.port, "last_seen": row.last_seen})
                    for kind in ("port", "ip"):
                        h = open_hist.pop((mac, kind), None)
                        if h is not None:
                            h.end = row.last_seen
            # The first merge after start only learns which ports are busy; otherwise every restart
            # would report ports that have been busy for months.
            if not first_run and self._busy_ready:
                for key, count in self.suspect_ports.items():
                    if key not in self._known_busy:
                        event("busy_port", None, None,
                              f"{key[0]} {key[1]} now carries {count} MAC addresses without a known neighbour: "
                              f"probably an unmanaged switch or a hypervisor", {"switch": key[0], "port": key[1], "macs": count})
            self._known_busy = set(self.suspect_ports)
            # Ready once every source has finished at least one run (successfully or not); until then
            # the picture is incomplete. last_run alone is set when a run starts, which is too early.
            self._busy_ready = all(st.last_ok or st.error for st in self.state.values())
        if fresh:
            self._new_events.extend(fresh)
        return changed

    def _check_scheme(self, event, device, mac: str, ip: str) -> None:
        """Event when a device moves to an address its naming convention does not expect."""
        if device is None or not self.conventions:
            return
        for w in naming.check(self.conventions, device.name, device.kind, [ip]):
            if w.startswith("ip_mismatch:"):
                expected = w.split(":", 1)[1]
                event("scheme", mac, device.id, f"Address outside the scheme: {device.name} uses {ip}, expected {expected}",
                      {"ip": ip, "expected": expected})

    def drain_events(self) -> list[dict[str, Any]]:
        out, self._new_events = self._new_events, []
        return out

def _where(o: Observed) -> str:
    return f"on {o.switch} {o.port}" if o.port else ""


def _ev(o: Observed) -> dict[str, Any]:
    return {"ip": o.ip, "switch": o.switch, "port": o.port, "hostname": o.hostname, "vendor": o.vendor}
