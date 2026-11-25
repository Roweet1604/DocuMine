# SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.
"""Thresholds and timing settings for Kestrel."""

READING_INTERVAL_MINUTES = 5

TEMP_MAX_C = 35.0
HUMIDITY_MIN_PCT = 40.0
SOIL_MOISTURE_WARN_PCT = 20.0

ALERT_COOLDOWN_MINUTES = 30

# Added after incident INC-007: alert when a sensor sends nothing for this long.
STALE_DATA_MINUTES = 15
