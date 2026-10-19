"""Merge rules of the engine, with made-up snapshots."""

import time

import pytest

from deskside.config import Settings
from deskside.db import Database, EventLog, Sighting
from deskside.engine import Engine
from deskside.sources import AddressEntry, Neighbor, PortEntry, Snapshot


@pytest.fixture
def engine(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path}/t.db", secret_key="x" * 32, uplink_mac_threshold=3)
    s.raw = {"dns": {"reverse": False}}
    db = Database(s.database_url)
    db.create_schema()
    return Engine(s, db)


def _feed(engine, name, snap, interval=60):
    from deskside.engine import SourceState
    engine.state.setdefault(name, SourceState(name, "test", interval))
    engine.snapshots[name] = snap


A, B, C = "00:11:22:00:00:0A", "00:11:22:00:00:0B", "00:11:22:00:00:0C"


def test_access_port_beats_uplink(engine):
    # A is learned on the core uplink (towards the edge switch) and on the edge access port.
    _feed(engine, "core", Snapshot(ports=[PortEntry("core", "Gi1", A)], neighbors=[Neighbor("core", "Gi1", "edge")]))
    _feed(engine, "edge", Snapshot(ports=[PortEntry("edge", "Gi5", A)]))
    o = engine.compute()[A]
    assert (o.switch, o.port, o.behind_uplink, o.live) == ("edge", "Gi5", False, True)


def test_busy_port_is_flagged(engine):
    _feed(engine, "core", Snapshot(ports=[PortEntry("core", "Gi2", m) for m in (A, B, C, "00:11:22:00:00:0D")]))
    obs = engine.compute()
    assert obs[A].behind_uplink is True
    assert engine.suspect_ports == {("core", "Gi2"): 4}


def test_arp_ip_wins_and_lease_alone_is_not_online(engine):
    _feed(engine, "dhcp", Snapshot(addresses=[AddressEntry(A, "10.0.0.50", "dhcp", "ws01", True),
                                              AddressEntry(B, "10.0.0.51", "dhcp", "ws02", True)]))
    _feed(engine, "arp", Snapshot(addresses=[AddressEntry(A, "10.0.0.60", "arp")]))
    obs = engine.compute()
    assert obs[A].ip == "10.0.0.60" and obs[A].live is True
    assert obs[A].hostname is None          # the lease name belongs to the old address
    assert obs[B].ip == "10.0.0.51" and obs[B].hostname == "ws02" and obs[B].live is False


def test_stale_snapshot_is_ignored(engine):
    snap = Snapshot(ports=[PortEntry("core", "Gi3", A)])
    snap.taken_at = time.time() - 10_000
    _feed(engine, "core", snap)
    assert engine.compute() == {}


def test_events_after_first_run(engine):
    _feed(engine, "core", Snapshot(ports=[PortEntry("core", "Gi3", A)]))
    engine._persist(engine.compute())                       # first run: no per-device events
    _feed(engine, "core", Snapshot(ports=[PortEntry("core", "Gi4", A), PortEntry("core", "Gi9", B)]))
    engine._persist(engine.compute())
    with engine.db.session() as s:
        kinds = sorted(e.kind for e in s.query(EventLog))
        assert kinds == ["discovery", "moved", "new"]
        assert s.get(Sighting, A).port == "Gi4"


def test_offline_after_threshold(engine):
    engine.settings.offline_after = 0
    _feed(engine, "core", Snapshot(ports=[PortEntry("core", "Gi3", A)]))
    engine._persist(engine.compute())
    engine.snapshots.clear()
    with engine.db.session() as s:
        s.get(Sighting, A).last_seen -= 5
    engine._persist(engine.compute())
    with engine.db.session() as s:
        assert s.get(Sighting, A).online is False
        assert any(e.kind == "offline" for e in s.query(EventLog))
