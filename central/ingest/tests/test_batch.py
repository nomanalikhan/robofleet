import gzip
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest

from batch import Error, State, parse

READING = {
    "robot_id": "rv-1", "ts_ms": 1760700000123, "received_ms": 1760700000200, "seq": 7,
    "battery_pct": 80.0, "state": "working", "error": None,
    "x_m": 1.5, "y_m": 2.5, "heading_rad": 0.5, "speed_mps": 0.8,
}


def batch(readings=(READING,), **extra) -> bytes:
    body = {
        "site_id": "site-1",
        "sent_ms": 1760700000300,
        "backlog": {"readings": 0, "oldest_received_ms": None},
        "robots": [{"id": "rv-1", "vendor": "rovo", "last_seen_ms": 1760700000200}],
        "readings": list(readings),
    } | extra
    return gzip.compress(json.dumps(body).encode())


def test_gateway_batch_parses_with_utc_times():
    b = parse(batch())
    assert (b.site_id, b.robots[0].vendor, b.backlog.readings) == ("site-1", "rovo", 0)
    assert b.readings[0].ts == datetime(2025, 10, 17, 11, 20, 0, 123000, tzinfo=UTC)
    assert b.sent.tzinfo == UTC


def test_reading_fields_follow_the_table_column_order():
    assert list(parse(batch()).readings[0].model_dump()) == [
        "robot_id", "ts", "received_at", "seq", "battery_pct", "state", "error",
        "x_m", "y_m", "heading_rad", "speed_mps",
    ]


def test_empty_heartbeat_batch_parses():
    assert parse(batch(readings=())).readings == []


def test_unknown_fields_are_ignored():
    assert parse(batch(firmware="2.1")).site_id == "site-1"


@pytest.mark.parametrize(
    "body, error",
    [
        (b"not gzip", OSError),
        (gzip.compress(b"x" * 100)[:-8], EOFError),  # cut off in transit
        (gzip.compress(b"{not json"), ValueError),
        (gzip.compress(json.dumps({"site_id": "site-1"}).encode()), ValueError),
        (batch(readings=[READING | {"state": "dancing"}]), ValueError),
        (batch(readings=[READING | {"robot_id": "ghost"}]), ValueError),
    ],
)
def test_unreadable_batches_raise_what_ingest_rejects(body, error):
    with pytest.raises(error):
        parse(body)


def test_state_and_error_values_match_the_schema():
    schema = (Path(__file__).parents[1] / "schema.sql").read_text()

    def check(column):
        return set(re.findall(r"'(\w+)'", re.search(rf"{column} .*?CHECK \((.*?)\)\)", schema).group(1)))

    assert check("state") == set(get_args(State))
    assert check("error") == set(get_args(Error))
