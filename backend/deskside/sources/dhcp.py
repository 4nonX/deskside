"""DHCP lease sources.

Five ways in, so most DHCP servers are covered:

* ``dhcp-file``: a lease file or export on disk (Windows PowerShell CSV,
  Windows DHCP console export, dnsmasq, ISC dhcpd, Kea memfile CSV)
* ``dhcp-push``: the same exports, uploaded by the DHCP server itself to
  ``POST /api/ingest/<source name>`` (no share, no account for deskside)
* ``dhcp-windows``: Windows DHCP Server over WinRM, read-only
* ``dhcp-kea``: the Kea control agent API
* ``dhcp-opnsense``: the OPNsense API (ISC or Kea backend)
"""

from __future__ import annotations

import asyncio
import csv
import io
import hmac
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .. import tls
from ..netaddr import normalize_mac, parse_ip
from .base import AddressEntry, Snapshot, Source, SourceError


def _short(host: str | None) -> str | None:
    """Hostnames are kept as reported; empty strings become None."""
    host = (host or "").strip().strip('"')
    return host or None


def _ts(value: str | None) -> int | None:
    """Parse the timestamp formats lease files use. Unknown formats give None."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y %I:%M:%S %p"):
        try:
            return int(datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    m = re.fullmatch(r"/Date\((\d+)\)/", value)  # ConvertTo-Json date format
    return int(m.group(1)) // 1000 if m else None


# --- parsers, each returns a list of AddressEntry -------------------------------------------

def parse_windows_csv(text: str) -> list[AddressEntry]:
    """Output of ``Get-DhcpServerv4Lease | Export-Csv`` (any column order)."""
    out = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        mac, ip = normalize_mac(row.get("ClientId")), parse_ip(row.get("IPAddress"))
        state = (row.get("AddressState") or "").lower()
        if not (mac and ip) or state.startswith("inactive") or state in ("expired", "declined"):
            continue
        out.append(AddressEntry(mac, ip, "dhcp", _short(row.get("HostName")),
                                dynamic="reservation" not in state, expires=_ts(row.get("LeaseExpiryTime"))))
    return out


def parse_windows_mmc(text: str) -> list[AddressEntry]:
    """Tab-separated export from the DHCP console ("Export List").

    Column headers are localised, so columns are read by position: IP address,
    name, lease expiration (or a reservation marker), type, unique ID.
    """
    out = []
    lines = text.lstrip("﻿").splitlines()
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) < 5:
            continue
        ip, mac = parse_ip(cols[0]), normalize_mac(cols[4])
        if not (ip and mac):
            continue
        expiry = cols[2].strip()
        reservation = not re.search(r"\d", expiry)
        if reservation and re.search(r"inaktiv|inactive", expiry, re.I):
            continue
        out.append(AddressEntry(mac, ip, "dhcp", _short(cols[1]), dynamic=not reservation,
                                expires=None if reservation else _ts(expiry)))
    return out


def parse_dnsmasq(text: str) -> list[AddressEntry]:
    """dnsmasq lease file: ``expiry mac ip hostname client-id``."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            mac, ip = normalize_mac(parts[1]), parse_ip(parts[2])
            if mac and ip:
                exp = int(parts[0]) if parts[0].isdigit() and parts[0] != "0" else None
                out.append(AddressEntry(mac, ip, "dhcp", None if parts[3] == "*" else parts[3], True, exp))
    return out


_ISC_LEASE = re.compile(r"lease\s+([0-9.]+)\s*\{(.*?)\}", re.S)


def parse_isc(text: str) -> list[AddressEntry]:
    """ISC dhcpd.leases. Later entries for the same address win, as in dhcpd."""
    latest: dict[str, AddressEntry] = {}
    for ip, body in _ISC_LEASE.findall(text):
        if not re.search(r"binding state active", body):
            continue
        m = re.search(r"hardware ethernet ([0-9a-fA-F:]+);", body)
        mac = normalize_mac(m.group(1)) if m else None
        if not mac:
            continue
        host = re.search(r'client-hostname "([^"]*)";', body)
        ends = re.search(r"ends \d (\S+ \S+);", body)
        latest[ip] = AddressEntry(mac, ip, "dhcp", _short(host.group(1)) if host else None, True,
                                  _ts(ends.group(1)) if ends else None)
    return list(latest.values())


