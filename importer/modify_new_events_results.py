"""
Manual-modification stage for freshly-imported results, run after Import and before a
calculation starts. Edits new_events_results directly via stored procedures
(dbo.sp_SearchNewEventsResults, dbo.sp_UpdateNewEventResultPosition -- see
db/procedures/import/sp_SearchNewEventsResults_and_Update.sql), which also compute the
recomputed ranking_points and log the change to new_events_results_modification_log.
"""

from __future__ import annotations

import pyodbc

# Selectable result-position codes shown in the edit form, in a sensible display order --
# must match the allow-list enforced inside sp_UpdateNewEventResultPosition.
EDITABLE_RESULT_POSITIONS = [
    "W", "F", "SF", "QF", "R16", "R32", "R64", "R128", "R256",
    "QUAL", "QER", "QR1", "QR2", "QR3", "QR4", "GL", "G2L", "G3L", "G4L",
]


def search_new_events_results(
    conn: pyodbc.Connection, *, category_code: str | None = None,
    player_name: str | None = None, country_code: str | None = None,
) -> list[pyodbc.Row]:
    cur = conn.cursor()
    cur.execute(
        "{CALL dbo.sp_SearchNewEventsResults(?, ?, ?)}",
        category_code, player_name, country_code,
    )
    return cur.fetchall()


def get_new_event_result(conn: pyodbc.Connection, new_event_result_id: int) -> pyodbc.Row | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT n.*, c.player_name, c.country_code, e.event_name, e.event_type_general_code
        FROM dbo.new_events_results n
        JOIN dbo.competitors c ON c.competitor_id = n.competitor_id
        JOIN dbo.events e ON e.event_id = n.event_id
        WHERE n.new_event_result_id = ?
        """,
        (new_event_result_id,),
    )
    return cur.fetchone()


def update_result_position(
    conn: pyodbc.Connection, *, new_event_result_id: int, new_result_position: str, modified_by: str,
) -> dict:
    """Updates result_position, recomputes ranking_points, and logs the change (all inside
    dbo.sp_UpdateNewEventResultPosition). Raises pyodbc.Error (THROW 51300/51301) on an
    unrecognized position or a missing row, matching the prior ValueError-raising contract
    closely enough for web/app.py's existing try/except Exception handling."""
    cur = conn.cursor()
    cur.execute(
        "{CALL dbo.sp_UpdateNewEventResultPosition(?, ?, ?, ?, ?)}",
        new_event_result_id, new_result_position, modified_by, None, None,
    )
    result = cur.fetchone()
    return {
        "old_result_position": result.old_result_position, "new_result_position": result.new_result_position,
        "old_ranking_points": result.old_ranking_points, "new_ranking_points": result.new_ranking_points,
    }
