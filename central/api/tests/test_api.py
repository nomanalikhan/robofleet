"""Runs the API against a throwaway database in the compose TimescaleDB, because
the health rules are SQL and only a real database proves them. See make test-api."""

import asyncio
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

import asyncpg
import pytest
from fastapi.testclient import TestClient

from models import Error, State
from robots import bucket_for

ADMIN_URL = os.environ["TEST_ADMIN_URL"]  # any database on the server, used to create fleet_test
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + "/fleet_test"
SCHEMA = (Path(__file__).parents[2] / "ingest" / "schema.sql").read_text()

# One robot per health case. Readings are 1s apart, the newest `newest` seconds ago.
# site-3 is draining a 10 minute backlog, so its robot's newest delivered reading
# is 10 minutes old by central's clock but current by what the site has sent.
FIXTURES = """
INSERT INTO sites (id, last_sent_at, backlog_readings, backlog_oldest_at) VALUES
    ('site-1', now(), 0, NULL),
    ('site-2', now() - INTERVAL '5 minutes', 0, NULL),
    ('site-3', now(), 6000, now() - INTERVAL '10 minutes');

INSERT INTO robots (id, site_id, vendor) VALUES
    ('rv-ok', 'site-1', 'rovo'), ('rv-low', 'site-1', 'rovo'), ('rv-err', 'site-1', 'rovo'),
    ('rv-stuck', 'site-1', 'rovo'), ('rv-off', 'site-1', 'rovo'), ('cx-new', 'site-1', 'cleanix'),
    ('rv-dock', 'site-1', 'rovo'), ('cx-dark', 'site-2', 'cleanix'), ('rv-lag', 'site-3', 'rovo');

INSERT INTO robot_telemetry (robot_id, ts, received_at, battery_pct, state, error, x_m, y_m, heading_rad)
SELECT robot_id, now() - (newest + i) * INTERVAL '1 second', now() - (newest + i) * INTERVAL '1 second',
       battery, state, error, x + i * step, 5, 0
FROM (VALUES
    ('rv-ok',    0,   80, 'working',  NULL,         0, 0.5),
    ('rv-low',   0,   10, 'idle',     NULL,         0, 0),
    ('rv-dock',  0,   10, 'charging', NULL,         1, 0),
    ('rv-err',   0,   50, 'error',    'bumper_hit', 0, 0),
    ('rv-stuck', 0,   60, 'working',  NULL,         3, 0),
    ('rv-off',   120, 70, 'working',  NULL,         0, 0.5),
    ('cx-dark',  0,   90, 'working',  NULL,         0, 0.5),
    ('rv-lag',   610, 70, 'working',  NULL,         0, 0.5)
) AS f (robot_id, newest, battery, state, error, x, step),
generate_series(0, 39) AS i;

-- An hour of older history for the averaged telemetry view.
INSERT INTO robot_telemetry (robot_id, ts, received_at, battery_pct, state, x_m, y_m, heading_rad)
SELECT 'rv-ok', now() - INTERVAL '2 hours' + i * INTERVAL '1 minute', now() - INTERVAL '2 hours',
       90, 'working', 1, 1, 0
FROM generate_series(0, 59) AS i;
"""


async def reset_database() -> None:
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute("DROP DATABASE IF EXISTS fleet_test WITH (FORCE)")
    await admin.execute("CREATE DATABASE fleet_test")
    await admin.close()
    con = await asyncpg.connect(TEST_URL)
    await con.execute(SCHEMA)
    await con.execute(FIXTURES)
    await con.close()


@pytest.fixture(scope="module")
def client():
    asyncio.run(reset_database())
    os.environ["DATABASE_URL"] = TEST_URL
    from main import app

    with TestClient(app) as c:
        yield c


def robots(client, **params):
    return client.get("/api/v1/robots", params=params).json()


def test_health_rules_worst_first(client):
    assert [(r["id"], r["status"]) for r in robots(client)["items"]] == [
        ("cx-dark", "unknown"),  # its site went quiet, so nothing about it is known
        ("cx-new", "offline"),  # discovered, never heard from
        ("rv-off", "offline"),
        ("rv-err", "error"),
        ("rv-stuck", "stuck"),
        ("rv-low", "low_battery"),
        ("rv-dock", "ok"),  # low but already charging
        ("rv-lag", "ok"),  # behind only because its site is catching up
        ("rv-ok", "ok"),
    ]


def test_robot_carries_its_newest_reading(client):
    r = client.get("/api/v1/robots/rv-err").json()
    assert (r["state"], r["error"], r["problems"]) == ("error", "bumper_hit", ["error"])
    assert r["last_seen_s"] < 5


