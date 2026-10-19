"""SNMP sources: switch MAC tables and router ARP tables.

Only standard MIBs are used, so any managed switch that implements them works:

* BRIDGE-MIB / Q-BRIDGE-MIB (RFC 4188, RFC 4363) for learned MAC addresses
* IF-MIB (RFC 2863) for port names and descriptions
* LLDP-MIB (IEEE 802.1AB) for neighbours, which mark uplinks
* IP-MIB (RFC 4293) for ARP / neighbour tables on routers and layer-3 switches

All requests are reads. deskside never sends SNMP SET.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget,
    UsmUserData, bulk_walk_cmd, get_cmd, walk_cmd,
)
from pysnmp.hlapi.v3arch.asyncio import auth as _auth

from ..netaddr import normalize_mac
from .base import AddressEntry, Neighbor, PortEntry, Snapshot, Source, SourceError

# OIDs, named after their MIB objects.
SYS_NAME = "1.3.6.1.2.1.1.5.0"
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
DOT1D_BASE_PORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
DOT1D_TP_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
DOT1D_TP_FDB_STATUS = "1.3.6.1.2.1.17.4.3.1.3"
DOT1Q_TP_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"
DOT1Q_TP_FDB_STATUS = "1.3.6.1.2.1.17.7.1.2.2.1.3"
DOT1Q_VLAN_FDB_ID = "1.3.6.1.2.1.17.7.1.4.2.1.3"
LLDP_LOC_PORT_ID = "1.0.8802.1.1.2.1.3.7.1.3"
LLDP_LOC_PORT_DESC = "1.0.8802.1.1.2.1.3.7.1.4"
LLDP_REM_PORT_ID = "1.0.8802.1.1.2.1.4.1.1.7"
LLDP_REM_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"
IP_NET_TO_PHYSICAL_PHYS = "1.3.6.1.2.1.4.35.1.4"
IP_NET_TO_MEDIA_PHYS = "1.3.6.1.2.1.4.22.1.2"

# FDB status values that describe the switch itself rather than a learned host.
_FDB_NOT_LEARNED = {4, 5}  # self(4), mgmt(5)

_AUTH = {
    "md5": _auth.usmHMACMD5AuthProtocol, "sha": _auth.usmHMACSHAAuthProtocol,
    "sha224": _auth.usmHMAC128SHA224AuthProtocol, "sha256": _auth.usmHMAC192SHA256AuthProtocol,
    "sha384": _auth.usmHMAC256SHA384AuthProtocol, "sha512": _auth.usmHMAC384SHA512AuthProtocol,
}
_PRIV = {
    "des": _auth.usmDESPrivProtocol, "aes": _auth.usmAesCfb128Protocol, "aes128": _auth.usmAesCfb128Protocol,
    "aes192": _auth.usmAesCfb192Protocol, "aes256": _auth.usmAesCfb256Protocol,
}


class SnmpClient:
    """Thin read-only wrapper around pysnmp for one target."""

    def __init__(self, conf: dict[str, Any], label: str) -> None:
        self.label = label
        self.host: str = conf["host"]
        self.port = int(conf.get("port", 161))
        self.timeout = float(conf.get("timeout", 3))
        self.retries = int(conf.get("retries", 1))
        version = str(conf.get("version", "2c")).lower()
        self.bulk = version != "1"
        if version in ("1", "2c"):
            if not conf.get("community"):
                raise SourceError(f"{label}: SNMP v{version} needs community or community_file")
            self.auth = CommunityData(conf["community"], mpModel=0 if version == "1" else 1)
        elif version == "3":
            if not conf.get("user"):
                raise SourceError(f"{label}: SNMPv3 needs user")
            auth_proto = _AUTH.get(str(conf.get("auth_protocol", "sha")).lower())
            priv_proto = _PRIV.get(str(conf.get("priv_protocol", "aes")).lower())
            if conf.get("auth_key") and auth_proto is None:
                raise SourceError(f"{label}: unknown auth_protocol {conf.get('auth_protocol')!r}")
            if conf.get("priv_key") and priv_proto is None:
                raise SourceError(f"{label}: unknown priv_protocol {conf.get('priv_protocol')!r}")
            self.auth = UsmUserData(
                conf["user"],
                authKey=conf.get("auth_key"), privKey=conf.get("priv_key"),
                authProtocol=auth_proto if conf.get("auth_key") else _auth.usmNoAuthProtocol,
                privProtocol=priv_proto if conf.get("priv_key") else _auth.usmNoPrivProtocol,
            )
        else:
            raise SourceError(f"{label}: SNMP version must be 1, 2c or 3")
        self.engine = SnmpEngine()
        self._target: UdpTransportTarget | None = None

    async def _tgt(self) -> UdpTransportTarget:
        if self._target is None:
            self._target = await UdpTransportTarget.create((self.host, self.port), timeout=self.timeout,
                                                           retries=self.retries)
        return self._target

    async def get(self, oid: str) -> Any:
        err, status, _idx, binds = await get_cmd(self.engine, self.auth, await self._tgt(), ContextData(),
                                                 ObjectType(ObjectIdentity(oid)))
        if err:
            raise SourceError(f"{self.label}: no SNMP answer from {self.host} ({err})")
        if status:
            raise SourceError(f"{self.label}: SNMP error {status.prettyPrint()}")
        return binds[0][1]

    async def walk(self, base: str) -> AsyncIterator[tuple[tuple[int, ...], Any]]:
        """Yield (index suffix, value) for every row below ``base``."""
        prefix = tuple(int(x) for x in base.split("."))
        if self.bulk:
            it = bulk_walk_cmd(self.engine, self.auth, await self._tgt(), ContextData(), 0, 40,
                               ObjectType(ObjectIdentity(base)), lexicographicMode=False)
        else:
            it = walk_cmd(self.engine, self.auth, await self._tgt(), ContextData(),
                          ObjectType(ObjectIdentity(base)), lexicographicMode=False)
        async for err, status, _idx, binds in it:
            if err:
                raise SourceError(f"{self.label}: no SNMP answer from {self.host} ({err})")
            if status:
                raise SourceError(f"{self.label}: SNMP error {status.prettyPrint()}")
            for oid, val in binds:
                t = tuple(oid)
                if t[: len(prefix)] != prefix or val.__class__.__name__ in ("EndOfMibView", "NoSuchObject", "NoSuchInstance"):
                    return
                yield t[len(prefix):], val

    def close(self) -> None:
        self.engine.close_dispatcher()


def _text(val: Any) -> str:
    try:
        return bytes(val.asOctets()).decode("utf-8", "replace").strip("\x00 ").strip()
    except AttributeError:
        return str(val)


class SnmpSwitch(Source):
    """Learned MAC addresses per port of a managed switch.

    Settings: ``host``, SNMP credentials (see :class:`SnmpClient`), optional
    ``display_name``, ``uplinks`` (list of port names that connect to other
    switches) and ``ignore_ports``.
    """

    type = "snmp-switch"
    default_interval = 60

    async def collect(self) -> Snapshot:
        self.require("host")
        c = SnmpClient(self.conf, f"source {self.name}")
        try:
            switch = self.conf.get("display_name") or _text(await c.get(SYS_NAME)) or self.conf["host"]
            ifname: dict[int, str] = {}
            async for idx, val in c.walk(IF_NAME):
                ifname[idx[0]] = _text(val)
            if not ifname:
                async for idx, val in c.walk(IF_DESCR):
                    ifname[idx[0]] = _text(val)
            alias: dict[int, str] = {}
            async for idx, val in c.walk(IF_ALIAS):
                if _text(val):
                    alias[idx[0]] = _text(val)
            bp_to_if: dict[int, int] = {}
            async for idx, val in c.walk(DOT1D_BASE_PORT_IFINDEX):
                bp_to_if[idx[0]] = int(val)

            def port_name(bridge_port: int) -> str:
                ifi = bp_to_if.get(bridge_port, bridge_port)
                return ifname.get(ifi, f"port {bridge_port}")

            fdb_vlan: dict[int, int] = {}
            async for idx, val in c.walk(DOT1Q_VLAN_FDB_ID):
                fdb_vlan[int(val)] = idx[-1]
            status: dict[tuple[int, ...], int] = {}
            async for idx, val in c.walk(DOT1Q_TP_FDB_STATUS):
                status[idx] = int(val)
            snap = Snapshot()
            ignore = set(self.conf.get("ignore_ports") or [])
            async for idx, val in c.walk(DOT1Q_TP_FDB_PORT):
                fdb_id, mac_bytes = idx[0], bytes(idx[1:7])
                bport = int(val)
                if bport == 0 or status.get(idx) in _FDB_NOT_LEARNED:
                    continue
                mac = normalize_mac(mac_bytes)
                name = port_name(bport)
                if mac and name not in ignore:
                    snap.ports.append(PortEntry(switch, name, mac, fdb_vlan.get(fdb_id, fdb_id)))
            if not snap.ports:  # switch without Q-BRIDGE: fall back to the plain bridge table
                status1: dict[tuple[int, ...], int] = {}
                async for idx, val in c.walk(DOT1D_TP_FDB_STATUS):
                    status1[idx] = int(val)
                async for idx, val in c.walk(DOT1D_TP_FDB_PORT):
                    bport = int(val)
                    if bport == 0 or status1.get(idx) in _FDB_NOT_LEARNED:
                        continue
                    mac = normalize_mac(bytes(idx[:6]))
                    name = port_name(bport)
                    if mac and name not in ignore:
                        snap.ports.append(PortEntry(switch, name, mac))

            loc_port: dict[int, str] = {}
            async for idx, val in c.walk(LLDP_LOC_PORT_ID):
                loc_port[idx[0]] = _text(val)
            names_by_text = set(ifname.values())
            async for idx, val in c.walk(LLDP_REM_SYS_NAME):
                local_num = idx[1]
                local = loc_port.get(local_num)
                if local not in names_by_text:
                    local = ifname.get(local_num, local or f"port {local_num}")
                snap.neighbors.append(Neighbor(switch, local, _text(val) or None))
            for p in self.conf.get("uplinks") or []:
                snap.neighbors.append(Neighbor(switch, str(p), "configured uplink"))
            for ifi, text in alias.items():
                if ifi in ifname:
                    snap.port_names[(switch, ifname[ifi])] = text
            return snap
        finally:
            c.close()


class SnmpArp(Source):
    """MAC/IP pairs from the ARP or neighbour table of a router or layer-3 switch."""

    type = "snmp-arp"
    default_interval = 120

    async def collect(self) -> Snapshot:
        self.require("host")
        c = SnmpClient(self.conf, f"source {self.name}")
        snap = Snapshot()
        try:
            async for idx, val in c.walk(IP_NET_TO_PHYSICAL_PHYS):
                # index: ifIndex, addressType, length, address octets
                if len(idx) >= 7 and idx[1] == 1 and idx[2] == 4:
                    ip = ".".join(str(x) for x in idx[3:7])
                    mac = normalize_mac(bytes(val.asOctets()))
                    if mac:
                        snap.addresses.append(AddressEntry(mac, ip, "arp"))
            if not snap.addresses:
                async for idx, val in c.walk(IP_NET_TO_MEDIA_PHYS):
                    if len(idx) == 5:
                        mac = normalize_mac(bytes(val.asOctets()))
                        if mac:
                            snap.addresses.append(AddressEntry(mac, ".".join(map(str, idx[1:5])), "arp"))
            return snap
        finally:
            c.close()