def parse_kea_csv(text: str) -> list[AddressEntry]:
    """Kea memfile lease CSV (``kea-leases4.csv``). The last row per address wins."""
    latest: dict[str, AddressEntry] = {}
    for row in csv.DictReader(io.StringIO(text)):
        ip, mac = parse_ip(row.get("address")), normalize_mac(row.get("hwaddr"))
        if not (ip and mac):
            continue
        if row.get("state", "0") != "0" or row.get("valid_lifetime") == "0":
            latest.pop(ip, None)  # declined, expired or released
            continue
        exp = row.get("expire")
        latest[ip] = AddressEntry(mac, ip, "dhcp", _short(row.get("hostname")), True,
                                  int(exp) if exp and exp.isdigit() else None)
    return list(latest.values())


PARSERS = {
    "windows-csv": parse_windows_csv, "windows-mmc": parse_windows_mmc, "dnsmasq": parse_dnsmasq,
    "isc": parse_isc, "kea-csv": parse_kea_csv,
}


class DhcpFile(Source):
    """Reads a lease file or export. Settings: ``path``, ``format`` (see PARSERS)."""

    type = "dhcp-file"
    default_interval = 300

    async def collect(self) -> Snapshot:
        self.require("path", "format")
        parser = PARSERS.get(self.conf["format"])
        if parser is None:
            raise SourceError(f"source {self.name}: format must be one of {', '.join(PARSERS)}")
        path = Path(self.conf["path"])
        try:
            raw = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise SourceError(f"source {self.name}: cannot read {path}: {exc.strerror}") from exc
        return Snapshot(addresses=parser(_decode(raw)))


