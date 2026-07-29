"""Signed webhook receiver, failure lab, and delivery observability API."""
from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .security import SIGNATURE_HEADER, TIMESTAMP_HEADER, valid_signature
from .store import Attempt, DeliveryStore

APP_DIR = Path(__file__).parent
SECRET = os.getenv("WEBHOOKLAB_SIGNING_SECRET", "whlab_development_secret_change_me")
DATABASE = Path(os.getenv("WEBHOOKLAB_DATABASE", str(APP_DIR.parent / "webhooklab.sqlite3")))
store = DeliveryStore(DATABASE)
app = FastAPI(title="Webhook Delivery Debugger", version="1.1.0")


class Event(BaseModel):
    id: UUID
    type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,100}$")
    created_at: datetime
    data: dict[str, object] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage": "sqlite-wal", "signature_verification": "enabled", "payload_retention": "digest-only"}


@app.get("/api/stats")
def stats() -> dict[str, object]:
    return store.stats()


@app.get("/api/deliveries")
def deliveries(limit: int = Query(default=50, ge=1, le=100), outcome: str | None = None) -> dict[str, object]:
    return {"deliveries": store.recent(limit, outcome)}


@app.get("/api/events/{event_id}")
def event_detail(event_id: str) -> dict[str, object]:
    event = store.event(event_id)
    if not event: raise HTTPException(404, "Event not found")
    return event


@app.post("/api/webhooks", status_code=202)
async def receive_webhook(request: Request) -> dict[str, object]:
    started = time.perf_counter()
    body = await request.body()
    timestamp, supplied = request.headers.get(TIMESTAMP_HEADER), request.headers.get(SIGNATURE_HEADER)
    if not valid_signature(SECRET, timestamp, supplied, body):
        raise HTTPException(400, "Invalid or stale webhook signature")
    try:
        event = Event.model_validate_json(body)
    except ValueError as error:
        raise HTTPException(422, "Invalid event envelope") from error
    digest = hashlib.sha256(body).hexdigest()
    received_at = datetime.now(UTC).isoformat()
    outcome = store.record(Attempt(
        event_id=str(event.id), event_type=event.type, received_at=received_at,
        outcome="processed", http_status=202,
        duration_ms=round((time.perf_counter() - started) * 1_000),
        payload_sha256=digest, detail="Payload verified; business work would be queued.",
    ))
    if outcome == "id_collision":
        raise HTTPException(409, "Event ID was previously used with a different payload")
    return {"accepted": True, "outcome": outcome, "event_id": str(event.id), "payload_sha256": digest}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")
