"""People and departments from an LDAP directory (Active Directory, OpenLDAP, FreeIPA, ...).

Only the attributes named in the ``attributes`` mapping are requested, so the
configuration is also the complete list of personal data deskside stores.
People who disappear from the directory are marked inactive, not deleted,
because devices may still point to them.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from .db import Database, Department, Person

log = logging.getLogger("deskside.directory")

FLAVORS: dict[str, dict[str, Any]] = {
    "ad": {
        "filter": "(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))",
        "id_attribute": "objectGUID",
        "attributes": {"display_name": "displayName", "username": "sAMAccountName", "email": "mail",
                       "phone": "telephoneNumber", "mobile": "mobile", "title": "title", "department": "department"},
    },
    "openldap": {
        "filter": "(objectClass=inetOrgPerson)",
        "id_attribute": "entryUUID",
        "attributes": {"display_name": "cn", "username": "uid", "email": "mail", "phone": "telephoneNumber",
                       "mobile": "mobile", "title": "title", "department": "ou"},
    },
}
FIELDS = ("display_name", "username", "email", "phone", "mobile", "chat", "title", "department")


class DirectoryError(Exception):
    pass


@dataclass
class DirectoryState:
    name: str = "directory"
    type: str = "ldap"
    interval: int = 3600
    last_run: float | None = None
    last_ok: float | None = None
    duration: float | None = None
    error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


class Directory:
    def __init__(self, conf: dict[str, Any], db: Database) -> None:
        self.db = db
        flavor = FLAVORS.get(str(conf.get("flavor", "ad")).lower())
        if flavor is None:
            raise DirectoryError(f"directory.flavor must be one of {', '.join(FLAVORS)}")
        for key in ("url", "base_dn"):
            if not conf.get(key):
                raise DirectoryError(f"directory.{key} is required")
        self.conf = conf
        self.filter = conf.get("filter") or flavor["filter"]
        self.id_attr = conf.get("id_attribute") or flavor["id_attribute"]
        attrs = conf.get("attributes") or flavor["attributes"]
        unknown = set(attrs) - set(FIELDS)
        if unknown:
            raise DirectoryError(f"directory.attributes: unknown field(s) {', '.join(sorted(unknown))}; "
                                 f"allowed: {', '.join(FIELDS)}")
        if "display_name" not in attrs:
            raise DirectoryError("directory.attributes must map display_name")
        self.attrs: dict[str, str] = attrs
        self.state = DirectoryState(interval=int(conf.get("interval", 3600)))

    def _fetch(self) -> list[dict[str, str]]:
        import ldap3
        from ldap3.core.exceptions import LDAPException

        url = self.conf["url"]
        tls = None
        if url.startswith("ldaps://") or self.conf.get("start_tls"):
            tls = ldap3.Tls(validate=ssl.CERT_REQUIRED if self.conf.get("verify_tls", True) else ssl.CERT_NONE,
                            ca_certs_file=self.conf.get("ca_file"))
        try:
            server = ldap3.Server(url, tls=tls, get_info=ldap3.NONE, connect_timeout=10)
            conn = ldap3.Connection(server, user=self.conf.get("user"), password=self.conf.get("password"),
                                    auto_bind=False, receive_timeout=30, read_only=True)
            if self.conf.get("start_tls"):
                conn.open()
                conn.start_tls()
            if not conn.bind():
                raise DirectoryError(f"directory: sign-in to {url} failed: {conn.result.get('description')}")
            wanted = sorted(set(self.attrs.values()) | {self.id_attr})
            rows = []
            for entry in conn.extend.standard.paged_search(self.conf["base_dn"], self.filter, attributes=wanted,
                                                           paged_size=int(self.conf.get("page_size", 500)),
                                                           generator=True):
                if entry.get("type") != "searchResEntry":
                    continue
                a = entry.get("attributes", {})
                raw_id = entry.get("raw_attributes", {}).get(self.id_attr, [b""])
                ident = a.get(self.id_attr)
                if isinstance(raw_id, list) and raw_id and len(raw_id[0]) == 16 and self.id_attr.lower() == "objectguid":
                    ident = str(uuid.UUID(bytes_le=raw_id[0]))
                row = {"external_id": str(ident or entry.get("dn"))}
                for fld, attr in self.attrs.items():
                    v = a.get(attr)
                    if isinstance(v, list):
                        v = v[0] if v else ""
                    row[fld] = str(v or "").strip()
                if row.get("display_name"):
                    rows.append(row)
            conn.unbind()
            return rows
        except LDAPException as exc:
            raise DirectoryError(f"directory: {url}: {exc}") from exc

    def _store(self, rows: list[dict[str, str]]) -> dict[str, int]:
        seen: set[str] = set()
        created = updated = 0
        with self.db.session() as s:
            depts = {d.name: d for d in s.scalars(select(Department))}
            people = {p.external_id: p for p in s.scalars(select(Person).where(Person.source == "directory"))}
            for row in rows:
                ext = row["external_id"]
                seen.add(ext)
                dept_name = row.pop("department", "") or ""
                dept = None
                if dept_name:
                    dept = depts.get(dept_name)
                    if dept is None:
                        dept = Department(name=dept_name, source="directory")
                        s.add(dept)
                        depts[dept_name] = dept
                p = people.get(ext)
                is_new = p is None
                if p is None:
                    p = Person(source="directory", external_id=ext, display_name=row["display_name"])
                    s.add(p)
                    created += 1

                def snapshot(x: Person) -> tuple:
                    return (x.display_name, x.username, x.email, x.phone, x.mobile, x.chat, x.title, x.active,
                            x.department.name if x.department else None)

                before = None if is_new else snapshot(p)
                for fld in ("display_name", "username", "email", "phone", "mobile", "chat", "title"):
                    if fld in self.attrs:
                        setattr(p, fld, row.get(fld, ""))
                if "department" in self.attrs:
                    p.department = dept
                p.active = True
                if before is not None and before != snapshot(p):
                    updated += 1
            gone = 0
            for ext, p in people.items():
                if ext not in seen and p.active:
                    p.active = False
                    gone += 1
        return {"people": len(rows), "new": created, "changed": updated, "inactive": gone}

    async def sync(self) -> bool:
        st = self.state
        start = time.time()
        st.last_run = start
        try:
            rows = await asyncio.to_thread(self._fetch)
            st.counts = await asyncio.to_thread(self._store, rows)
            st.error = None
            st.last_ok = time.time()
            return True
        except DirectoryError as exc:
            st.error = str(exc)
            log.warning("%s", exc)
        except Exception as exc:
            st.error = f"directory: unexpected error: {exc!r}"
            log.exception("directory sync failed")
        finally:
            st.duration = round(time.time() - start, 2)
        return False
