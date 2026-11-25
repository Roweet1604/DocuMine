<!-- SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine. -->
# kestrel-service

Small Python service for the Kestrel greenhouse monitor.

- `kestrel/config.py` - thresholds and timing settings
- `kestrel/auth.py` - device token hashing and checking
- `kestrel/alerts.py` - threshold alerts, cooldown and stale-data detection
- `kestrel/api.py` - `POST /readings` endpoint (FastAPI)

Run the API: `uvicorn kestrel.api:app --reload`
Run tests: `pytest`
