"""Netdisco as a source.

For sites that already run Netdisco, or whose networks are large or mixed
enough that its vendor handling pays off. deskside reads Netdisco's REST API
and never queues jobs there. A read-only API token is enough.

Endpoints used (Netdisco 2.x, ``/api/v1``):

* ``search/device``                  to list devices when ``devices`` is not set
* ``object/device/{ip}/ports``       for port names, descriptions and uplink flags
* ``object/device/{ip}/nodes``       for active MACs per port, with
  ``include=ips,netbios,manufacturer`` for addresses, names and vendor
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .. import tls
from ..netaddr import normalize_mac, parse_ip
from .base import AddressEntry, Neighbor, PortEntry, Snapshot, Source, SourceError


def _first(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return None


class Netdisco(Source):
    """Settings: ``url`` (e.g. https://netdisco.example.org), ``token``,
    optional ``devices`` (list of switch IPs; default: every device Netdisco knows),
    ``verify_tls`` (default true)."""

    type = "netdisco"
    default_interval = 120

    async def collect(self) -> Snapshot:
        self.require("url", "token")
        base = self.conf["url"].rstrip("/") + "/api/v1/"
        headers = {"Authorization": self.conf["token"], "Accept": "application/json"}
        async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30,
                                     verify=tls.verify(self.conf)) as cl:

            async def get(path: str, **params: Any) -> Any:
                try:
                    r = await cl.get(path, params=params)
                except httpx.HTTPError as exc:
                    raise SourceError(f"source {self.name}: Netdisco not reachable: {exc}") from exc
                if r.status_code == 401:
                    raise SourceError(f"source {self.name}: Netdisco rejected the API token")
                if r.status_code == 404:
                    return None
                if r.is_error:
                    raise SourceError(f"source {self.name}: Netdisco answered {r.status_code} for {path}")
                return r.json()

            devices = self.conf.get("devices")
            names: dict[str, str] = {}
            if not devices:
                rows = await get("search/device", limit=10000, offset=0) or []
                devices = [d["ip"] for d in rows if d.get("ip")]
                names = {d["ip"]: _first(d, "name", "dns") or d["ip"] for d in rows if d.get("ip")}
            snap = Snapshot()
            for dev in devices:
                switch = names.get(dev) or dev
                if not names:
                    info = await get(f"object/device/{quote(dev)}")
                    if info:
                        switch = _first(info, "name", "dns") or dev
                for p in await get(f"object/device/{quote(dev)}/ports") or []:
                    port = p.get("port")
                    if not port:
                        continue
                    if p.get("is_uplink") or p.get("remote_ip"):
                        snap.neighbors.append(Neighbor(switch, port, _first(p, "remote_id", "remote_ip")))
                    if p.get("name"):
                        snap.port_names[(switch, port)] = p["name"]
                nodes = await get(f"object/device/{quote(dev)}/nodes", active_only="true",
                                  include="ips,netbios,manufacturer") or []
                for n in nodes:
                    mac = normalize_mac(n.get("mac"))
                    if not mac or not n.get("port"):
                        continue
                    vlan = n.get("vlan")
                    snap.ports.append(PortEntry(switch, n["port"], mac, int(vlan) if str(vlan or "").isdigit() else None))
                    nb = (n.get("netbios") or [{}])[0] or {}
                    for ipr in n.get("ips") or []:
                        ip = parse_ip(ipr.get("ip"))
                        if ip and ipr.get("active", True):
                            host = _first(ipr, "dns") or nb.get("nbname")
                            snap.addresses.append(AddressEntry(mac, ip, "netdisco", host))
                    manu = n.get("manufacturer") or {}
                    vendor = _first(manu, "company", "abbrev") if isinstance(manu, dict) else None
                    if vendor:
                        snap.vendors[mac] = vendor
            return snap
