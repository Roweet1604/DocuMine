# SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.
"""Decides when to send Telegram alerts."""

from datetime import datetime, timedelta

from kestrel import config


def check_reading(metric: str, value: float) -> str | None:
    """Return 'alert', 'warning' or None for one reading."""
    if metric == "temperature" and value > config.TEMP_MAX_C:
        return "alert"
    if metric == "humidity" and value < config.HUMIDITY_MIN_PCT:
        return "alert"
    if metric == "soil_moisture" and value < config.SOIL_MOISTURE_WARN_PCT:
        return "warning"
    return None


def should_send(last_sent: datetime | None, now: datetime) -> bool:
    """Apply the cooldown so the same alert is not repeated too often."""
    if last_sent is None:
        return True
    return now - last_sent >= timedelta(minutes=config.ALERT_COOLDOWN_MINUTES)


def find_stale_sensors(last_seen: dict[str, datetime], now: datetime) -> list[str]:
    """Sensors that have sent nothing for STALE_DATA_MINUTES (see incident INC-007)."""
    limit = timedelta(minutes=config.STALE_DATA_MINUTES)
    return sorted(sensor for sensor, seen in last_seen.items() if now - seen > limit)
