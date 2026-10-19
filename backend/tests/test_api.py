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


def test_remote_entries_rdp_download_and_search(client):
    dev = client.post("/api/devices", json={"name": "WS05", "kind": "workstation", "mac": "00:00:5e:00:53:05"}).json()["id"]
    from deskside.db import Sighting
    with client.app.state.db.session() as s:
        s.add(Sighting(mac="00:00:5E:00:53:05", ip="10.0.10.105", hostname="ws05.example.org", online=True))
    assert client.post(f"/api/devices/{dev}/remote", json={"tool": "rustdesk", "value": "987654321"}).status_code == 200
    assert client.post(f"/api/devices/{dev}/remote", json={"tool": "rdp", "username": "EXAMPLE\\alice"}).status_code == 200
    assert client.post(f"/api/devices/{dev}/remote", json={"tool": "rustdesk", "value": "1 2"}).status_code == 400
    remote = {r["tool"]: r for r in client.get(f"/api/devices/{dev}").json()["remote"]}
    assert remote["rustdesk"]["href"] == "rustdesk://connect/987654321"
    rdp = client.get(remote["rdp"]["download"])
    assert rdp.status_code == 200 and rdp.headers["content-type"].startswith("application/x-rdp")
    assert "full address:s:ws05.example.org" in rdp.text and 'filename="WS05.rdp"' in rdp.headers["content-disposition"]
    assert [r["name"] for r in client.get("/api/devices", params={"q": "987654321"}).json()["rows"]] == ["WS05"]


def test_peripherals_relations_and_graph(client):
    from deskside.db import Sighting
    pc = client.post("/api/devices", json={"name": "WS07", "kind": "workstation", "mac": "00:00:5e:00:53:07"}).json()["id"]
    mon = client.post("/api/devices", json={"name": "WS07 monitor", "kind": "monitor", "parent_id": pc, "connection": "dp",
                                            "manufacturer": "Example", "model": "M24", "serial": "SN-1"}).json()["id"]
    dock = client.post("/api/devices", json={"name": "WS07 dock", "kind": "dock", "parent_id": pc}).json()["id"]
    # no cycles: a device cannot hang off its own peripheral
    assert client.patch(f"/api/devices/{pc}", json={"parent_id": mon}).status_code == 400
    assert client.patch(f"/api/devices/{mon}", json={"parent_id": dock}).status_code == 200
    with client.app.state.db.session() as s:
        s.add(Sighting(mac="00:00:5E:00:53:07", ip="10.0.10.107", switch="core", port="GigabitEthernet9", online=True,
                       port_mac_count=2))
        s.add(Sighting(mac="00:00:5E:00:53:99", ip="10.0.10.99", switch="core", port="GigabitEthernet9", online=True,
                       port_mac_count=2, hostname="printer"))
    card = client.get(f"/api/devices/{pc}").json()
    assert [c["name"] for c in card["children"]] == ["WS07 dock"]
    assert card["segment"]["port"] == "GigabitEthernet9" and card["segment"]["peers"][0]["name"] == "printer"
    assert client.get(f"/api/devices/{mon}").json()["parent"]["name"] == "WS07 dock"
    assert [r["name"] for r in client.get("/api/devices", params={"q": "SN-1"}).json()["rows"]] == ["WS07 monitor"]
    graph = client.get("/api/graph").json()
    edges = {(e["source"], e["target"]): e for e in graph["edges"]}
    # the PC and an unknown printer share the port: one shared connection, both behind it
    seg = "seg:sw:core:GigabitEthernet9"
    assert edges[("sw:core", seg)]["label"] == "GigabitEthernet9" and (seg, f"d:{pc}") in edges
    assert (f"d:{pc}", f"d:{dock}") in edges and (f"d:{dock}", f"d:{mon}") in edges
    assert client.put("/api/kinds/monitor", json={"icon": "device-desktop"}).status_code == 200
    assert {k["kind"]: k["icon"] for k in client.get("/api/kinds").json()}["monitor"] == "device-desktop"
    assert client.put("/api/kinds/monitor", json={"icon": "<svg>"}).status_code == 400


def test_lease_only_addresses_have_their_own_filter(client):
    from deskside.db import Sighting
    with client.app.state.db.session() as s:
        s.add(Sighting(mac="02:00:5E:00:53:01", ip="10.0.10.201", online=False, last_seen=0, dhcp=True))   # only a lease
        s.add(Sighting(mac="00:00:5E:00:53:02", ip="10.0.10.50", online=True, switch="core", port="Gi3"))
    res = client.get("/api/devices").json()
    assert [r["ip"] for r in res["rows"]] == ["10.0.10.50"] and res["lease_only"] == 1
    assert [r["ip"] for r in client.get("/api/devices", params={"show": "leases"}).json()["rows"]] == ["10.0.10.201"]
    assert [r["ip"] for r in client.get("/api/devices", params={"q": "10.0.10.201"}).json()["rows"]] == ["10.0.10.201"]


def test_dhcp_push_upload(tmp_path):
    token = "t" * 32
    s = Settings(database_url=f"sqlite:///{tmp_path}/p.db", secret_key="k" * 40, admin_password="initial-password",
                 sources=[{"type": "dhcp-push", "name": "dhcp", "format": "windows-csv", "token": token}])
    s.raw = {"dns": {"reverse": False}}
    csv_text = ('"IPAddress","ClientId","HostName","AddressState","LeaseExpiryTime"\r\n'
                '"10.0.10.150","00-00-5e-00-53-50","ws50.example.org","Active","27.10.2026 08:41:39"\r\n')
    with TestClient(create_app(s)) as c:
        url = "/api/ingest/dhcp"
        assert c.post(url, content=csv_text, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.post("/api/ingest/other", content=csv_text, headers={"Authorization": f"Bearer {token}"}).status_code == 401
        r = c.post(url, content=csv_text.encode("utf-16"), headers={"Authorization": f"Bearer {token}",
                                                                     "Content-Type": "text/csv"})
        assert r.status_code == 200 and r.json() == {"ok": True, "addresses": 1}
        assert c.post("/api/login", json={"username": "admin", "password": "initial-password"}).status_code == 200
        rows = c.get("/api/devices", params={"show": "leases"}).json()["rows"]
        assert [(x["ip"], x["hostname"]) for x in rows] == [("10.0.10.150", "ws50.example.org")]
