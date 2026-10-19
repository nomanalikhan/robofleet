import pytest

from model import Reading


@pytest.fixture
def base() -> Reading:
    """One valid reading from a registered Rovo robot."""
    return Reading(
        robot_id="rv-1", ts_ms=1000, received_ms=1000, seq=1, battery_pct=80,
        state="working", error=None, x_m=1, y_m=1, heading_rad=0, speed_mps=0.8,
    )
