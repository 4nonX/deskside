"""Certificate checking for outgoing HTTPS connections.

Every HTTPS client in deskside (NetBox, OpenID Connect, notifications, DHCP and
Netdisco APIs) asks this module how to verify certificates, so an internal
certificate authority only has to be configured once:

* ``verify_tls: false`` in a block turns checking off for that connection.
* ``ca_file`` in a block, or the environment variable ``DESKSIDE_CA_FILE`` for
  all connections, adds a CA certificate (PEM) to the usual public ones.
"""

from __future__ import annotations

import os
import ssl
from functools import lru_cache
from typing import Any

import certifi


@lru_cache(maxsize=8)
def _context(ca_file: str | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    if ca_file:
        ctx.load_verify_locations(cafile=ca_file)
    return ctx


def verify(conf: dict[str, Any] | None = None) -> bool | ssl.SSLContext:
    """The ``verify`` argument for httpx for a configuration block."""
    conf = conf or {}
    if conf.get("verify_tls", True) is False:
        return False
    ca = conf.get("ca_file") or os.environ.get("DESKSIDE_CA_FILE") or None
    return _context(ca) if ca else True
