# SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.
from datetime import datetime, timedelta

from kestrel import alerts


def test_hot_greenhouse_alerts():
    assert alerts.check_reading("temperature", 36.2) == "alert"


def test_dry_soil_is_only_a_warning():
    assert alerts.check_reading("soil_moisture", 15) == "warning"


def test_cooldown():
    now = datetime(2026, 10, 14, 6, 30)
    assert not alerts.should_send(now - timedelta(minutes=10), now)
    assert alerts.should_send(now - timedelta(minutes=31), now)


def test_stale_sensors():
    now = datetime(2026, 10, 14, 7, 0)
    seen = {"B-03": now - timedelta(hours=5), "A-01": now - timedelta(minutes=2)}
    assert alerts.find_stale_sensors(seen, now) == ["B-03"]
