> SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.

# Kestrel - rough design notes
written by maya, 2 oct 2026, very rough, will clean up later

## what is it
monitor temperature, humidity and soil moisture in 3 greenhouses (A, B, C) of the
Northfield College botany dept. ~40 sensors on ESP32 boards.
goal for v1: live dashboard + alerts before plants get damaged.

## architecture v1
- ESP32 boards -> HTTPS POST /readings every 5 min (JSON body)
- "kestrel-api" (FastAPI) validates and stores readings in Postgres (Supabase)
- alert worker runs every 1 min, compares latest readings with thresholds, sends Telegram message
- Streamlit dashboard reads straight from postgres

## data
table readings(id, sensor_id, greenhouse, metric, value, recorded_at)
- index on (sensor_id, recorded_at)
- raw readings are kept for 30 days, then rolled up into hourly averages
- rollup = nightly job at 02:00

## thresholds
- temperature > 35 C -> alert (orchids in greenhouse B)
- humidity < 40 % -> alert
- soil moisture < 20 % -> warning on dashboard only, no alert
- cooldown: same alert for same sensor not repeated within 30 min

## auth
- every board has its own device token, sent in header X-Device-Token
- server stores only sha256 hash of the token, compares with constant-time compare
- no shared password

## open questions
- battery level metric? omar to check if the boards can report it
- backups - supabase daily backup probably enough?

## not in v1
- email alerts
- mobile app
- per-plant profiles
