"""
Port of the "Null RANKINGPOINTS Validation" check referenced in sp_Validation_NULL_RANKINGPOINTS_CurrentweekRanking.sql
and confirmed via real dbo_Ranking_Validation_Summary.csv sample rows. Checked against
new_events_results (nullable ranking_points) since players_events_results_master enforces
NOT NULL at the schema level and can never carry a null value.
"""

import sqlite3


def check(conn: sqlite3.Connection, *, category_code: str) -> list[dict]:
    rows = conn.execute(
        "SELECT new_event_result_id, competitor_id, event_id FROM new_events_results "
        "WHERE category_code = ? AND ranking_points IS NULL",
        (category_code,),
    ).fetchall()

    if not rows:
        return [{
            "check_name": "Null RANKINGPOINTS Validation", "passed": 1,
            "remarks": "No null ranking_points found in new_events_results", "table_name": "new_events_results",
            "competitor_id": None, "event_id": None, "total_points": None, "main_ranking_points": None,
        }]

    return [
        {
            "check_name": "Null RANKINGPOINTS Validation", "passed": 0,
            "remarks": "ranking_points is NULL", "table_name": "new_events_results",
            "competitor_id": r["competitor_id"], "event_id": r["event_id"],
            "total_points": None, "main_ranking_points": None,
        }
        for r in rows
    ]
