# SAMPLE DATA - fictional project "Kestrel" made up for testing DocuMine.
"""Per-device tokens. Only the sha256 hash of a token is ever stored."""

import hashlib
import hmac


def hash_token(device_token: str) -> str:
    """Return the sha256 hex digest that we store for a device token."""
    return hashlib.sha256(device_token.encode("utf-8")).hexdigest()


def verify_token(device_token: str, stored_hash: str) -> bool:
    """Check a token from the X-Device-Token header in constant time."""
    return hmac.compare_digest(hash_token(device_token), stored_hash)
