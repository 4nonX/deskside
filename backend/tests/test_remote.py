import pytest

from deskside.remote import RemoteError, load, render_link, render_rdp


def test_builtin_links():
    t = load(None)
    assert render_link(t["rustdesk"], value="123456789", user=None, hostname=None, ip=None) == "rustdesk://connect/123456789"
    assert render_link(t["teamviewer"], value="123 456", user=None, hostname=None, ip=None) == \
        "tvcontrol1://control?device=123%20456"
    assert render_link(t["anydesk"], value="123456789", user=None, hostname=None, ip=None) is None   # copy only
    assert render_link(t["vnc"], value=None, user=None, hostname="ws09.example.org", ip="10.0.0.9") == \
        "vnc://ws09.example.org"
    assert render_link(t["ssh"], value=None, user=None, hostname=None, ip="10.0.0.9") == "ssh://10.0.0.9"
    assert render_link(t["ssh"], value=None, user="admin", hostname=None, ip="10.0.0.9") == "ssh://admin@10.0.0.9"
    assert render_link(t["rustdesk"], value=None, user=None, hostname="x", ip=None) is None             # needs an ID


def test_values_cannot_change_the_link():
    t = load(None)
    link = render_link(t["teamviewer"], value="1&password=x", user=None, hostname=None, ip=None)
    assert link == "tvcontrol1://control?device=1%26password%3Dx"
    # an address with unsafe characters is ignored and the next candidate is used
    assert render_link(t["vnc"], value="evil host/x", user=None, hostname=None, ip="10.0.0.9") == "vnc://10.0.0.9"


def test_rdp_file_and_injection():
    t = load({"rdp": {"rdp_options": {"screen mode id:i": 1}}})
    body = render_rdp(t["rdp"], value=None, user="EXAMPLE\\alice", hostname="ws09.example.org", ip=None)
    assert "full address:s:ws09.example.org\r\n" in body
    assert "username:s:EXAMPLE\\alice\r\n" in body and "screen mode id:i:1\r\n" in body
    with pytest.raises(RemoteError):
        render_rdp(t["rdp"], value=None, user="x\r\nalternate shell:s:cmd", hostname="h", ip=None)
    with pytest.raises(RemoteError):
        render_rdp(t["rdp"], value=None, user=None, hostname=None, ip=None)


def test_configuration_overrides_and_validation():
    t = load({"anydesk": {"link": "anydesk:{value}"}, "vnc": False, "intranet": {"label": "Admin page",
              "link": "https://{address}:8443/", "auto_kinds": ["printer"]}})
    assert render_link(t["anydesk"], value="42", user=None, hostname=None, ip=None) == "anydesk:42"
    assert "vnc" not in t and t["intranet"].auto_kinds == ["printer"]
    for bad in ({"x": {"link": "javascript:alert(1)"}}, {"x": {"link": "no-scheme"}}, {"x": {"needs": "both"}},
                {"rdp": {"rdp_options": {"alternate shell": "cmd"}}}):
        with pytest.raises(RemoteError):
            load(bad)
