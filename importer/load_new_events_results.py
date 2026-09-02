"""
Result import loader -- the prototype's stand-in for the legacy 7-step TTU-driven import
chain (SP_Import_Step1..6, SP_SyncZPPNonParticipentPlayers, sp_Import_Web_EventsResults).

NOTE (documented limitation, per the approved plan): the legacy points/position derivation
lives inside a table-valued function, ufnGetEventResultsForRanking_stat, whose body is not
present in the exported SPS/ folder -- only its calling pattern is visible. Rather than
guess at its internals, this loader computes ranking_points directly from the two reference
tables that ARE fully documented: result_position (Position -> canonical round code) and
ranking_calc_main (round code -> points, by category/age-category/ranking-category/event
type). This is a reasonable, testable reconstruction, not a guaranteed byte-for-byte port.

Input file format: a flat CSV, one row per player-per-event result (folder note: this is a
synthetic "result import file" shaped like the legacy NewEventsResults/PlayersEventsResults
records, not the raw multi-file OVR export format -- see sample_data/README.md).
Columns: event_id, event_name, event_type_general_code, event_type_code, ranking_year,
ranking_month, ranking_week, competitor_id, player_name, dob, gender, country_code,
age_category_code, is_retired, sub_event_code, ranking_category_code, category_code,
result_position, matches_played, matches_won, matches_lost, qualifier, zero_point_penalty
"""

import csv
import sqlite3
from pathlib import Path

# result_position values that have a matching column in ranking_calc_main.
POINTS_COLUMNS = {
    "W": "w", "F": "f", "SF": "sf", "QF": "qf",
    "R16": "r16", "R32": "r32", "R64": "r64", "R128": "r128", "R256": "r256",
    "QUAL": "qual", "QER": "qer",
    "QR4": "qr4", "QR3": "qr3", "QR2": "qr2", "QR1": "qr1",
    "G4L": "g4l", "G3L": "g3l", "G2L": "g2l", "GL": "gl",
}


def compute_points(conn: sqlite3.Connection, *, category_code, age_category_code,
                    ranking_category_code, event_type_general_code, result_position) -> float:
    col = POINTS_COLUMNS.get(result_position.upper())
    if col is None:
        return 0.0
    row = conn.execute(
        f"SELECT {col} FROM ranking_calc_main WHERE category_code=? AND age_category_code=? "
        f"AND ranking_category_code=? AND event_type=?",
        (category_code, age_category_code, ranking_category_code, event_type_general_code),
    ).fetchone()
    return float(row[0]) if row is not None else 0.0


def _upsert_competitor(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        "INSERT INTO competitors (competitor_id, player_name, dob, gender, country_code, "
        "nationality_code, age_category_code, is_retired) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(competitor_id) DO NOTHING",
        (
            int(row["competitor_id"]), row["player_name"], row.get("dob") or None, row.get("gender") or None,
            row.get("country_code") or None, row.get("country_code") or None,
            row.get("age_category_code") or None, int(row.get("is_retired") or 0),
        ),
    )


def _upsert_event(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_type_general_code, event_type_code, "
        "ranking_year, ranking_month, ranking_week) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(event_id) DO NOTHING",
        (
            int(row["event_id"]), row["event_name"], row["event_type_general_code"], row.get("event_type_code") or None,
            int(row["ranking_year"]), int(row["ranking_month"]), int(row["ranking_week"]),
        ),
    )


def load_new_events_results(conn: sqlite3.Connection, csv_path: Path) -> dict:
    """Loads one result file into competitors / events / new_events_results. Returns row counts."""
    csv_path = Path(csv_path)
    counts = {"competitors_upserted": 0, "events_upserted": 0, "results_inserted": 0}

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    conn.execute("BEGIN")
    try:
        for row in rows:
            _upsert_competitor(conn, row)
            _upsert_event(conn, row)

            zero_point_penalty = int(row.get("zero_point_penalty") or 0)
            if zero_point_penalty:
                points = 0.0  # ZPP results always carry 0 points, per regulation, regardless of round reached
            else:
                points = compute_points(
                    conn,
                    category_code=row["category_code"],
                    age_category_code=row["age_category_code"],
                    ranking_category_code=row["ranking_category_code"],
                    event_type_general_code=row["event_type_general_code"],
                    result_position=row["result_position"],
                )

            conn.execute(
                "INSERT INTO new_events_results "
                "(event_id, competitor_id, sub_event_code, result_position, matches_played, matches_won, "
                " matches_lost, qualifier, zero_point_penalty, ranking_category_code, age_category_code, "
                " category_code, ranking_points) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(row["event_id"]), int(row["competitor_id"]), row["sub_event_code"], row["result_position"],
                    int(row.get("matches_played") or 0), int(row.get("matches_won") or 0),
                    int(row.get("matches_lost") or 0), int(row.get("qualifier") or 0),
                    zero_point_penalty, row["ranking_category_code"],
                    row["age_category_code"], row["category_code"], points,
                ),
            )
            counts["results_inserted"] += 1
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

    counts["competitors_upserted"] = len({int(r["competitor_id"]) for r in rows})
    counts["events_upserted"] = len({int(r["event_id"]) for r in rows})
    return counts


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
