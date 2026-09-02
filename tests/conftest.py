"""Shared pytest fixtures: a fresh, isolated SQLite DB per test."""

import sqlite3
from pathlib import Path

import pytest

from db.init_db import build

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture()
def db_path(tmp_path) -> Path:
    path = tmp_path / "rankingapp_test.db"
    build(path)
    return path


@pytest.fixture()
def conn(db_path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


def fixture_csv(name: str) -> Path:
    return SAMPLE_DATA / name / "result_file.csv"


def fixture_setup_sql(name: str) -> str | None:
    path = SAMPLE_DATA / name / "setup.sql"
    return path.read_text(encoding="utf-8") if path.exists() else None
