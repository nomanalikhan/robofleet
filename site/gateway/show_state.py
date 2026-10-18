"""Print the latest state of every robot. Run with python show_state.py."""

import sqlite3
import time

from config import Config


def main() -> None:
    db = sqlite3.connect(Config.from_env().db_path)
    rows = db.execute("""
        SELECT r.id, r.vendor, l.state, l.error, l.battery_pct, l.x_m, l.y_m, l.ts_ms,
               (SELECT count(*) FROM robot_telemetry WHERE robot_id = r.id)
        FROM robots r
        LEFT JOIN latest l ON l.robot_id = r.id
        ORDER BY r.vendor, r.id
    """).fetchall()
    now = time.time() * 1000
    print(f"{'robot':<11} {'vendor':<8} {'state':<10} {'error':<18} {'batt':>5} {'x,y (m)':>13} {'age':>6} {'rows':>6}")
    for rid, vendor, state, error, batt, x, y, ts, n in rows:
        head = f"{rid:<11} {vendor:<8}"
        if state is None:
            print(f"{head} no data")
            continue
        age = (now - ts) / 1000
        print(f"{head} {state:<10} {error or '':<18} {batt:5.1f} {x:6.1f},{y:6.1f} {age:5.1f}s {n:6}")


if __name__ == "__main__":
    main()
