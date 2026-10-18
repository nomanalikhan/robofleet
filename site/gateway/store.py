"""Local SQLite storage.

robot_telemetry only holds readings that central has not confirmed yet. The
uplink deletes rows as soon as RabbitMQ confirms them, so in normal operation
it holds about one batch. During an outage it is the store and forward buffer.

Everything runs on the event loop thread, so one connection and no locks.
Readings are buffered and written in one transaction per flush, because a
commit per row would not keep up with hundreds of robots at 1 Hz.
"""

import sqlite3
import time
from dataclasses import asdict

from model import Reading

SCHEMA = """
-- Every robot discovered on this site. The vendor lives here only.
CREATE TABLE IF NOT EXISTS robots (
    id         TEXT PRIMARY KEY,   -- serial, e.g. cx-260723
    vendor     TEXT NOT NULL,
    ip         TEXT,               -- NULL for vendors reached through a broker
    first_seen INTEGER NOT NULL,   -- gateway clock, epoch ms
    last_seen  INTEGER NOT NULL    -- gateway clock, epoch ms
);

-- Readings not yet delivered to central, in the canonical format. The key
-- drops the same reading arriving twice before it is sent.
CREATE TABLE IF NOT EXISTS robot_telemetry (
    robot_id    TEXT NOT NULL REFERENCES robots (id),
    ts_ms       INTEGER NOT NULL,  -- robot clock, when it was measured
    received_ms INTEGER NOT NULL,  -- gateway clock, when it arrived
    seq         INTEGER,
    battery_pct REAL NOT NULL,
    state       TEXT NOT NULL,
    error       TEXT,
    x_m         REAL NOT NULL,
    y_m         REAL NOT NULL,
    heading_rad REAL NOT NULL,
    speed_mps   REAL,
    PRIMARY KEY (robot_id, ts_ms)
) WITHOUT ROWID;

-- The uplink sends oldest arrival first, which matters when a backlog drains.
CREATE INDEX IF NOT EXISTS robot_telemetry_arrival ON robot_telemetry (received_ms);
"""


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.pending: list[Reading] = []
        # robot_id -> ip, so a robot that is seen again costs no write
        self.known = dict(self.db.execute("""
            SELECT id, ip
            FROM robots
        """))

    def register(self, robot_id: str, vendor: str, ip: str | None = None) -> bool:
        """Record a discovered robot. Returns True the first time it is seen.

        A known robot that turns up at a new IP (restart or DHCP renewal) gets
        its IP updated, because commands go there.
        """
        if robot_id in self.known:
            if ip and ip != self.known[robot_id]:
                self.known[robot_id] = ip
                with self.db:
                    self.db.execute("""
                        UPDATE robots
                        SET ip = ?
                        WHERE id = ?
                    """, (ip, robot_id))
            return False
        self.known[robot_id] = ip
        t = now_ms()
        with self.db:
            self.db.execute("""
                INSERT INTO robots (id, vendor, ip, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            """, (robot_id, vendor, ip, t, t))
        return True

    def add(self, reading: Reading) -> None:
        self.pending.append(reading)

    def flush(self) -> int:
        """Write buffered readings in one transaction. Returns how many were new."""
        if not self.pending:
            return 0
        rows = [asdict(r) for r in self.pending]
        last_seen = {r.robot_id: r.received_ms for r in self.pending}
        self.pending = []
        with self.db:
            before = self.db.total_changes
            self.db.executemany("""
                INSERT OR IGNORE INTO robot_telemetry (
                    robot_id, ts_ms, received_ms, seq, battery_pct, state, error,
                    x_m, y_m, heading_rad, speed_mps
                ) VALUES (
                    :robot_id, :ts_ms, :received_ms, :seq, :battery_pct, :state, :error,
                    :x_m, :y_m, :heading_rad, :speed_mps
                )
            """, rows)
            inserted = self.db.total_changes - before
            self.db.executemany("""
                UPDATE robots
                SET last_seen = max(last_seen, ?)
                WHERE id = ?
            """, [(t, rid) for rid, t in last_seen.items()])
        return inserted

    def unsent(self, limit: int) -> list[dict]:
        """The oldest readings central has not confirmed yet, oldest arrival first."""
        cur = self.db.execute("""
            SELECT robot_id, ts_ms, received_ms, seq, battery_pct, state, error,
                   x_m, y_m, heading_rad, speed_mps
            FROM robot_telemetry
            ORDER BY received_ms
            LIMIT ?
        """, (limit,))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur]

    def backlog(self) -> tuple[int, int | None]:
        """How many readings wait for delivery, and when the oldest arrived."""
        return self.db.execute("""
            SELECT count(*), min(received_ms)
            FROM robot_telemetry
        """).fetchone()

    def robots(self) -> list[dict]:
        cur = self.db.execute("""
            SELECT id, vendor, last_seen
            FROM robots
            ORDER BY id
        """)
        return [{"id": i, "vendor": v, "last_seen_ms": t} for i, v, t in cur]

    def delivered(self, keys: list[tuple[str, int]]) -> None:
        """Delete readings central has confirmed. Only these keys, so readings
        that arrived while the batch was in flight stay for the next one."""
        with self.db:
            self.db.executemany("""
                DELETE FROM robot_telemetry
                WHERE robot_id = ? AND ts_ms = ?
            """, keys)

    def prune(self, retention_hours: float) -> int:
        """Drop undelivered readings older than the cap, so a dead uplink cannot
        fill the disk. Normally deletes nothing."""
        with self.db:
            return self.db.execute("""
                DELETE FROM robot_telemetry
                WHERE received_ms < ?
            """, (now_ms() - int(retention_hours * 3_600_000),)).rowcount
