# Architecture

```text
fixture CLI ──► timestamped HMAC ──► receiver ──► event claim
                                      │              │
                                      │              └─ unique event digest
                                      └──────────────── attempt ledger
                                                          │
                                               dashboard / inspect CLI
```

The receiver validates signature and timestamp before parsing the event. SQLite
uses WAL mode and `BEGIN IMMEDIATE` to make event claiming atomic. Payload bodies
are not stored; only their SHA-256 digests are retained.

An event ID with the same digest is a duplicate. The same event ID with a
different digest is an ID collision and returns `409`.
