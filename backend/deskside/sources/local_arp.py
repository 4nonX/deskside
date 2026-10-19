"""Local ARP sweep: finds MAC/IP pairs in networks the deskside host sits in.

Useful in flat networks where no router exposes its ARP table over SNMP.
The sweep sends one empty UDP datagram to every address (port 9, "discard").
That needs no special privileges, but it makes the operating system resolve
each address via ARP. Afterwards the host's own neighbour table is read, plus the
host's own addresses, which never appear in its neighbour table.

Only directly attached networks can be swept this way. In a container that
means host networking (``network_mode: host``).
"""

from __future__ import annotations

import asyncio
import ipaddress
import platform
import re
import socket
from pathlib import Path

from ..netaddr import normalize_mac, parse_ip
from .base import AddressEntry, Snapshot, Source, SourceError

_ARP_LINE = re.compile(r"(\d+\.\d+\.\d+\.\d+)\D+?([0-9A-Fa-f]{1,2}(?:[:-][0-9A-Fa-f]{1,2}){5})")


def read_neighbor_table() -> list[tuple[str, str]]:
    """(ip, mac) pairs from the operating system's ARP cache."""
    proc = Path("/proc/net/arp")
    if proc.exists():
        out = []
        for line in proc.read_text().splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 4 and cols[2] != "0x0":  # flags 0x0 = incomplete
                out.append((cols[0], cols[3]))
        return out
    import subprocess

    cmd = ["arp", "-a"] if platform.system() == "Windows" else ["arp", "-an"]
    text = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    return [(ip, mac) for ip, mac in _ARP_LINE.findall(text)]


def read_own_addresses() -> list[tuple[str, str]]:
    """(ip, mac) of this host's own IPv4 interfaces. A host never appears in its own neighbour table."""
    import subprocess

    out: list[tuple[str, str]] = []
    try:
        if platform.system() == "Windows":
            script = ("Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { $a = Get-NetAdapter -InterfaceIndex "
                      "$_.InterfaceIndex -ErrorAction SilentlyContinue; if ($a) { $_.IPAddress + ' ' + $a.MacAddress } }")
            text = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                  capture_output=True, text=True, timeout=30).stdout
            for line in text.splitlines():
                parts = line.split()
                if len(parts) == 2:
                    out.append((parts[0], parts[1]))
        else:
            text = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=10).stdout
            for line in text.splitlines():
                m = re.match(r"\d+:\s+(\S+?)(?:@\S+)?\s+inet\s+(\d+\.\d+\.\d+\.\d+)", line)
                mac_file = Path(f"/sys/class/net/{m.group(1)}/address") if m else None
                if m and mac_file and mac_file.exists():
                    out.append((m.group(2), mac_file.read_text().strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def _poke(ip: str) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"", (ip, 9))
    except OSError:
        pass


class LocalArp(Source):
    """Settings: ``networks`` (list of CIDRs to sweep and keep), optional ``sweep`` (default true)."""

    type = "local-arp"
    default_interval = 300

    async def collect(self) -> Snapshot:
        self.require("networks")
        try:
            nets = [ipaddress.ip_network(n, strict=False) for n in self.conf["networks"]]
        except ValueError as exc:
            raise SourceError(f"source {self.name}: {exc}") from exc
        if any(n.version != 4 for n in nets):
            raise SourceError(f"source {self.name}: only IPv4 networks can be swept")
        if self.conf.get("sweep", True):
            hosts = [str(h) for n in nets for h in n.hosts()]
            if len(hosts) > 4096:
                raise SourceError(f"source {self.name}: refusing to sweep {len(hosts)} addresses, keep networks at /20 or smaller")
            for i in range(0, len(hosts), 256):
                await asyncio.gather(*(asyncio.to_thread(_poke, h) for h in hosts[i:i + 256]))
            await asyncio.sleep(float(self.conf.get("settle_seconds", 3)))
        pairs = await asyncio.to_thread(read_neighbor_table) + await asyncio.to_thread(read_own_addresses)
        snap = Snapshot()
        for ip, mac in pairs:
            ip_n, mac_n = parse_ip(ip), normalize_mac(mac)
            if ip_n and mac_n and any(ipaddress.ip_address(ip_n) in n for n in nets):
                snap.addresses.append(AddressEntry(mac_n, ip_n, "arp"))
        return snap
