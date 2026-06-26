import json
import os
import sqlite3
from datetime import datetime, timezone

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "audit.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _connect() as conn:
        # fields note:
        # - event_type: classification, appeal_submitted, appeal_reviewed
        # - original_request_id: for appeal_submitted and appeal_reviewed, points to the original classification request
        # - text:  for classification, the text of the original content; for appeal_submitted and appeal_reviewed, the text of the appeal reason
        # - status: for classification, can be "classified" or "appealed"; for appeal_submitted, can be "pending" or "reviewed"; for appeal_reviewed, can be "final"
        # - final_classification: for appeal_reviewed, this is the re-evaluated classification, and can be "Human" or "AI"
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type           TEXT    NOT NULL,
                creator_id           TEXT    NOT NULL,
                content_id           TEXT    NOT NULL,
                request_id           TEXT    NOT NULL,
                original_request_id  TEXT,
                timestamp            TEXT    NOT NULL,
                text                 TEXT,
                text_length          INTEGER,
                llm_result           TEXT,
                stylometric_result   TEXT,
                final_classification TEXT,
                confidence           REAL,
                Status               TEXT
            )
        """)
        conn.commit()



_init_db()


def add_log(
    event_type: str,
    creator_id: str,
    content_id: str,
    request_id: str,
    original_request_id: str,
    text: str,
    llm_result: dict | None = None,
    stylometric_result: dict | None = None,
    final_classification: str | None = None,
    confidence: float | None = None,
    status: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                event_type, creator_id, content_id, request_id, original_request_id, timestamp,
                text, text_length, llm_result, stylometric_result,
                final_classification, confidence, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                creator_id,
                content_id,
                request_id,
                original_request_id,
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                text,
                len(text),
                json.dumps(llm_result) if llm_result is not None else None,
                json.dumps(stylometric_result) if stylometric_result is not None else None,
                final_classification,
                confidence,
                status,
            ),
        )
        conn.commit()

def _deserialize_row(row: dict) -> dict:
    """Lowercase all keys and parse JSON-encoded fields back to dicts."""
    row = {k.lower(): v for k, v in row.items()}
    for field in ("llm_result", "stylometric_result"):
        if row.get(field) is not None:
            row[field] = json.loads(row[field])
    return row


def get_entries_by_content_id(content_id: str) -> list[dict]:
    with _connect() as conn:
        cursor = conn.execute(
            "SELECT * FROM audit_log WHERE content_id = ? ORDER BY timestamp ASC",
            (content_id,),
        )
        return [_deserialize_row(dict(row)) for row in cursor.fetchall()]


def get_logs(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        cursor = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [_deserialize_row(dict(row)) for row in cursor.fetchall()]