def _decode(raw: bytes) -> str:
    """Exports come as UTF-8 (with or without BOM) or, from Windows PowerShell 5, as UTF-16."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


class DhcpPush(Source):
    """A lease export that the DHCP server uploads itself.

    Settings: ``format`` (see PARSERS), ``token`` (or ``token_file``; at least 24
    characters, sent as ``Authorization: Bearer <token>``), optional ``max_age``
    in seconds (default 3600): an upload older than that counts as missing.
    The last upload is kept in memory; after a restart the source waits for
    the next one.
    """

    type = "dhcp-push"
    default_interval = 60

    def __init__(self, conf: dict[str, Any]) -> None:
        super().__init__(conf)
        self.received: tuple[float, list[AddressEntry]] | None = None

    def check_token(self, header: str | None) -> bool:
        token = str(self.conf.get("token") or "")
        return len(token) >= 24 and hmac.compare_digest((header or "").encode(), f"Bearer {token}".encode())

    def accept(self, raw: bytes) -> int:
        """Parse and keep an upload. Raises SourceError for an unusable one, keeping the previous."""
        parser = PARSERS.get(self.conf.get("format", ""))
        if parser is None:
            raise SourceError(f"source {self.name}: format must be one of {', '.join(PARSERS)}")
        try:
            entries = parser(_decode(raw))
        except (ValueError, KeyError, csv.Error) as exc:
            raise SourceError(f"source {self.name}: the upload could not be read: {exc}") from exc
        self.received = (time.time(), entries)
        return len(entries)

    async def collect(self) -> Snapshot:
        self.require("format", "token")
        if len(str(self.conf["token"])) < 24:
            raise SourceError(f"source {self.name}: the token must be at least 24 characters")
        if self.received is None:
            raise SourceError(f"source {self.name}: no upload received yet")
        age = time.time() - self.received[0]
        if age > int(self.conf.get("max_age", 3600)):
            raise SourceError(f"source {self.name}: the last upload is {int(age // 60)} minutes old")
        return Snapshot(addresses=list(self.received[1]), taken_at=self.received[0])


_WINRM_SCRIPT = (
    "Get-DhcpServerv4Scope | Get-DhcpServerv4Lease | "
    "Select-Object @{n='IPAddress';e={$_.IPAddress.ToString()}},ClientId,HostName,AddressState,"
    "@{n='LeaseExpiryTime';e={if($_.LeaseExpiryTime){$_.LeaseExpiryTime.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')}}} | "
    "ConvertTo-Json -Compress"
)


class DhcpWindows(Source):
    """Windows DHCP Server via WinRM.

    The account only needs to be in the built-in "DHCP Users" group on the
    server (read access to DHCP) plus permission to use WinRM ("Remote
    Management Users"). Settings: ``host``, ``user``, ``password``,
    optional ``transport`` (ntlm, kerberos; default ntlm), ``scheme``
    (https, http; default https), ``verify_tls`` (default true).
    """

    type = "dhcp-windows"
    default_interval = 300

    async def collect(self) -> Snapshot:
        self.require("host", "user", "password")
        import winrm  # imported lazily: only needed when this source is used

        scheme = self.conf.get("scheme", "https")
        port = self.conf.get("port", 5986 if scheme == "https" else 5985)
        session = winrm.Session(
            f"{scheme}://{self.conf['host']}:{port}/wsman", auth=(self.conf["user"], self.conf["password"]),
            transport=self.conf.get("transport", "ntlm"),
            server_cert_validation="validate" if self.conf.get("verify_tls", True) else "ignore",
        )
        try:
            result = await asyncio.to_thread(session.run_ps, _WINRM_SCRIPT)
        except Exception as exc:  # pywinrm raises many unrelated exception types
            raise SourceError(f"source {self.name}: WinRM connection to {self.conf['host']} failed: {exc}") from exc
        if result.status_code != 0:
            raise SourceError(f"source {self.name}: PowerShell failed: {result.std_err.decode(errors='replace')[:300]}")
        rows = json.loads(result.std_out or b"[]")
        rows = rows if isinstance(rows, list) else [rows]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["IPAddress", "ClientId", "HostName", "AddressState", "LeaseExpiryTime"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) or "" for k in w.fieldnames})
        return Snapshot(addresses=parse_windows_csv(buf.getvalue()))


class DhcpKea(Source):
    """Kea control agent: ``url`` (e.g. http://kea:8000/), optional ``user``/``password``."""

    type = "dhcp-kea"
    default_interval = 300

    async def collect(self) -> Snapshot:
        self.require("url")
        auth = (self.conf["user"], self.conf["password"]) if self.conf.get("user") else None
        async with httpx.AsyncClient(timeout=15, verify=tls.verify(self.conf), auth=auth) as cl:
            try:
                r = await cl.post(self.conf["url"], json={"command": "lease4-get-all", "service": ["dhcp4"]})
                r.raise_for_status()
            except httpx.HTTPError as exc:
                raise SourceError(f"source {self.name}: Kea API request failed: {exc}") from exc
        reply = r.json()
        reply = reply[0] if isinstance(reply, list) else reply
        if reply.get("result") not in (0, 3):  # 3 = no leases
            raise SourceError(f"source {self.name}: Kea answered: {reply.get('text')}")
        out = []
        for lease in (reply.get("arguments") or {}).get("leases", []):
            mac, ip = normalize_mac(lease.get("hw-address")), parse_ip(lease.get("ip-address"))
            if mac and ip and lease.get("state", 0) == 0:
                exp = (lease.get("cltt") or 0) + (lease.get("valid-lft") or 0)
                out.append(AddressEntry(mac, ip, "dhcp", _short(lease.get("hostname")), True, exp or None))
        return Snapshot(addresses=out)


class DhcpOpnsense(Source):
    """OPNsense API: ``url`` (https://firewall/), ``key``, ``secret``, ``backend`` (isc or kea)."""

    type = "dhcp-opnsense"
    default_interval = 300

    async def collect(self) -> Snapshot:
        self.require("url", "key", "secret")
        path = "api/kea/leases4/search" if self.conf.get("backend", "isc") == "kea" else "api/dhcpv4/leases/searchLease"
        url = self.conf["url"].rstrip("/") + "/" + path
        async with httpx.AsyncClient(timeout=15, verify=tls.verify(self.conf),
                                     auth=(self.conf["key"], self.conf["secret"])) as cl:
            try:
                r = await cl.get(url)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                raise SourceError(f"source {self.name}: OPNsense API request failed: {exc}") from exc
        out = []
        for row in r.json().get("rows", []):
            mac = normalize_mac(row.get("mac") or row.get("hwaddr"))
            ip = parse_ip(row.get("address"))
            # "status" in OPNsense is ARP reachability, not lease validity, so it is not filtered on.
            if mac and ip:
                static = str(row.get("type", "")).lower() == "static"
                out.append(AddressEntry(mac, ip, "dhcp", _short(row.get("hostname")), dynamic=not static))
        return Snapshot(addresses=out)
