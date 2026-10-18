"""TimescaleDB access. One transaction per batch."""

from pathlib import Path

import asyncpg

from batch import Batch

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


async def connect(database_url: str) -> asyncpg.Connection:
    con = await asyncpg.connect(database_url)
    await con.execute(SCHEMA)
    return con


async def save(con: asyncpg.Connection, batch: Batch) -> int:
    """Returns how many readings were new."""
    async with con.transaction():
        # Only a newer batch moves the heartbeat, so a late or redelivered one
        # cannot make a site look fresher or further behind than it is.
        await con.execute("""
            INSERT INTO sites (id, last_sent_at, backlog_readings, backlog_oldest_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE
            SET last_sent_at = excluded.last_sent_at,
                backlog_readings = excluded.backlog_readings,
                backlog_oldest_at = excluded.backlog_oldest_at
            WHERE sites.last_sent_at < excluded.last_sent_at
        """, batch.site_id, batch.sent, batch.backlog.readings, batch.backlog.oldest_received)

        await con.execute("""
            INSERT INTO robots (id, site_id, vendor)
            SELECT id, $2, vendor
            FROM unnest($1::text[], $3::text[]) AS r (id, vendor)
            ON CONFLICT (id) DO UPDATE
            SET site_id = excluded.site_id,
                vendor = excluded.vendor
            WHERE (robots.site_id, robots.vendor) IS DISTINCT FROM (excluded.site_id, excluded.vendor)
        """, [r.id for r in batch.robots], batch.site_id, [r.vendor for r in batch.robots])

        status = await con.execute("""
            INSERT INTO robot_telemetry
            SELECT *
            FROM unnest($1::robot_telemetry[])
            ON CONFLICT (robot_id, ts) DO NOTHING
        """, [tuple(r.model_dump().values()) for r in batch.readings])
    return int(status.split()[-1])  # "INSERT 0 <rows>"
