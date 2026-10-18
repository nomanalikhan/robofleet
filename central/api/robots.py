"""Robot routes."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

import health
from db import Db
from models import Robot, RobotPage, RobotStatus, Telemetry

router = APIRouter(prefix="/robots", tags=["robots"])

Period = Literal["hour", "day", "week", "month"]
PERIODS = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}
RAW_UP_TO = timedelta(hours=1)
BUCKETS_S = [60, 300, 1800, 7200, 21600]  # the smallest that keeps a chart near MAX_POINTS wins
MAX_POINTS = 400
MAX_RANGE = timedelta(days=31)  # history is kept 30 days


def bucket_for(span: timedelta) -> int | None:
    """Seconds per point for a range, None for raw readings."""
    if span <= RAW_UP_TO:
        return None
    return next((b for b in BUCKETS_S if span.total_seconds() / b <= MAX_POINTS), BUCKETS_S[-1])


@router.get("")
async def list_robots(
    db: Db,
    site_id: str | None = None,
    status: RobotStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RobotPage:
    """Robots with their newest reading and health, worst problems first."""
    rows = await health.robots(db, site_id=site_id, status=status, limit=limit, offset=offset)
    return RobotPage(items=[Robot(**r) for r in rows], total=rows[0]["total"] if rows else 0)


@router.get("/{robot_id}")
async def get_robot(robot_id: str, db: Db) -> Robot:
    rows = await health.robots(db, robot_id=robot_id)
    if not rows:
        raise HTTPException(404, f"unknown robot {robot_id}")
    return Robot(**rows[0])


@router.get("/{robot_id}/telemetry")
async def get_telemetry(
    robot_id: str,
    db: Db,
    period: Period | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> Telemetry:
    """Chart data for one robot. Use `period` for the last hour, day, week or
    month, or `from` and `to` for any range up to 31 days. Defaults to the last
    15 minutes. Up to an hour returns raw readings, longer ranges are averaged
    into buckets so a chart stays around 400 points."""
    end = end or datetime.now(UTC)
    start = start or end - (PERIODS[period] if period else timedelta(minutes=15))
    if not timedelta(0) < end - start <= MAX_RANGE:
        raise HTTPException(422, f"range must be positive and at most {MAX_RANGE.days} days")
    if not await db.fetchval("SELECT 1 FROM robots WHERE id = $1", robot_id):
        raise HTTPException(404, f"unknown robot {robot_id}")

    bucket_s = bucket_for(end - start)
    if bucket_s is None:
        rows = await db.fetch("""
            SELECT ts, battery_pct, state, error, x_m, y_m
            FROM robot_telemetry
            WHERE robot_id = $1 AND ts BETWEEN $2 AND $3
            ORDER BY ts
        """, robot_id, start, end)
    else:
        rows = await db.fetch("""
            SELECT time_bucket($4 * INTERVAL '1 second', ts) AS ts,
                   avg(battery_pct) AS battery_pct,
                   last(state, ts) AS state,
                   last(error, ts) AS error,
                   avg(x_m) AS x_m,
                   avg(y_m) AS y_m
            FROM robot_telemetry
            WHERE robot_id = $1 AND ts BETWEEN $2 AND $3
            GROUP BY 1
            ORDER BY 1
        """, robot_id, start, end, bucket_s)
    return Telemetry(bucket_s=bucket_s, points=[dict(r) for r in rows])
