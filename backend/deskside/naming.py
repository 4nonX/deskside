"""Naming conventions.

A convention turns a pattern such as ``WS{nn}`` into three things:

* a regular expression that recognises names (and host names) following it,
* the next free name, given the names already in use,
* optionally, the IP address a device with that number is expected to have.

Placeholders: ``{n}`` any number, ``{nn}`` two digits, ``{nnn}`` three digits,
and so on. The IP template may use ``{n}`` or ``{OFFSET+n}``, for example
``10.0.10.{100+n}``. Anything else in the pattern is literal text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_PLACEHOLDER = re.compile(r"\{(n+)\}")
_IP_PART = re.compile(r"\{(?:(\d+)\+)?n\}")


class NamingError(Exception):
    pass


@dataclass
class Convention:
    key: str
    pattern: str
    kind: str = ""
    ip: str | None = None
    match_hostname: bool = True

    def __post_init__(self) -> None:
        holders = _PLACEHOLDER.findall(self.pattern)
        if len(holders) != 1:
            raise NamingError(f"naming.{self.key}: the pattern needs exactly one number placeholder like {{nn}}")
        self.width = len(holders[0]) if len(holders[0]) > 1 else 0
        parts = _PLACEHOLDER.split(self.pattern)
        digits = rf"(\d{{{self.width},}})" if self.width else r"(\d+)"
        self.regex = re.compile("^" + re.escape(parts[0]) + digits + re.escape(parts[2]) + "$", re.I)
        if self.ip and not _IP_PART.search(self.ip):
            raise NamingError(f"naming.{self.key}: the ip template needs {{n}} or {{OFFSET+n}}")

    def number(self, name: str | None) -> int | None:
        """The number in a name that follows this convention. Host names may carry a domain."""
        if not name:
            return None
        m = self.regex.match(name.split(".")[0] if self.match_hostname else name)
        return int(m.group(1)) if m else None

    def format(self, n: int) -> str:
        return _PLACEHOLDER.sub(str(n).zfill(self.width) if self.width else str(n), self.pattern)

    def next_free(self, names: list[str]) -> str:
        used = {x for x in (self.number(n) for n in names) if x is not None}
        n = 1
        while n in used:
            n += 1
        return self.format(n)

    def expected_ip(self, n: int) -> str | None:
        if not self.ip:
            return None
        return _IP_PART.sub(lambda m: str(int(m.group(1) or 0) + n), self.ip)


def load(conf: Any) -> dict[str, Convention]:
    """Accept a mapping ``{key: {pattern: ..., kind: ..., ip: ...}}``."""
    if not conf:
        return {}
    if not isinstance(conf, dict):
        raise NamingError("naming must be a mapping of convention names to settings")
    out = {}
    for key, c in conf.items():
        if isinstance(c, str):
            c = {"pattern": c}
        if not isinstance(c, dict) or "pattern" not in c:
            raise NamingError(f"naming.{key}: needs a pattern")
        out[key] = Convention(key, c["pattern"], c.get("kind", ""), c.get("ip"), c.get("match_hostname", True))
    return out


def check(conventions: dict[str, Convention], name: str, kind: str, ips: list[str]) -> list[str]:
    """Human-readable warnings for a device that does not fit its convention."""
    warnings = []
    for c in conventions.values():
        if c.kind and c.kind.lower() != (kind or "").lower():
            continue
        n = c.number(name)
        if n is None:
            if c.kind:
                warnings.append(f"name_mismatch:{c.pattern}")
            continue
        exp = c.expected_ip(n)
        if exp and ips and exp not in ips:
            warnings.append(f"ip_mismatch:{exp}")
        break
    return warnings


def suggest(conventions: dict[str, Convention], hostname: str | None) -> str | None:
    """A name for an unknown device: the convention's form of its host name, if one matches."""
    for c in conventions.values():
        n = c.number(hostname)
        if n is not None:
            return c.format(n)
    return None
