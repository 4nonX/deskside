import pytest
from sqlalchemy import select

from deskside.db import Database, Department, Person
from deskside.directory import Directory, DirectoryError


@pytest.fixture
def directory(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/t.db")
    db.create_schema()
    return Directory({"url": "ldaps://dc.example.org", "base_dn": "DC=example,DC=org",
                      "attributes": {"display_name": "displayName", "phone": "telephoneNumber",
                                     "department": "department"}}, db)


def test_store_creates_updates_and_deactivates(directory):
    counts = directory._store([
        {"external_id": "1", "display_name": "Ada", "phone": "100", "department": "Lab"},
        {"external_id": "2", "display_name": "Bo", "phone": "200", "department": ""},
    ])
    assert counts == {"people": 2, "new": 2, "changed": 0, "inactive": 0}
    counts = directory._store([{"external_id": "1", "display_name": "Ada", "phone": "101", "department": "Lab"}])
    assert counts == {"people": 1, "new": 0, "changed": 1, "inactive": 1}
    with directory.db.session() as s:
        people = {p.display_name: p for p in s.scalars(select(Person))}
        assert people["Ada"].phone == "101" and people["Ada"].department.name == "Lab"
        assert people["Bo"].active is False          # gone from the directory: kept, but inactive
        assert people["Ada"].email == ""             # not in the attribute list, never stored
        assert s.scalar(select(Department).where(Department.name == "Lab")).source == "directory"


def test_rejects_unknown_attribute_fields(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/t.db")
    with pytest.raises(DirectoryError):
        Directory({"url": "ldap://x", "base_dn": "dc=x", "attributes": {"display_name": "cn", "salary": "x"}}, db)