def test_filters_and_pagination(client):
    assert robots(client, site_id="site-2")["total"] == 1
    assert [r["id"] for r in robots(client, status="offline")["items"]] == ["cx-new", "rv-off"]
    page = robots(client, limit=2, offset=2)
    assert page["total"] == 9
    assert [r["id"] for r in page["items"]] == ["rv-off", "rv-err"]


def test_sites(client):
    sites = {s["id"]: s for s in client.get("/api/v1/sites").json()}
    assert {i: s["status"] for i, s in sites.items()} == {"site-1": "online", "site-2": "offline", "site-3": "degraded"}
    site = client.get("/api/v1/sites/site-1").json()
    assert site["robots_by_status"] == {"unknown": 0, "offline": 2, "error": 1, "stuck": 1, "low_battery": 1, "ok": 2}
    assert site["robots_by_vendor"] == {"rovo": 6, "cleanix": 1}


def telemetry(client, **params):
    return client.get("/api/v1/robots/rv-ok/telemetry", params=params).json()


def test_robot_filters_by_vendor_and_search(client):
    assert [r["id"] for r in robots(client, vendor="cleanix")["items"]] == ["cx-dark", "cx-new"]
    assert [r["id"] for r in robots(client, q="DOCK")["items"]] == ["rv-dock"]


def test_robot_filters_take_several_values(client):
    assert robots(client, site_id=["site-2", "site-3"])["total"] == 2
    assert [r["id"] for r in robots(client, status=["error", "stuck"])["items"]] == ["rv-err", "rv-stuck"]


def test_site_activity_counts_robots_by_state(client):
    a = client.get("/api/v1/sites/site-1/activity", params={"period": "hour"}).json()
    assert a["bucket_s"] == 60
    last = a["points"][-1]  # the newest minute, every site-1 robot with recent readings
    assert (last["working"], last["idle"], last["charging"], last["error"]) == (2, 1, 1, 1)
    day = client.get("/api/v1/sites/site-1/activity", params={"period": "day"}).json()
    assert day["bucket_s"] == 300
    assert client.get("/api/v1/sites/nowhere/activity").status_code == 404


def test_telemetry_is_raw_for_short_ranges(client):
    t = telemetry(client)
    assert (t["bucket_s"], len(t["points"])) == (None, 40)


@pytest.mark.parametrize("period, bucket_s", [("hour", None), ("day", 300), ("week", 1800), ("month", 7200)])
def test_telemetry_periods_pick_their_bucket(client, period, bucket_s):
    assert telemetry(client, period=period)["bucket_s"] == bucket_s


def test_day_view_averages_into_five_minute_points(client):
    points = telemetry(client, period="day")["points"]
    assert 12 <= len(points) <= 14  # an hour of history in 12 buckets plus the recent readings
    assert points[0]["battery_pct"] == 90


def test_buckets_keep_errors_that_cleared_before_they_end(client):
    points = client.get("/api/v1/robots/rv-err/telemetry", params={"period": "day"}).json()["points"]
    assert points[-1]["error"] == "bumper_hit"


def test_custom_range_gets_a_bucket_too(client):
    now = datetime.now(UTC)
    t = telemetry(client, **{"from": (now - timedelta(hours=3)).isoformat(), "to": now.isoformat()})
    assert t["bucket_s"] == 60
    assert 60 <= len(t["points"]) <= 62


@pytest.mark.parametrize(
    "hours, bucket_s",
    [(1, None), (2, 60), (24, 300), (24 * 7, 1800), (24 * 30, 7200), (24 * 31, 7200)],
)
def test_bucket_ladder(hours, bucket_s):
    assert bucket_for(timedelta(hours=hours)) == bucket_s


def test_unknown_things_are_404(client):
    assert client.get("/api/v1/sites/nowhere").status_code == 404
    assert client.get("/api/v1/robots/nobody").status_code == 404
    assert client.get("/api/v1/robots/nobody/telemetry").status_code == 404


def test_bad_parameters_are_422(client):
    assert client.get("/api/v1/robots", params={"status": "sleepy"}).status_code == 422
    assert client.get("/api/v1/robots", params={"limit": 0}).status_code == 422
    now = datetime.now(UTC)
    empty = {"from": now.isoformat(), "to": now.isoformat()}
    assert client.get("/api/v1/robots/rv-ok/telemetry", params=empty).status_code == 422
    too_long = {"from": (now - timedelta(days=40)).isoformat(), "to": now.isoformat()}
    assert client.get("/api/v1/robots/rv-ok/telemetry", params=too_long).status_code == 422
    assert client.get("/api/v1/robots/rv-ok/telemetry", params={"period": "year"}).status_code == 422


def test_state_and_error_values_match_the_schema():
    def check(column):
        return set(re.findall(r"'(\w+)'", re.search(rf"{column} .*?CHECK \((.*?)\)\)", SCHEMA).group(1)))

    assert check("state") == set(get_args(State))
    assert check("error") == set(get_args(Error))
