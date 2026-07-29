import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.security import SIGNATURE_HEADER, TIMESTAMP_HEADER, signature, valid_signature
from app.store import DeliveryStore

SECRET = "whlab_development_secret_change_me"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", DeliveryStore(tmp_path / "test.sqlite3"))
    return TestClient(main.app)


def event_body(event_id: str | None = None, *, amount: int = 4200) -> bytes:
    return json.dumps({"id": event_id or str(uuid4()), "type": "payment.succeeded", "created_at": "2026-01-01T00:00:00Z", "data": {"amount": amount}}, separators=(",", ":")).encode()


def signed_headers(body: bytes, *, timestamp: str | None = None, supplied: str | None = None) -> dict[str, str]:
    timestamp = timestamp or str(int(datetime.now(UTC).timestamp()))
    return {"content-type": "application/json", TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: supplied or signature(SECRET, timestamp, body)}


def test_signed_event_is_accepted_and_visible(client):
    body = event_body()
    response = client.post("/api/webhooks", content=body, headers=signed_headers(body))
    assert response.status_code == 202
    assert response.json()["outcome"] == "processed"
    assert client.get(f"/api/events/{response.json()['event_id']}").json()["process_count"] == 1


def test_invalid_signature_is_rejected_without_ledger_entry(client):
    body = event_body()
    response = client.post("/api/webhooks", content=body, headers=signed_headers(body, supplied="wrong"))
    assert response.status_code == 400
    assert client.get("/api/stats").json()["delivery_attempts"] == 0


def test_stale_timestamp_is_rejected(client):
    body, timestamp = event_body(), "1"
    response = client.post("/api/webhooks", content=body, headers=signed_headers(body, timestamp=timestamp))
    assert response.status_code == 400


def test_duplicate_is_acknowledged_and_counted(client):
    body, headers = event_body(), None
    headers = signed_headers(body)
    assert client.post("/api/webhooks", content=body, headers=headers).json()["outcome"] == "processed"
    assert client.post("/api/webhooks", content=body, headers=headers).json()["outcome"] == "duplicate"
    stats = client.get("/api/stats").json()
    assert stats["unique_events"] == 1
    assert stats["delivery_attempts"] == 2
    assert stats["duplicate_rate"] == 0.5


def test_same_event_id_with_different_payload_is_collision(client):
    event_id = str(uuid4())
    first, changed = event_body(event_id, amount=100), event_body(event_id, amount=200)
    assert client.post("/api/webhooks", content=first, headers=signed_headers(first)).status_code == 202
    response = client.post("/api/webhooks", content=changed, headers=signed_headers(changed))
    assert response.status_code == 409
    detail = client.get(f"/api/events/{event_id}").json()
    assert detail["attempts"][-1]["outcome"] == "id_collision"


def test_payload_body_is_not_persisted(client):
    marker = "sensitive-customer-marker"
    body = json.dumps({"id": str(uuid4()), "type": "customer.updated", "created_at": "2026-01-01T00:00:00Z", "data": {"note": marker}}, separators=(",", ":")).encode()
    event_id = client.post("/api/webhooks", content=body, headers=signed_headers(body)).json()["event_id"]
    assert marker not in str(client.get(f"/api/events/{event_id}").json())


def test_signature_comparison_rejects_bad_timestamp():
    assert valid_signature(SECRET, "not-an-int", "anything", b"{}") is False


def test_delivery_filter_returns_only_requested_outcome(client):
    body, headers = event_body(), None
    headers = signed_headers(body)
    client.post("/api/webhooks", content=body, headers=headers)
    client.post("/api/webhooks", content=body, headers=headers)
    rows = client.get("/api/deliveries?outcome=duplicate").json()["deliveries"]
    assert len(rows) == 1 and rows[0]["outcome"] == "duplicate"
