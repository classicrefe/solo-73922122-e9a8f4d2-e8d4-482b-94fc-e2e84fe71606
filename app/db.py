"""SQLite connection and schema management."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ships (
    ship_code       TEXT PRIMARY KEY,
    revision        INTEGER NOT NULL,
    allocation_json TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holds (
    ship_code            TEXT NOT NULL,
    hold_no              INTEGER NOT NULL,
    certified_total_kg   INTEGER NOT NULL CHECK (certified_total_kg >= 0),
    PRIMARY KEY (ship_code, hold_no),
    FOREIGN KEY (ship_code) REFERENCES ships(ship_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batches (
    ship_code   TEXT NOT NULL,
    batch_index INTEGER NOT NULL,
    batch_no    TEXT NOT NULL,
    PRIMARY KEY (ship_code, batch_index),
    FOREIGN KEY (ship_code) REFERENCES ships(ship_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS weight_rows (
    ship_code   TEXT NOT NULL,
    line_key    TEXT NOT NULL,
    line_no_json TEXT NOT NULL,
    batch_index INTEGER NOT NULL,
    row_order   INTEGER NOT NULL,
    hold_no     INTEGER NOT NULL,
    weight_text TEXT NOT NULL,
    PRIMARY KEY (ship_code, line_key),
    FOREIGN KEY (ship_code) REFERENCES ships(ship_code) ON DELETE CASCADE,
    FOREIGN KEY (ship_code, batch_index)
        REFERENCES batches(ship_code, batch_index) ON DELETE CASCADE,
    FOREIGN KEY (ship_code, hold_no)
        REFERENCES holds(ship_code, hold_no)
);

CREATE INDEX IF NOT EXISTS idx_weight_rows_batch
    ON weight_rows(ship_code, batch_index, row_order);
"""


def resolve_db_path(db_path: str | os.PathLike[str] | None = None) -> Path:
    raw = db_path or os.getenv("DB_PATH") or "data/weights.db"
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def connect_db(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(path),
        timeout=15.0,
        check_same_thread=False,
        # Explicit BEGIN IMMEDIATE/commit/rollback in the service layer.
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers/getters proceed while another ship is committing.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(db_path: str | os.PathLike[str] | None = None) -> None:
    conn = connect_db(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
