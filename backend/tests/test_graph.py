"""The network map graph: switch cascades from NetBox, inferred uplinks, virtual machines and the Internet."""

from dataclasses import dataclass, field

from deskside.graph import Dev, Graph, Seen
from deskside.sources import Neighbor


def M(n: int) -> str:
    return f"00:00:5E:00:53:{n:02X}"


@dataclass
class If:
    id: int
    device_id: int
    name: str
    endpoints: list = field(default_factory=list)
    mgmt: bool = False
    macs: list = field(default_factory=list)


class FakeNb:
    """core (read via SNMP) GE2 -> desk-sw sfp1; desk-sw p3 -> WS03; floor-sw p8 -> WS08, uplink not documented."""

    def __init__(self):
        role = lambda r: {"name": r}
        self.devices = {1: {"name": "core", "role": role("Switch")}, 2: {"name": "desk-sw", "role": role("Switch")},
                        3: {"name": "floor-sw", "role": role("Switch")}, 10: {"name": "WS03"}, 11: {"name": "WS08"},
                        12: {"name": "hv1"}}
        ep = lambda dev_id, name, port: [{"name": port, "device": {"id": dev_id, "name": name}}]
        self.ifaces = {1: If(1, 1, "GE2", ep(2, "desk-sw", "sfp1")), 2: If(2, 2, "sfp1", ep(1, "core", "GE2")),
                       3: If(3, 2, "p3", ep(10, "WS03", "LAN")), 4: If(4, 3, "p8", ep(11, "WS08", "LAN")),
                       5: If(5, 1, "GE32", ep(12, "hv1", "eno1")), 6: If(6, 1, "GE22", ep(12, "hv1", "iLO")),
                       7: If(7, 12, "iLO", mgmt=True)}
        self.ifaces[6].endpoints[0]["id"] = 7
        self.tunnels = [{"name": "staff-vpn", "owner": "fw", "role": "hub"}]

    def device_for(self, name, macs, external_id=None):
        return {"ws03": 10, "ws08": 11, "hv1": 12}.get(name.lower())


def build(devices, seen, **kw):
    g = Graph(devices, seen, **kw).build()
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = {(e["source"], e["target"]): e for e in g["edges"]}
    return g, nodes, edges


def test_cascade_inferred_uplink_vms_and_internet():
    devs = [Dev(1, "WS03", "workstation", macs=[M(3)]), Dev(2, "WS08", "workstation", macs=[M(8)]),
            Dev(3, "hv1", "Hypervisor", macs=[M(0x30), M(0x32)], labels={M(0x32): "iLO"}), Dev(4, "fw", "Firewall", connection="virtual", parent_id=3,
                                                              macs=[M(0x31)]),
            Dev(5, "WS03 monitor", "monitor", connection="dp", parent_id=1), Dev(6, "spare", "workstation"),
            Dev(7, "modem", "Modem")]
    seen = [Seen(M(3), "10.0.10.103", "core", "GigabitEthernet2", port_mac_count=6),
            Seen(M(8), "10.0.10.108", "core", "GigabitEthernet5", port_mac_count=3),
            Seen(M(0x30), "10.0.10.3", "core", "GigabitEthernet32", port_mac_count=2),
            Seen(M(0x32), "10.0.10.171", "core", "GigabitEthernet22", port_mac_count=1),     # out-of-band port
            Seen(M(0x31), "10.0.10.250", "core", "GigabitEthernet32", port_mac_count=2),
            *[Seen(M(0x40 + i), None, "core", "GigabitEthernet2", port_mac_count=6) for i in range(5)]]
    g, nodes, edges = build(devs, seen, netbox=FakeNb())
    core, desk, floor = "sw:core", "sw:desk-sw", "sw:floor-sw"
    assert nodes[core]["managed"] and not nodes[desk]["managed"]
    assert edges[(core, desk)]["kind"] == "link" and edges[(core, desk)]["label"] == "GE2"
    # seen on the core's uplink to desk-sw, documented on desk-sw p3: drawn on desk-sw
    assert edges[(desk, "d:1")]["label"] == "p3"
    # floor-sw has no documented uplink; WS08 is documented on it and seen on GE5, so it hangs there
    assert nodes[floor]["uplink_undocumented"] and edges[(core, floor)]["kind"] == "inferred"
    assert edges[(core, floor)]["label"] == "GigabitEthernet5" and edges[(floor, "d:2")]["label"] == "p8"
    # Internet -> modem -> the host carrying the firewall VM -> the core switch on the host's data port
    assert edges[("internet", "d:7")]["kind"] == "wan" and edges[("d:7", "d:3")]["kind"] == "wan"
    assert edges[("d:3", core)]["kind"] == "uplink" and edges[("d:3", core)]["target_label"] == "GE32"
    assert edges[("d:3", "d:4")]["kind"] == "virtual" and nodes["d:4"]["online"] and nodes["d:4"]["gateway"]
    # the out-of-band port is a management line, not the host's position
    mgmt = [e for e in g["edges"] if e["kind"] == "mgmt"]
    assert [(e["source"], e["target"], e["label"]) for e in mgmt] == [(core, "d:3", "GigabitEthernet22")]
    assert edges[("d:3", "vpn:staff-vpn")]["via"] == "fw"
    assert edges[("d:1", "d:5")]["kind"] == "attached"
    # five unknown addresses behind desk-sw become one group
    group = next(n for n in g["nodes"] if n["type"] == "group")
    assert len(group["members"]) == 5 and (desk, group["id"]) in edges
    assert [n["name"] for n in g["unplaced"]] == ["spare"]


