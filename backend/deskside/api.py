"""HTTP API. The web interface uses exactly these endpoints; nothing is private to it."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .auth import COOKIE, MAX_AGE, ROLES, current_user, hash_password, require, verify_password
from . import naming
from .db import (AuditLog, Department, Device, DevicePerson, EventLog, History, Interface, Note, Person, Proposal, Room,
                 Sighting, User, now)
from .netaddr import ip_sort_key, is_locally_administered, mac_search_key, normalize_mac
from .oidc import STATE_COOKIE, STATE_MAX_AGE, OidcError
from .search import filter_rows, search_blob

router = APIRouter(prefix="/api")
log = logging.getLogger("deskside")


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


@router.get("/auth/config")
def auth_config(request: Request) -> dict[str, Any]:
    """What the sign-in page offers. Public: it reveals nothing but the button label."""
    oidc = getattr(request.app.state, "oidc", None)
    return {"local_login": request.app.state.settings.local_login, "sso": oidc.label if oidc else None}


@router.get("/auth/start")
def auth_start(request: Request, next: str = "/") -> RedirectResponse:
    oidc = getattr(request.app.state, "oidc", None)
    if oidc is None:
        raise HTTPException(404, "Single sign-on is not configured.")
    try:
        url, state = oidc.start(next)
    except OidcError as exc:
        return RedirectResponse("/?login_error=" + quote(str(exc)), status_code=303)
    resp = RedirectResponse(url, status_code=303)
    # Lax, not strict: the identity provider sends the browser back with a cross-site navigation.
    resp.set_cookie(STATE_COOKIE, state, max_age=STATE_MAX_AGE, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https", path="/api/auth")
    return resp


@router.get("/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "", error: str = "",
                  error_description: str = "") -> RedirectResponse:
    oidc = getattr(request.app.state, "oidc", None)
    if oidc is None:
        raise HTTPException(404, "Single sign-on is not configured.")

    def fail(msg: str) -> RedirectResponse:
        resp = RedirectResponse("/?login_error=" + quote(msg[:300]), status_code=303)
        resp.delete_cookie(STATE_COOKIE, path="/api/auth")
        return resp

    if error:
        return fail(error_description or error)
    try:
        info = oidc.finish(code, state, request.cookies.get(STATE_COOKIE, ""))
    except OidcError as exc:
        return fail(str(exc))
    if info["role"] is None:
        log.info("sign-in refused for %s: none of the configured groups", info["username"])
        return fail("Your account is not in a group that may use deskside.")
    with _db(request).session() as s:
        user = s.scalar(select(User).where(User.username == info["username"]))
        if user is None:
            user = User(username=info["username"], password_hash="!sso", role=info["role"], source="sso")
            s.add(user)
            s.flush()
        elif user.role != info["role"]:
            s.add(AuditLog(username=user.username, action="user.role_from_groups", target=user.username,
                           detail={"from": user.role, "to": info["role"]}))
        user.role, user.source, user.last_login = info["role"], "sso", now()
        token = request.app.state.sessions.issue(user)
    resp = RedirectResponse(info["next"], status_code=303)
    resp.delete_cookie(STATE_COOKIE, path="/api/auth")
    resp.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https", path="/")
    return resp


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    if not request.app.state.settings.local_login:
        raise HTTPException(403, "Sign in with single sign-on.")
    client = request.client.host if request.client else "?"
    window = _attempts[client]
    t = time.time()
    while window and t - window[0] > 300:
        window.popleft()
    if len(window) >= 10:
        raise HTTPException(429, "Too many failed sign-ins. Wait five minutes and try again.")
    with _db(request).session() as s:
        user = s.scalar(select(User).where(User.username == body.username))
        if user is None or user.source == "sso" or not verify_password(body.password, user.password_hash):
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

def _sighting_dict(sg: Sighting | None, ports: Any) -> dict[str, Any]:
    if sg is None:
        return {"online": False}
    return {
        "mac": sg.mac, "ip": sg.ip, "hostname": sg.hostname, "hostname_source": sg.hostname_source,
        "vendor": sg.vendor, "switch": sg.switch, "port": sg.port, "vlan": sg.vlan,
        "port_alias": ports.port_alias(sg.switch, sg.port), "port_place": ports.port_place(sg.switch, sg.port),
        "port_mac_count": sg.port_mac_count,
        "behind_uplink": sg.behind_uplink, "dhcp": sg.dhcp, "online": sg.online,
        "first_seen": sg.first_seen, "last_seen": sg.last_seen or None, "port_since": sg.port_since,
        "sources": sg.sources,
    }


def _primary(sightings: list[Sighting], mgmt: set[str] | frozenset[str] = frozenset()) -> Sighting | None:
    """The interface shown in the list: online first, not a management port (iLO, iDRAC), most recently seen."""
    return max(sightings, key=lambda x: (x.online, x.mac not in mgmt, x.last_seen), default=None)


def mgmt_macs(ports: Any, d: Device) -> set[str]:
    """MAC addresses of a device's management interfaces, by the interface names NetBox marks management-only."""
    names = ports.mgmt_names() if hasattr(ports, "mgmt_names") else set()
    return {i.mac for i in d.interfaces if (i.label or "").lower() in names}


