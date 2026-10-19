"""Database schema and session handling.

Timestamps are stored as integer Unix seconds (UTC). That keeps SQLite and
PostgreSQL behaving the same and serialises without timezone surprises.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, inspect, select, text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def now() -> int:
    return int(time.time())


class Base(DeclarativeBase):
    pass


class Device(Base):
    """A device someone cares about. Created by hand or from an unknown sighting."""

    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(50), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"),
                                                      nullable=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now)
    updated_at: Mapped[int] = mapped_column(Integer, default=now, onupdate=now)

    room: Mapped[Room | None] = relationship()
    department: Mapped[Department | None] = relationship()
    people: Mapped[list[DevicePerson]] = relationship(back_populates="device", cascade="all, delete-orphan")
    remote: Mapped[list[RemoteAccess]] = relationship(cascade="all, delete-orphan", order_by="RemoteAccess.position")
    interfaces: Mapped[list[Interface]] = relationship(back_populates="device", cascade="all, delete-orphan")
    notes: Mapped[list[Note]] = relationship(back_populates="device", cascade="all, delete-orphan",
                                             order_by="Note.created_at.desc()")


class Room(Base):
    """A place devices stand in. Number and name are free text; both are searchable."""

    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(50), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    building: Mapped[str] = mapped_column(String(100), default="")
    floor: Mapped[str] = mapped_column(String(50), default="")
    description: Mapped[str] = mapped_column(Text, default="")


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")   # "manual" or "directory"


class Person(Base):
    """Someone who uses devices. Either maintained by hand or synced from the directory."""

    __tablename__ = "people"
    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), index=True)
    username: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    mobile: Mapped[str] = mapped_column(String(100), default="")
    chat: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")   # "manual" or "directory"
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[int] = mapped_column(Integer, default=now, onupdate=now)

    department: Mapped[Department | None] = relationship()


class DevicePerson(Base):
    __tablename__ = "device_people"
    __table_args__ = (UniqueConstraint("device_id", "person_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    device: Mapped[Device] = relationship(back_populates="people")
    person: Mapped[Person] = relationship()


class RemoteAccess(Base):
    """A remote access entry on a device: a tool key plus the value it needs (an ID or an address)."""

    __tablename__ = "remote_access"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str] = mapped_column(String(200), default="")
    label: Mapped[str] = mapped_column(String(100), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


class Interface(Base):
    """A MAC address that belongs to a device. Live data attaches through the MAC."""

    __tablename__ = "interfaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    mac: Mapped[str] = mapped_column(String(17), unique=True)
    label: Mapped[str] = mapped_column(String(100), default="")
    expected_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    device: Mapped[Device] = relationship(back_populates="interfaces")


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    author: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[int] = mapped_column(Integer, default=now)
    updated_at: Mapped[int] = mapped_column(Integer, default=now, onupdate=now)

    device: Mapped[Device] = relationship(back_populates="notes")


class Sighting(Base):
    """What the collectors currently know about one MAC address."""

    __tablename__ = "sightings"
    mac: Mapped[str] = mapped_column(String(17), primary_key=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hostname_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    switch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    port: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vlan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_mac_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    behind_uplink: Mapped[bool] = mapped_column(Boolean, default=False)
    dhcp: Mapped[bool] = mapped_column(Boolean, default=False)
    online: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen: Mapped[int] = mapped_column(Integer, default=now)
    last_seen: Mapped[int] = mapped_column(Integer, default=now)
    port_since: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)


class EventLog(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[int] = mapped_column(Integer, default=now, index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    mac: Mapped[str | None] = mapped_column(String(17), nullable=True, index=True)
    device_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    created_at: Mapped[int] = mapped_column(Integer, default=now)
    last_login: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditLog(Base):
    """Every change made through the API, with who made it."""

    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[int] = mapped_column(Integer, default=now, index=True)
    username: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Database:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, future=True)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        """Create missing tables, then add missing columns to existing ones.

        Only additive changes are applied automatically: new tables and new
        nullable or defaulted columns. Anything else will come with an explicit
        migration and a note in the changelog.
        """
        Base.metadata.create_all(self.engine)
        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                have = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in have:
                        continue
                    ddl = col.type.compile(dialect=self.engine.dialect)
                    default = ""
                    if col.default is not None and getattr(col.default, "is_scalar", False):
                        val = col.default.arg
                        default = f" DEFAULT {int(val) if isinstance(val, bool) else repr(val)}"
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{default}'))

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    def device_for_mac(self, s: Session, mac: str) -> Device | None:
        iface = s.scalar(select(Interface).where(Interface.mac == mac))
        return iface.device if iface else None
