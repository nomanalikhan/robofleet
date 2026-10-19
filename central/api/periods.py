"""Time ranges for chart routes, and how coarse their points are."""

from datetime import timedelta
from typing import Literal

Period = Literal["hour", "day", "week", "month"]
PERIODS = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}
RAW_UP_TO = timedelta(hours=1)
BUCKETS_S = [60, 300, 1800, 7200]  # the smallest that keeps a chart near MAX_POINTS wins
MAX_POINTS = 400
MAX_RANGE = timedelta(days=31)  # history is kept 30 days


def bucket_for(span: timedelta) -> int | None:
    """Seconds per point for a range, None for raw readings."""
    if span <= RAW_UP_TO:
        return None
    return next((b for b in BUCKETS_S if span.total_seconds() / b <= MAX_POINTS), BUCKETS_S[-1])
