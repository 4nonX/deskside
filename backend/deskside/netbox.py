"""NetBox connection.

Reads NetBox on every cycle and compares it with what the collectors see.

Written automatically (low risk, can be switched off):

* the address of an IP object with status "DHCP" on the device's interface,
  when the device now has a different DHCP address;
* a "last seen" date in a custom field on the interface, if an admin created
  that field (see docs/netbox.md). Updated at most once per day per interface,
  so NetBox's change log does not fill up.

Proposed, applied only after someone confirms (structural):

* ``mac``: a MAC address seen for a device is missing on its NetBox interface;
* ``cable``: a device's interface (or the patch panel port in front of it) is
  not connected to the switch port it was seen on;
* ``moved``: NetBox has a cable path to one switch port, the device was seen
  on another; the last cable of the path is moved to the new port;
* ``location``: the room set in deskside differs from the NetBox location.

deskside never deletes anything in NetBox.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select

from .db import Database, Device, EventLog, Proposal, Room, Sighting, now
from .search import port_variants

log = logging.getLogger("deskside.netbox")


class NetboxError(Exception):
    pass


@dataclass
class NetboxState:
    name: str = "netbox"
    type: str = "netbox"
    interval: int = 300
    last_run: float | None = None
    last_ok: float | None = None
    duration: float | None = None
    error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class NbIface:
    id: int
    device_id: int
    device: str
    name: str
    mgmt: bool
    cable: int | None
    peer_type: str | None
    peers: list[dict[str, Any]]
    endpoints: list[dict[str, Any]]
    macs: list[str]


def _norm_port(name: str) -> set[str]:
    return {v.lower() for v in port_variants(name)}


class Netbox:
    def __init__(self, conf: dict[str, Any], db: Database) -> None:
        for key in ("url", "token"):
            if not conf.get(key):
                raise NetboxError(f"netbox.{key} is required")
        self.conf = conf
        self.db = db
        self.base = conf["url"].rstrip("/") + "/api/"
        self.ui = conf["url"].rstrip("/")
        self.read_only = bool(conf.get("read_only", False))
        auto = conf.get("auto") or {}
        self.auto_dhcp = not self.read_only and bool(auto.get("dhcp_addresses", True))
        self.auto_seen = not self.read_only and bool(auto.get("last_seen", True))
        self.seen_field = str(conf.get("last_seen_field", "deskside_last_seen"))
        self.name_rx = re.compile(conf.get("name_pattern") or r"^(?P<name>.+)$", re.I)
        if "name" not in self.name_rx.groupindex:
            raise NetboxError("netbox.name_pattern needs a named group (?P<name>...)")
        self.import_rooms = bool(conf.get("import_locations", True))
        imp = conf.get("import_devices") or {}
        roles = imp.get("roles") or []
        roles = [roles] if isinstance(roles, str) else roles
        self.import_roles = {str(r).lower() for r in roles}
        # "all": every device with network interfaces (patch panels and shelves have none)
        self.import_all = bool(self.import_roles & {"all", "*"})
        self.exclude_roles = {str(r).lower() for r in imp.get("exclude_roles") or []}
        self.import_vms = bool(imp.get("virtual_machines", False))
        self.parent_rx = re.compile(imp["parent_pattern"], re.I) if imp.get("parent_pattern") else None
        if self.parent_rx is not None and "parent" not in self.parent_rx.groupindex:
            raise NetboxError("netbox.import_devices.parent_pattern needs a named group (?P<parent>...)")
        self.state = NetboxState(interval=int(conf.get("interval", 300)))
        # filled by sync(), read by the API
        self.by_mac: dict[str, NbIface] = {}
        self.ifaces: dict[int, NbIface] = {}
        self.devices: dict[int, dict[str, Any]] = {}
        self.device_by_name: dict[str, int] = {}
        self.switch_ports: dict[tuple[str, str], NbIface] = {}
        self.has_seen_field = False
        self.locations: list[dict[str, Any]] = []
        self.vms: dict[int, dict[str, Any]] = {}
        self.vm_macs: dict[int, list[str]] = {}
        self.ips_by_device: dict[int, list[tuple[str, str]]] = {}   # device -> [(address, interface name)]
        self.ips_by_vm: dict[int, list[tuple[str, str]]] = {}
        self.tunnels: list[dict[str, Any]] = []
        self._front_for_rear: dict[int, dict[str, Any]] = {}
        self._seen: dict[int, str] = {}
        self.transport: httpx.AsyncBaseTransport | None = None   # tests plug in a fake NetBox here

    # --- HTTP ------------------------------------------------------------------------------
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, timeout=30, verify=self.conf.get("verify_tls", True), transport=self.transport,
                                 headers={"Authorization": f"Token {self.conf['token']}", "Accept": "application/json"})

    async def _all(self, cl: httpx.AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        url: str | None = path
        query: dict[str, Any] | None = {"limit": 1000, **params}
        while url:
            try:
                r = await cl.get(url, params=query)
            except httpx.HTTPError as exc:
                raise NetboxError(f"netbox: not reachable: {exc}") from exc
            if r.status_code in (401, 403):
                raise NetboxError("netbox: the token was rejected or lacks read permission")
            if r.is_error:
                raise NetboxError(f"netbox: {path} answered {r.status_code}")
            data = r.json()
            out += data.get("results", [])
            url, query = data.get("next"), None
        return out

    async def _write(self, cl: httpx.AsyncClient, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.read_only:
            raise NetboxError("netbox: deskside is configured read-only for NetBox")
        r = await cl.request(method, path, json=body)
        if r.is_error:
            raise NetboxError(f"netbox: {method} {path} failed ({r.status_code}): {r.text[:300]}")
        return r.json() if r.content else {}

    # --- reading ---------------------------------------------------------------------------
    async def load(self) -> None:
        async with self._client() as cl:
            devices, ifaces, macs, cfs = await asyncio.gather(
                self._all(cl, "dcim/devices/"), self._all(cl, "dcim/interfaces/"),
                self._all(cl, "dcim/mac-addresses/"), self._all(cl, "extras/custom-fields/"))
            self.locations = await self._all(cl, "dcim/locations/") if self.import_rooms else []
            ips = await self._all(cl, "ipam/ip-addresses/")
            vms = await self._all(cl, "virtualization/virtual-machines/") if self.import_vms else []
            vm_ifaces = await self._all(cl, "virtualization/interfaces/") if self.import_vms else []
            try:
                terms = await self._all(cl, "vpn/tunnel-terminations/")
            except NetboxError:
                terms = []                                  # NetBox before 3.7 has no VPN models
        self.tunnels = []
        for t in terms:
            obj = t.get("termination") or {}
            owner = (obj.get("device") or obj.get("virtual_machine") or {}).get("name")
            if owner and (t.get("tunnel") or {}).get("name"):
                self.tunnels.append({"name": t["tunnel"]["name"], "owner": owner,
                                     "role": (t.get("role") or {}).get("value")})
        self.vms = {v["id"]: v for v in vms}
        self.vm_macs = {}
        for i in vm_ifaces:
            mac = (i.get("primary_mac_address") or {}).get("mac_address")
            if mac and i.get("virtual_machine"):
                self.vm_macs.setdefault(i["virtual_machine"]["id"], []).append(mac.upper())
        self.ips_by_device, self.ips_by_vm = {}, {}
        for ip in ips:
            if (ip.get("status") or {}).get("value") == "dhcp":
                continue                                    # changing addresses identify nothing
            obj = ip.get("assigned_object") or {}
            addr = ip["address"].split("/")[0]
            if obj.get("device"):
                self.ips_by_device.setdefault(obj["device"]["id"], []).append((addr, obj.get("name") or ""))
            elif obj.get("virtual_machine"):
                self.ips_by_vm.setdefault(obj["virtual_machine"]["id"], []).append((addr, obj.get("name") or ""))
        self.has_seen_field = any(c["name"] == self.seen_field and "dcim.interface" in c.get("object_types", [])
                                  for c in cfs)
        self.devices = {d["id"]: d for d in devices}
        self.device_by_name = {}
        for d in devices:
            m = self.name_rx.match(d.get("name") or "")
            if m:
                self.device_by_name.setdefault(m.group("name").lower(), d["id"])
        mac_by_iface: dict[int, list[str]] = {}
        for m in macs:
            if m.get("assigned_object_type") == "dcim.interface" and m.get("assigned_object_id"):
                mac_by_iface.setdefault(m["assigned_object_id"], []).append(m["mac_address"].upper())
        self.ifaces, self.by_mac, self.switch_ports = {}, {}, {}
        for i in ifaces:
            nb = NbIface(id=i["id"], device_id=i["device"]["id"], device=i["device"]["name"] or "", name=i["name"],
                         mgmt=bool(i.get("mgmt_only")), cable=(i.get("cable") or {}).get("id"),
                         peer_type=i.get("link_peers_type"), peers=i.get("link_peers") or [],
                         endpoints=i.get("connected_endpoints") or [], macs=mac_by_iface.get(i["id"], []))
            self.ifaces[nb.id] = nb
            for mac in nb.macs:
                self.by_mac[mac] = nb
            self.switch_ports[(nb.device.lower(), nb.name.lower())] = nb

    def switch_port(self, switch: str | None, port: str | None) -> NbIface | None:
        if not (switch and port):
            return None
        for variant in _norm_port(port):
            hit = self.switch_ports.get((switch.lower(), variant))
            if hit:
                return hit
        return None

    def device_for(self, name: str, macs: list[str], external_id: str | None = None) -> int | None:
        if external_id and external_id.startswith("netbox:device:"):
            return int(external_id.rsplit(":", 1)[1])
        for mac in macs:
            if mac in self.by_mac:
                return self.by_mac[mac].device_id
        return self.device_by_name.get(name.lower())

    def device_url(self, nb_id: int) -> str:
        return f"{self.ui}/dcim/devices/{nb_id}/"

    def info(self, name: str, macs: list[str], external_id: str | None = None) -> dict[str, Any] | None:
        """What NetBox knows about a deskside device, for the device card."""
        nb_id = self.device_for(name, macs, external_id)
        if nb_id is None or nb_id not in self.devices:
            return None
        d = self.devices[nb_id]
        ifaces = [i for i in self.ifaces.values() if i.device_id == nb_id and not i.mgmt]
        return {
            "id": nb_id, "name": d.get("name"), "url": self.device_url(nb_id),
            "location": (d.get("location") or {}).get("name"),
            "interfaces": [{"name": i.name, "macs": i.macs, "via": self._via(i),
                            "endpoint": " ".join(filter(None, [((i.endpoints or [{}])[0].get("device") or {}).get("name"),
                                                                (i.endpoints or [{}])[0].get("name")])) or None}
                           for i in ifaces],
        }

    def _via(self, i: NbIface) -> str | None:
        """The patch panel port in front of an interface, if it is cabled to one."""
        if i.peer_type == "dcim.rearport" and i.peers:
            front = self._front_for_rear.get(i.peers[0].get("id"))
            if front:
                return f"{front['device']['name']} {front['name']}"
            return f"{(i.peers[0].get('device') or {}).get('name', '')} {i.peers[0].get('name', '')}".strip() or None
        return None

    def _import_devices(self) -> dict[str, int]:
        """Create or update deskside devices for NetBox devices of the configured roles, and for virtual machines."""
        if not self.import_roles and not self.import_vms:
            return {}
        from .db import Interface
        created = 0
        with self.db.session() as s:
            all_devs = list(s.scalars(select(Device)))
            by_ext = {d.external_id: d for d in all_devs if d.external_id}
            by_name = {d.name.lower(): d for d in all_devs if d.source != "netbox"}
            owned = {i.mac for d in all_devs for i in d.interfaces}
            linked = {self.device_for(d.name, [i.mac for i in d.interfaces]) for d in all_devs if d.source != "netbox"}
            for nb in self.devices.values():
                role = ((nb.get("role") or {}).get("name") or "")
                if nb["id"] in linked or role.lower() in self.exclude_roles:
                    continue
                if role.lower() not in self.import_roles:
                    if not self.import_all or not any(i.device_id == nb["id"] for i in self.ifaces.values()):
                        continue                    # with "all": skip passive ones (patch panels, shelves)
                ext = f"netbox:device:{nb['id']}"
                d = by_ext.get(ext)
                if d is None:
                    d = Device(source="netbox", external_id=ext, name=nb.get("name") or f"NetBox {nb['id']}")
                    s.add(d)
                    created += 1
                dtype = nb.get("device_type") or {}
                m = self.name_rx.match(nb.get("name") or "")
                d.name = (m.group("name") if m else nb.get("name")) or d.name      # "WS22-Client-PC" -> "WS22"
                d.kind = role
                d.manufacturer = ((dtype.get("manufacturer") or {}).get("name") or "")
                d.model = dtype.get("model") or ""
                d.serial = nb.get("serial") or ""
                if d.parent_id is None and self.parent_rx is not None:
                    m = self.parent_rx.match(d.name)
                    parent = by_name.get(m.group("parent").lower()) if m else None
                    if parent is not None:
                        d.parent = parent
                for iface in self.ifaces.values():
                    if iface.device_id == nb["id"]:
                        for mac in iface.macs:
                            if mac not in owned:
                                d.interfaces.append(Interface(mac=mac, label=iface.name))
                                owned.add(mac)
                self._attach_by_ip(s, d, self.ips_by_device.get(nb["id"], []), owned)
            if self.import_vms:
                hosts = {}
                for d in all_devs + list(s.new):
                    if isinstance(d, Device):
                        nb_id = self.device_for(d.name, [i.mac for i in d.interfaces], d.external_id)
                        if nb_id:
                            hosts.setdefault(nb_id, d)
                for vm in self.vms.values():
                    ext = f"netbox:vm:{vm['id']}"
                    d = by_ext.get(ext) or next((x for x in all_devs if x.source != "netbox" and x.name.lower() == vm["name"].lower()), None)
                    if d is None:
                        d = Device(source="netbox", external_id=ext, name=vm["name"])
                        s.add(d)
                        by_ext[ext] = d
                        created += 1
                    if d.source == "netbox":
                        d.name = vm["name"]
                        d.kind = (vm.get("role") or {}).get("name") or "VM"
                        d.model = (vm.get("platform") or {}).get("name") or ""
                    d.connection = d.connection or "virtual"
                    host_id = (vm.get("device") or {}).get("id")
                    if host_id is None and vm.get("cluster"):
                        # A cluster with a single host says where the machine runs, even without a pinned device.
                        members = [i for i, x in self.devices.items()
                                   if (x.get("cluster") or {}).get("id") == vm["cluster"]["id"]]
                        host_id = members[0] if len(members) == 1 else None
                    host = hosts.get(host_id)
                    if host is not None and d.parent_id is None and host is not d:
                        d.parent = host
                    for mac in self.vm_macs.get(vm["id"], []):
                        if mac not in owned:
                            d.interfaces.append(Interface(mac=mac, label="virtual"))
                            owned.add(mac)
                    self._attach_by_ip(s, d, self.ips_by_vm.get(vm["id"], []), owned)
        return {"imported": created}

    def _attach_by_ip(self, s, d: Device, ips: list[tuple[str, str]], owned: set[str]) -> None:
        """Fixed addresses documented in NetBox identify infrastructure whose MAC NetBox does not know."""
        from .db import Interface
        if not ips:
            return
        names = dict(ips)
        for sg in s.scalars(select(Sighting).where(Sighting.ip.in_(list(names)))):
            if sg.mac not in owned:
                d.interfaces.append(Interface(mac=sg.mac, label=names.get(sg.ip) or f"seen with {sg.ip}"))
                owned.add(sg.mac)

    # --- comparing -------------------------------------------------------------------------
    def _target_iface(self, nb_device: int, mac: str) -> NbIface | None:
        if mac in self.by_mac:
            return self.by_mac[mac]
        candidates = [i for i in self.ifaces.values() if i.device_id == nb_device and not i.mgmt]
        if len(candidates) == 1:
            return candidates[0]
        named = [i for i in candidates if i.name.lower() == str(self.conf.get("interface_name", "")).lower()]
        return named[0] if len(named) == 1 else None

    def compare(self) -> list[dict[str, Any]]:
        """Proposals for the current state. Each has a stable ``key``; a changed situation gives a new key."""
        out: list[dict[str, Any]] = []
        with self.db.session() as s:
            sightings = {x.mac: x for x in s.scalars(select(Sighting))}
            rooms = {r.id: r for r in s.scalars(select(Room))}
            devices = list(s.scalars(select(Device)))
            # A switch port takes one cable. If several known devices share a port (a desk switch, a phone
            # with a PC behind it, a docking station), no cable can be proposed for any of them.
            per_port: dict[tuple[str, str], set[int]] = {}
            for dev in devices:
                if dev.connection == "virtual":
                    continue                    # virtual machines share their host's port by nature
                for i in dev.interfaces:
                    sg = sightings.get(i.mac)
                    if sg and sg.online and sg.port:
                        per_port.setdefault((sg.switch or "", sg.port), set()).add(dev.id)
            for d in devices:
                macs = [i.mac for i in d.interfaces]
                nb_id = self.device_for(d.name, macs, d.external_id)
                if nb_id is None:
                    continue
                nb_name = self.devices.get(nb_id, {}).get("name", "?")
                for mac in macs:
                    sg = sightings.get(mac)
                    iface = self._target_iface(nb_id, mac)
                    if iface is None:
                        continue
                    if mac not in iface.macs:
                        out.append({"key": f"mac:{iface.id}:{mac}", "kind": "mac", "device_id": d.id, "mac": mac,
                                    "summary": f"Add MAC {mac} to {nb_name} {iface.name}",
                                    "payload": {"interface": iface.id, "mac": mac,
                                                "display": {"mac": mac, "device": nb_name, "iface": iface.name}}})
                    if not sg or not sg.online or not sg.port or sg.behind_uplink:
                        continue
                    if len(per_port.get((sg.switch or "", sg.port), ())) > 1:
                        continue
                    port = self.switch_port(sg.switch, sg.port)
                    if port is None:
                        continue
                    end = next((e for e in iface.endpoints if e.get("id")), None)
                    if end and end["id"] == port.id:
                        continue
                    if end:
                        old = self.ifaces.get(end["id"])
                        if old and old.cable and not port.cable:
                            out.append({"key": f"moved:{iface.id}:{old.id}:{port.id}", "kind": "moved", "device_id": d.id,
                                        "mac": mac, "summary": f"{nb_name} {iface.name} was seen on {port.device} {port.name}, "
                                                               f"NetBox has {old.device} {old.name}: move that cable",
                                        "payload": {"cable": old.cable, "from": old.id, "to": port.id,
                                                    "display": {"device": nb_name, "iface": iface.name,
                                                                "seen": f"{port.device} {port.name}",
                                                                "recorded": f"{old.device} {old.name}"}}})
                        continue
                    if port.cable:
                        continue  # port already connected to something else; nothing safe to propose
                    target = {"object_type": "dcim.interface", "object_id": iface.id}
                    where = f"{iface.device} {iface.name}"
                    if iface.cable and iface.peer_type == "dcim.rearport" and iface.peers:
                        rear = iface.peers[0]
                        front = self._front_for_rear.get(rear["id"])
                        if not front or front.get("cable"):
                            continue
                        target = {"object_type": "dcim.frontport", "object_id": front["id"]}
                        where = f"{front['device']['name']} {front['name']}"
                    elif iface.cable:
                        continue
                    out.append({"key": f"cable:{port.id}:{target['object_type']}:{target['object_id']}", "kind": "cable",
                                "device_id": d.id, "mac": mac,
                                "summary": f"Connect {port.device} {port.name} to {where} ({nb_name})",
                                "payload": {"a": {"object_type": "dcim.interface", "object_id": port.id}, "b": target,
                                            "display": {"port": f"{port.device} {port.name}", "target": where, "device": nb_name}}})
                if d.room_id and rooms.get(d.room_id) and (rooms[d.room_id].external_id or "").startswith("netbox:location:"):
                    want = int(rooms[d.room_id].external_id.rsplit(":", 1)[1])
                    have = (self.devices.get(nb_id, {}).get("location") or {}).get("id")
                    if want != have:
                        out.append({"key": f"location:{nb_id}:{want}", "kind": "location", "device_id": d.id, "mac": None,
                                    "summary": f"Set the NetBox location of {nb_name} to {rooms[d.room_id].name}",
                                    "payload": {"device": nb_id, "location": want,
                                                "display": {"device": nb_name, "location": rooms[d.room_id].name}}})
        return out

    async def _load_front_ports(self) -> None:
        async with self._client() as cl:
            fronts = await self._all(cl, "dcim/front-ports/")
        self._front_for_rear = {}
        for f in fronts:
            for m in f.get("rear_ports") or []:
                rid = m.get("rear_port") if isinstance(m.get("rear_port"), int) else (m.get("rear_port") or {}).get("id")
                if rid:
                    self._front_for_rear[rid] = f

    # --- writing ---------------------------------------------------------------------------
    async def auto_writes(self) -> int:
        """Low-risk updates. Returns how many objects were changed."""
        if not (self.auto_dhcp or (self.auto_seen and self.has_seen_field)):
            return 0
        changed = 0
        today = dt.date.today().isoformat()
        with self.db.session() as s:
            sightings = [x for x in s.scalars(select(Sighting).where(Sighting.online))]
        async with self._client() as cl:
            ips = await self._all(cl, "ipam/ip-addresses/", status="dhcp") if self.auto_dhcp else []
            by_iface: dict[int, list[dict[str, Any]]] = {}
            for ip in ips:
                if ip.get("assigned_object_type") == "dcim.interface":
                    by_iface.setdefault(ip["assigned_object_id"], []).append(ip)
            all_addresses = {ip["address"].split("/")[0] for ip in await self._all(cl, "ipam/ip-addresses/")} if ips else set()
            for sg in sightings:
                iface = self.by_mac.get(sg.mac)
                if iface is None:
                    continue
                if self.auto_dhcp and sg.dhcp and sg.ip and len(by_iface.get(iface.id, [])) == 1:
                    obj = by_iface[iface.id][0]
                    old, prefix = obj["address"].split("/")
                    if old != sg.ip and sg.ip not in all_addresses:
                        await self._write(cl, "PATCH", f"ipam/ip-addresses/{obj['id']}/", {"address": f"{sg.ip}/{prefix}"})
                        all_addresses.add(sg.ip)
                        changed += 1
                        self._event("netbox", sg.mac, f"NetBox: DHCP address of {iface.device} {iface.name} updated {old} -> {sg.ip}")
                if self.auto_seen and self.has_seen_field:
                    current = self._seen.get(iface.id)
                    if current != today:
                        await self._write(cl, "PATCH", f"dcim/interfaces/{iface.id}/", {"custom_fields": {self.seen_field: today}})
                        self._seen[iface.id] = today
                        changed += 1
        return changed

    def _event(self, kind: str, mac: str | None, message: str) -> None:
        with self.db.session() as s:
            s.add(EventLog(kind=kind, mac=mac, message=message))

    async def apply(self, p: Proposal) -> None:
        body = p.payload
        async with self._client() as cl:
            if p.kind == "mac":
                m = await self._write(cl, "POST", "dcim/mac-addresses/", {
                    "mac_address": body["mac"], "assigned_object_type": "dcim.interface", "assigned_object_id": body["interface"]})
                await self._write(cl, "PATCH", f"dcim/interfaces/{body['interface']}/", {"primary_mac_address": m["id"]})
            elif p.kind == "cable":
                await self._write(cl, "POST", "dcim/cables/", {
                    "a_terminations": [body["a"]], "b_terminations": [body["b"]], "status": "connected",
                    "description": "Proposed by deskside from the switch MAC table"})
            elif p.kind == "moved":
                r = await cl.get(f"dcim/cables/{body['cable']}/")
                if r.is_error:
                    raise NetboxError(f"netbox: cable {body['cable']} not found")
                cable = r.json()

                def swap(terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
                    return [{"object_type": t["object_type"],
                             "object_id": body["to"] if t["object_id"] == body["from"] and t["object_type"] == "dcim.interface"
                             else t["object_id"]} for t in terms]

                await self._write(cl, "PATCH", f"dcim/cables/{body['cable']}/", {
                    "a_terminations": swap(cable["a_terminations"]), "b_terminations": swap(cable["b_terminations"])})
            elif p.kind == "location":
                await self._write(cl, "PATCH", f"dcim/devices/{body['device']}/", {"location": body["location"]})
            else:
                raise NetboxError(f"unknown proposal kind {p.kind}")

    # --- the cycle -------------------------------------------------------------------------
    def _store_proposals(self, current: list[dict[str, Any]]) -> dict[str, int]:
        t = now()
        keys = {c["key"] for c in current}
        new = 0
        with self.db.session() as s:
            existing = {p.key: p for p in s.scalars(select(Proposal))}
            for c in current:
                p = existing.get(c["key"])
                if p is None:
                    s.add(Proposal(key=c["key"], kind=c["kind"], device_id=c["device_id"], mac=c["mac"],
                                   summary=c["summary"], payload=c["payload"], status="open", created_at=t, updated_at=t))
                    new += 1
                elif p.status == "resolved":
                    p.status, p.updated_at, p.summary, p.payload = "open", t, c["summary"], c["payload"]
                elif p.status in ("open", "failed"):
                    p.summary, p.payload = c["summary"], c["payload"]
            for key, p in existing.items():
                if p.status == "open" and key not in keys:
                    p.status, p.updated_at = "resolved", t
        return {"proposals": len(current), "new": new}

    def _import_rooms(self) -> None:
        if not self.import_rooms:
            return
        with self.db.session() as s:
            rooms = {r.external_id: r for r in s.scalars(select(Room).where(Room.source == "netbox"))}
            for loc in self.locations:
                ext = f"netbox:location:{loc['id']}"
                r = rooms.get(ext)
                if r is None:
                    r = Room(source="netbox", external_id=ext, number="", name=loc["name"])
                    s.add(r)
                r.name = loc["name"]
                r.building = (loc.get("site") or {}).get("name", "") or ""
                r.description = loc.get("description") or ""
            s.flush()
            by_ext = {r.external_id: r.id for r in s.scalars(select(Room).where(Room.source == "netbox"))}
            for d in s.scalars(select(Device).where(Device.room_id.is_(None))):
                nb_id = self.device_for(d.name, [i.mac for i in d.interfaces], d.external_id)
                loc = (self.devices.get(nb_id, {}).get("location") or {}) if nb_id else {}
                if loc.get("id") and f"netbox:location:{loc['id']}" in by_ext:
                    d.room_id = by_ext[f"netbox:location:{loc['id']}"]

    async def sync(self) -> bool:
        st = self.state
        start = time.time()
        st.last_run = start
        try:
            await self.load()
            await self._load_front_ports()
            imported = await asyncio.to_thread(self._import_devices)
            await asyncio.to_thread(self._import_rooms)
            counts = await asyncio.to_thread(self._store_proposals, await asyncio.to_thread(self.compare))
            counts["written"] = await self.auto_writes()
            counts["devices"] = len(self.devices)
            counts.update(imported)
            st.counts, st.error, st.last_ok = counts, None, time.time()
            return True
        except NetboxError as exc:
            st.error = str(exc)
            log.warning("%s", exc)
        except Exception as exc:
            st.error = f"netbox: unexpected error: {exc!r}"
            log.exception("netbox sync failed")
        finally:
            st.duration = round(time.time() - start, 2)
        return False

