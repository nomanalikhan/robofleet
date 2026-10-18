"""The canonical model every vendor is normalized into."""

from dataclasses import dataclass
from typing import Literal

State = Literal["idle", "working", "returning", "charging", "paused", "error"]
Error = Literal["wheel_stuck", "bumper_hit", "localization_lost"]


@dataclass(frozen=True, slots=True)
class Reading:
    robot_id: str
    ts_ms: int  # robot clock, epoch milliseconds
    received_ms: int  # gateway clock
    seq: int | None  # only vendors that send one
    battery_pct: float  # 0..100
    state: State
    error: Error | None
    x_m: float
    y_m: float
    heading_rad: float
    speed_mps: float | None  # only vendors that send one
