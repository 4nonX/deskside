import pytest

from deskside.naming import Convention, NamingError, check, load, suggest


def test_pattern_number_and_format():
    c = Convention("ws", "WS{nn}", kind="workstation", ip="10.0.10.{100+n}")
    assert c.number("WS07") == 7
    assert c.number("ws07.example.org") == 7          # host names may carry a domain and other case
    assert c.number("WS7") is None                    # two digits required
    assert c.number("PC07") is None
    assert c.format(3) == "WS03"
    assert c.expected_ip(9) == "10.0.10.109"


def test_next_free_fills_gaps():
    c = Convention("ws", "WS{nn}")
    assert c.next_free(["WS01", "WS02", "WS04", "Printer"]) == "WS03"
    assert c.next_free([]) == "WS01"


def test_plain_number_and_suffix():
    c = Convention("pr", "PRN-{n}-A")
    assert c.number("PRN-12-A") == 12 and c.format(5) == "PRN-5-A"


def test_check_and_suggest():
    conv = load({"workstation": {"pattern": "WS{nn}", "kind": "workstation", "ip": "10.0.10.{100+n}"}})
    assert check(conv, "WS09", "workstation", ["10.0.10.109"]) == []
    assert check(conv, "WS09", "workstation", ["10.0.10.188"]) == ["ip_mismatch:10.0.10.109"]
    assert check(conv, "reception", "workstation", []) == ["name_mismatch:WS{nn}"]
    assert check(conv, "printer-1", "printer", []) == []      # other kinds are not checked
    assert suggest(conv, "ws12.example.org") == "WS12"
    assert suggest(conv, "laptop") is None


def test_invalid_patterns():
    with pytest.raises(NamingError):
        Convention("x", "NO-NUMBER")
    with pytest.raises(NamingError):
        Convention("x", "WS{nn}", ip="10.0.0.5")