def test_without_netbox_and_with_lldp():
    devs = [Dev(1, "WS03", "workstation", macs=[M(3)])]
    seen = [Seen(M(3), "10.0.10.103", "core", "Gi3", port_mac_count=1), Seen(M(9), "10.0.10.9", "edge", "Gi1")]
    g, nodes, edges = build(devs, seen, neighbors=[Neighbor("core", "Gi24", "edge", "Gi48")],
                            options={"internet": False})
    assert edges[("sw:core", "sw:edge")]["label"] == "Gi24"
    assert edges[("sw:core", "d:1")]["label"] == "Gi3" and ("sw:edge", "u:" + M(9)) in edges
    assert "internet" not in nodes


def test_switch_placed_by_its_own_management_address():
    nb = FakeNb()
    nb.devices[4] = {"name": "desk-sw2", "role": {"name": "Switch"}}
    nb.ifaces[8] = If(8, 4, "mgmt0", mgmt=True, macs=[M(0x50)])
    devs = [Dev(9, "desk-sw2", "Switch", macs=[M(0x50)], labels={M(0x50): "mgmt0"})]
    seen = [Seen(M(0x50), "10.0.10.186", "core", "GigabitEthernet9", port_mac_count=4)]
    g, nodes, edges = build(devs, seen, netbox=nb, options={"internet": False})
    assert edges[("sw:core", "d:9")]["kind"] == "inferred" and edges[("sw:core", "d:9")]["label"] == "GigabitEthernet9"
    assert not [e for e in g["edges"] if e["kind"] == "mgmt" and e["target"] == "d:9"]


def test_racks_list_mounted_devices_top_down_including_passive_ones():
    nb = FakeNb()
    rack = {"id": 1, "name": "Rack 1"}
    nb.devices[1].update(rack=rack, position=40.0)
    nb.devices[12].update(rack=rack, position=20.0)
    nb.devices[20] = {"name": "patch-1", "role": {"name": "Patch panel"}, "rack": rack, "position": 42.0}
    nb.devices[21] = {"name": "ups", "role": {"name": "UPS"}, "rack": rack, "position": 1.0}
    devs = [Dev(3, "hv1", "Hypervisor", macs=[M(0x30)]), Dev(8, "ups", "UPS")]
    nb.device_for = lambda name, macs, external_id=None: {"hv1": 12, "ups": 21}.get(name.lower())
    seen = [Seen(M(0x30), "10.0.10.3", "core", "GigabitEthernet32", port_mac_count=1)]
    g, nodes, edges = build(devs, seen, netbox=nb, options={"internet": False})
    (r,) = g["racks"]
    assert [(i["name"], i["node"]) for i in r["items"]] == [
        ("patch-1", None), ("core", "sw:core"), ("hv1", "d:3"), ("ups", "d:8")]
    assert nodes["d:8"]["rack"] == "rack:1"            # not cabled, but it has its place in the rack
    assert "ups" not in [n["name"] for n in g["unplaced"]]


