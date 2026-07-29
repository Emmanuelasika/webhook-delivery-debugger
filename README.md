<div align="center">

# WebhookLab

**Make webhook failures reproducible before they become a support escalation.**

[![CI](https://github.com/Emmanuelasika/WebhookLab/actions/workflows/ci.yml/badge.svg)](https://github.com/Emmanuelasika/WebhookLab/actions/workflows/ci.yml)
[![Pages](https://github.com/Emmanuelasika/WebhookLab/actions/workflows/pages.yml/badge.svg)](https://emmanuelasika.github.io/WebhookLab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-1.1.0-6f42c1.svg)](CHANGELOG.md)

</div>

WebhookLab is a provider-neutral local webhook reliability lab. It sends signed
fixtures, verifies timestamped HMAC signatures, prevents duplicate processing,
and exposes a small delivery ledger for support investigations.

**[Explore the interactive project site →](https://emmanuelasika.github.io/WebhookLab/)**

## Failure modes covered

| Scenario | What WebhookLab proves |
| --- | --- |
| Invalid or stale signature | Rejected before payload processing. |
| Duplicate delivery | Acknowledged but not processed twice. |
| Out-of-order fixture | Reproduced through the chaos CLI. |
| Reused ID with changed body | Recorded as an ID collision and rejected with `409`. |
| Delivery troubleshooting | Operator can inspect the local, read-only ledger. |

## Quick start

```bash
git clone https://github.com/Emmanuelasika/WebhookLab.git
cd webhooklab
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m app.cli serve --port 8080
```

In another terminal:

```bash
python -m app.cli send payment.succeeded
python -m app.cli chaos payment.succeeded --duplicate --out-of-order
```

Open `http://127.0.0.1:8080` for the delivery ledger and `/docs` for the API.

## Security model

1. The sender computes `HMAC-SHA256(timestamp + "." + body)`.
2. The receiver validates the timestamp tolerance and compares signatures in
   constant time.
3. The receiver writes an event ID only once, preventing replay from invoking
   business work twice.
4. The receiver immediately returns `202`; real business work would move to a
   durable queue.

> [!CAUTION]
> The default secret is for local development only. Set
> `WEBHOOKLAB_SIGNING_SECRET` for every non-demo environment and do not use the
> local SQLite ledger as production infrastructure.

## Commands

| Command | Description |
| --- | --- |
| `webhooklab serve --port 8080` | Start the receiver. |
| `webhooklab send <event-type>` | Send a valid signed fixture. |
| `webhooklab chaos <event-type> --duplicate --out-of-order` | Exercise duplicate and ordering behavior. |
| `webhooklab chaos <event-type> --invalid-signature` | Confirm rejection behavior. |
| `webhooklab replay <event-id>` | Demonstrate safe duplicate replay handling. |
| `webhooklab inspect [event-id]` | Inspect aggregate stats or one event’s attempts. |

## Quality gates

```bash
python -m compileall -q app
python -m pytest -q
docker build -t webhooklab .
```

The included CI workflow runs compilation and tests on every push and pull
request. The ledger retains event metadata and SHA-256 payload digests, never
payload bodies. See [the architecture note](docs/architecture.md) and
[SECURITY.md](SECURITY.md) before reporting vulnerabilities.

## License

Released under the [MIT License](LICENSE).
