"""
Port of the "Duplicated Results Validation" check (sp_Validation_DuplicatedResults_CurrentweekRanking.sql):
flags players_events_results_master rows that share the same natural key
(competitor_id, event_id, ranking_category_code) more than once while active.
"""

import sqlite3


def check(conn: sqlite3.Connection, *, category_code: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT competitor_id, event_id, ranking_category_code, COUNT(*) AS n
        FROM players_events_results_master
        WHERE category_code = ? AND active = 1
        GROUP BY competitor_id, event_id, ranking_category_code
        HAVING COUNT(*) > 1
        """,
        (category_code,),
    ).fetchall()

    if not rows:
        return [{
            "check_name": "Duplicated Results Validation", "passed": 1,
            "remarks": "No duplicate (competitor, event, ranking_category) rows found",
            "table_name": "players_events_results_master",
            "competitor_id": None, "event_id": None, "total_points": None, "main_ranking_points": None,
        }]

    return [
        {
            "check_name": "Duplicated Results Validation", "passed": 0,
            "remarks": f"{r['n']} active rows share this (competitor, event, ranking_category) key",
            "table_name": "players_events_results_master",
            "competitor_id": r["competitor_id"], "event_id": r["event_id"],
            "total_points": None, "main_ranking_points": None,
        }
        for r in rows
    ]
