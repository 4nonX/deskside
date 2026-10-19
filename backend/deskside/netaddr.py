"""Helpers for MAC and IP addresses.

MAC addresses are stored in one canonical form everywhere: upper case, colon
separated (``00:00:5E:00:53:2A``). Every source normalises through
:func:`normalize_mac` before handing data to the engine.
"""

from __future__ import annotations

import ipaddress
import re

_HEX = re.compile(r"[0-9A-Fa-f]")


def normalize_mac(value: str | bytes | None) -> str | None:
    """Return the canonical form of a MAC address, or None if it is not one.

    Accepts the usual notations (``aa:bb:..``, ``aa-bb-..``, ``aabb.ccdd.eeff``,
    ``aabbccddeeff``) and raw 6-byte values as returned by SNMP. Windows DHCP
    client IDs sometimes carry trailing padding (``7ca62a39b518000000``); only
    the first 12 hex digits are used when the rest is zero padding.
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 6:
            return None
        return ":".join(f"{b:02X}" for b in value)
    digits = "".join(_HEX.findall(value))
    if len(digits) > 12 and set(digits[12:]) == {"0"}:
        digits = digits[:12]
    if len(digits) != 12:
        return None
    mac = ":".join(digits[i : i + 2] for i in range(0, 12, 2)).upper()
    if mac in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
        return None
    return mac


def mac_search_key(value: str) -> str:
    """Strip everything but hex digits, for notation-independent matching."""
    return "".join(_HEX.findall(value)).upper()


def is_locally_administered(mac: str) -> bool:
    """True for randomised or software-assigned MACs (second-lowest bit of the first octet)."""
    return bool(int(mac[:2], 16) & 0x02)


def oui(mac: str) -> str:
    """The vendor prefix of a canonical MAC, e.g. ``00:00:5E``."""
    return mac[:8]


def parse_ip(value: str | None) -> str | None:
    """Return a normalised IPv4/IPv6 address string, or None."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip().split("/")[0]))
    except ValueError:
        return None


def ip_sort_key(ip: str | None) -> tuple[int, int]:
    """Sort key that orders addresses numerically and puts missing ones last."""
    if not ip:
        return (1, 0)
    try:
        return (0, int(ipaddress.ip_address(ip)))
    except ValueError:
        return (1, 0)
