"""Small, explicit signing primitives used by both the sender and receiver."""
from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_HEADER = "x-webhooklab-signature"
TIMESTAMP_HEADER = "x-webhooklab-timestamp"


def signature(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def valid_signature(secret: str, timestamp: str | None, supplied: str | None, body: bytes, *, tolerance_seconds: int = 300) -> bool:
    if not timestamp or not supplied:
        return False
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return False
    expected = signature(secret, timestamp, body)
    return age <= tolerance_seconds and hmac.compare_digest(expected, supplied)
