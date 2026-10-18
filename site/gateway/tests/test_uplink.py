import asyncio
import gzip
import json
from dataclasses import replace

import pytest

from model import Reading
from store import Store
from uplink import send_once

BASE = Reading(
    robot_id="rv-1", ts_ms=1000, received_ms=1000, seq=1, battery_pct=80,
    state="working", error=None, x_m=1, y_m=1, heading_rad=0, speed_mps=0.8,
)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.register("rv-1", "rovo")
    for i in range(3):
        s.add(replace(BASE, ts_ms=1000 + i, received_ms=1000 + i))
    s.flush()
    return s


def send(store, publish, limit=100):
    return asyncio.run(send_once(store, publish, "site-1", limit))


def test_confirmed_batch_is_deleted(store):
    sent = []

    async def publish(body):
        sent.append(json.loads(gzip.decompress(body)))

    assert send(store, publish) == 3
    assert store.backlog() == (0, None)
    [batch] = sent
    assert batch["site_id"] == "site-1"
    assert [r["ts_ms"] for r in batch["readings"]] == [1000, 1001, 1002]
    assert batch["robots"][0] | {"last_seen_ms": None} == {"id": "rv-1", "vendor": "rovo", "last_seen_ms": None}
    assert batch["backlog"] == {"readings": 3, "oldest_received_ms": 1000}


def test_failed_delivery_keeps_everything(store):
    async def publish(body):
        raise ConnectionError("broker down")

    with pytest.raises(ConnectionError):
        send(store, publish)
    assert store.backlog()[0] == 3  # all three go out with the next batch


def test_reading_that_arrives_mid_flight_waits_for_the_next_batch(store):
    async def publish(body):
        store.add(replace(BASE, ts_ms=2000, received_ms=2000))  # lands while the batch is in flight
        store.flush()

    assert send(store, publish) == 3
    assert store.backlog() == (1, 2000)


def test_backlog_drains_in_capped_batches(store):
    async def publish(body):
        pass

    assert send(store, publish, limit=2) == 2
    assert send(store, publish, limit=2) == 1
    assert store.backlog() == (0, None)


def test_empty_batch_is_still_sent_as_heartbeat():
    s = Store(":memory:")
    sent = []

    async def publish(body):
        sent.append(json.loads(gzip.decompress(body)))

    assert send(s, publish) == 0
    assert sent[0]["readings"] == [] and sent[0]["site_id"] == "site-1"
