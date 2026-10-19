"""Device types with their icons, and the data behind the network map."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .api import _audit, _db, _engine
from .auth import current_user, require
from .db import Device, KindSetting, Sighting, User

router = APIRouter(prefix="/api")
_ICON = re.compile(r"^[a-z0-9-]{1,60}$")


@router.get("/kinds")
def list_kinds(request: Request, user: User = Depends(current_user)) -> list[dict[str, Any]]:
    """Every device type in use or configured, with its icon and how many devices have it."""
    with _db(request).session() as s:
        counts = dict(s.execute(select(Device.kind, func.count()).group_by(Device.kind)).all())
        icons = {k.kind: k.icon for k in s.scalars(select(KindSetting))}
    kinds = sorted({k for k in counts if k} | set(icons), key=str.lower)
    return [{"kind": k, "icon": icons.get(k, ""), "devices": counts.get(k, 0)} for k in kinds]


class KindBody(BaseModel):
    icon: str = Field(default="", max_length=60)


@router.put("/kinds/{kind}")
def set_kind(kind: str, body: KindBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    if body.icon and not _ICON.match(body.icon):
        raise HTTPException(400, "Unknown icon name.")
    with _db(request).session() as s:
        k = s.get(KindSetting, kind)
        if k is None:
            k = KindSetting(kind=kind)
            s.add(k)
        k.icon = body.icon
        _audit(s, user, "kind.icon", kind, icon=body.icon)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


def _port_key(port: str) -> tuple:
    """Natural sort: GigabitEthernet2 before GigabitEthernet10, TenGigabit ports after the rest."""
    parts = re.split(r"(\d+)", port)
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)


@router.get("/topology")
def topology(request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
    """Switches, their ports, what is plugged into each port, and what hangs off those devices."""
    eng = _engine(request)
    uplinks: set[tuple[str, str]] = set()
    for snap in eng.snapshots.values():
        for n in snap.neighbors:
            uplinks.add((n.switch, n.port))
    with _db(request).session() as s:
        devices = {d.id: d for d in s.scalars(select(Device).options(selectinload(Device.interfaces)))}
        owner = {i.mac: d.id for d in devices.values() for i in d.interfaces}
        children: dict[int, list[int]] = defaultdict(list)
        for d in devices.values():
            if d.parent_id in devices:
                children[d.parent_id].append(d.id)

        def node(dev_id: int, depth: int = 0) -> dict[str, Any]:
            d = devices[dev_id]
            kids = [] if depth > 4 else [node(c, depth + 1) for c in sorted(children[dev_id], key=lambda c: devices[c].name.lower())]
            return {"type": "device", "id": d.id, "name": d.name, "kind": d.kind, "icon": d.icon,
                    "connection": d.connection, "children": kids}

        ports: dict[tuple[str, str], dict[str, Any]] = {}
        placed: set[int] = set()
        for sg in s.scalars(select(Sighting).where(Sighting.online, Sighting.port.is_not(None))):
            key = (sg.switch or "?", sg.port or "?")
            p = ports.setdefault(key, {"port": key[1], "alias": eng.port_aliases.get(key), "uplink": key in uplinks,
                                       "macs": sg.port_mac_count or 0, "items": [], "_devs": set()})
            dev_id = owner.get(sg.mac)
            if dev_id is not None:
                if dev_id in p["_devs"]:
                    continue
                p["_devs"].add(dev_id)
                placed.add(dev_id)
                item = node(dev_id)
                item.update(ip=sg.ip, online=True)
                p["items"].append(item)
            else:
                p["items"].append({"type": "unknown", "mac": sg.mac, "name": sg.hostname, "ip": sg.ip,
                                   "vendor": sg.vendor, "online": True, "children": []})
    switches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (sw, _), p in ports.items():
        p.pop("_devs")
        p["items"].sort(key=lambda i: (i["type"] != "device", (i.get("name") or i.get("mac") or "").lower()))
        p["shared"] = len(p["items"]) > 1 or (not p["uplink"] and p["macs"] > eng.settings.uplink_mac_threshold)
        switches[sw].append(p)
    out = [{"name": sw, "ports": sorted(ps, key=lambda p: _port_key(p["port"]))} for sw, ps in sorted(switches.items())]
    # Devices with attached equipment that are not on any switch port right now (switched off, or Wi-Fi).
    roots = [d for d in devices.values() if d.parent_id is None and d.id not in placed and children[d.id]]
    return {"switches": out, "unplaced": [node(d.id) for d in sorted(roots, key=lambda d: d.name.lower())]}
