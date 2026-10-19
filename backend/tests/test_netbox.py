"""NetBox comparison and writes against a small in-memory fake of the NetBox API."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from deskside.db import Database, Device, Interface, Proposal, Room, Sighting
from deskside.netbox import Netbox, NetboxError

PC_MAC = "00:00:5E:00:53:09"


class FakeNetbox:
    """Just enough of the NetBox REST API: lists, a few detail reads, and recorded writes."""

    def __init__(self) -> None:
        dev = lambda i, name, loc=None: {"id": i, "name": name, "location": loc}
        self.devices = [dev(1, "core-sw"), dev(2, "WS09-Client-PC", {"id": 7, "name": "Lab"}), dev(3, "patch-1")]
        self.ifaces = [
            self._iface(10, 1, "core-sw", "GE7", cable=100),
            self._iface(11, 1, "core-sw", "GE12"),
            self._iface(20, 2, "WS09-Client-PC", "LAN", cable=101, peer_type="dcim.rearport", peers=[{"id": 30}],
                        endpoints=[{"id": 10, "name": "GE7", "device": {"name": "core-sw"}}]),
        ]
        self.macs = [{"id": 1, "mac_address": PC_MAC, "assigned_object_type": "dcim.interface", "assigned_object_id": 20}]
        self.fronts = [{"id": 40, "name": "F1", "device": {"name": "patch-1"}, "cable": 100, "rear_ports": [{"rear_port": 30}]}]
        self.cables = {100: {"id": 100, "a_terminations": [{"object_type": "dcim.interface", "object_id": 10}],
                             "b_terminations": [{"object_type": "dcim.frontport", "object_id": 40}]}}
        self.ips = [{"id": 5, "address": "10.0.10.150/24", "status": {"value": "dhcp"},
                     "assigned_object_type": "dcim.interface", "assigned_object_id": 20}]
        self.locations = [{"id": 7, "name": "Lab", "site": {"name": "Main"}}, {"id": 8, "name": "Office", "site": {"name": "Main"}}]
        self.custom_fields = []
        self.writes: list[tuple[str, str, dict]] = []

    @staticmethod
    def _iface(i, dev_id, dev, name, cable=None, peer_type=None, peers=None, endpoints=None):
        return {"id": i, "device": {"id": dev_id, "name": dev}, "name": name, "mgmt_only": False,
                "cable": {"id": cable} if cable else None, "link_peers_type": peer_type, "link_peers": peers or [],
                "connected_endpoints": endpoints or []}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/")
        if request.method != "GET":
            body = json.loads(request.content or b"{}")
            self.writes.append((request.method, path, body))
            return httpx.Response(201, json={"id": 999})
        lists = {"dcim/devices/": self.devices, "dcim/interfaces/": self.ifaces, "dcim/mac-addresses/": self.macs,
                 "extras/custom-fields/": self.custom_fields, "dcim/locations/": self.locations,
                 "virtualization/virtual-machines/": getattr(self, "vms", []),
                 "ipam/prefixes/": getattr(self, "prefixes", []),
                 "virtualization/interfaces/": getattr(self, "vm_ifaces", []),
                 "dcim/front-ports/": self.fronts, "ipam/ip-addresses/": self.ips}
        if path in lists:
            rows = lists[path]
            if path == "ipam/ip-addresses/" and request.url.params.get("status") == "dhcp":
                rows = [ip for ip in rows if ip["status"]["value"] == "dhcp"]
            return httpx.Response(200, json={"count": len(rows), "next": None, "results": rows})
        if path.startswith("dcim/cables/"):
            return httpx.Response(200, json=self.cables[int(path.split("/")[2])])
        return httpx.Response(404, json={})


@pytest.fixture
def setup(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/t.db")
    db.create_schema()
    fake = FakeNetbox()
    nb = Netbox({"url": "https://netbox.example.org", "token": "t", "name_pattern": r"^(?P<name>WS\d+)-Client-PC$"}, db)
    nb.transport = httpx.MockTransport(fake.handler)
    with db.session() as s:
        d = Device(name="WS09", kind="workstation")
        d.interfaces.append(Interface(mac=PC_MAC))
        s.add(d)
    return db, nb, fake


def _sight(db, **kw):
    with db.session() as s:
        s.merge(Sighting(mac=PC_MAC, online=True, switch="core-sw", **kw))


def _proposals(db):
    with db.session() as s:
        return {p.kind: p for p in s.scalars(select(Proposal)) if p.status == "open"}


def test_in_sync_gives_no_proposals_and_imports_rooms(setup):
    db, nb, fake = setup
    _sight(db, port="GigabitEthernet7", ip="10.0.10.150", dhcp=True)
    assert asyncio.run(nb.sync()) is True, nb.state.error
    assert _proposals(db) == {}
    with db.session() as s:
        rooms = {r.name: r for r in s.scalars(select(Room))}
        assert set(rooms) == {"Lab", "Office"} and rooms["Lab"].source == "netbox"
        assert s.scalar(select(Device)).room_id == rooms["Lab"].id       # filled from the NetBox location
    info = nb.info("WS09", [PC_MAC])
    assert info["name"] == "WS09-Client-PC" and info["interfaces"][0]["endpoint"] == "core-sw GE7"


def test_moved_device_proposes_moving_the_last_cable(setup):
    db, nb, fake = setup
    _sight(db, port="GigabitEthernet12")
    asyncio.run(nb.sync())
    p = _proposals(db)["moved"]
    assert {k: p.payload[k] for k in ("cable", "from", "to")} == {"cable": 100, "from": 10, "to": 11}
    assert p.payload["display"] == {"device": "WS09-Client-PC", "iface": "LAN", "seen": "core-sw GE12", "recorded": "core-sw GE7"}
    asyncio.run(nb.apply(p))
    method, path, body = fake.writes[-1]
    assert (method, path) == ("PATCH", "dcim/cables/100/")
    assert body["a_terminations"] == [{"object_type": "dcim.interface", "object_id": 11}]
    assert body["b_terminations"] == [{"object_type": "dcim.frontport", "object_id": 40}]


def test_missing_patch_cable_and_missing_mac(setup):
    db, nb, fake = setup
    fake.fronts[0]["cable"] = None
    fake.ifaces[2]["connected_endpoints"] = []
    fake.ifaces[0]["cable"] = None
    fake.macs.clear()
    _sight(db, port="GigabitEthernet7")
    asyncio.run(nb.sync())
    props = _proposals(db)
    assert (props["cable"].payload["a"], props["cable"].payload["b"]) == (
        {"object_type": "dcim.interface", "object_id": 10}, {"object_type": "dcim.frontport", "object_id": 40})
    assert (props["mac"].payload["interface"], props["mac"].payload["mac"]) == (20, PC_MAC)
    asyncio.run(nb.apply(props["mac"]))
    assert [w[:2] for w in fake.writes[-2:]] == [("POST", "dcim/mac-addresses/"), ("PATCH", "dcim/interfaces/20/")]


def test_dhcp_address_written_automatically_but_not_twice(setup):
    db, nb, fake = setup
    _sight(db, port="GigabitEthernet7", ip="10.0.10.177", dhcp=True)
    asyncio.run(nb.sync())
    assert ("PATCH", "ipam/ip-addresses/5/", {"address": "10.0.10.177/24"}) in fake.writes
    # an address that is already used by another IP object in NetBox is never written
    fake.writes.clear()
    fake.ips.append({"id": 6, "address": "10.0.10.180/24", "status": {"value": "active"}})
    _sight(db, port="GigabitEthernet7", ip="10.0.10.180", dhcp=True)
    asyncio.run(nb.sync())
    assert not any(w[1] == "ipam/ip-addresses/5/" for w in fake.writes)


def test_read_only_never_writes(setup):
    db, _, fake = setup
    nb = Netbox({"url": "https://netbox.example.org", "token": "t", "read_only": True,
                 "name_pattern": r"^(?P<name>WS\d+)-Client-PC$"}, db)
    nb.transport = httpx.MockTransport(fake.handler)
    fake.custom_fields.append({"name": "deskside_last_seen", "object_types": ["dcim.interface"]})
    _sight(db, port="GigabitEthernet12", ip="10.0.10.177", dhcp=True)
    asyncio.run(nb.sync())
    assert fake.writes == []
    with pytest.raises(NetboxError):
        asyncio.run(nb.apply(_proposals(db)["moved"]))


def test_resolved_and_dismissed_proposals(setup):
    db, nb, fake = setup
    _sight(db, port="GigabitEthernet12")
    asyncio.run(nb.sync())
    with db.session() as s:
        s.scalar(select(Proposal).where(Proposal.kind == "moved")).status = "dismissed"
    asyncio.run(nb.sync())
    assert "moved" not in _proposals(db)                                 # dismissed stays dismissed
    _sight(db, port="GigabitEthernet7")
    asyncio.run(nb.sync())
    with db.session() as s:
        assert {p.status for p in s.scalars(select(Proposal))} <= {"dismissed", "resolved"}


def test_last_seen_written_once_per_day_when_field_exists(setup):
    db, nb, fake = setup
    fake.custom_fields.append({"name": "deskside_last_seen", "object_types": ["dcim.interface"]})
    _sight(db, port="GigabitEthernet7", ip="10.0.10.150", dhcp=True)
    asyncio.run(nb.sync())
    asyncio.run(nb.sync())
    seen = [w for w in fake.writes if w[1] == "dcim/interfaces/20/"]
    assert len(seen) == 1 and "deskside_last_seen" in seen[0][2]["custom_fields"]


def test_no_cable_proposal_when_devices_share_a_port(setup):
    db, nb, fake = setup
    fake.fronts[0]["cable"] = None
    fake.ifaces[2]["connected_endpoints"] = []
    fake.ifaces[0]["cable"] = None
    with db.session() as s:
        other = Device(name="WS10", kind="workstation")
        other.interfaces.append(Interface(mac="00:00:5E:00:53:10"))
        s.add(other)
        s.merge(Sighting(mac="00:00:5E:00:53:10", online=True, switch="core-sw", port="GigabitEthernet7"))
    _sight(db, port="GigabitEthernet7")
    asyncio.run(nb.sync())
    assert "cable" not in _proposals(db)


def test_import_peripherals_with_parent_rule(setup):
    db, _, fake = setup
    fake.devices.append({"id": 4, "name": "WS09-Monitor", "location": None, "role": {"name": "Monitor"},
                         "device_type": {"model": "M24", "manufacturer": {"name": "Example"}}, "serial": "SN-9"})
    fake.devices.append({"id": 5, "name": "Lobby-TV", "location": None, "role": {"name": "Monitor"}, "device_type": {}})
    fake.devices.append({"id": 6, "name": "WS09-Phone", "location": None, "role": {"name": "Phone"}, "device_type": {}})
    nb = Netbox({"url": "https://netbox.example.org", "token": "t", "name_pattern": r"^(?P<name>WS\d+)-Client-PC$",
                 "import_devices": {"roles": ["monitor"], "parent_pattern": r"^(?P<parent>WS\d+)-"}}, db)
    nb.transport = httpx.MockTransport(fake.handler)
    _sight(db, port="GigabitEthernet7")
    assert asyncio.run(nb.sync()), nb.state.error
    assert asyncio.run(nb.sync())                                  # second run updates, does not duplicate
    with db.session() as s:
        devs = {d.name: d for d in s.scalars(select(Device))}
        assert set(devs) == {"WS09", "WS09-Monitor", "Lobby-TV"}    # phone role not imported, PC not duplicated
        mon = devs["WS09-Monitor"]
        assert (mon.source, mon.kind, mon.model, mon.serial, mon.parent.name) == ("netbox", "Monitor", "M24", "SN-9", "WS09")
        assert devs["Lobby-TV"].parent_id is None


def test_import_hosts_and_virtual_machines(setup):
    db, _, fake = setup
    fake.devices.append({"id": 4, "name": "hv1", "location": None, "role": {"name": "Hypervisor"}, "device_type": {},
                         "cluster": {"id": 3}})
    fake.ifaces.append(fake._iface(50, 4, "hv1", "eno1"))
    fake.ips.append({"id": 6, "address": "10.0.10.3/24", "status": {"value": "active"},
                     "assigned_object": {"id": 50, "device": {"id": 4, "name": "hv1"}}})
    fake.ips.append({"id": 7, "address": "10.0.10.250/24", "status": {"value": "active"},
                     "assigned_object": {"id": 60, "virtual_machine": {"id": 1, "name": "fw"}}})
    fake.vms = [{"id": 1, "name": "fw", "role": {"name": "Firewall"}, "device": {"id": 4, "name": "hv1"}},
                {"id": 2, "name": "files", "role": None, "device": None, "cluster": {"id": 3}}]
    fake.vm_ifaces = [{"id": 61, "name": "eth0", "virtual_machine": {"id": 2, "name": "files"},
                       "primary_mac_address": {"mac_address": "00:00:5e:00:53:62"}}]
    with db.session() as s:
        s.add(Sighting(mac="00:00:5E:00:53:30", ip="10.0.10.3", online=True))      # NetBox knows no MAC for these two
        s.add(Sighting(mac="00:00:5E:00:53:31", ip="10.0.10.250", online=True))
    nb = Netbox({"url": "https://netbox.example.org", "token": "t", "name_pattern": r"^(?P<name>WS\d+)-Client-PC$",
                 "import_devices": {"roles": "all", "virtual_machines": True}}, db)
    nb.transport = httpx.MockTransport(fake.handler)
    assert asyncio.run(nb.sync()), nb.state.error
    assert asyncio.run(nb.sync())
    with db.session() as s:
        devs = {d.name: d for d in s.scalars(select(Device))}
        assert set(devs) == {"WS09", "hv1", "fw", "files", "core-sw"}     # patch-1 has no interfaces: passive
        fw = devs["fw"]
        assert (fw.kind, fw.connection, fw.parent.name) == ("Firewall", "virtual", "hv1")
        assert [i.mac for i in fw.interfaces] == ["00:00:5E:00:53:31"]
        assert [i.mac for i in devs["hv1"].interfaces] == ["00:00:5E:00:53:30"]
        assert [i.mac for i in devs["files"].interfaces] == ["00:00:5E:00:53:62"] and devs["files"].kind == "VM"
        assert devs["files"].parent.name == "hv1"                  # found through the cluster
        # Fixed addresses of virtual machines count as documented, like those of devices.
        assert nb.documented_ip("fw", [], fw.external_id) == "10.0.10.250"
        assert nb.documented_ip("files", [], devs["files"].external_id) is None
        assert nb.documented_ip("hv1", [], devs["hv1"].external_id) == "10.0.10.3"   # no primary_ip4, assigned address


def test_port_place_follows_the_cabling(setup):
    db, nb, fake = setup
    fake.ifaces[0].update(link_peers_type="dcim.frontport", link_peers=[{"id": 40, "name": "F1", "device": {"name": "patch-1"}}],
                          connected_endpoints=[{"id": 20, "name": "LAN", "device": {"id": 2, "name": "WS09-Client-PC"}}])
    assert asyncio.run(nb.sync()), nb.state.error
    assert nb.port_place("core-sw", "GigabitEthernet7") == {"documented": True, "panel": "patch-1 F1", "endpoint": "WS09",
                                                            "room": "Lab", "switch": False}
    assert nb.port_place("core-sw", "GigabitEthernet12") == {"documented": False}     # known switch, no cable
    assert nb.port_place("other-sw", "Gi1") is None                                   # NetBox does not know it


def test_documented_ip_for_devices_without_a_live_address(setup):
    db, nb, fake = setup
    fake.devices[1]["primary_ip4"] = {"address": "10.0.10.109/24"}
    assert asyncio.run(nb.sync()), nb.state.error
    assert nb.documented_ip("WS09", [PC_MAC]) == "10.0.10.109"
    assert nb.documented_ip("WS99", []) is None
