"""Site routes."""

from collections import Counter
from datetime import UTC, datetime
from typing import get_args

import asyncpg
from fastapi import APIRouter, HTTPException

import health
from db import Db
from models import RobotStatus, Site, SiteActivity
from periods import PERIODS, Period, bucket_for

router = APIRouter(prefix="/sites", tags=["sites"])


async def site_list(db: asyncpg.Pool, site_id: str | None = None) -> list[Site]:
    robots = await health.robots(db, site_id=site_id)
    statuses = Counter((r["site_id"], r["status"]) for r in robots)
    vendors = Counter((r["site_id"], r["vendor"]) for r in robots)
    return [
        Site(
            **s,
            robots_by_status={st: statuses[s["id"], st] for st in get_args(RobotStatus)},
            robots_by_vendor={v: n for (site, v), n in vendors.items() if site == s["id"]},
        )
        for s in await health.sites(db, site_id)
    ]


@router.get("")
async def list_sites(db: Db) -> list[Site]:
    return await site_list(db)


@router.get("/{site_id}")
async def get_site(site_id: str, db: Db) -> Site:
    sites = await site_list(db, site_id)
    if not sites:
        raise HTTPException(404, f"unknown site {site_id}")
    return sites[0]


@router.get("/{site_id}/activity")
async def get_activity(site_id: str, db: Db, period: Period = "hour") -> SiteActivity:
    """What the site's robots were doing over the last hour, day, week or month:
    how many were in each state per bucket, and their average battery."""
    bucket_s = bucket_for(PERIODS[period]) or 60  # per second counts are noise
    rows = await db.fetch("""
        WITH per_robot AS (
            SELECT time_bucket($3 * INTERVAL '1 second', t.ts) AS ts,
                   t.robot_id,
                   last(t.state, t.ts) AS state,
                   avg(t.battery_pct) AS battery_pct
            FROM robot_telemetry t
            JOIN robots r ON r.id = t.robot_id
            WHERE r.site_id = $1 AND t.ts > $2
            GROUP BY 1, 2
        )
        SELECT ts,
               avg(battery_pct) AS battery_pct,
               count(*) FILTER (WHERE state = 'idle') AS idle,
               count(*) FILTER (WHERE state = 'working') AS working,
               count(*) FILTER (WHERE state = 'returning') AS returning,
               count(*) FILTER (WHERE state = 'charging') AS charging,
               count(*) FILTER (WHERE state = 'paused') AS paused,
               count(*) FILTER (WHERE state = 'error') AS error
        FROM per_robot
        GROUP BY ts
        ORDER BY ts
    """, site_id, datetime.now(UTC) - PERIODS[period], bucket_s)
    if not rows and not await db.fetchval("SELECT 1 FROM sites WHERE id = $1", site_id):
        raise HTTPException(404, f"unknown site {site_id}")
    return SiteActivity(bucket_s=bucket_s, points=[dict(r) for r in rows])
