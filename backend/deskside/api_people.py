"""API for rooms, departments, people, device assignments and naming conventions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from .api import _audit, _contacts_ok, _conventions, _db, _engine, _person_dict, _room_dict
from .auth import current_user, require
from .db import Department, Device, DevicePerson, Person, Room, Sighting, User

router = APIRouter(prefix="/api")


def _refresh(request: Request) -> None:
    _engine(request).publish({"type": "refresh"})


# --- rooms ----------------------------------------------------------------------------------

class RoomBody(BaseModel):
    number: str = Field(default="", max_length=50)
    name: str = Field(default="", max_length=200)
    building: str = Field(default="", max_length=100)
    floor: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=5000)


@router.get("/rooms")
def list_rooms(request: Request, user: User = Depends(current_user)) -> list[dict[str, Any]]:
    with _db(request).session() as s:
        counts = dict(s.execute(select(Device.room_id, func.count()).group_by(Device.room_id)).all())
        rooms = s.scalars(select(Room).order_by(Room.building, Room.floor, Room.number, Room.name))
        return [{**_room_dict(r), "devices": counts.get(r.id, 0)} for r in rooms]


def _check_room(body: RoomBody) -> None:
    if not (body.number.strip() or body.name.strip()):
        raise HTTPException(400, "A room needs a number or a name.")


@router.post("/rooms")
def create_room(body: RoomBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    _check_room(body)
    with _db(request).session() as s:
        r = Room(**{k: v.strip() if k != "description" else v for k, v in body.model_dump().items()})
        s.add(r)
        s.flush()
        _audit(s, user, "room.create", f"{r.number} {r.name}".strip())
        return {"id": r.id}


@router.patch("/rooms/{room_id}")
def update_room(room_id: int, body: RoomBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    _check_room(body)
    with _db(request).session() as s:
        r = s.get(Room, room_id)
        if r is None:
            raise HTTPException(404, "No such room.")
        for k, v in body.model_dump().items():
            setattr(r, k, v.strip() if k != "description" else v)
        _audit(s, user, "room.update", f"{r.number} {r.name}".strip())
    _refresh(request)
    return {"ok": True}


@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        r = s.get(Room, room_id)
        if r is None:
            raise HTTPException(404, "No such room.")
        for d in s.scalars(select(Device).where(Device.room_id == room_id)):
            d.room_id = None
        _audit(s, user, "room.delete", f"{r.number} {r.name}".strip())
        s.delete(r)
    _refresh(request)
    return {"ok": True}


# --- departments ----------------------------------------------------------------------------

class DepartmentBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


@router.get("/departments")
def list_departments(request: Request, user: User = Depends(current_user)) -> list[dict[str, Any]]:
    with _db(request).session() as s:
        devs = dict(s.execute(select(Device.department_id, func.count()).group_by(Device.department_id)).all())
        ppl = dict(s.execute(select(Person.department_id, func.count()).where(Person.active)
                             .group_by(Person.department_id)).all())
        return [{"id": d.id, "name": d.name, "description": d.description, "source": d.source,
                 "devices": devs.get(d.id, 0), "people": ppl.get(d.id, 0)}
                for d in s.scalars(select(Department).order_by(Department.name))]


@router.post("/departments")
def create_department(body: DepartmentBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    with _db(request).session() as s:
        if s.scalar(select(Department).where(Department.name == body.name.strip())):
            raise HTTPException(409, "A department with that name exists.")
        d = Department(name=body.name.strip(), description=body.description)
        s.add(d)
        s.flush()
        _audit(s, user, "department.create", d.name)
        return {"id": d.id}


@router.patch("/departments/{dep_id}")
def update_department(dep_id: int, body: DepartmentBody, request: Request,
                      user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        d = s.get(Department, dep_id)
        if d is None:
            raise HTTPException(404, "No such department.")
        if d.source == "directory" and body.name.strip() != d.name:
            raise HTTPException(400, "This department comes from the directory; rename it there.")
        d.name, d.description = body.name.strip(), body.description
        _audit(s, user, "department.update", d.name)
    _refresh(request)
    return {"ok": True}


@router.delete("/departments/{dep_id}")
def delete_department(dep_id: int, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        d = s.get(Department, dep_id)
        if d is None:
            raise HTTPException(404, "No such department.")
        if d.source == "directory":
            raise HTTPException(400, "This department comes from the directory and would come back on the next sync.")
        for dev in s.scalars(select(Device).where(Device.department_id == dep_id)):
            dev.department_id = None
        for p in s.scalars(select(Person).where(Person.department_id == dep_id)):
            p.department_id = None
        _audit(s, user, "department.delete", d.name)
        s.delete(d)
    _refresh(request)
    return {"ok": True}


# --- people ---------------------------------------------------------------------------------

class PersonBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    username: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=100)
    mobile: str = Field(default="", max_length=100)
    chat: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    department_id: int | None = None


@router.get("/people")
def list_people(request: Request, q: str | None = None, include_inactive: bool = False,
                user: User = Depends(current_user)) -> list[dict[str, Any]]:
    contacts = _contacts_ok(request, user)
    with _db(request).session() as s:
        stmt = select(Person).order_by(Person.display_name)
        if not include_inactive:
            stmt = stmt.where(Person.active)
        if q:
            like = f"%{q.strip()}%"
            fields = [Person.display_name, Person.username, Person.title]
            if contacts:
                fields += [Person.email, Person.phone, Person.mobile, Person.chat]
            stmt = stmt.where(or_(*(f.ilike(like) for f in fields)))
        counts = dict(s.execute(select(DevicePerson.person_id, func.count()).group_by(DevicePerson.person_id)).all())
        return [{**_person_dict(p, contacts), "devices": counts.get(p.id, 0)} for p in s.scalars(stmt.limit(500))]


@router.post("/people")
def create_person(body: PersonBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    with _db(request).session() as s:
        if body.department_id is not None and s.get(Department, body.department_id) is None:
            raise HTTPException(404, "No such department.")
        p = Person(**{k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items()})
        s.add(p)
        s.flush()
        _audit(s, user, "person.create", p.display_name)
        return {"id": p.id}


@router.patch("/people/{person_id}")
def update_person(person_id: int, body: PersonBody, request: Request,
                  user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        p = s.get(Person, person_id)
        if p is None:
            raise HTTPException(404, "No such person.")
        if p.source == "directory":
            raise HTTPException(400, "This person comes from the directory; change the details there.")
        for k, v in body.model_dump().items():
            setattr(p, k, v.strip() if isinstance(v, str) else v)
        _audit(s, user, "person.update", p.display_name)
    _refresh(request)
    return {"ok": True}


@router.delete("/people/{person_id}")
def delete_person(person_id: int, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        p = s.get(Person, person_id)
        if p is None:
            raise HTTPException(404, "No such person.")
        if p.source == "directory":
            raise HTTPException(400, "This person comes from the directory and would come back on the next sync.")
        _audit(s, user, "person.delete", p.display_name)
        s.delete(p)
    _refresh(request)
    return {"ok": True}


# --- people on devices ----------------------------------------------------------------------

class LinkBody(BaseModel):
    person_id: int
    primary: bool = False


class LinkPatch(BaseModel):
    primary: bool


def _make_primary(s, link: DevicePerson) -> None:
    for other in s.scalars(select(DevicePerson).where(DevicePerson.device_id == link.device_id)):
        other.is_primary = other.id == link.id


@router.post("/devices/{device_id}/people")
def link_person(device_id: int, body: LinkBody, request: Request, user: User = Depends(require("editor"))) -> dict[str, Any]:
    with _db(request).session() as s:
        d, p = s.get(Device, device_id), s.get(Person, body.person_id)
        if d is None or p is None:
            raise HTTPException(404, "No such device or person.")
        if s.scalar(select(DevicePerson).where(DevicePerson.device_id == d.id, DevicePerson.person_id == p.id)):
            raise HTTPException(409, f"{p.display_name} is already assigned to {d.name}.")
        first = not s.scalar(select(DevicePerson.id).where(DevicePerson.device_id == d.id).limit(1))
        link = DevicePerson(device_id=d.id, person_id=p.id, is_primary=body.primary or first)
        s.add(link)
        s.flush()
        if link.is_primary:
            _make_primary(s, link)
        _audit(s, user, "device.person.add", d.name, person=p.display_name)
        lid = link.id
    _refresh(request)
    return {"id": lid}


@router.patch("/device-people/{link_id}")
def update_link(link_id: int, body: LinkPatch, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        link = s.get(DevicePerson, link_id)
        if link is None:
            raise HTTPException(404, "No such assignment.")
        if body.primary:
            _make_primary(s, link)
        else:
            link.is_primary = False
        _audit(s, user, "device.person.primary", link.device.name, person=link.person.display_name)
    _refresh(request)
    return {"ok": True}


@router.delete("/device-people/{link_id}")
def unlink_person(link_id: int, request: Request, user: User = Depends(require("editor"))) -> dict[str, bool]:
    with _db(request).session() as s:
        link = s.get(DevicePerson, link_id)
        if link is None:
            raise HTTPException(404, "No such assignment.")
        _audit(s, user, "device.person.remove", link.device.name, person=link.person.display_name)
        s.delete(link)
    _refresh(request)
    return {"ok": True}


# --- naming and directory -------------------------------------------------------------------

@router.get("/naming")
def list_conventions(request: Request, user: User = Depends(current_user)) -> list[dict[str, Any]]:
    conv = _conventions(request)
    with _db(request).session() as s:
        # Names in use are device names plus host names seen on the network, so a machine that is
        # not yet in deskside does not get its name handed out a second time.
        names = list(s.scalars(select(Device.name))) + [h for h in s.scalars(select(Sighting.hostname)) if h]
    return [{"key": c.key, "pattern": c.pattern, "kind": c.kind, "ip": c.ip, "next": c.next_free(names)}
            for c in conv.values()]


@router.post("/directory/sync")
async def directory_sync(request: Request, user: User = Depends(require("admin"))) -> dict[str, Any]:
    d = _engine(request).directory
    if d is None:
        raise HTTPException(400, "No directory is configured.")
    ok = await d.sync()
    _refresh(request)
    return {"ok": ok, "error": d.state.error, "counts": d.state.counts}
