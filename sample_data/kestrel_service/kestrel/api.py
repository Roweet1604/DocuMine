# SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.
"""HTTP API that the ESP32 boards post readings to."""

from datetime import datetime

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from kestrel import auth

app = FastAPI(title="kestrel-api")

DEVICE_HASHES: dict[str, str] = {}  # sensor_id -> token hash, loaded from the database at startup
READINGS: list[dict] = []           # stand-in for the Postgres readings table


class Reading(BaseModel):
    sensor_id: str
    greenhouse: str
    metric: str
    value: float
    recorded_at: datetime


@app.post("/readings")
def post_reading(reading: Reading, x_device_token: str = Header(...)):
    stored_hash = DEVICE_HASHES.get(reading.sensor_id)
    if stored_hash is None or not auth.verify_token(x_device_token, stored_hash):
        raise HTTPException(status_code=401, detail="unknown device or bad token")
    READINGS.append(reading.model_dump())
    return {"status": "stored"}