def build_rows(s: Session, ports: Any, contacts: bool) -> list[dict[str, Any]]:
    sightings = {x.mac: x for x in s.scalars(select(Sighting))}
    rows: list[dict[str, Any]] = []
    owned: set[str] = set()
    devices = s.scalars(select(Device).options(
        selectinload(Device.interfaces), selectinload(Device.notes), selectinload(Device.room),
        selectinload(Device.department), selectinload(Device.people).selectinload(DevicePerson.person),
        selectinload(Device.remote)))
    devices = list(devices)
    names = {d.id: d.name for d in devices}
    child_count: dict[int, int] = {}
    for d in devices:
        if d.parent_id:
            child_count[d.parent_id] = child_count.get(d.parent_id, 0) + 1
    for d in devices:
        macs = [i.mac for i in d.interfaces]
        owned.update(macs)
        sgs = [sightings[m] for m in macs if m in sightings]
        links = sorted(d.people, key=lambda dp: (not dp.is_primary, dp.person.display_name.lower()))
        row = {"type": "device", "id": d.id, "name": d.name, "kind": d.kind, "description": d.description,
               **_sighting_dict(_primary(sgs, mgmt_macs(ports, d)), ports), "macs": macs,
               "pinned": [n.text for n in d.notes if n.pinned],
               "icon": d.icon, "parent_id": d.parent_id, "parent": names.get(d.parent_id) if d.parent_id else None,
               "children": child_count.get(d.id, 0), "manufacturer": d.manufacturer, "model": d.model,
               "connection": d.connection, "source": d.source,
               "room": _room_label(d.room) or None, "department": d.department.name if d.department else None,
               "people": [dp.person.display_name for dp in links]}
        row["mac"] = row.get("mac") or (macs[0] if macs else None)
        live_ip = row.get("ip")
        if not live_ip:
            # Fixed addresses that no DHCP or ARP source reports: what NetBox documents, else what was set in deskside.
            doc, by = _documented_ip(ports, d)
            if doc:
                row["ip"], row["ip_documented"], row["ip_documented_by"] = doc, True, by
        elif d.fixed_ip and d.fixed_ip != live_ip:
            row["ip_expected"] = d.fixed_ip
        extra = [n.text for n in d.notes] + [x.ip for x in sgs if x.ip] + ([row["ip"]] if row.get("ip_documented") else [])
        extra += [d.fixed_ip] if d.fixed_ip else []
        extra += [x.hostname for x in sgs if x.hostname] + [i.label for i in d.interfaces if i.label]
        if d.room:
            extra += [d.room.number, d.room.name, d.room.building, d.room.floor]
        if d.department:
            extra.append(d.department.name)
        extra += [r.value for r in d.remote] + [r.label for r in d.remote]
        extra += [d.manufacturer, d.model, d.serial, names.get(d.parent_id, "") if d.parent_id else ""]
        for dp in links:
            extra += [dp.person.display_name, dp.person.username]
            if contacts:
                extra += [dp.person.email, dp.person.phone, dp.person.mobile, dp.person.chat]
        row["search_extra"] = [x for x in extra if x]
        rows.append(row)
    for mac, sg in sightings.items():
        if mac not in owned:
            rows.append({"type": "unknown", "id": None, "name": None, "kind": "", **_sighting_dict(sg, ports),
                         "macs": [mac], "pinned": [], "room": None, "department": None, "people": [],
                         "icon": "", "parent_id": None, "parent": None, "children": 0})
    for r in rows:
        r["_blob"] = search_blob(r)
        r["_mackeys"] = [mac_search_key(m) for m in r["macs"]]
    return rows


