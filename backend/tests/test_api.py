"""API round trips with an in-process app and no data sources."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from deskside.config import Settings
from deskside.db import Database
from deskside.main import create_app

JSON = {"X-Requested-With": "deskside"}


@pytest.fixture
def client(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path}/t.db", secret_key="k" * 40, admin_password="initial-password")
    s.naming = {"workstation": {"pattern": "WS{nn}", "kind": "workstation", "ip": "10.0.10.{100+n}"}}
    s.raw = {"dns": {"reverse": False}}
    with TestClient(create_app(s)) as c:
        assert c.post("/api/login", json={"username": "admin", "password": "initial-password"}).status_code == 200
        yield c


def _login_as(client, username, role):
    client.post("/api/users", json={"username": username, "password": "x" * 12, "role": role})
    other = TestClient(client.app)
    assert other.post("/api/login", json={"username": username, "password": "x" * 12}).status_code == 200
    return other


def test_device_room_department_people_and_search(client):
    room = client.post("/api/rooms", json={"number": "1.04", "name": "Lab"}).json()["id"]
    dep = client.post("/api/departments", json={"name": "Quality"}).json()["id"]
    person = client.post("/api/people", json={"display_name": "Ada Example", "phone": "+49 30 1234-56",
                                              "email": "ada@example.org", "department_id": dep}).json()["id"]
    dev = client.post("/api/devices", json={"name": "WS09", "kind": "workstation", "mac": "00:00:5e:00:53:2a"}).json()["id"]
    assert client.patch(f"/api/devices/{dev}", json={"room_id": room, "department_id": dep}).status_code == 200
    assert client.post(f"/api/devices/{dev}/people", json={"person_id": person}).status_code == 200

    card = client.get(f"/api/devices/{dev}").json()
    assert card["room"]["name"] == "Lab" and card["department"]["name"] == "Quality"
    assert card["people"][0]["primary"] is True and card["people"][0]["phone"] == "+49 30 1234-56"

    for q in ("1.04", "lab", "quality", "ada", "1234-56"):
        rows = client.get("/api/devices", params={"q": q}).json()["rows"]
        assert [r["name"] for r in rows] == ["WS09"], q

    assert client.patch(f"/api/devices/{dev}", json={"clear": ["room"]}).status_code == 200
    assert client.get(f"/api/devices/{dev}").json()["room"] is None


def test_contacts_hidden_from_viewers_by_default(client):
    person = client.post("/api/people", json={"display_name": "Bo Example", "phone": "555-0100"}).json()["id"]
    dev = client.post("/api/devices", json={"name": "WS01", "kind": "workstation"}).json()["id"]
    client.post(f"/api/devices/{dev}/people", json={"person_id": person})
    viewer = _login_as(client, "support", "viewer")
    p = viewer.get(f"/api/devices/{dev}").json()["people"][0]
    assert p["display_name"] == "Bo Example" and "phone" not in p
    assert viewer.get("/api/devices", params={"q": "555-0100"}).json()["rows"] == []
    assert viewer.post("/api/rooms", json={"name": "x"}, headers=JSON).status_code == 403


def test_naming_next_and_warnings(client):
    client.post("/api/devices", json={"name": "WS01", "kind": "workstation"})
    client.post("/api/devices", json={"name": "WS03", "kind": "workstation"})
    odd = client.post("/api/devices", json={"name": "reception", "kind": "workstation"}).json()["id"]
    conv = client.get("/api/naming").json()
    assert conv[0]["next"] == "WS02"
    assert client.get(f"/api/devices/{odd}").json()["naming_warnings"] == ["name_mismatch:WS{nn}"]


def test_directory_people_are_read_only(client):
    db: Database = client.app.state.db
    from deskside.db import Person
    with db.session() as s:
        s.add(Person(display_name="Dir User", source="directory", external_id="abc"))
    pid = client.get("/api/people", params={"q": "Dir"}).json()[0]["id"]
    assert client.patch(f"/api/people/{pid}", json={"display_name": "x"}).status_code == 400
    assert client.delete(f"/api/people/{pid}", headers=JSON).status_code == 400


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY, name VARCHAR(200), kind VARCHAR(50), "
                "description TEXT, created_at INTEGER, updated_at INTEGER)")
    con.execute("INSERT INTO devices (name, kind, description, created_at, updated_at) VALUES ('old', '', '', 0, 0)")
    con.commit()
    con.close()
    Database(f"sqlite:///{path}").create_schema()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(devices)")}
    assert {"room_id", "department_id"} <= cols


def test_next_free_name_respects_hosts_on_the_network(client):
    from deskside.db import Sighting
    with client.app.state.db.session() as s:
        s.add(Sighting(mac="00:00:5E:00:53:01", hostname="ws01.example.org"))
    assert client.get("/api/naming").json()[0]["next"] == "WS02"
