"""Operator CLI for sending, replaying, and inspecting webhook fixtures."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx

from .security import SIGNATURE_HEADER, TIMESTAMP_HEADER, signature

SECRET = os.getenv("WEBHOOKLAB_SIGNING_SECRET", "whlab_development_secret_change_me")
BASE_URL = os.getenv("WEBHOOKLAB_URL", "http://127.0.0.1:8080").rstrip("/")


def fixture(event_type: str, event_id: UUID | None = None, *, created_at: datetime | None = None) -> dict[str, object]:
    return {"id": str(event_id or uuid4()), "type": event_type, "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "data": {"source": "webhooklab", "object": {"id": f"obj_{uuid4().hex[:10]}", "amount": 4200, "currency": "usd"}}}


def send(event: dict[str, object], *, invalid_signature: bool = False, stale: bool = False, base_url: str = BASE_URL) -> httpx.Response:
    body = json.dumps(event, separators=(",", ":")).encode()
    timestamp = str(int(time.time()) - 600 if stale else int(time.time()))
    signed = "invalid" if invalid_signature else signature(SECRET, timestamp, body)
    return httpx.post(f"{base_url}/api/webhooks", content=body,
                      headers={"content-type": "application/json", TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signed}, timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webhooklab", description="Exercise webhook delivery and replay behavior.")
    parser.add_argument("--version", action="version", version="Webhook Delivery Debugger 1.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve"); serve.add_argument("--port", type=int, default=8080)
    for name in ("send", "chaos"):
        sub = commands.add_parser(name); sub.add_argument("event_type"); sub.add_argument("--event-id", type=UUID)
        if name == "chaos":
            sub.add_argument("--duplicate", action="store_true"); sub.add_argument("--out-of-order", action="store_true")
            sub.add_argument("--invalid-signature", action="store_true"); sub.add_argument("--stale", action="store_true")
    replay = commands.add_parser("replay"); replay.add_argument("event_id", type=UUID); replay.add_argument("--event-type", default="replayed.event")
    inspect = commands.add_parser("inspect"); inspect.add_argument("event_id", nargs="?")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)], check=False).returncode
    if args.command == "inspect":
        endpoint = f"/api/events/{args.event_id}" if args.event_id else "/api/stats"
        response = httpx.get(BASE_URL + endpoint, timeout=5)
        print(json.dumps(response.json(), indent=2, sort_keys=True)); return 0 if response.is_success else 1
    event_type = getattr(args, "event_type", "replayed.event")
    event_id = getattr(args, "event_id", None)
    event = fixture(event_type, event_id)
    events = [event]
    if args.command == "chaos" and args.out_of_order:
        events.insert(0, fixture("customer.updated", created_at=datetime.now(UTC) + timedelta(seconds=10)))
    if args.command == "chaos" and args.duplicate: events.append(event)
    exit_code = 0
    for item in events:
        try:
            response = send(item, invalid_signature=getattr(args, "invalid_signature", False), stale=getattr(args, "stale", False))
            print(json.dumps({"http_status": response.status_code, "response": response.json()}, sort_keys=True))
            if response.is_error: exit_code = 1
        except httpx.HTTPError as error:
            print(f"webhooklab: {error}", file=sys.stderr); return 2
    return exit_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__": main()
