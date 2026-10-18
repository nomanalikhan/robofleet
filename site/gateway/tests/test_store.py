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


def count(store, unsent_only=False):
    return store.db.execute("""
        SELECT count(*)
        FROM robot_telemetry
        WHERE uploaded = 0 OR NOT ?
    """, (unsent_only,)).fetchone()[0]


def latest_battery(store):
    [(battery,)] = store.db.execute("""
        SELECT battery_pct
        FROM latest
        WHERE robot_id = 'rv-1'
    """)
    return battery


def test_late_reading_goes_to_history_but_not_latest(store):
    store.add(replace(BASE, ts_ms=2000, battery_pct=70))
    store.flush()
    store.add(replace(BASE, ts_ms=1000, battery_pct=80))  # arrives late
    store.flush()
    assert latest_battery(store) == 70
    assert count(store) == 2


def test_out_of_order_within_one_batch(store):
    store.add(replace(BASE, ts_ms=3000, battery_pct=60))
    store.add(replace(BASE, ts_ms=2000, battery_pct=70))
    store.flush()
    assert latest_battery(store) == 60


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


def test_prune_keeps_each_robots_newest_reading(store):
    store.add(replace(BASE, ts_ms=1000, received_ms=1000))
    store.add(replace(BASE, ts_ms=2000, received_ms=2000, battery_pct=70))
    store.flush()
    assert store.prune(uploaded_keep_s=0, retention_hours=0) == 1  # all old, the newest survives
    assert latest_battery(store) == 70
    assert count(store) == 1


def test_unsent_history_waits_for_upload(store):
    now = now_ms()
    for i in range(3):
        store.add(replace(BASE, ts_ms=now - 5000 + i, received_ms=now - 5000 + i))  # arrived 5s ago
    store.flush()
    assert count(store, unsent_only=True) == 3  # new rows start unsent
    assert store.prune(uploaded_keep_s=0, retention_hours=24) == 0  # nothing confirmed yet
    store.db.execute("""
        UPDATE robot_telemetry
        SET uploaded = 1
    """)
    assert store.prune(uploaded_keep_s=0, retention_hours=24) == 2  # confirmed, newest kept


def test_unsent_lookup_uses_the_partial_index(store):
    plan = store.db.execute("""
        EXPLAIN QUERY PLAN
        SELECT *
        FROM robot_telemetry
        WHERE uploaded = 0
        ORDER BY received_ms
    """).fetchall()
    assert any("robot_telemetry_unsent" in row[3] for row in plan)


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
