"""Common types for data sources.

A source collects one snapshot per run and returns it as a :class:`Snapshot`.
Sources never write to the database themselves; the engine merges all
snapshots and decides what changed. That keeps every source small, easy to
test with recorded data, and replaceable.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class PortEntry:
    """A MAC address learned on a switch port."""

    switch: str
    port: str
    mac: str
    vlan: int | None = None


@dataclass(frozen=True)
class AddressEntry:
    """A MAC/IP pair, from DHCP, ARP or a similar table."""

    mac: str
    ip: str
    origin: str                     # "dhcp", "arp", "netdisco", ...
    hostname: str | None = None
    dynamic: bool | None = None     # True for DHCP leases, False for reservations
    expires: int | None = None      # lease end, Unix seconds


@dataclass(frozen=True)
class Neighbor:
    """A layer-2 neighbour seen on a switch port (LLDP or similar)."""

    switch: str
    port: str
    remote_name: str | None = None
    remote_port: str | None = None


@dataclass
class Snapshot:
    ports: list[PortEntry] = field(default_factory=list)
    addresses: list[AddressEntry] = field(default_factory=list)
    neighbors: list[Neighbor] = field(default_factory=list)
    vendors: dict[str, str] = field(default_factory=dict)       # mac -> vendor name
    port_names: dict[tuple[str, str], str] = field(default_factory=dict)  # (switch, port) -> alias
    taken_at: float = field(default_factory=time.time)


class SourceError(Exception):
    """A source could not collect. The message is shown on the status page."""


class Source(ABC):
    """Base class for every data source. Subclasses register under ``type``."""

    type: ClassVar[str]
    default_interval: ClassVar[int] = 300
    registry: ClassVar[dict[str, type[Source]]] = {}

    def __init__(self, conf: dict[str, Any]) -> None:
        self.conf = conf
        self.name: str = conf["name"]
        self.interval: int = int(conf.get("interval", self.default_interval))

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        if getattr(cls, "type", None):
            Source.registry[cls.type] = cls

    def require(self, *keys: str) -> None:
        missing = [k for k in keys if not self.conf.get(k)]
        if missing:
            raise SourceError(f"source {self.name}: missing setting(s) {', '.join(missing)}")

    @abstractmethod
    async def collect(self) -> Snapshot:
        """Take one snapshot. Raise SourceError with a readable message on failure."""


def build_sources(confs: list[dict[str, Any]]) -> list[Source]:
    from . import dhcp, local_arp, netdisco, snmp  # noqa: F401  (registers the classes)

    out: list[Source] = []
    for conf in confs:
        if conf.get("enabled", True) is False:
            continue
        cls = Source.registry.get(conf["type"])
        if cls is None:
            known = ", ".join(sorted(Source.registry))
            raise SourceError(f"source {conf['name']}: unknown type {conf['type']!r} (known: {known})")
        out.append(cls(conf))
    return out
