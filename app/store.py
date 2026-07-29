"""Transactional SQLite ledger for webhook delivery debugging.

Payload bodies are intentionally not persisted. The ledger stores a SHA-256
digest plus event metadata and one row per delivery attempt.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Attempt:
    event_id: str
    event_type: str
    received_at: str
    outcome: str
    http_status: int
    duration_ms: int
    payload_sha256: str
    detail: str = ""


class DeliveryStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                    process_count INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, received_at TEXT NOT NULL,
                    outcome TEXT NOT NULL, http_status INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL, payload_sha256 TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_attempts_received ON attempts(received_at DESC);
                CREATE INDEX IF NOT EXISTS idx_attempts_event ON attempts(event_id, id);
            """)

    def record(self, attempt: Attempt) -> str:
        """Atomically claim a new event and record every delivery attempt."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT payload_sha256 FROM events WHERE event_id = ?", (attempt.event_id,)).fetchone()
            if existing is None:
                outcome = attempt.outcome
                connection.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?, 1)",
                    (attempt.event_id, attempt.event_type, attempt.received_at, attempt.payload_sha256),
                )
            elif existing["payload_sha256"] != attempt.payload_sha256:
                outcome = "id_collision"
            else:
                outcome = "duplicate"
            values = asdict(attempt)
            values["outcome"] = outcome
            connection.execute(
                """INSERT INTO attempts
                (event_id, event_type, received_at, outcome, http_status, duration_ms, payload_sha256, detail)
                VALUES (:event_id, :event_type, :received_at, :outcome, :http_status, :duration_ms, :payload_sha256, :detail)""",
                values,
            )
        return outcome

    def recent(self, limit: int = 50, outcome: str | None = None) -> list[dict[str, object]]:
        query, values = "SELECT * FROM attempts", []
        if outcome:
            query += " WHERE outcome = ?"; values.append(outcome)
        query += " ORDER BY id DESC LIMIT ?"; values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def event(self, event_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            event = connection.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
            attempts = connection.execute("SELECT * FROM attempts WHERE event_id = ? ORDER BY id", (event_id,)).fetchall()
        return {**dict(event), "attempts": [dict(row) for row in attempts]} if event else None

    def stats(self) -> dict[str, object]:
        with self.connect() as connection:
            total_events = connection.execute("SELECT count(*) FROM events").fetchone()[0]
            total_attempts = connection.execute("SELECT count(*) FROM attempts").fetchone()[0]
            outcomes = connection.execute("SELECT outcome, count(*) AS count FROM attempts GROUP BY outcome ORDER BY count DESC").fetchall()
        return {"unique_events": total_events, "delivery_attempts": total_attempts, "duplicate_rate": round((total_attempts - total_events) / total_attempts, 4) if total_attempts else 0.0,
                "outcomes": [dict(row) for row in outcomes]}
