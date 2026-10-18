import json
import math
from pathlib import Path

import pytest

from vendors import cleanix, rovo

FIXTURES = Path(__file__).parent / "fixtures"


def contract(name: str) -> bytes:
    """An example payload exactly as the vendor documents it."""
    return (FIXTURES / name).read_bytes()


def test_rovo_contract_example():
    r = rovo.normalize(contract("rovo/telemetry.json"), received_ms=1)
    assert (r.robot_id, r.seq) == ("rv-3f9a21", 4211)
    assert r.ts_ms == 1760700000123
    assert r.battery_pct == 87.0
    assert (r.state, r.error) == ("working", None)
    assert (r.x_m, r.y_m, r.heading_rad, r.speed_mps) == (12.4, 7.9, 1.57, 0.8)


def test_cleanix_contract_example():
    r = cleanix.normalize(contract("cleanix/status.json"), received_ms=1)
    assert (r.robot_id, r.seq, r.speed_mps) == ("cx-8b20d4", None, None)
    assert r.ts_ms == 1760700000123
    assert r.battery_pct == pytest.approx(42.0)
    assert (r.state, r.error) == ("error", "bumper_hit")
    assert (r.x_m, r.y_m) == (12.4, 7.9)
    assert r.heading_rad == pytest.approx(math.pi / 2)


def test_both_vendors_land_in_the_same_units():
    """The same physical robot state reads the same no matter the vendor."""
    rv = json.loads(contract("rovo/telemetry.json"))
    rv.update(battery=42, status="ERROR", errorCode=102)
    cx = cleanix.normalize(contract("cleanix/status.json"), 1)
    r = rovo.normalize(json.dumps(rv).encode(), 1)
    for field in ("ts_ms", "battery_pct", "state", "error", "x_m", "y_m"):
        assert getattr(r, field) == pytest.approx(getattr(cx, field)), field


@pytest.mark.parametrize(
    "vendor, name, patch",
    [
        (rovo, "rovo/telemetry.json", {"status": "DANCING"}),
        (rovo, "rovo/telemetry.json", {"errorCode": 999}),
        (rovo, "rovo/telemetry.json", {"battery": "full"}),
        (cleanix, "cleanix/status.json", {"work_state": "dancing"}),
        (cleanix, "cleanix/status.json", {"fault": {"code": "E999", "message": "?"}}),
    ],
)
def test_unknown_values_are_rejected(vendor, name, patch):
    raw = json.loads(contract(name)) | patch
    with pytest.raises(ValueError):  # pydantic's ValidationError is a ValueError
        vendor.normalize(json.dumps(raw).encode(), 1)
