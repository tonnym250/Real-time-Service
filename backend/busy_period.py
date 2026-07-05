"""Simple busy period prediction based on historical request patterns."""
import datetime
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

    # Get average for this hour across all weeks
    average = baseline.get(key, 0)

    if average == 0:
        # No historical data, default to normal
        return 'normal'

    # Simple thresholds
    ratio = current_table_requests / average

    if ratio >= 1.8:
        return 'very_busy'
    elif ratio >= 1.3:
        return 'busy'
    else:
        return 'normal'


def describe_busy_period(period: str, hour: int, day: str) -> str:
    """Generate human-readable description of busy period."""
    period_emoji = {'normal': '🟢', 'busy': '🟡', 'very_busy': '🔴'}
    emoji = period_emoji.get(period, '❓')

    if period == 'very_busy':
        return f"{emoji} Very busy! {day} at {hour}:00 is often overloaded."
    elif period == 'busy':
        return f"{emoji} Busy period. {day} at {hour}:00 typically needs extra hands."
    else:
        return f"{emoji} Normal period. {day} at {hour}:00 is usually quiet."
