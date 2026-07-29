<div align="center">

# Webhook Delivery Debugger

### A small forensic bench for webhook incidents

Recreate signatures, retries, replays, and event-ID collisions locally—then leave the incident with evidence instead of guesses.

[![CI](https://github.com/Emmanuelasika/webhook-delivery-debugger/actions/workflows/ci.yml/badge.svg)](https://github.com/Emmanuelasika/webhook-delivery-debugger/actions/workflows/ci.yml)
[![Live investigation](https://img.shields.io/badge/live-investigation-171717?logo=githubpages&logoColor=white)](https://emmanuelasika.github.io/webhook-delivery-debugger/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-1E293B?logo=python&logoColor=white)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/license-MIT-0E7C66.svg)](LICENSE)

**[Walk through a webhook incident →](https://emmanuelasika.github.io/webhook-delivery-debugger/)**

</div>

---

I built Webhook Delivery Debugger around a support problem I have seen repeatedly: a customer says _“your webhook was sent twice”_, the provider says _“we received a non-2xx response”_, and neither side has enough safe evidence to explain what actually happened.

Webhook Delivery Debugger gives me a controlled receiver and a fixture sender. I can submit a correctly signed event, deliberately repeat it, age its timestamp, corrupt its signature, or reuse its event ID with a different body. Every accepted attempt is classified in a local ledger. The payload itself is never retained.

This is not another request bin. It is a focused way to answer four operational questions:

1. **Did the request prove who sent it?**
2. **Was this event already claimed?**
3. **Did the same ID arrive with different content?**
4. **What can I show an engineer or customer without exposing the payload?**

## When I would reach for it

| The report I receive | What I reproduce | Evidence I expect |
| --- | --- | --- |
| “Customers were charged twice.” | Send the same signed event twice. | Two delivery attempts, one unique event, second outcome `duplicate`. |
| “The signature from our test script never validates.” | Send one valid fixture, then use `--invalid-signature` and `--stale`. | The valid request gets `202`; invalid and expired requests get `400` before parsing or storage. |
| “The provider reused an event ID.” | Send the ID once, then submit a changed body with that ID. | `409 id_collision`, with both digests visible in the event attempt history. |
| “Updates arrived in the wrong order.” | Use `--out-of-order`. | A later-created fixture reaches the receiver first; the application’s ordering assumption can now be tested. |
| “Can you send us the original payload from your logs?” | Inspect the ledger. | Metadata and SHA-256 digests are available; sensitive payload bodies are not. |

Webhook Delivery Debugger is most useful during integration development, support reproduction, runbook authoring, and post-incident learning. It is deliberately **not** a hosted webhook gateway or production retry service.

## Try the two-minute investigation

You need Python 3.11 or newer.

```bash
git clone https://github.com/Emmanuelasika/webhook-delivery-debugger.git
cd webhook-delivery-debugger
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
webhooklab serve --port 8080
```

Leave the receiver running. In a second terminal:

```bash
webhooklab chaos payment.succeeded --duplicate
```

The sender prints one line per attempt:

```json
{"http_status": 202, "response": {"accepted": true, "event_id": "…", "outcome": "processed", "payload_sha256": "…"}}
{"http_status": 202, "response": {"accepted": true, "event_id": "…", "outcome": "duplicate", "payload_sha256": "…"}}
```

Now inspect the aggregate ledger:

```bash
webhooklab inspect
```

```json
{
  "delivery_attempts": 2,
  "duplicate_rate": 0.5,
  "outcomes": [
    {"count": 1, "outcome": "processed"},
    {"count": 1, "outcome": "duplicate"}
  ],
  "unique_events": 1
}
```

The useful result is not merely “both requests returned 202.” It is that the receiver acknowledged the retry while claiming the event only once. That is the behavior I want before attaching real business work.

Open:

- `http://127.0.0.1:8080` for the delivery ledger
- `http://127.0.0.1:8080/docs` for the generated API explorer
- `http://127.0.0.1:8080/health` for receiver and retention guarantees

## A realistic incident: “the invoice was fulfilled twice”

Suppose a merchant reports that `payment.succeeded` triggered fulfillment twice. Their webhook provider retried after a network timeout, but the provider dashboard only shows two successful deliveries.

### 1. Establish the control

```bash
webhooklab send payment.succeeded
```

Expected: `202` and `outcome: "processed"`. This proves the event envelope, timestamp, signature construction, and receiver are compatible.

### 2. Reproduce provider retry behavior

```bash
webhooklab chaos payment.succeeded \
  --event-id 6fbc2c2f-c3da-40f8-bdf6-a6b494a3cdf0 \
  --duplicate
```

Expected:

```text
attempt 1 → HTTP 202 → processed
attempt 2 → HTTP 202 → duplicate
```

The same raw body produces the same SHA-256 digest. Inside one SQLite transaction, the first delivery creates the event claim and both attempts are written to the ledger. The second delivery cannot claim the event again.

### 3. Rule out an event-ID collision

An ordinary duplicate has the same ID **and** the same body digest. A reused ID with changed content is materially different. The API returns `409` for that condition:

```bash
EVENT_ID=6fbc2c2f-c3da-40f8-bdf6-a6b494a3cdf0

# First body: amount 4200
BODY_A='{"id":"'$EVENT_ID'","type":"payment.succeeded","created_at":"2026-07-29T09:30:00Z","data":{"amount":4200}}'

# A support script can sign and post BODY_A, then repeat with amount 8400.
# The second request is classified as id_collision, not duplicate.
```

For an executable version of this exact condition, see
[`test_same_event_id_with_different_payload_is_collision`](tests/test_api.py).

### 4. Inspect without copying customer data

```bash
webhooklab inspect 6fbc2c2f-c3da-40f8-bdf6-a6b494a3cdf0
```

The result contains event type, first-seen time, payload digest, and every classified attempt. It does not contain the `data` object.

### 5. Close the support loop

The evidence now separates two failure domains:

- If the second attempt is `duplicate`, the receiving application must ensure business work happens only after the event claim succeeds.
- If the second attempt is `id_collision`, the sender or fixture generator reused an identifier for different content.
- If both attempts are `processed` in the production system but the debugger classifies the second as `duplicate`, production likely lacks an atomic idempotency claim or performs side effects before claiming.

That is a much tighter escalation than “webhooks might be firing twice.”

## Failure recipes

### Prove bad signatures never reach application parsing

```bash
webhooklab chaos customer.updated --invalid-signature
# {"http_status": 400, "response": {"detail": "Invalid or stale webhook signature"}}

webhooklab inspect
# delivery_attempts is unchanged
```

The receiver verifies the signature over the exact raw body before Pydantic parses the event. A rejected request is therefore absent from the accepted-delivery ledger.

### Prove timestamp tolerance is active

```bash
webhooklab chaos invoice.created --stale
# HTTP 400: timestamp is 600 seconds old; default tolerance is 300 seconds
```

The timestamp is included in the signed message, so changing it after signing also invalidates the request.

### Surface ordering assumptions

```bash
webhooklab chaos subscription.updated --out-of-order
```

This sends a `customer.updated` fixture whose `created_at` is ten seconds in the future **before** the requested event. Webhook Delivery Debugger records the order; it does not impose a universal ordering policy. That decision belongs to the consuming domain—for example, comparing provider object versions or authoritative timestamps.

### Probe a known event ID

```bash
webhooklab replay 6fbc2c2f-c3da-40f8-bdf6-a6b494a3cdf0
```

`replay` creates a new `replayed.event` body with the supplied ID. It is a collision probe, not a byte-for-byte reconstruction of a payload that the debugger intentionally did not retain. If that ID already belongs to a different digest, expect `409`.

## What happens inside the receiver

```text
raw HTTP body
    │
    ├─ read timestamp + signature headers
    │
    ├─ HMAC-SHA256(secret, timestamp + "." + body)
    │      └─ reject stale/missing/mismatched signature with 400
    │
    ├─ validate the event envelope
    │      └─ reject malformed events with 422
    │
    ├─ SHA-256 the raw body
    │
    └─ BEGIN IMMEDIATE transaction
           ├─ unseen ID                       → processed
           ├─ known ID + matching digest      → duplicate
           └─ known ID + different digest     → id_collision / 409
                    │
                    └─ append attempt metadata; never store body
```

Two tables serve different questions:

- `events` is the unique event claim: ID, type, first-seen time, and original digest.
- `attempts` is the delivery history: one row per accepted request, including outcome, status, duration, and digest.

SQLite runs in WAL mode. `BEGIN IMMEDIATE` serializes competing claims before the lookup and insert, avoiding the familiar “check, then insert” race.

More detail: [`docs/architecture.md`](docs/architecture.md).

## Command and API reference

| Command | What it actually does |
| --- | --- |
| `webhooklab serve --port 8080` | Starts Uvicorn on loopback with the receiver, ledger UI, and API docs. |
| `webhooklab send <type> [--event-id UUID]` | Generates one valid provider-neutral fixture, signs it, and sends it. |
| `webhooklab chaos <type> --duplicate` | Sends the exact same generated event twice. |
| `webhooklab chaos <type> --out-of-order` | Prepends a future-dated `customer.updated` fixture. |
| `webhooklab chaos <type> --invalid-signature` | Replaces the HMAC with `invalid`. Applies to every generated attempt. |
| `webhooklab chaos <type> --stale` | Signs with a timestamp 600 seconds in the past. |
| `webhooklab replay <event-id>` | Sends a fresh `replayed.event` fixture using a known ID. |
| `webhooklab inspect` | Prints unique event count, attempt count, duplicate rate, and outcome counts. |
| `webhooklab inspect <event-id>` | Prints the event claim and its complete attempt history. |

| Endpoint | Purpose |
| --- | --- |
| `POST /api/webhooks` | Verify, validate, digest, claim, and classify an event. |
| `GET /api/deliveries?outcome=duplicate` | Read recent attempts, optionally filtered by outcome. |
| `GET /api/events/{event_id}` | Read one event claim and all its attempts. |
| `GET /api/stats` | Read aggregate counts and duplicate rate. |
| `GET /health` | Report storage, verification, and retention posture. |

Environment variables:

```bash
export WEBHOOKLAB_SIGNING_SECRET='replace-this-for-any-shared-environment'
export WEBHOOKLAB_URL='http://127.0.0.1:8080'
export WEBHOOKLAB_DATABASE='/tmp/webhooklab-investigation.sqlite3'
```

## What this lab proves—and what it does not

**It does prove**

- timestamped HMAC verification over the raw bytes;
- constant-time signature comparison;
- an atomic, digest-aware event claim;
- duplicate versus collision classification;
- digest-only evidence retention;
- deterministic failure reproduction through a CLI.

**It does not claim**

- provider-specific signature compatibility;
- a production-grade queue, retry scheduler, or dead-letter store;
- distributed idempotency across several database nodes;
- business-level ordering or exactly-once side effects;
- payload recovery after receipt;
- authentication for the read-only ledger API.

In production I would return quickly after a durable claim, enqueue business work, add authentication and retention controls to operational endpoints, use a managed transactional store, and emit structured metrics/traces. “Exactly once” is not a property of HTTP delivery; the practical target is at-least-once delivery plus idempotent effects.

## Verification

```bash
python -m ruff check .
python -m compileall -q app
python -m pytest -q
docker build -t webhooklab .
docker run --rm -p 8080:8080 webhooklab
```

The test suite covers accepted signatures, rejected signatures, stale timestamps, duplicate classification, ID collisions, payload non-retention, filtered delivery reads, and the GitHub Pages artifact. CI runs against Python 3.11 and 3.12 and smoke-tests the container through `/health`.

## Project map

```text
app/
├── cli.py          # fixture construction and failure controls
├── main.py         # HTTP boundary and event validation
├── security.py     # HMAC signing and timestamp verification
├── store.py        # transactional event claims and attempt ledger
└── static/         # local operator ledger
docs/
├── index.html      # public, interactive incident walkthrough
├── site.css
└── architecture.md
tests/
├── test_api.py
└── test_site.py
```

If you find a security issue, please use the private reporting path in
[`SECURITY.md`](SECURITY.md). For changes, start with
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Why I made it

Support engineering is often evidence engineering. The fastest route through an integration incident is a reproduction that is small enough to understand, safe enough to share, and precise enough to change someone’s mind. Webhook Delivery Debugger is my version of that reproduction for webhook delivery.

— [Emmanuel Asika](https://github.com/Emmanuelasika)

Released under the [MIT License](LICENSE).
