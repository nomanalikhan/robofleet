"""Cleanix robots each run their own HTTP server and must be polled. Wire format
is in simulator/botsim/README.md.

Discovery resolves a name to candidate IPs and probes GET /api/v1/info on each.
Whatever answers is a robot and says its serial. A robot whose IP leaves the
candidates is no longer polled.

The name lookup is a simulation stand-in. Docker DNS resolves the compose
service to every replica. A real site would get candidates from a subnet scan
or a static list instead, and only resolve() would change.
"""

import asyncio
import logging
import math
import socket
from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from model import Error, Reading, State
from store import Store, now_ms

VENDOR = "cleanix"
BASE_PATH = "/api/v1"
log = logging.getLogger(__name__)

STATES: dict[str, State] = {
    "idle": "idle",
    "cleaning": "working",
    "returning_home": "returning",
    "docked_charging": "charging",
    "paused": "paused",
    "fault": "error",
}
ERRORS: dict[str, Error] = {"E201": "wheel_stuck", "E102": "bumper_hit", "E310": "localization_lost"}


class Fault(BaseModel):
    code: str


class Location(BaseModel):
    x_cm: int
    y_cm: int
    heading_deg: int


class Status(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    serial: str = Field(max_length=64)
    ts: datetime
    battery_level: float = Field(ge=0, le=1)
    work_state: str
    fault: Fault | None
    location: Location


def normalize(raw: bytes, received_ms: int) -> Reading:
    """Turn one status response into a Reading. Raises ValueError if it does not fit."""
    s = Status.model_validate_json(raw)
    if s.work_state not in STATES or (s.fault and s.fault.code not in ERRORS):
        raise ValueError(f"unknown work_state {s.work_state!r} or fault {s.fault}")
    return Reading(
        robot_id=s.serial,
        ts_ms=int(s.ts.timestamp() * 1000),
        received_ms=received_ms,
        seq=None,
        battery_pct=s.battery_level * 100,
        state=STATES[s.work_state],
        error=ERRORS[s.fault.code] if s.fault else None,
        x_m=s.location.x_cm / 100,
        y_m=s.location.y_cm / 100,
        heading_rad=math.radians(s.location.heading_deg),
        speed_mps=None,
    )


RETRY_S = 5  # discovery comes back this soon after finding nothing or a silent probe


async def run(store: Store, discovery: str, discovery_interval_s: float, poll_interval_s: float) -> None:
    """Keep one poller per discovered robot, refreshing discovery forever."""
    host, port = discovery.rsplit(":", 1)
    pollers: dict[str, asyncio.Task] = {}  # by robot IP
    async with httpx.AsyncClient(timeout=2) as http:
        while True:
            ips = await resolve(host)
            if ips is None:
                log.warning("cleanix: cannot resolve %s, retrying in %ds", host, RETRY_S)
                await asyncio.sleep(RETRY_S)
                continue
            missed = not ips
            urls = {ip: f"http://{ip}:{port}{BASE_PATH}" for ip in ips - pollers.keys()}
            serials = await asyncio.gather(*(probe(http, url) for url in urls.values()))
            for (ip, url), serial in zip(urls.items(), serials, strict=True):
                if not serial:
                    missed = True  # booting or not a Cleanix robot, look again soon
                    continue
                new = store.register(serial, VENDOR, ip)
                log.info("cleanix: %s %s at %s, polling", "discovered" if new else "found", serial, ip)
                pollers[ip] = asyncio.create_task(poll(store, http, ip, url, serial, poll_interval_s))
            for ip in pollers.keys() - ips:
                log.info("cleanix: %s left the network", ip)
                pollers.pop(ip).cancel()
            await asyncio.sleep(RETRY_S if missed else discovery_interval_s)


async def resolve(host: str) -> set[str] | None:
    """Candidate IPs. Empty means the name resolves to nothing (scaled to zero),
    None means DNS itself failed and nothing is known."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, family=socket.AF_INET)
    except socket.gaierror:
        return None
    return {info[4][0] for info in infos}


async def probe(http: httpx.AsyncClient, url: str) -> str | None:
    try:
        res = await http.get(f"{url}/info")
        res.raise_for_status()
        return res.json()["serial"]
    except Exception:  # whatever does not answer /info properly is not a Cleanix robot
        return None


async def poll(store: Store, http: httpx.AsyncClient, ip: str, url: str, serial: str, interval_s: float) -> None:
    loop = asyncio.get_running_loop()
    next_at = loop.time()
    while True:
        try:
            res = await http.get(f"{url}/status")
            if res.status_code == 200:
                reading = normalize(res.content, now_ms())
                # Another robot may have taken over this IP since /info was probed.
                store.register(reading.robot_id, VENDOR, ip)
                store.add(reading)
            else:
                log.debug("cleanix: %s answered %d", serial, res.status_code)
        except httpx.HTTPError as e:
            log.debug("cleanix: %s unreachable: %s", serial, e)
        except (ValidationError, ValueError) as e:
            log.warning("cleanix: dropping bad status from %s: %s", serial, e)
        except Exception:
            log.exception("cleanix: poll of %s failed", serial)
        next_at += interval_s
        await asyncio.sleep(max(0, next_at - loop.time()))
