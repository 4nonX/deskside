"""Device types with their icons, and the data behind the network map."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .api import _audit, _db, _engine
from .auth import current_user, require
from .db import Device, KindSetting, Sighting, User
from .graph import Dev, Graph, Seen

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


@router.get("/graph")
def graph(request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
    """The network map: switches, cables between them, devices, virtual machines and peripherals."""
    eng = _engine(request)
    neighbors = [n for snap in eng.snapshots.values() for n in snap.neighbors]
    with _db(request).session() as s:
        devs = [Dev(id=d.id, name=d.name, kind=d.kind or "", icon=d.icon or "", connection=d.connection or "",
                    parent_id=d.parent_id, macs=[i.mac for i in d.interfaces], external_id=d.external_id,
                    labels={i.mac: i.label or "" for i in d.interfaces})
                for d in s.scalars(select(Device).options(selectinload(Device.interfaces)))]
        seen = [Seen(mac=x.mac, ip=x.ip, switch=x.switch, port=x.port, hostname=x.hostname, vendor=x.vendor,
                     port_mac_count=x.port_mac_count)
                for x in s.scalars(select(Sighting).where(Sighting.online))]
    return Graph(devs, seen, neighbors=neighbors, netbox=eng.netbox, aliases=eng.port_aliases,
                 options=eng.settings.raw.get("map") or {}).build()
