"""API for remote access entries and generated connection files."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .api import _audit, _db, _engine, _primary, mgmt_macs
from .auth import current_user, require
from .db import Device, RemoteAccess, Sighting, User
from .remote import RemoteError, Tool, render_link, render_rdp

router = APIRouter(prefix="/api")


def _tools(request: Request) -> dict[str, Tool]:
    return request.app.state.remote_tools


def device_remote(request: Request, s, d: Device) -> list[dict[str, Any]]:
    """Buttons for a device: its own entries, then automatic ones for its kind."""
    tools = _tools(request)
    sightings = list(s.scalars(select(Sighting).where(Sighting.mac.in_([i.mac for i in d.interfaces]))))
    sg = _primary(sightings, mgmt_macs(_engine(request), d))
    host, ip = (sg.hostname, sg.ip) if sg else (None, None)
    out: list[dict[str, Any]] = []
    used: set[str] = set()

    def entry(tool: Tool, e: RemoteAccess | None) -> dict[str, Any]:
        value = e.value if e else None
        user = e.username if e else None
        href = render_link(tool, value=value, user=user, hostname=host, ip=ip)
        download = None
        if tool.file == "rdp":
            download = f"/api/devices/{d.id}/remote/{tool.key}.rdp" + (f"?entry={e.id}" if e else "")
        copy = value if tool.needs == "id" else (value or host or ip)
        return {"id": e.id if e else None, "tool": tool.key, "tool_label": tool.label, "label": (e.label if e else "") or "",
                "value": value or "", "username": user or "", "href": href, "download": download, "copy": copy,
                "needs": tool.needs, "automatic": e is None}

    for e in d.remote:
        tool = tools.get(e.tool)
        if tool is None:
            continue  # tool removed from the configuration; the entry stays but is not shown
        out.append(entry(tool, e))
        used.add(tool.key)
    kind = (d.kind or "").lower()
    for tool in tools.values():
        if tool.key not in used and tool.needs == "address" and kind and kind in tool.auto_kinds and (host or ip):
            out.append(entry(tool, None))
    return out


@router.get("/remote-tools")
def list_tools(request: Request, user: User = Depends(current_user)) -> list[dict[str, Any]]:
    return [t.as_dict() for t in _tools(request).values()]


class RemoteBody(BaseModel):
    tool: str = Field(max_length=50)
    value: str = Field(default="", max_length=255)
    username: str = Field(default="", max_length=200)
    label: str = Field(default="", max_length=100)


_VALUE = re.compile(r"^[^\s\r\n]*$")


@router.post("/devices/{device_id}/remote")
def add_remote(device_id: int, body: RemoteBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    tool = _tools(request).get(body.tool)
    if tool is None:
        raise HTTPException(400, "Unknown remote tool.")
    value, username = body.value.strip(), body.username.strip()
    if tool.needs == "id" and not value:
        raise HTTPException(400, f"{tool.label} needs an ID.")
    if not _VALUE.match(value) or any(c in username for c in "\r\n"):
        raise HTTPException(400, "The value must not contain spaces or line breaks.")
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        pos = (s.scalar(select(func.max(RemoteAccess.position)).where(RemoteAccess.device_id == d.id)) or 0) + 1
        e = RemoteAccess(device_id=d.id, tool=tool.key, value=value, username=username, label=body.label.strip(), position=pos)
        s.add(e)
        s.flush()
        _audit(s, user, "remote.add", d.name, tool=tool.key)
        eid = e.id
    _engine(request).publish({"type": "refresh"})
    return {"id": eid}


@router.delete("/remote/{entry_id}")
def delete_remote(entry_id: int, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        e = s.get(RemoteAccess, entry_id)
        if e is None:
            raise HTTPException(404, "No such entry.")
        d = s.get(Device, e.device_id)
        _audit(s, user, "remote.remove", d.name if d else "", tool=e.tool)
        s.delete(e)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


@router.get("/devices/{device_id}/remote/{tool_key}.rdp")
def rdp_file(device_id: int, tool_key: str, request: Request, entry: int | None = None,
             user: User = Depends(current_user)) -> Response:
    tool = _tools(request).get(tool_key)
    if tool is None or tool.file != "rdp":
        raise HTTPException(404, "No such Remote Desktop tool.")
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        e = s.get(RemoteAccess, entry) if entry else None
        if e is not None and (e.device_id != d.id or e.tool != tool.key):
            raise HTTPException(404, "No such entry.")
        sg = _primary(list(s.scalars(select(Sighting).where(Sighting.mac.in_([i.mac for i in d.interfaces])))),
                      mgmt_macs(_engine(request), d))
        try:
            body = render_rdp(tool, value=e.value if e else None, user=e.username if e else None,
                              hostname=sg.hostname if sg else None, ip=sg.ip if sg else None)
        except RemoteError as exc:
            raise HTTPException(400, str(exc)) from exc
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", d.name) or "device"
    return Response(body.encode("utf-8"), media_type="application/x-rdp",
                    headers={"Content-Disposition": f'attachment; filename="{name}.rdp"', "Cache-Control": "no-store"})
