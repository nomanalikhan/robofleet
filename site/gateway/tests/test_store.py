import sqlite3
from dataclasses import replace

import pytest

from model import Reading
from store import Store, now_ms

BASE = Reading(
    robot_id="rv-1", ts_ms=1000, received_ms=1000, seq=1, battery_pct=80,
    state="working", error=None, x_m=1, y_m=1, heading_rad=0, speed_mps=0.8,
)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.register("rv-1", "rovo")
    return s


def count(store):
    return store.db.execute("""
        SELECT count(*)
        FROM robot_telemetry
    """).fetchone()[0]


def test_same_reading_twice_is_stored_once(store):
    store.add(BASE)
    store.add(BASE)  # a Cleanix poll can return the snapshot it returned before
    assert store.flush() == 1
    store.add(BASE)
    assert store.flush() == 0
    assert count(store) == 1


def test_readings_need_a_registered_robot(store):
    store.add(replace(BASE, robot_id="ghost"))
    with pytest.raises(sqlite3.IntegrityError):
        store.flush()


def test_unsent_is_oldest_arrival_first_and_capped(store):
    store.add(replace(BASE, ts_ms=3000, received_ms=30))
    store.add(replace(BASE, ts_ms=1000, received_ms=10))  # measured earlier, arrived first
    store.add(replace(BASE, ts_ms=2000, received_ms=20))
    store.flush()
    assert [r["ts_ms"] for r in store.unsent(limit=2)] == [1000, 2000]


def test_delivered_deletes_only_the_confirmed_keys(store):
    store.add(replace(BASE, ts_ms=1000))
    store.add(replace(BASE, ts_ms=2000))
    store.flush()
    store.delivered([("rv-1", 1000)])
    assert [r["ts_ms"] for r in store.unsent(limit=10)] == [2000]


def test_backlog_counts_waiting_readings(store):
    assert store.backlog() == (0, None)
    store.add(replace(BASE, ts_ms=1000, received_ms=500))
    store.add(replace(BASE, ts_ms=2000, received_ms=700))
    store.flush()
    assert store.backlog() == (2, 500)


def test_prune_drops_only_readings_past_the_cap(store):
    now = now_ms()
    store.add(replace(BASE, ts_ms=1, received_ms=now - 25 * 3_600_000))  # waited 25h
    store.add(replace(BASE, ts_ms=2, received_ms=now))
    store.flush()
    assert store.prune(retention_hours=24) == 1
    assert [r["ts_ms"] for r in store.unsent(limit=10)] == [2]


def test_register_reports_first_sighting_only(store):
    assert store.register("cx-1", "cleanix", "10.0.0.5")
    assert not store.register("cx-1", "cleanix")


def test_register_updates_a_moved_robot(store):
    def ip():
        return store.db.execute("""
            SELECT ip
            FROM robots
            WHERE id = 'cx-1'
        """).fetchone()[0]

    store.register("cx-1", "cleanix", "10.0.0.5")
    assert not store.register("cx-1", "cleanix", "10.0.0.9")
    assert ip() == "10.0.0.9"
    store.register("cx-1", "cleanix")  # no IP keeps the last one
    assert ip() == "10.0.0.9"
