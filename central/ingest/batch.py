"""A batch as the site gateway sends it. See site/gateway/README.md."""

import gzip
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Same values as the CHECKs in schema.sql, enforced by a test.
State = Literal["idle", "working", "returning", "charging", "paused", "error"]
Error = Literal["wheel_stuck", "bumper_hit", "localization_lost"]


class Backlog(BaseModel):
    readings: int
    oldest_received: datetime | None = Field(validation_alias="oldest_received_ms")


class Robot(BaseModel):
    id: str
    vendor: str


class Reading(BaseModel):
    """Field order matches robot_telemetry columns. Epoch ms become datetimes."""

    model_config = ConfigDict(allow_inf_nan=False)

    robot_id: str
    ts: datetime = Field(validation_alias="ts_ms")
    received_at: datetime = Field(validation_alias="received_ms")
    seq: int | None
    battery_pct: float
    state: State
    error: Error | None
    x_m: float
    y_m: float
    heading_rad: float
    speed_mps: float | None


class Batch(BaseModel):
    site_id: str
    sent: datetime = Field(validation_alias="sent_ms")
    backlog: Backlog
    robots: list[Robot]
    readings: list[Reading]

    @model_validator(mode="after")
    def readings_have_known_robots(self) -> "Batch":
        unknown = {r.robot_id for r in self.readings} - {r.id for r in self.robots}
        if unknown:
            raise ValueError(f"readings for robots not in the batch: {sorted(unknown)}")
        return self


def parse(body: bytes) -> Batch:
    return Batch.model_validate_json(gzip.decompress(body))
