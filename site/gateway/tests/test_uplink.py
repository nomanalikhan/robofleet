import asyncio
import gzip
import json
from dataclasses import replace

import pytest

from store import Store
from uplink import send_once


@pytest.fixture
def store(base):
    s = Store(":memory:")
    s.register("rv-1", "rovo")
    for i in range(3):
        s.add(replace(base, ts_ms=1000 + i, received_ms=1000 + i))
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
    assert batch["backlog"] == {"readings": 0, "oldest_received_ms": None}  # nothing left behind it


def test_failed_delivery_keeps_everything(store):
    async def publish(body):
        raise ConnectionError("broker down")

    with pytest.raises(ConnectionError):
        send(store, publish)
    assert store.backlog()[0] == 3  # all three go out with the next batch


def test_reading_that_arrives_mid_flight_waits_for_the_next_batch(store, base):
    async def publish(body):
        store.add(replace(base, ts_ms=2000, received_ms=2000))  # lands while the batch is in flight
        store.flush()

    assert send(store, publish) == 3
    assert store.backlog() == (1, 2000)


def test_backlog_drains_in_capped_batches(store):
    sent = []

    async def publish(body):
        sent.append(json.loads(gzip.decompress(body))["backlog"])

    assert send(store, publish, limit=2) == 2
    assert sent[0] == {"readings": 1, "oldest_received_ms": 1002}  # one reading waits for the next batch
    assert send(store, publish, limit=2) == 1
    assert store.backlog() == (0, None)


def test_empty_batch_is_still_sent_as_heartbeat():
    s = Store(":memory:")
    sent = []

    async def publish(body):
        sent.append(json.loads(gzip.decompress(body)))

    assert send(s, publish) == 0
    assert sent[0]["readings"] == [] and sent[0]["site_id"] == "site-1"
