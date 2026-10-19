"""Remote access tools: link templates and generated .rdp files.

A tool is either a link template (``link``) or a generated file (``file: rdp``).
Tools come in two kinds:

* ``needs: id``: the device must carry a value for the tool, such as a
  RustDesk ID. Shown only on devices that have one.
* ``needs: address``: the tool connects to the device's address. Shown on
  devices that have an entry for it, and automatically on devices whose type
  is listed in ``auto_kinds``.

Placeholders in a link: ``{value}`` (the device's entry, e.g. an ID),
``{address}`` (entry value, else host name, else IP), ``{ip}``, ``{hostname}``,
``{user}``. Every substituted value is URL-encoded, so a value can never change
the structure of the link.

Link schemes were checked as follows (see docs/remote-access.md):
RDP files follow Microsoft's documented format; ``rustdesk://connect/<id>`` is
parsed by RustDesk's own source (flutter/lib/common.dart, urlLinkToCmdArgs);
``tvcontrol1://control?device=<id>`` is registered by the TeamViewer client and
widely used by management tools, but not officially documented; AnyDesk
documents no URL scheme, so it is offered as copy-only by default.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

BUILTIN: dict[str, dict[str, Any]] = {
    "rdp": {"label": "Remote Desktop", "file": "rdp", "needs": "address", "auto_kinds": []},
    "vnc": {"label": "VNC", "link": "vnc://{address}", "needs": "address", "auto_kinds": []},
    "ssh": {"label": "SSH", "link": "ssh://{user}@{address}", "needs": "address", "auto_kinds": [], "user": ""},
    "web": {"label": "Web interface", "link": "https://{address}/", "needs": "address", "auto_kinds": []},
    "rustdesk": {"label": "RustDesk", "link": "rustdesk://connect/{value}", "needs": "id"},
    "teamviewer": {"label": "TeamViewer", "link": "tvcontrol1://control?device={value}", "needs": "id"},
    "anydesk": {"label": "AnyDesk", "link": None, "needs": "id"},
}
_SAFE_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.I)
_BLOCKED_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")
_HOST = re.compile(r"^[A-Za-z0-9._:\-\[\]]{1,255}$")
_RDP_KEY = re.compile(r"^[a-z0-9 ]+:[isb]$")


class RemoteError(Exception):
    pass


@dataclass
class Tool:
    key: str
    label: str
    needs: str = "address"
    link: str | None = None
    file: str | None = None
    auto_kinds: list[str] = field(default_factory=list)
    user: str = ""
    rdp_options: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "needs": self.needs, "launch": self.file or ("link" if self.link else "copy")}


def load(conf: Any) -> dict[str, Tool]:
    """Built-in tools merged with ``remote_tools`` from the configuration.

    Setting a tool to ``false`` removes it; a mapping overrides or adds keys.
    """
    merged = copy.deepcopy(BUILTIN)
    if conf:
        if not isinstance(conf, dict):
            raise RemoteError("remote_tools must be a mapping of tool keys to settings")
        for key, c in conf.items():
            if c is False:
                merged.pop(key, None)
            elif isinstance(c, dict):
                merged.setdefault(key, {"needs": "address"}).update(c)
            else:
                raise RemoteError(f"remote_tools.{key}: must be a mapping or false")
    tools = {}
    for key, c in merged.items():
        if c.get("needs", "address") not in ("address", "id"):
            raise RemoteError(f"remote_tools.{key}: needs must be address or id")
        link = c.get("link")
        if link:
            if not _SAFE_SCHEME.match(link) or link.lower().startswith(_BLOCKED_SCHEMES):
                raise RemoteError(f"remote_tools.{key}: the link must start with a URL scheme such as rdp:, vnc: or https:")
        if c.get("file") not in (None, "rdp"):
            raise RemoteError(f"remote_tools.{key}: file must be rdp")
        opts = c.get("rdp_options") or {}
        for k in opts:
            if not _RDP_KEY.match(str(k)):
                raise RemoteError(f"remote_tools.{key}.rdp_options: {k!r} is not an RDP setting like 'screen mode id:i'")
        tools[key] = Tool(key=key, label=str(c.get("label") or key), needs=c.get("needs", "address"), link=link,
                          file=c.get("file"), auto_kinds=[str(k).lower() for k in c.get("auto_kinds") or []],
                          user=str(c.get("user") or ""), rdp_options=opts)
    return tools


def _address(value: str | None, hostname: str | None, ip: str | None) -> str | None:
    for candidate in (value, hostname, ip):
        if candidate and _HOST.match(candidate):
            return candidate
    return None


def render_link(tool: Tool, *, value: str | None, user: str | None, hostname: str | None, ip: str | None) -> str | None:
    if not tool.link:
        return None
    address = _address(value if tool.needs == "address" else None, hostname, ip)
    params = {"value": value or "", "address": address or "", "ip": ip or "", "hostname": hostname or "",
              "user": user or tool.user or ""}
    if tool.needs == "id" and not value:
        return None
    if tool.needs == "address" and not address:
        return None
    out = tool.link if params["user"] else tool.link.replace("{user}@", "")
    for k, v in params.items():
        out = out.replace("{" + k + "}", quote(v, safe=":[]"))
    return out


def render_rdp(tool: Tool, *, value: str | None, user: str | None, hostname: str | None, ip: str | None) -> str:
    """A minimal .rdp file. Values are validated so they cannot add lines (and with them settings)."""
    address = _address(value, hostname, ip)
    if not address:
        raise RemoteError("This device has no usable address for Remote Desktop.")
    username = (user or tool.user or "").strip()
    if any(ch in username for ch in "\r\n"):
        raise RemoteError("The user name contains a line break.")
    lines = {"full address:s": address, "prompt for credentials:i": 1, "screen mode id:i": 2,
             "use multimon:i": 0, "redirectclipboard:i": 1, "audiomode:i": 0}
    if username:
        lines["username:s"] = username
    for k, v in tool.rdp_options.items():
        if any(ch in str(v) for ch in "\r\n"):
            raise RemoteError("An RDP option contains a line break.")
        lines[str(k)] = v
    return "".join(f"{k}:{v}\r\n" for k, v in lines.items())
