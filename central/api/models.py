"""Response shapes. They define openapi.json, which the web UI generates its client from."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SiteStatus = Literal["online", "degraded", "offline"]
RobotStatus = Literal["unknown", "offline", "error", "stuck", "low_battery", "ok"]  # worst first
# Same values as the CHECKs in central/ingest/schema.sql, enforced by a test.
State = Literal["idle", "working", "returning", "charging", "paused", "error"]
Error = Literal["wheel_stuck", "bumper_hit", "localization_lost"]


class Site(BaseModel):
    id: str
    status: SiteStatus
    last_sent_at: datetime
    backlog_readings: int
    backlog_oldest_at: datetime | None
    robots_by_status: dict[RobotStatus, int]


class Robot(BaseModel):
    id: str
    site_id: str
    vendor: str
    status: RobotStatus
    problems: list[RobotStatus]
    # From the newest reading. Null for a robot discovered but never heard from.
    last_seen_s: float | None
    state: State | None
    error: Error | None
    battery_pct: float | None
    x_m: float | None
    y_m: float | None


class RobotPage(BaseModel):
    items: list[Robot]
    total: int


class TelemetryPoint(BaseModel):
    ts: datetime
    battery_pct: float
    state: State
    error: Error | None
    x_m: float
    y_m: float


class Telemetry(BaseModel):
    bucket_s: int | None  # seconds each point averages, null for raw readings
    points: list[TelemetryPoint]
