"""Shared SQLite connection helper for the ranking engine prototype."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "rankingapp.db"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit off; we manage BEGIN/COMMIT explicitly
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