@router.get("/devices")
def list_devices(request: Request, q: str | None = None, show: str = "all",
                 user: User = Depends(current_user)) -> dict[str, Any]:
    with _db(request).session() as s:
        rows = build_rows(s, _engine(request), _contacts_ok(request, user))
    # Addresses that only a DHCP lease knows about and that no switch or ARP table ever showed: mostly
    # phones and laptops with a new random MAC per network, valid for days after they left. Kept out of
    # the default list (a search still finds them) and available under their own filter.
    def lease_only(r: dict[str, Any]) -> bool:
        return r["type"] == "unknown" and not r.get("online") and not r.get("last_seen")

    hidden = sum(1 for r in rows if lease_only(r))
    if show == "all" and not q:
        rows = [r for r in rows if not lease_only(r)]
    elif show == "leases":
        rows = [r for r in rows if lease_only(r)]
    elif show == "known":
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
    return {"total": total, "rows": rows, "lease_only": hidden}


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
    ports = _engine(request)
    contacts = _contacts_ok(request, user)
    with _db(request).session() as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(404, "No such device.")
        sightings = {x.mac: x for x in s.scalars(select(Sighting).where(Sighting.mac.in_([i.mac for i in d.interfaces])))}
        ips = [x.ip for x in sightings.values() if x.ip]
        links = sorted(d.people, key=lambda dp: (not dp.is_primary, dp.person.display_name.lower()))
        # Same fallback as the device list: a fixed address no live source reports, as documented.
        documented, documented_by = _documented_ip(ports, d) if not ips else (None, None)
        # A fixed address seen on the network under a MAC that belongs to no device yet: offer to take it over.
        seen_at_ip = None
        if d.fixed_ip:
            owned = select(Interface.mac)
            # Randomised MACs are phones and laptops that got the address from a pool; never a fixed-address device.
            sg = next((x for x in s.scalars(select(Sighting).where(Sighting.ip == d.fixed_ip, Sighting.mac.not_in(owned))
                                            .order_by(Sighting.online.desc(), Sighting.last_seen.desc()))
                       if not is_locally_administered(x.mac)), None)
            if sg is not None:
                seen_at_ip = {"mac": sg.mac, "vendor": sg.vendor, "online": sg.online, "last_seen": sg.last_seen or None}
        return {
            "type": "device", "id": d.id, "name": d.name, "kind": d.kind, "description": d.description,
            "created_at": d.created_at, "updated_at": d.updated_at,
            "icon": d.icon, "manufacturer": d.manufacturer, "model": d.model, "serial": d.serial,
            "connection": d.connection, "source": d.source,
            "parent": _brief(d.parent) if d.parent else None,
            "children": [{**_brief(c), "connection": c.connection, "manufacturer": c.manufacturer, "model": c.model,
                          "serial": c.serial, "children": len(c.children)}
                         for c in sorted(d.children, key=lambda c: (c.kind.lower(), c.name.lower()))],
            "segment": _segment(s, d, sightings, ports),
            "room": _room_dict(d.room),
            "department": {"id": d.department.id, "name": d.department.name} if d.department else None,
            "people": [{"link_id": dp.id, "primary": dp.is_primary, **_person_dict(dp.person, contacts)} for dp in links],
            "contacts_visible": contacts,
            "documented_ip": documented, "documented_by": documented_by,
            "fixed_ip": d.fixed_ip, "fixed_ip_seen": seen_at_ip,
            "fixed_ip_mismatch": sorted({ip for ip in ips if d.fixed_ip and ip != d.fixed_ip}),
            "naming_warnings": naming.check(_conventions(request), d.name, d.kind, ips),
            "interfaces": [{"id": i.id, "mac": i.mac, "label": i.label, "expected_ip": i.expected_ip,
                            **{k: v for k, v in _sighting_dict(sightings.get(i.mac), ports).items() if k != "mac"}}
                           for i in d.interfaces],
            "notes": [{"id": n.id, "text": n.text, "pinned": n.pinned, "author": n.author,
                       "created_at": n.created_at, "updated_at": n.updated_at} for n in d.notes],
            "events": _events_for(s, [i.mac for i in d.interfaces], d.id),
            "remote": device_remote(request, s, d),
            "netbox": (_engine(request).netbox.info(d.name, [i.mac for i in d.interfaces], d.external_id)
                       if _engine(request).netbox else None),
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
        return {"type": "unknown", "mac": m, **_sighting_dict(sg, _engine(request)),
                "suggested_name": naming.suggest(_conventions(request), sg.hostname),
                "events": _events_for(s, [m], None)}


class DeviceBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=5000)
    mac: str | None = None
    parent_id: int | None = None
    connection: str = Field(default="", max_length=30)
    manufacturer: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=100)
    serial: str = Field(default="", max_length=100)
    icon: str = Field(default="", max_length=60)
    fixed_ip: str = Field(default="", max_length=45)


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    room_id: int | None = None
    department_id: int | None = None
    parent_id: int | None = None
    connection: str | None = Field(default=None, max_length=30)
    manufacturer: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    icon: str | None = Field(default=None, max_length=60)
    fixed_ip: str | None = Field(default=None, max_length=45)   # "" removes it
    clear: list[str] = Field(default_factory=list)   # "room", "department", "parent": remove the assignment


