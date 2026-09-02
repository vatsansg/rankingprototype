"""
Manual-modification stage for freshly-imported results, run after Import and before a
calculation starts. Edits new_events_results directly (the raw import staging row) rather
than staging an override in players_events_results_master_modified, since that table only
takes effect once a calculation run has already seeded the book-of-record -- this needs to
apply before any run begins. Every edit is logged to new_events_results_modification_log
with the old and new result_position/ranking_points, who made it, and when.
"""

import sqlite3

from engine.step_runner import now_iso
from importer.load_new_events_results import POINTS_COLUMNS, compute_points

# Selectable result-position codes shown in the edit form, in a sensible display order.
EDITABLE_RESULT_POSITIONS = [
    "W", "F", "SF", "QF", "R16", "R32", "R64", "R128", "R256",
    "QUAL", "QER", "QR1", "QR2", "QR3", "QR4", "GL", "G2L", "G3L", "G4L",
]
assert set(EDITABLE_RESULT_POSITIONS) == set(POINTS_COLUMNS)


def search_new_events_results(
    conn: sqlite3.Connection, *, category_code: str | None = None,
    player_name: str | None = None, country_code: str | None = None,
) -> list[sqlite3.Row]:
    clauses = []
    params: list = []
    if category_code:
        clauses.append("n.category_code = ?")
        params.append(category_code)
    if player_name:
        clauses.append("c.player_name LIKE ?")
        params.append(f"%{player_name}%")
    if country_code:
        clauses.append("c.country_code LIKE ?")
        params.append(f"%{country_code}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(
        f"""
        SELECT n.new_event_result_id, n.competitor_id, c.player_name, c.country_code,
               n.event_id, e.event_name, e.event_type_general_code, n.sub_event_code,
               n.ranking_category_code, n.category_code, n.age_category_code,
               n.result_position, n.ranking_points, n.zero_point_penalty
        FROM new_events_results n
        JOIN competitors c ON c.competitor_id = n.competitor_id
        JOIN events e ON e.event_id = n.event_id
        {where}
        ORDER BY n.new_event_result_id
        """,
        params,
    ).fetchall()


def get_new_event_result(conn: sqlite3.Connection, new_event_result_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT n.*, c.player_name, c.country_code, e.event_name, e.event_type_general_code
        FROM new_events_results n
        JOIN competitors c ON c.competitor_id = n.competitor_id
        JOIN events e ON e.event_id = n.event_id
        WHERE n.new_event_result_id = ?
        """,
        (new_event_result_id,),
    ).fetchone()


def update_result_position(
    conn: sqlite3.Connection, *, new_event_result_id: int, new_result_position: str, modified_by: str,
) -> dict:
    """Updates result_position, recomputes ranking_points from ranking_calc_main, and logs the change."""
    if new_result_position not in EDITABLE_RESULT_POSITIONS:
        raise ValueError(f"Unrecognized result position {new_result_position!r}")

    row = get_new_event_result(conn, new_event_result_id)
    if row is None:
        raise ValueError(f"new_events_results row {new_event_result_id} not found")

    if row["zero_point_penalty"]:
        new_points = 0.0  # ZPP results always carry 0 points, regardless of round reached
    else:
        new_points = compute_points(
            conn,
            category_code=row["category_code"],
            age_category_code=row["age_category_code"],
            ranking_category_code=row["ranking_category_code"],
            event_type_general_code=row["event_type_general_code"],
            result_position=new_result_position,
        )

    old_position, old_points = row["result_position"], row["ranking_points"]
    modified_at = now_iso()

    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE new_events_results SET result_position=?, ranking_points=? WHERE new_event_result_id=?",
            (new_result_position, new_points, new_event_result_id),
        )
        conn.execute(
            "INSERT INTO new_events_results_modification_log "
            "(new_event_result_id, competitor_id, event_id, old_result_position, new_result_position, "
            " old_ranking_points, new_ranking_points, modified_by, modified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_event_result_id, row["competitor_id"], row["event_id"],
                old_position, new_result_position, old_points, new_points, modified_by, modified_at,
            ),
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

    return {
        "old_result_position": old_position, "new_result_position": new_result_position,
        "old_ranking_points": old_points, "new_ranking_points": new_points,
    }
