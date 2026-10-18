-- Central fleet schema. Applied by ingest at startup, every statement is idempotent.
-- The state and error values match batch.py and site/gateway/model.py.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS sites (
    id                TEXT PRIMARY KEY,         -- 'site-1'
    last_sent_at      TIMESTAMPTZ NOT NULL,     -- gateway clock, when it sent its newest batch. The heartbeat.
    backlog_readings  INTEGER NOT NULL,         -- readings still waiting on site after that batch
    backlog_oldest_at TIMESTAMPTZ               -- oldest of those, NULL if none
);

CREATE TABLE IF NOT EXISTS robots (
    id      TEXT PRIMARY KEY,                    -- serial, e.g. 'rv-14fa03'
    site_id TEXT NOT NULL REFERENCES sites (id), -- follows the robot if it moves site
    vendor  TEXT NOT NULL
);

-- Column order matches batch.Reading, rows are inserted as whole tuples.
CREATE TABLE IF NOT EXISTS robot_telemetry (
    robot_id    TEXT        NOT NULL REFERENCES robots (id),
    ts          TIMESTAMPTZ NOT NULL,            -- robot clock, when it was measured
    received_at TIMESTAMPTZ NOT NULL,            -- gateway clock, when it arrived on site
    seq         INTEGER,                         -- Rovo only
    battery_pct REAL        NOT NULL,
    state       TEXT        NOT NULL CHECK (state IN ('idle', 'working', 'returning', 'charging', 'paused', 'error')),
    error       TEXT        CHECK (error IN ('wheel_stuck', 'bumper_hit', 'localization_lost')),
    x_m         REAL        NOT NULL,
    y_m         REAL        NOT NULL,
    heading_rad REAL        NOT NULL,
    speed_mps   REAL,                            -- Rovo only
    PRIMARY KEY (robot_id, ts)
);

SELECT create_hypertable('robot_telemetry', 'ts', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('robot_telemetry', INTERVAL '30 days', if_not_exists => TRUE);
