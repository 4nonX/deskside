"""Search over everything shown on a card.

Every term must match somewhere in the row (AND). Matching is case-insensitive
and substring-based, with two additions:

* MAC addresses match in any notation: a term made only of hex digits and
  separators, with at least four hex digits, is compared against the MAC with
  the separators removed.
* Switch ports match long and short names: ``GigabitEthernet7`` is also
  found as ``Gi7`` or ``GE7``.
"""

from __future__ import annotations

import re
from typing import Any

from .netaddr import mac_search_key

_PORT_SHORT = [
    (re.compile(r"^TenGigabitEthernet", re.I), ("Te", "XGE", "TenGE")),
    (re.compile(r"^TwentyFiveGigE", re.I), ("Twe", "25GE")),
    (re.compile(r"^FortyGigabitEthernet", re.I), ("Fo", "40GE")),
    (re.compile(r"^GigabitEthernet", re.I), ("Gi", "GE")),
    (re.compile(r"^FastEthernet", re.I), ("Fa", "FE")),
    (re.compile(r"^Ethernet", re.I), ("Eth", "Et")),
]
_MAC_TERM = re.compile(r"^[0-9A-Fa-f:.\-]+$")


def port_variants(port: str | None) -> list[str]:
    if not port:
        return []
    out = [port]
    for rx, shorts in _PORT_SHORT:
        if rx.match(port):
            rest = rx.sub("", port)
            out += [s + rest for s in shorts]
            break
    return out


def search_blob(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "kind", "description", "ip", "hostname", "vendor", "switch", "port_alias", "mac"):
        if row.get(key):
            parts.append(str(row[key]))
    parts += port_variants(row.get("port"))
    for extra in row.get("search_extra", []):
        parts.append(str(extra))
    return "\n".join(parts).lower()


def matches(row: dict[str, Any], terms: list[str]) -> bool:
    blob = row.get("_blob") or search_blob(row)
    macs = row.get("_mackeys") or [mac_search_key(m) for m in row.get("macs", [])]
    for term in terms:
        if term in blob:
            continue
        if _MAC_TERM.match(term):
            key = mac_search_key(term)
            if len(key) >= 4 and any(key in m for m in macs):
                continue
        return False
    return True


def filter_rows(rows: list[dict[str, Any]], q: str | None) -> list[dict[str, Any]]:
    terms = [t for t in (q or "").lower().split() if t]
    if not terms:
        return rows
    return [r for r in rows if matches(r, terms)]
