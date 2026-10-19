"""Rovo robots push telemetry to the site MQTT broker. Wire format is in
simulator/botsim/README.md.

Discovery is passive. A serial seen on rovo/+/online or rovo/+/telemetry for
the first time is a new robot.
"""

import asyncio
import logging

import aiomqtt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from model import Error, Reading, State
from store import Store, now_ms

VENDOR = "rovo"
log = logging.getLogger(__name__)

STATES: dict[str, State] = {
    "IDLE": "idle",
    "WORKING": "working",
    "RETURNING": "returning",
    "CHARGING": "charging",
    "PAUSED": "paused",
    "ERROR": "error",
}
ERRORS: dict[int, Error | None] = {0: None, 101: "wheel_stuck", 102: "bumper_hit", 103: "localization_lost"}


class Pose(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    x: float
    y: float
    theta: float


class Telemetry(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    robotId: str = Field(max_length=64)
    timestamp: int
    seq: int
    battery: int = Field(ge=0, le=100)
    status: str
    errorCode: int
    pose: Pose
    speed: float


def normalize(raw: bytes, received_ms: int) -> Reading:
    """Turn one telemetry message into a Reading. Raises ValueError if it does not fit."""
    t = Telemetry.model_validate_json(raw)
    if t.status not in STATES or t.errorCode not in ERRORS:
        raise ValueError(f"unknown status {t.status!r} or errorCode {t.errorCode}")
    return Reading(
        robot_id=t.robotId,
        ts_ms=t.timestamp,
        received_ms=received_ms,
        seq=t.seq,
        battery_pct=float(t.battery),
        state=STATES[t.status],
        error=ERRORS[t.errorCode],
        x_m=t.pose.x,
        y_m=t.pose.y,
        heading_rad=t.pose.theta,
        speed_mps=t.speed,
    )


async def run(store: Store, host: str, port: int, client_id: str) -> None:
    """Listen to every Rovo robot on the broker. Reconnects forever."""
    while True:
        try:
            async with aiomqtt.Client(host, port, identifier=client_id) as client:
                await client.subscribe("rovo/+/online", qos=1)
                await client.subscribe("rovo/+/telemetry")
                log.info("rovo: subscribed on %s:%d", host, port)
                async for msg in client.messages:
                    handle(store, msg.topic.value, msg.payload)
        except aiomqtt.MqttError as e:
            log.warning("rovo: broker unavailable (%s), retrying in 2s", e)
            await asyncio.sleep(2)


def handle(store: Store, topic: str, payload: bytes) -> None:
    _, robot_id, leaf = topic.split("/", 2)
    if store.register(robot_id, VENDOR):
        log.info("rovo: discovered %s", robot_id)
    if leaf != "telemetry":
        return  # online flags only matter for discovery until events exist
    try:
        reading = normalize(payload, now_ms())
        # The row is keyed by the payload's id but only the topic's id is registered.
        if reading.robot_id != robot_id:
            raise ValueError(f"robotId {reading.robot_id!r} does not match topic")
        store.add(reading)
    except (ValidationError, ValueError) as e:
        log.warning("rovo: dropping bad telemetry from %s: %s", robot_id, e)