def _brief(d: Device) -> dict[str, Any]:
    return {"id": d.id, "name": d.name, "kind": d.kind, "icon": d.icon}


def _check_parent(s: Session, d: Device, parent_id: int) -> None:
    """A device cannot hang off itself or off one of its own attached devices."""
    p = s.get(Device, parent_id)
    if p is None:
        raise HTTPException(404, "No such parent device.")
    seen = set()
    while p is not None:
        if p.id == d.id:
            raise HTTPException(400, f"{d.name} cannot be attached to itself or to one of its own devices.")
        if p.id in seen:
            break
        seen.add(p.id)
        p = p.parent


def _segment(s: Session, d: Device, sightings: dict[str, Sighting], ports: Any) -> dict[str, Any] | None:
    """Where the device is plugged in, and who else is on the same switch port."""
    sg = _primary(list(sightings.values()), mgmt_macs(ports, d))
    if sg is None or not sg.port:
        return None
    own = {i.mac for i in d.interfaces}
    others = [x for x in s.scalars(select(Sighting).where(Sighting.switch == sg.switch, Sighting.port == sg.port,
                                                         Sighting.online)) if x.mac not in own]
    owners = dict(s.execute(select(Interface.mac, Interface.device_id).where(Interface.mac.in_([x.mac for x in others]))).all())
    devs = {x.id: x for x in s.scalars(select(Device).where(Device.id.in_(set(owners.values()))))} if owners else {}
    peers, seen_dev = [], set()
    for x in others:
        dev = devs.get(owners.get(x.mac))
        if dev is not None:
            if dev.id not in seen_dev:
                seen_dev.add(dev.id)
                peers.append({"type": "device", **_brief(dev), "ip": x.ip})
        else:
            peers.append({"type": "unknown", "mac": x.mac, "name": x.hostname, "ip": x.ip, "vendor": x.vendor})
    return {"switch": sg.switch, "port": sg.port, "alias": ports.port_alias(sg.switch, sg.port),
            "place": ports.port_place(sg.switch, sg.port),
            "port_mac_count": sg.port_mac_count, "behind_uplink": sg.behind_uplink, "online": sg.online, "peers": peers}


def _documented_ip(ports: Any, d: Device) -> tuple[str | None, str | None]:
    """The address a device should have when no live source reports one, and who says so: NetBox first, as the
    documentation of record where it is connected, then the address set in deskside."""
    if hasattr(ports, "documented_ip"):
        doc = ports.documented_ip(d.name, [i.mac for i in d.interfaces], d.external_id)
        if doc:
            return doc, "netbox"
    return (d.fixed_ip, "deskside") if d.fixed_ip else (None, None)


def _clean_ip(value: str) -> str | None:
    """A fixed address as entered: empty means none, anything else must be one IPv4 or IPv6 address."""
    value = value.strip()
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.split("/")[0]))
    except ValueError:
        raise HTTPException(400, f"{value} is not an IP address.") from None


def _mac_free(s: Session, mac: str) -> None:
    owner = s.scalar(select(Device).join(Interface).where(Interface.mac == mac))
    if owner:
        raise HTTPException(409, f"{mac} already belongs to {owner.name}.")


