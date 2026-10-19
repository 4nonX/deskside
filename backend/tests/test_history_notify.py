"""Port/address history, the newer events, and notifications against fake endpoints."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from deskside.config import Settings
from deskside.db import Database, Device, EventLog, History, Interface, Sighting
from deskside.engine import Engine, SourceState
from deskside.notify import Notifier, NotifyError, render_text
from deskside.sources import AddressEntry, PortEntry, Snapshot

A = "00:00:5E:00:53:0A"


@pytest.fixture
def engine(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path}/t.db", secret_key="x" * 32, uplink_mac_threshold=2,
                 naming={"ws": {"pattern": "WS{nn}", "kind": "workstation", "ip": "10.0.10.{100+n}"}})
    s.raw = {"dns": {"reverse": False}}
    db = Database(s.database_url)
    db.create_schema()
    with db.session() as ses:
        d = Device(name="WS09", kind="workstation")
        d.interfaces.append(Interface(mac=A))
        ses.add(d)
    return Engine(s, db)


def feed(engine, ports=(), addrs=()):
    engine.state.setdefault("t", SourceState("t", "test", 60))
    engine.snapshots["t"] = Snapshot(ports=list(ports), addresses=list(addrs))
    engine._persist(engine.compute())


def hist(engine):
    with engine.db.session() as s:
        return [(h.kind, h.value, h.end is None) for h in s.scalars(select(History).order_by(History.id))]


def test_port_and_ip_periods(engine):
    feed(engine, [PortEntry("core", "Gi7", A)], [AddressEntry(A, "10.0.10.109", "arp")])
    feed(engine, [PortEntry("core", "Gi12", A)], [AddressEntry(A, "10.0.10.109", "arp")])
    assert hist(engine) == [("port", "Gi7", False), ("ip", "10.0.10.109", True), ("port", "Gi12", True)]
    # going offline closes the open periods at the last-seen time
    engine.settings.offline_after = 0
    engine.snapshots.clear()
    with engine.db.session() as s:
        s.get(Sighting, A).last_seen -= 10
    engine._persist(engine.compute())
    assert all(not open_ for _, _, open_ in hist(engine))


def test_scheme_and_busy_port_events_and_device_names(engine):
    feed(engine, [PortEntry("core", "Gi7", A)], [AddressEntry(A, "10.0.10.109", "arp")])
    engine.drain_events()
    others = [PortEntry("core", "Gi2", f"00:00:5E:00:53:{i:02X}") for i in range(0x20, 0x24)]
    feed(engine, [PortEntry("core", "Gi7", A), *others], [AddressEntry(A, "10.0.10.188", "arp")])
    kinds = {e["kind"]: e for e in engine.drain_events()}
    assert "WS09" in kinds["ip_changed"]["message"]
    assert kinds["scheme"]["data"] == {"ip": "10.0.10.188", "expected": "10.0.10.109"}
    assert kinds["busy_port"]["data"]["port"] == "Gi2"
    feed(engine, [PortEntry("core", "Gi7", A), *others], [AddressEntry(A, "10.0.10.188", "arp")])
    assert not any(e["kind"] == "busy_port" for e in engine.drain_events())       # reported once, not every cycle


def ev(kind, msg, device_id=None, mac="00:00:5E:00:53:01"):
    return {"ts": 1_760_000_000, "kind": kind, "mac": mac, "device_id": device_id, "device": None, "message": msg, "data": {}}


def test_webhook_batches_and_filters():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200)

    n = Notifier([{"type": "webhook", "name": "chat", "url": "https://chat.example.org/hook", "events": ["moved", "new"],
                   "only_known": True},
                  {"type": "webhook", "name": "auto", "url": "https://auto.example.org/hook", "format": "json", "events": ["all"]}],
                 public_url="https://deskside.example.org")
    n.transport = httpx.MockTransport(handler)
    n._queue = [ev("moved", "Moved: WS09", device_id=1), ev("new", "New device: 00:00:5E:00:53:99"), ev("offline", "Offline: WS10", 2)]
    asyncio.run(n.flush())
    chat, auto = sent
    assert "Moved: WS09" in chat["text"] and "00:00:5E:00:53:99" not in chat["text"]   # unknown device filtered out
    assert len(auto["events"]) == 3 and auto["summary"].startswith("3 network events")
    assert n.channels[0].state.counts == {"sent": 1, "events": 1}


def test_failing_webhook_keeps_error_and_other_channels_work():
    def handler(request):
        return httpx.Response(500 if "bad" in str(request.url) else 200)

    n = Notifier([{"type": "webhook", "name": "bad", "url": "https://bad.example.org/"},
                  {"type": "webhook", "name": "good", "url": "https://good.example.org/"}])
    n.transport = httpx.MockTransport(handler)
    n._queue = [ev("new", "New device")]
    asyncio.run(n.flush())
    assert "500" in n.channels[0].state.error and n.channels[1].state.error is None


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.tls, self.auth = host, port, False, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.auth = user

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, self.tls, self.auth, msg))


def test_email_with_starttls():
    n = Notifier([{"type": "email", "host": "smtp.example.org", "user": "deskside", "password": "x",
                   "from": "deskside@example.org", "to": ["it@example.org"], "events": ["offline"]}])
    n.smtp_factory = FakeSMTP
    n._queue = [ev("offline", "Offline: WS10"), ev("new", "New device")]
    asyncio.run(n.flush())
    host, port, tls, auth, msg = FakeSMTP.sent[-1]
    assert (host, port, tls, auth) == ("smtp.example.org", 587, True, "deskside")
    assert msg["Subject"] == "[deskside] Offline: WS10" and msg["To"] == "it@example.org"


def test_config_validation_and_digest_cap():
    for bad in ([{"type": "pager"}], [{"type": "webhook"}], [{"type": "webhook", "url": "x", "events": ["typo"]}],
                [{"type": "email", "host": "h", "from": "a"}]):
        with pytest.raises(NotifyError):
            Notifier(bad)
    subject, body = render_text([ev("new", f"New {i}") for i in range(55)], None)
    assert subject == "55 network events: 55 new" and body.endswith("… and 15 more")
