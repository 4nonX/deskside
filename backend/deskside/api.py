"""HTTP API. The web interface uses exactly these endpoints; nothing is private to it."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .auth import COOKIE, MAX_AGE, ROLES, current_user, hash_password, require, verify_password
from . import naming
from .db import (AuditLog, Department, Device, DevicePerson, EventLog, Interface, Note, Person, Proposal, Room, Sighting,
                 User, now)
from .netaddr import ip_sort_key, mac_search_key, normalize_mac
from .search import filter_rows, search_blob

router = APIRouter(prefix="/api")


def _db(request: Request):
    return request.app.state.db


def _engine(request: Request):
    return request.app.state.engine


def _contacts_ok(request: Request, user: User) -> bool:
    return ROLES.index(user.role) >= ROLES.index(request.app.state.settings.contacts_visible_to)


def _conventions(request: Request) -> dict[str, naming.Convention]:
    return request.app.state.naming


def _room_dict(r: Room | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {"id": r.id, "number": r.number, "name": r.name, "building": r.building, "floor": r.floor,
            "description": r.description}


def _room_label(r: Room | None) -> str:
    if r is None:
        return ""
    return " ".join(x for x in (r.number, r.name) if x)


def _person_dict(p: Person, contacts: bool) -> dict[str, Any]:
    d = {"id": p.id, "display_name": p.display_name, "username": p.username, "title": p.title,
         "department": p.department.name if p.department else None,
         "department_id": p.department_id, "source": p.source, "active": p.active}
    if contacts:
        d.update(email=p.email, phone=p.phone, mobile=p.mobile, chat=p.chat)
    return d


def _audit(s: Session, user: User, action: str, target: str = "", **detail: Any) -> None:
    s.add(AuditLog(username=user.username, action=action, target=target, detail=detail))


# --- session --------------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=500)


_attempts: dict[str, deque[float]] = defaultdict(deque)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    client = request.client.host if request.client else "?"
    window = _attempts[client]
    t = time.time()
    while window and t - window[0] > 300:
        window.popleft()
    if len(window) >= 10:
        raise HTTPException(429, "Too many failed sign-ins. Wait five minutes and try again.")
    with _db(request).session() as s:
        user = s.scalar(select(User).where(User.username == body.username))
        if user is None or not verify_password(body.password, user.password_hash):
            window.append(t)
            raise HTTPException(401, "Wrong user name or password.")
        user.last_login = now()
        token = request.app.state.sessions.issue(user)
        response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/")
        return {"username": user.username, "role": user.role}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"username": user.username, "role": user.role, "version": __version__}


# --- device list and search -----------------------------------------------------------------

def _sighting_dict(sg: Sighting | None, aliases: dict) -> dict[str, Any]:
    if sg is None:
        return {"online": False}
    return {
        "mac": sg.mac, "ip": sg.ip, "hostname": sg.hostname, "hostname_source": sg.hostname_source,
        "vendor": sg.vendor, "switch": sg.switch, "port": sg.port, "vlan": sg.vlan,
        "port_alias": aliases.get((sg.switch, sg.port)), "port_mac_count": sg.port_mac_count,
        "behind_uplink": sg.behind_uplink, "dhcp": sg.dhcp, "online": sg.online,
        "first_seen": sg.first_seen, "last_seen": sg.last_seen or None, "port_since": sg.port_since,
        "sources": sg.sources,
    }


def _primary(sightings: list[Sighting]) -> Sighting | None:
    """The interface shown in the list: online first, then most recently seen."""
    return max(sightings, key=lambda x: (x.online, x.last_seen), default=None)


def build_rows(s: Session, aliases: dict, contacts: bool) -> list[dict[str, Any]]:
    sightings = {x.mac: x for x in s.scalars(select(Sighting))}
    rows: list[dict[str, Any]] = []
    owned: set[str] = set()
    devices = s.scalars(select(Device).options(
        selectinload(Device.interfaces), selectinload(Device.notes), selectinload(Device.room),
        selectinload(Device.department), selectinload(Device.people).selectinload(DevicePerson.person),
        selectinload(Device.remote)))
    for d in devices:
        macs = [i.mac for i in d.interfaces]
        owned.update(macs)
        sgs = [sightings[m] for m in macs if m in sightings]
        links = sorted(d.people, key=lambda dp: (not dp.is_primary, dp.person.display_name.lower()))
        row = {"type": "device", "id": d.id, "name": d.name, "kind": d.kind, "description": d.description,
               **_sighting_dict(_primary(sgs), aliases), "macs": macs,
               "pinned": [n.text for n in d.notes if n.pinned],
               "room": _room_label(d.room) or None, "department": d.department.name if d.department else None,
               "people": [dp.person.display_name for dp in links]}
        row["mac"] = row.get("mac") or (macs[0] if macs else None)
        extra = [n.text for n in d.notes] + [x.ip for x in sgs if x.ip]
        extra += [x.hostname for x in sgs if x.hostname] + [i.label for i in d.interfaces if i.label]
        if d.room:
            extra += [d.room.number, d.room.name, d.room.building, d.room.floor]
        if d.department:
            extra.append(d.department.name)
        extra += [r.value for r in d.remote] + [r.label for r in d.remote]
        for dp in links:
            extra += [dp.person.display_name, dp.person.username]
            if contacts:
                extra += [dp.person.email, dp.person.phone, dp.person.mobile, dp.person.chat]
        row["search_extra"] = [x for x in extra if x]
        rows.append(row)
    for mac, sg in sightings.items():
        if mac not in owned:
            rows.append({"type": "unknown", "id": None, "name": None, "kind": "", **_sighting_dict(sg, aliases),
                         "macs": [mac], "pinned": [], "room": None, "department": None, "people": []})
    for r in rows:
        r["_blob"] = search_blob(r)
        r["_mackeys"] = [mac_search_key(m) for m in r["macs"]]
    return rows


@router.get("/devices")
def list_devices(request: Request, q: str | None = None, show: str = "all",
                 user: User = Depends(current_user)) -> dict[str, Any]:
    with _db(request).session() as s:
        rows = build_rows(s, _engine(request).port_aliases, _contacts_ok(request, user))
    if show == "known":
        rows = [r for r in rows if r["type"] == "device"]
    elif show == "unknown":
        rows = [r for r in rows if r["type"] == "unknown"]
    elif show == "online":
        rows = [r for r in rows if r.get("online")]
    total = len(rows)
    rows = filter_rows(rows, q)
    rows.sort(key=lambda r: (r["type"] != "device", (r.get("name") or "").lower(), ip_sort_key(r.get("ip"))))
    for r in rows:
        r.pop("_blob", None), r.pop("_mackeys", None), r.pop("search_extra", None)
    return {"total": total, "rows": rows}


# --- device card ----------------------------------------------------------------------------

def _events_for(s: Session, macs: list[str], device_id: int | None, limit: int = 30) -> list[dict[str, Any]]:
    cond = [EventLog.mac.in_(macs)] if macs else []
    if device_id:
        cond.append(EventLog.device_id == device_id)
    if not cond:
        return []
    rows = s.scalars(select(EventLog).where(or_(*cond)).order_by(EventLog.ts.desc()).limit(limit))
    return [{"ts": e.ts, "kind": e.kind, "message": e.message} for e in rows]


@router.get("/devices/{device_id}")
def get_device(device_id: int, request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
    from .api_remote import device_remote  # local import: api_remote builds on this module
    aliases = _engine(request).port_aliases
    contacts = _contacts_ok(request, user)
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        sightings = {x.mac: x for x in s.scalars(select(Sighting).where(Sighting.mac.in_([i.mac for i in d.interfaces])))}
        ips = [x.ip for x in sightings.values() if x.ip]
        links = sorted(d.people, key=lambda dp: (not dp.is_primary, dp.person.display_name.lower()))
        return {
            "type": "device", "id": d.id, "name": d.name, "kind": d.kind, "description": d.description,
            "created_at": d.created_at, "updated_at": d.updated_at,
            "room": _room_dict(d.room),
            "department": {"id": d.department.id, "name": d.department.name} if d.department else None,
            "people": [{"link_id": dp.id, "primary": dp.is_primary, **_person_dict(dp.person, contacts)} for dp in links],
            "contacts_visible": contacts,
            "naming_warnings": naming.check(_conventions(request), d.name, d.kind, ips),
            "interfaces": [{"id": i.id, "mac": i.mac, "label": i.label, "expected_ip": i.expected_ip,
                            **{k: v for k, v in _sighting_dict(sightings.get(i.mac), aliases).items() if k != "mac"}}
                           for i in d.interfaces],
            "notes": [{"id": n.id, "text": n.text, "pinned": n.pinned, "author": n.author,
                       "created_at": n.created_at, "updated_at": n.updated_at} for n in d.notes],
            "events": _events_for(s, [i.mac for i in d.interfaces], d.id),
            "remote": device_remote(request, s, d),
            "netbox": _engine(request).netbox.info(d.name, [i.mac for i in d.interfaces]) if _engine(request).netbox else None,
            "netbox_writable": bool(_engine(request).netbox and not _engine(request).netbox.read_only),
            "proposals": [{"id": p.id, "kind": p.kind, "summary": p.summary, "status": p.status,
                           "display": (p.payload or {}).get("display", {})}
                          for p in s.scalars(select(Proposal).where(Proposal.device_id == d.id, Proposal.status.in_(("open", "failed"))))],
        }


@router.get("/macs/{mac}")
def get_mac(mac: str, request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
    m = normalize_mac(mac)
    if not m:
        raise HTTPException(400, "That is not a MAC address.")
    with _db(request).session() as s:
        dev = s.scalar(select(Interface.device_id).where(Interface.mac == m))
        if dev:
            return {"type": "redirect", "device_id": dev}
        sg = s.get(Sighting, m)
        if sg is None:
            raise HTTPException(404, "This MAC address has not been seen.")
        return {"type": "unknown", "mac": m, **_sighting_dict(sg, _engine(request).port_aliases),
                "suggested_name": naming.suggest(_conventions(request), sg.hostname),
                "events": _events_for(s, [m], None)}


class DeviceBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=5000)
    mac: str | None = None


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    room_id: int | None = None
    department_id: int | None = None
    clear: list[str] = Field(default_factory=list)   # "room", "department": remove the assignment


def _mac_free(s: Session, mac: str) -> None:
    owner = s.scalar(select(Device).join(Interface).where(Interface.mac == mac))
    if owner:
        raise HTTPException(409, f"{mac} already belongs to {owner.name}.")


@router.post("/devices")
def create_device(body: DeviceBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    with _db(request).session() as s:
        d = Device(name=body.name.strip(), kind=body.kind.strip(), description=body.description)
        if body.mac:
            mac = normalize_mac(body.mac)
            if not mac:
                raise HTTPException(400, "That is not a MAC address.")
            _mac_free(s, mac)
            d.interfaces.append(Interface(mac=mac))
        s.add(d)
        s.flush()
        _audit(s, user, "device.create", d.name, mac=body.mac)
        did = d.id
    _engine(request).publish({"type": "refresh"})
    return {"id": did}


@router.patch("/devices/{device_id}")
def update_device(device_id: int, body: DevicePatch, request: Request,
                  user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        changes = body.model_dump(exclude_none=True, exclude={"clear"})
        for k in ("name", "kind", "description"):
            if k in changes:
                setattr(d, k, changes[k].strip() if k != "description" else changes[k])
        if "room_id" in changes:
            if s.get(Room, changes["room_id"]) is None:
                raise HTTPException(404, "No such room.")
            d.room_id = changes["room_id"]
        if "department_id" in changes:
            if s.get(Department, changes["department_id"]) is None:
                raise HTTPException(404, "No such department.")
            d.department_id = changes["department_id"]
        for what in body.clear:
            if what in ("room", "department"):
                setattr(d, f"{what}_id", None)
                changes[f"{what}_id"] = None
        _audit(s, user, "device.update", d.name, **changes)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


@router.delete("/devices/{device_id}")
def delete_device(device_id: int, request: Request, user: User = Depends(require("admin"))) -> dict[str, bool]:
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        _audit(s, user, "device.delete", d.name, macs=[i.mac for i in d.interfaces])
        s.delete(d)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


class InterfaceBody(BaseModel):
    mac: str
    label: str = Field(default="", max_length=100)


@router.post("/devices/{device_id}/interfaces")
def add_interface(device_id: int, body: InterfaceBody, request: Request,
                  user: User = Depends(require("editor"))) -> dict[str, Any]:
    mac = normalize_mac(body.mac)
    if not mac:
        raise HTTPException(400, "That is not a MAC address.")
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        _mac_free(s, mac)
        i = Interface(device_id=d.id, mac=mac, label=body.label.strip())
        s.add(i)
        s.flush()
        _audit(s, user, "interface.add", d.name, mac=mac)
        iid = i.id
    _engine(request).publish({"type": "refresh"})
    return {"id": iid}


@router.delete("/interfaces/{interface_id}")
def remove_interface(interface_id: int, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        i = s.get(Interface, interface_id)
        if i is None:
            raise HTTPException(404, "No such interface.")
        _audit(s, user, "interface.remove", i.device.name, mac=i.mac)
        s.delete(i)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


class NoteBody(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    pinned: bool = False


class NotePatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=5000)
    pinned: bool | None = None


@router.post("/devices/{device_id}/notes")
def add_note(device_id: int, body: NoteBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        n = Note(device_id=d.id, text=body.text.strip(), pinned=body.pinned, author=user.username)
        s.add(n)
        s.flush()
        _audit(s, user, "note.add", d.name, pinned=body.pinned)
        nid = n.id
    _engine(request).publish({"type": "refresh"})
    return {"id": nid}


@router.patch("/notes/{note_id}")
def update_note(note_id: int, body: NotePatch, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        n = s.get(Note, note_id)
        if n is None:
            raise HTTPException(404, "No such note.")
        if body.text is not None:
            n.text = body.text.strip()
        if body.pinned is not None:
            n.pinned = body.pinned
        _audit(s, user, "note.update", n.device.name, note=n.id)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        n = s.get(Note, note_id)
        if n is None:
            raise HTTPException(404, "No such note.")
        _audit(s, user, "note.delete", n.device.name, text=n.text[:200])
        s.delete(n)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


# --- events, sources, users -----------------------------------------------------------------

@router.get("/events")
def list_events(request: Request, limit: int = 200, kind: str | None = None,
                user: User = Depends(current_user)) -> list[dict[str, Any]]:
    with _db(request).session() as s:
        q = select(EventLog).order_by(EventLog.ts.desc()).limit(min(limit, 1000))
        if kind:
            q = q.where(EventLog.kind == kind)
        return [{"id": e.id, "ts": e.ts, "kind": e.kind, "mac": e.mac, "device_id": e.device_id,
                 "message": e.message} for e in s.scalars(q)]


@router.get("/sources")
def list_sources(request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
    eng = _engine(request)
    return {
        "last_merge": eng.last_merge,
        "sources": [vars(st) for st in eng.state.values()] + ([vars(eng.directory.state)] if eng.directory else [])
                   + ([vars(eng.netbox.state)] if eng.netbox else []),
        "suspect_ports": [{"switch": k[0], "port": k[1], "macs": v} for k, v in sorted(eng.suspect_ports.items())],
    }


class UserBody(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=12, max_length=500)
    role: str = "viewer"


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=12, max_length=500)
    role: str | None = None


@router.get("/users")
def list_users(request: Request, user: User = Depends(require("admin"))) -> list[dict[str, Any]]:
    with _db(request).session() as s:
        return [{"id": u.id, "username": u.username, "role": u.role, "last_login": u.last_login}
                for u in s.scalars(select(User).order_by(User.username))]


@router.post("/users")
def create_user(body: UserBody, request: Request, user: User = Depends(require("admin"))) -> dict[str, Any]:
    if body.role not in ROLES:
        raise HTTPException(400, f"Role must be one of {', '.join(ROLES)}.")
    with _db(request).session() as s:
        if s.scalar(select(User).where(User.username == body.username)):
            raise HTTPException(409, "That user name is taken.")
        u = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
        s.add(u)
        s.flush()
        _audit(s, user, "user.create", body.username, role=body.role)
        return {"id": u.id}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, user: User = Depends(require("admin"))) -> dict[str, bool]:
    with _db(request).session() as s:
        u = s.get(User, user_id)
        if u is None:
            raise HTTPException(404, "No such user.")
        if body.role is not None:
            if body.role not in ROLES:
                raise HTTPException(400, f"Role must be one of {', '.join(ROLES)}.")
            if u.id == user.id and body.role != "admin":
                raise HTTPException(400, "You cannot remove your own admin role.")
            u.role = body.role
        if body.password is not None:
            u.password_hash = hash_password(body.password)
        _audit(s, user, "user.update", u.username, role=body.role, password_changed=body.password is not None)
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, user: User = Depends(require("admin"))) -> dict[str, bool]:
    if user_id == user.id:
        raise HTTPException(400, "You cannot delete your own account.")
    with _db(request).session() as s:
        u = s.get(User, user_id)
        if u is None:
            raise HTTPException(404, "No such user.")
        _audit(s, user, "user.delete", u.username)
        s.delete(u)
    return {"ok": True}


# --- live updates and health ----------------------------------------------------------------

@router.get("/stream")
async def stream(request: Request, user: User = Depends(current_user)) -> StreamingResponse:
    eng = _engine(request)

    async def gen():
        q = eng.subscribe()
        try:
            yield "retry: 5000\n\n"
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(msg)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            eng.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    eng = _engine(request)
    return {"status": "ok", "version": __version__, "sources": len(eng.sources),
            "failing": [st.name for st in eng.state.values() if st.error]}
