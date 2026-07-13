"""Simple busy period prediction based on historical request patterns."""
import datetime
import os
from typing import Dict, List, Any


def calculate_busy_baseline(events: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Calculate average request count for each hour of week.
    Returns: {'Monday_8': 3.5, 'Monday_9': 5.2, 'Tuesday_8': 2.1, ...}
    """
    hour_totals = {}
    hour_counts = {}

    for event in events:
        if not event or event.get('event_type') != 'requested':
            continue

        try:
            timestamp_str = event.get('timestamp') or event.get('iso_time')
            if not timestamp_str:
                continue

            # Parse ISO timestamp
            timestamp = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            hour = timestamp.hour
            weekday = timestamp.strftime('%A')
            key = f"{weekday}_{hour}"

            hour_totals[key] = hour_totals.get(key, 0) + 1
            hour_counts[key] = hour_counts.get(key, 0) + 1
        except Exception:
            continue

    # Calculate averages
    averages = {key: hour_totals[key] / hour_counts[key] for key in hour_totals}
    return averages


def _get_ratio_thresholds() -> Dict[str, float]:
    """Return configurable thresholds for busy-period classification."""
    def _read_threshold(name: str, default: float) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    return {
        'busy': _read_threshold('BUSY_PERIOD_BUSY_RATIO_THRESHOLD', 1.3),
        'very_busy': _read_threshold('BUSY_PERIOD_VERY_BUSY_RATIO_THRESHOLD', 1.8),
    }


def predict_busy_period(
    current_table_requests: int,
    current_hour: int,
    current_day: str,
    baseline: Dict[str, float]
) -> str:
    """
    Predict if current hour is busy based on historical average.

    Args:
        current_table_requests: total requests in current hour for a table
        current_hour: hour of day (0-23)
        current_day: day name (Monday, Tuesday, etc.)
        baseline: average requests per hour (from calculate_busy_baseline)

    Returns:
        'normal' | 'busy' | 'very_busy'
    """
    key = f"{current_day}_{current_hour}"

    # A single request should not look like an overload by itself.
    # Only sustained spikes above the historical baseline should be flagged.
    if current_table_requests <= 1:
        return 'normal'

    # Get average for this hour across all weeks
    average = baseline.get(key, 0)

    if average <= 0:
        # No historical data, default to normal
        return 'normal'

    # Thresholding uses environment overrides when configured
    ratio = current_table_requests / average
    thresholds = _get_ratio_thresholds()

    if ratio >= thresholds['very_busy']:
        return 'very_busy'
    elif ratio >= thresholds['busy']:
        return 'busy'
    else:
        return 'normal'


def describe_busy_period(
    period: str,
    hour: int,
    day: str,
    current_requests: int | None = None,
    baseline_average: float | None = None,
) -> str:
    """Generate a concise recommendation-style description for the current period."""
    period_emoji = {'normal': '🟢', 'busy': '🟡', 'very_busy': '🔴'}
    emoji = period_emoji.get(period, '❓')

    if baseline_average is None:
        return (
            f"{emoji} There is not enough historical {day} {hour}:00 data yet to compare this hour "
            "with past patterns, so this is being treated as steady for now."
        )

    if period == 'very_busy':
        return (
            f"{emoji} Compared with the usual {day} {hour}:00 pattern, this hour is running well above normal. "
            "Add support now."
        )
    if period == 'busy':
        return (
            f"{emoji} Compared with the usual {day} {hour}:00 pattern, this hour is busier than normal. "
            "A little extra support may help."
        )
    return (
        f"{emoji} Compared with the usual {day} {hour}:00 pattern, this hour is in line with normal demand. "
        "Service looks steady."
    )
