"""Local SQLite storage.

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

-- Every reading in the canonical format, stored once and sorted by robot and
-- time. The key drops the same reading arriving twice and makes "newest
-- reading of a robot" a direct lookup.
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
    uploaded    INTEGER NOT NULL DEFAULT 0,  -- 1 once central confirmed it
    PRIMARY KEY (robot_id, ts_ms)
) WITHOUT ROWID;

-- What the uplink still has to send, oldest arrival first. Stays small because
-- it only holds rows that are not uploaded yet.
CREATE INDEX IF NOT EXISTS robot_telemetry_unsent ON robot_telemetry (received_ms) WHERE uploaded = 0;

-- What each robot is doing right now. Newest by robot time, so a late reading
-- never moves it backwards. Pruning never deletes these rows.
CREATE VIEW IF NOT EXISTS latest AS
SELECT t.* FROM robots
JOIN robot_telemetry t ON t.robot_id = robots.id
 AND t.ts_ms = (SELECT max(ts_ms) FROM robot_telemetry WHERE robot_id = robots.id);
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

    def prune(self, uploaded_keep_s: float, retention_hours: float) -> int:
        """Delete history central no longer needs from us. Never a robot's newest reading.

        Uploaded rows go after uploaded_keep_s. Rows that never got uploaded go
        after retention_hours, so a dead uplink cannot fill the disk.
        """
        t = now_ms()
        with self.db:
            return self.db.execute("""
                DELETE FROM robot_telemetry
                WHERE ((uploaded = 1 AND received_ms < ?) OR received_ms < ?)
                  AND ts_ms < (
                      SELECT max(ts_ms)
                      FROM robot_telemetry newest
                      WHERE newest.robot_id = robot_telemetry.robot_id
                  )
            """, (t - int(uploaded_keep_s * 1000), t - int(retention_hours * 3_600_000))).rowcount
