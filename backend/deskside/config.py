"""Configuration loading.

deskside reads one YAML file (``DESKSIDE_CONFIG``, default ``/config/config.yaml``).
Two conventions keep secrets out of that file:

* ``${NAME}`` anywhere in a string value is replaced by the environment
  variable ``NAME``. A missing variable is an error, not an empty string.
* A key ending in ``_file`` is read from the named file, and the result is
  stored under the key without the suffix. ``community_file: /run/secrets/snmp``
  becomes ``community: <file content>``. Trailing whitespace is stripped.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """Raised for configuration problems, with a message meant for the admin."""


def _expand(value: Any, where: str) -> Any:
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in os.environ:
                raise ConfigError(f"{where}: environment variable {name} is not set")
            return os.environ[name]
        return _ENV.sub(sub, value)
    if isinstance(value, list):
        return [_expand(v, f"{where}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            v = _expand(v, f"{where}.{k}")
            if isinstance(k, str) and k.endswith("_file") and isinstance(v, str):
                path = Path(v)
                try:
                    out[k[: -len("_file")]] = path.read_text(encoding="utf-8").rstrip()
                except OSError as exc:
                    raise ConfigError(f"{where}.{k}: cannot read {path}: {exc.strerror}") from exc
            else:
                out[k] = v
        return out
    return value


@dataclass
class Settings:
    """Typed view of the top-level settings. Source blocks stay plain dicts."""

    database_url: str = "sqlite:///data/deskside.db"
    secret_key: str = ""
    offline_after: int = 900
    uplink_mac_threshold: int = 4
    retention_days: int = 90
    naming: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    admin_password: str | None = None
    contacts_visible_to: str = "editor"
    directory: dict[str, Any] | None = None
    base_path: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def load(path: str | os.PathLike[str] | None = None) -> Settings:
    path = Path(path or os.environ.get("DESKSIDE_CONFIG", "/config/config.yaml"))
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file {path} not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: the top level must be a mapping")
    data = _expand(data, "config")

    server = data.get("server") or {}
    s = Settings(raw=data)
    s.database_url = (data.get("database") or {}).get("url", s.database_url)
    s.secret_key = server.get("secret_key") or os.environ.get("DESKSIDE_SECRET_KEY", "")
    s.admin_password = server.get("admin_password") or os.environ.get("DESKSIDE_ADMIN_PASSWORD")
    s.base_path = (server.get("base_path") or "").rstrip("/")
    live = data.get("live") or {}
    s.offline_after = int(live.get("offline_after", s.offline_after))
    s.uplink_mac_threshold = int(live.get("uplink_mac_threshold", s.uplink_mac_threshold))
    s.retention_days = int(live.get("retention_days", s.retention_days))
    s.naming = data.get("naming") or {}
    from .naming import NamingError, load as load_naming
    try:
        load_naming(s.naming)
    except NamingError as exc:
        raise ConfigError(str(exc)) from exc
    privacy = data.get("privacy") or {}
    s.contacts_visible_to = str(privacy.get("contacts_visible_to", s.contacts_visible_to))
    if s.contacts_visible_to not in ("viewer", "editor", "admin"):
        raise ConfigError("privacy.contacts_visible_to must be viewer, editor or admin")
    s.directory = data.get("directory") or None
    s.sources = data.get("sources") or []
    if not isinstance(s.sources, list):
        raise ConfigError("sources must be a list")
    names = [src.get("name") for src in s.sources]
    for i, src in enumerate(s.sources):
        if not isinstance(src, dict) or "type" not in src:
            raise ConfigError(f"sources[{i}]: every source needs a type")
        src.setdefault("name", f"{src['type']}-{i + 1}")
    dupes = {n for n in names if n and names.count(n) > 1}
    if dupes:
        raise ConfigError(f"source names must be unique: {', '.join(sorted(dupes))}")
    if len(s.secret_key) < 32:
        raise ConfigError("server.secret_key (or DESKSIDE_SECRET_KEY) must be at least 32 characters")
    return s
