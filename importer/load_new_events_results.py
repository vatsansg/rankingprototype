"""
Result import loader -- reads the flat CSV import file (see sample_data/README.md) and bulk-
loads it into Azure SQL in one round trip via a table-valued parameter, calling
dbo.sp_ImportNewEventsResults (db/procedures/import/sp_ImportNewEventsResults.sql). All
points/position derivation and the competitors/events upsert now happen server-side inside
that stored procedure (dbo.fn_ComputeRankingPoints) -- this module's only job is parsing the
CSV into TVP rows and reading back the row counts from the procedure's trailing SELECT.

Input file format: a flat CSV, one row per player-per-event result. Columns: event_id,
event_name, event_type_general_code, event_type_code, ranking_year, ranking_month,
ranking_week, competitor_id, player_name, dob, gender, country_code, age_category_code,
is_retired, sub_event_code, ranking_category_code, category_code, result_position,
matches_played, matches_won, matches_lost, qualifier, zero_point_penalty
"""

from __future__ import annotations

import csv
from pathlib import Path

import pyodbc

# Column order MUST exactly match db/procedures/types/NewEventsResultTVP.sql.
# pyodbc has no TableValuedParam class -- a TVP is passed as a plain list with the type's
# name and schema prepended ahead of the row tuples (fixed in pyodbc 4.0.32, issue #595):
# [type_name, schema_name, row1, row2, ...]. See db/procedures/import/sp_ImportNewEventsResults.sql.
_TVP_TYPE_NAME = "NewEventsResultTVP"
_TVP_SCHEMA = "dbo"


def _int(value, default=0) -> int:
    return int(value) if value not in (None, "") else default


def _bit(value) -> int:
    return 1 if str(value or "0").strip() not in ("", "0", "False", "false") else 0


def _row_to_tvp_tuple(row: dict) -> tuple:
    return (
        int(row["event_id"]), row["event_name"], row["event_type_general_code"], row.get("event_type_code") or None,
        int(row["ranking_year"]), int(row["ranking_month"]), int(row["ranking_week"]),
        int(row["competitor_id"]), row["player_name"], row.get("dob") or None, row.get("gender") or None,
        row.get("country_code") or None, row["age_category_code"], _bit(row.get("is_retired")),
        row["sub_event_code"], row["ranking_category_code"], row["category_code"],
        row["result_position"], _int(row.get("matches_played")), _int(row.get("matches_won")),
        _int(row.get("matches_lost")), _bit(row.get("qualifier")), _bit(row.get("zero_point_penalty")),
    )


def load_new_events_results(conn: pyodbc.Connection, csv_path: Path, *, imported_by: str = "web-ui") -> dict:
    """Loads one result file via dbo.sp_ImportNewEventsResults. Returns row counts."""
    csv_path = Path(csv_path)
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [_row_to_tvp_tuple(r) for r in reader]

    tvp = [_TVP_TYPE_NAME, _TVP_SCHEMA, *rows]
    cur = conn.cursor()
    cur.execute(
        "{CALL dbo.sp_ImportNewEventsResults(?, ?, ?, ?, ?)}",
        tvp, imported_by, None, None, None,
    )
    result = cur.fetchone()
    return {
        "competitors_upserted": result.competitors_upserted,
        "events_upserted": result.events_upserted,
        "results_inserted": result.results_inserted,
    }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from engine.db import get_connection

    file_path = Path(sys.argv[1])
    conn = get_connection()
    try:
        result = load_new_events_results(conn, file_path)
        print(f"Imported {file_path.name}: {result}")
    finally:
        conn.close()