def test_network_peripheral_on_own_port_shared_ports_and_conflicts():
    devs = [Dev(1, "WS03", "workstation", macs=[M(3)]), Dev(2, "WS03-Printer", "printer", parent_id=1, macs=[M(4)]),
            Dev(3, "WS03-Monitor", "monitor", parent_id=1, connection="dp"),
            Dev(5, "WS05", "workstation", macs=[M(5)]), Dev(6, "WS06", "workstation", macs=[M(6)])]
    seen = [Seen(M(3), "10.0.10.103", "core", "GigabitEthernet3", port_mac_count=1),
            Seen(M(4), "10.0.10.13", "core", "GigabitEthernet14", port_mac_count=1),
            Seen(M(5), "10.0.10.105", "core", "GigabitEthernet41", port_mac_count=3),
            Seen(M(6), "10.0.10.106", "core", "GigabitEthernet41", port_mac_count=3),
            Seen(M(7), "10.0.10.150", "core", "GigabitEthernet41", port_mac_count=3)]
    g, nodes, edges = build(devs, seen, options={"internet": False})
    # the printer belongs to WS03 by name, but it has a port of its own
    assert edges[("sw:core", "d:2")]["label"] == "GigabitEthernet14" and ("d:1", "d:2") not in edges
    assert edges[("d:1", "d:3")]["kind"] == "attached"
    # three addresses on port 41: something sits in between
    seg = "seg:sw:core:GigabitEthernet41"
    assert nodes[seg]["count"] == 3 and edges[("sw:core", seg)]["label"] == "GigabitEthernet41"
    assert {t for (s, t) in edges if s == seg} == {"d:5", "d:6", "u:" + M(7)}


def test_documented_place_that_the_switch_contradicts_is_flagged():
    nb = FakeNb()          # core GE2 -> desk-sw; floor-sw has no uplink; WS08 documented on floor-sw p8
    nb.ifaces[9] = If(9, 1, "GE1", [{"name": "up", "device": {"id": 3, "name": "floor-sw"}}])
    nb.ifaces[10] = If(10, 3, "up", [{"name": "GE1", "device": {"id": 1, "name": "core"}}])
    devs = [Dev(2, "WS08", "workstation", macs=[M(8)])]
    seen = [Seen(M(8), "10.0.10.108", "core", "GigabitEthernet2", port_mac_count=4)]     # but seen behind GE2
    g, nodes, edges = build(devs, seen, netbox=nb, options={"internet": False})
    assert edges[("sw:floor-sw", "d:2")]["label"] == "p8"
    assert nodes["d:2"]["conflict"] == {"switch": "core", "port": "GigabitEthernet2", "doc_switch": "floor-sw", "doc_port": "p8"}


def test_neighbouring_mac_belongs_to_the_switch_and_a_moved_uplink_is_flagged():
    nb = FakeNb()          # NetBox: core GE2 -> desk-sw
    devs = [Dev(9, "desk-sw", "Switch", macs=["00:00:5E:00:53:A0"])]
    seen = [Seen("00:00:5E:00:53:A1", None, "core", "GigabitEthernet7", port_mac_count=3)]   # base MAC + 1, no IP
    g, nodes, edges = build(devs, seen, netbox=nb, options={"internet": False})
    assert not [n for n in g["nodes"] if n["type"] == "unknown"]
    assert nodes["d:9"]["conflict"]["port"] == "GigabitEthernet7" and nodes["d:9"]["conflict"]["doc_port"] == "GE2"