@router.post("/devices")
def create_device(body: DeviceBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    with _db(request).session() as s:
        d = Device(name=body.name.strip(), kind=body.kind.strip(), description=body.description,
                   connection=body.connection.strip(), manufacturer=body.manufacturer.strip(), model=body.model.strip(),
                   serial=body.serial.strip(), icon=body.icon.strip(), fixed_ip=_clean_ip(body.fixed_ip))
        if body.parent_id is not None:
            if s.get(Device, body.parent_id) is None:
                raise HTTPException(404, "No such parent device.")
            d.parent_id = body.parent_id
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
        if d.source == "netbox" and {"name", "manufacturer", "model", "serial"} & set(changes):
            raise HTTPException(400, "Name, manufacturer, model and serial of this device come from NetBox; change them there.")
        if d.source == "netbox" and "fixed_ip" in changes:
            raise HTTPException(400, "The addresses of this device come from NetBox; change them there.")
        if "fixed_ip" in changes:
            d.fixed_ip = changes["fixed_ip"] = _clean_ip(changes["fixed_ip"])
        for k in ("name", "kind", "description", "connection", "manufacturer", "model", "serial", "icon"):
            if k in changes:
                setattr(d, k, changes[k].strip() if k != "description" else changes[k])
        if "parent_id" in changes:
            _check_parent(s, d, changes["parent_id"])
            d.parent_id = changes["parent_id"]
        if "room_id" in changes:
            if s.get(Room, changes["room_id"]) is None:
                raise HTTPException(404, "No such room.")
            d.room_id = changes["room_id"]
        if "department_id" in changes:
            if s.get(Department, changes["department_id"]) is None:
                raise HTTPException(404, "No such department.")
            d.department_id = changes["department_id"]
        for what in body.clear:
            if what in ("room", "department", "parent"):
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
def list_events(request: Request, limit: int = 200, kind: str | None = None, q: str | None = None,
                device_id: int | None = None, before: int | None = None,
                user: User = Depends(current_user)) -> list[dict[str, Any]]:
    """Newest first. ``kind`` may list several kinds separated by commas; ``before`` pages back by id."""
    with _db(request).session() as s:
        stmt = select(EventLog).order_by(EventLog.id.desc()).limit(min(limit, 1000))
        if kind:
            stmt = stmt.where(EventLog.kind.in_([k for k in kind.split(",") if k]))
        if device_id:
            macs = list(s.scalars(select(Interface.mac).where(Interface.device_id == device_id)))
            stmt = stmt.where(or_(EventLog.device_id == device_id, EventLog.mac.in_(macs)))
        if before:
            stmt = stmt.where(EventLog.id < before)
        if q:
            stmt = stmt.where(EventLog.message.ilike(f"%{q.strip()}%"))
        return [{"id": e.id, "ts": e.ts, "kind": e.kind, "mac": e.mac, "device_id": e.device_id,
                 "message": e.message} for e in s.scalars(stmt)]


@router.get("/history")
def history(request: Request, device_id: int | None = None, mac: str | None = None,
            user: User = Depends(current_user)) -> list[dict[str, Any]]:
    """Port and address periods of a device (all its MAC addresses) or of one MAC address, newest first."""
    with _db(request).session() as s:
        if device_id:
            macs = list(s.scalars(select(Interface.mac).where(Interface.device_id == device_id)))
        elif mac and normalize_mac(mac):
            macs = [normalize_mac(mac)]
        else:
            raise HTTPException(400, "Give a device_id or a MAC address.")
        rows = s.scalars(select(History).where(History.mac.in_(macs)).order_by(History.start.desc()).limit(500))
        return [{"kind": h.kind, "mac": h.mac, "switch": h.switch, "value": h.value, "start": h.start, "end": h.end}
                for h in rows]


@router.post("/notifications/test")
async def test_notifications(request: Request, user: User = Depends(require("admin"))) -> list[dict[str, Any]]:
    n = _engine(request).notifier
    if not n.channels:
        raise HTTPException(400, "No notification channels are configured.")
    return await n.test()


@router.get("/sources")
def list_sources(request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
    eng = _engine(request)
    return {
        "last_merge": eng.last_merge,
        "sources": [vars(st) for st in eng.state.values()] + ([vars(eng.directory.state)] if eng.directory else [])
                   + ([vars(eng.netbox.state)] if eng.netbox else []) + [vars(c.state) for c in eng.notifier.channels],
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
        return [{"id": u.id, "username": u.username, "role": u.role, "last_login": u.last_login,
                 "source": u.source or "local"}
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


@router.post("/ingest/{name}")
async def ingest(name: str, request: Request) -> dict[str, Any]:
    """Uploads for push sources (dhcp-push). Authenticated by the source's token, not by a session."""
    from .sources.base import SourceError
    from .sources.dhcp import DhcpPush
    eng = _engine(request)
    src = next((s for s in eng.sources if s.name == name and isinstance(s, DhcpPush)), None)
    if src is None or not src.check_token(request.headers.get("authorization")):
        raise HTTPException(401, "Unknown source or wrong token.")
    raw = await request.body()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Upload too large.")
    try:
        count = src.accept(raw)
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    await eng.run_source(src)
    return {"ok": True, "addresses": count}


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    eng = _engine(request)
    return {"ok": True, "status": "ok", "version": __version__, "sources": len(eng.sources),
            "failing": [st.name for st in eng.state.values() if st.error]}
