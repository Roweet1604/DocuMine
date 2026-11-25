"""Loads settings from the .env file. Import values from here, never read os.environ elsewhere."""

import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
STORAGE_BUCKET = "uploads"


def require(name: str) -> str:
    """Return a required setting, or raise a clear error telling the user what to fix."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing setting {name}. Copy .env.example to .env and fill in {name}."
        )
    return value
