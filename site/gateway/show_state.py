"""Print every robot the gateway knows and what still waits for central. Run
with python show_state.py."""

import sqlite3
import time

from config import Config


def main() -> None:
    db = sqlite3.connect(Config.from_env().db_path)
    now = time.time() * 1000
    waiting, oldest = db.execute("""
        SELECT count(*), min(received_ms)
        FROM robot_telemetry
    """).fetchone()
    oldest_age = f"{(now - oldest) / 1000:.1f}s" if oldest else "-"
    print(f"waiting for central: {waiting} readings, oldest {oldest_age}\n")

    rows = db.execute("""
        SELECT r.id, r.vendor, r.ip, r.last_seen,
               (SELECT count(*) FROM robot_telemetry WHERE robot_id = r.id)
        FROM robots r
        ORDER BY r.vendor, r.id
    """).fetchall()
    print(f"{'robot':<11} {'vendor':<8} {'ip':<15} {'last seen':>9} {'waiting':>7}")
    for rid, vendor, ip, last_seen, n in rows:
        print(f"{rid:<11} {vendor:<8} {ip or '-':<15} {(now - last_seen) / 1000:8.1f}s {n:7}")


if __name__ == "__main__":
    main()
