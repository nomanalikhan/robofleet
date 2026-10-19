"""Health rules, derived on every request from the newest readings and each
site's last batch. Nothing is stored.

Liveness is measured on the gateway clock against what the site has delivered,
so batching, a draining backlog and site to central clock skew never make a
healthy robot look offline.
"""

from typing import get_args

import asyncpg

from models import RobotStatus

OFFLINE_S = 30  # site sent no batch, or robot sent no reading, for this long
LOW_BATTERY_PCT = 20  # below this, unless charging
STUCK_S = 30  # working this long while moving under STUCK_M is stuck
STUCK_M = 0.5
SEVERITY = list(get_args(RobotStatus))  # worst first

SITES = """
    SELECT id, last_sent_at, backlog_readings, backlog_oldest_at,
           CASE
               WHEN now() - last_sent_at > $1 * INTERVAL '1 second' THEN 'offline'
               WHEN backlog_readings > 0 THEN 'degraded'
               ELSE 'online'
           END AS status
    FROM sites
    WHERE $2::text IS NULL OR id = $2
    ORDER BY id
"""

ROBOTS = """
    SELECT r.id, r.site_id, r.vendor, t.state, t.error, t.battery_pct, t.x_m, t.y_m,
           -- greatest() skips nulls, so a never heard from robot must stay null itself.
           CASE WHEN t.received_at IS NOT NULL
                THEN greatest(0, extract(epoch FROM delivered - t.received_at))::real END AS last_seen_s,
           h.status, h.problems, count(*) OVER () AS total
    FROM robots r
    JOIN sites s ON s.id = r.site_id
    -- The site has delivered everything up to its oldest waiting reading, or
    -- up to its last batch when nothing waits.
    CROSS JOIN LATERAL (SELECT coalesce(s.backlog_oldest_at, s.last_sent_at) AS delivered) d
    LEFT JOIN LATERAL (
        SELECT *
        FROM robot_telemetry
        WHERE robot_id = r.id
        ORDER BY ts DESC
        LIMIT 1
    ) t ON true
    -- Stuck uses the robot's own clock and needs readings covering most of the window.
    LEFT JOIN LATERAL (
        SELECT bool_and(state = 'working')
               AND max(ts) - min(ts) >= 0.8 * $3 * INTERVAL '1 second'
               AND sqrt(power(max(x_m) - min(x_m), 2) + power(max(y_m) - min(y_m), 2)) < $4 AS stuck
        FROM robot_telemetry
        WHERE t.state = 'working'
          AND robot_id = r.id AND ts BETWEEN t.ts - $3 * INTERVAL '1 second' AND t.ts
    ) w ON true
    -- A dark site makes its robots unknown, one site alert instead of one per
    -- robot. An offline robot's reading is stale, so it gets no other problems.
    CROSS JOIN LATERAL (
        SELECT CASE
                   WHEN now() - s.last_sent_at > $1 * INTERVAL '1 second' THEN ARRAY['unknown']
                   WHEN t.received_at IS NULL OR delivered - t.received_at > $1 * INTERVAL '1 second'
                       THEN ARRAY['offline']
                   ELSE array_remove(ARRAY[
                       CASE WHEN t.state = 'error' THEN 'error' END,
                       CASE WHEN w.stuck THEN 'stuck' END,
                       CASE WHEN t.battery_pct < $2 AND t.state <> 'charging' THEN 'low_battery' END
                   ], NULL)
               END AS problems
    ) p
    CROSS JOIN LATERAL (SELECT p.problems, coalesce(p.problems[1], 'ok') AS status) h
    WHERE ($6::text[] IS NULL OR r.site_id = ANY($6))
      AND ($7::text IS NULL OR r.id = $7)
      AND ($8::text[] IS NULL OR h.status = ANY($8))
      AND ($9::text[] IS NULL OR r.vendor = ANY($9))
      AND ($10::text IS NULL OR strpos(lower(r.id), lower($10)) > 0)
    ORDER BY array_position($5::text[], h.status), r.id
    LIMIT $11 OFFSET $12
"""


async def sites(db: asyncpg.Pool, site_id: str | None = None) -> list[asyncpg.Record]:
    return await db.fetch(SITES, OFFLINE_S, site_id)


async def robots(
    db: asyncpg.Pool,
    site_ids: list[str] | None = None,
    robot_id: str | None = None,
    statuses: list[str] | None = None,
    vendors: list[str] | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[asyncpg.Record]:
    return await db.fetch(
        ROBOTS, OFFLINE_S, LOW_BATTERY_PCT, STUCK_S, STUCK_M, SEVERITY,
        site_ids, robot_id, statuses, vendors, q, limit, offset,
    )
