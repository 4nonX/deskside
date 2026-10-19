"""Parsers and helpers, tested with made-up but realistic sample data."""

from deskside.netaddr import mac_search_key, normalize_mac, parse_ip
from deskside.search import filter_rows, port_variants, search_blob
from deskside.sources.dhcp import parse_dnsmasq, parse_isc, parse_kea_csv, parse_windows_csv, parse_windows_mmc


def test_normalize_mac_notations():
    want = "AA:BB:CC:00:11:22"
    for v in ("aa:bb:cc:00:11:22", "AA-BB-CC-00-11-22", "aabb.cc00.1122", "aabbcc001122", b"\xaa\xbb\xcc\x00\x11\x22"):
        assert normalize_mac(v) == want
    assert normalize_mac("aabbcc001122000000") == want      # Windows client-id padding
    assert normalize_mac("00:00:00:00:00:00") is None
    assert normalize_mac("not a mac") is None
    assert mac_search_key("aa-bb-cc") == "AABBCC"


def test_parse_ip():
    assert parse_ip("10.0.0.5/24") == "10.0.0.5"
    assert parse_ip("nope") is None


WINDOWS_CSV = '''"IPAddress","ScopeId","ClientId","HostName","AddressState","LeaseExpiryTime"
"10.0.10.171","10.0.10.0","00-11-22-33-44-55","printer1.example.org","ActiveReservation",""
"10.0.10.180","10.0.10.0","00-11-22-33-44-66","WS05.example.org","Active","10/22/2026 5:16:11 PM"
"10.0.10.35","10.0.10.0","00-11-22-33-44-77","bmc","InactiveReservation",""
'''


def test_windows_csv():
    rows = {a.ip: a for a in parse_windows_csv(WINDOWS_CSV)}
    assert set(rows) == {"10.0.10.171", "10.0.10.180"}            # inactive reservation skipped
    assert rows["10.0.10.171"].dynamic is False
    assert rows["10.0.10.180"].dynamic is True and rows["10.0.10.180"].hostname == "WS05.example.org"
    assert rows["10.0.10.180"].expires is not None


def test_windows_mmc_positional():
    text = ("IP\tName\tExpiry\tType\tUnique ID\tDescription\n"
            "10.0.10.35\tbmc\tReservation (inactive)\tNone\t001122334477\t\n"
            "10.0.10.172\tWS25.example.org\tReservation (active)\tDHCP\t001122334488\t\n"
            "10.0.10.174\tWS20.example.org\t22.10.2026 16:56:49\tDHCP\t001122334499\t\n")
    rows = {a.ip: a for a in parse_windows_mmc(text)}
    assert set(rows) == {"10.0.10.172", "10.0.10.174"}
    assert rows["10.0.10.172"].dynamic is False and rows["10.0.10.174"].dynamic is True


def test_dnsmasq():
    rows = parse_dnsmasq("1760000000 00:11:22:33:44:55 10.0.0.20 laptop 01:00:11:22:33:44:55\n"
                         "0 00:11:22:33:44:56 10.0.0.21 * *\n")
    assert [(a.ip, a.hostname) for a in rows] == [("10.0.0.20", "laptop"), ("10.0.0.21", None)]


def test_isc_last_wins_and_active_only():
    text = """
lease 10.0.0.30 { starts 1 2026/10/19 08:00:00; ends 1 2026/10/19 20:00:00; binding state free;
  hardware ethernet 00:11:22:33:44:01; }
lease 10.0.0.31 { starts 1 2026/10/19 08:00:00; ends 1 2026/10/19 20:00:00; binding state active;
  hardware ethernet 00:11:22:33:44:02; client-hostname "old"; }
lease 10.0.0.31 { starts 1 2026/10/19 09:00:00; ends 1 2026/10/19 21:00:00; binding state active;
  hardware ethernet 00:11:22:33:44:02; client-hostname "new"; }
"""
    rows = parse_isc(text)
    assert len(rows) == 1 and rows[0].hostname == "new"


def test_kea_csv():
    text = ("address,hwaddr,client_id,valid_lifetime,expire,subnet_id,fqdn_fwd,fqdn_rev,hostname,state,user_context\n"
            "10.0.0.40,00:11:22:33:44:10,,3600,1760003600,1,0,0,host-a,0,\n"
            "10.0.0.41,00:11:22:33:44:11,,3600,1760003600,1,0,0,host-b,0,\n"
            "10.0.0.41,00:11:22:33:44:11,,0,1760003600,1,0,0,host-b,0,\n")
    assert [a.ip for a in parse_kea_csv(text)] == ["10.0.0.40"]   # released lease removed


def test_port_variants_and_search():
    assert set(port_variants("GigabitEthernet7")) >= {"GigabitEthernet7", "Gi7", "GE7"}
    rows = [
        {"name": "WS09", "ip": "10.0.10.109", "port": "GigabitEthernet7", "macs": ["00:00:5E:00:53:2A"]},
        {"name": "Printer lab", "ip": "10.0.10.13", "port": "GigabitEthernet1", "macs": ["00:00:5E:00:53:13"],
         "search_extra": ["toner low"]},
    ]
    for r in rows:
        r["_blob"] = search_blob(r)
    assert [r["name"] for r in filter_rows(rows, "ge7")] == ["WS09"]
    assert [r["name"] for r in filter_rows(rows, ".109")] == ["WS09"]
    assert [r["name"] for r in filter_rows(rows, "00-00-5e-00-53-2a")] == ["WS09"]
    assert [r["name"] for r in filter_rows(rows, "lab toner")] == ["Printer lab"]
    assert filter_rows(rows, "lab ws09") == []
    # "2a" is part of WS09's MAC, but two hex digits are too short to be treated as a MAC fragment
    assert filter_rows(rows, "2a") == []
    assert [r["name"] for r in filter_rows(rows, "53:2a")] == ["WS09"]
