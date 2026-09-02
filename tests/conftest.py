"""
Shared pytest fixtures for the Azure SQL backend. Unlike the old SQLite prototype (a fresh
file-backed DB per test), every test now shares one already-deployed database (either the CI
ephemeral SQL Server container, or a local/dev Azure SQL database pointed to by .env) and gets
isolation via dbo.sp_ResetDemoData, which clears every business/audit/run table (imports,
competitors, events, runs, validations) while leaving reference data and RBAC (app_user/
app_role) untouched -- run both before and after each test so a prior test's leftovers can
never leak into the next one.
"""

import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from engine.db import get_connection  # noqa: E402

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _reset(connection) -> None:
    connection.cursor().execute("{CALL dbo.sp_ResetDemoData}")


@pytest.fixture()
def conn():
    connection = get_connection()
    _reset(connection)
    yield connection
    _reset(connection)
    connection.close()


def fixture_csv(name: str) -> Path:
    return SAMPLE_DATA / name / "result_file.csv"


def fixture_setup_sql(name: str) -> str | None:
    path = SAMPLE_DATA / name / "setup.sql"
    return path.read_text(encoding="utf-8") if path.exists() else None
