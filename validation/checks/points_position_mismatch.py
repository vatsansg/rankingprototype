"""
Port of the MainRanking-vs-breakdown reconciliation check
(sp_Validation_MainRankingVsBreakDown_CurrentweekRanking.sql): confirms each main_ranking
row's ranking_points equals the sum of that competitor's counted (best_result_no_sen_you=1,
active=1) players_events_results_master rows for the same ranking category and run.
"""

import sqlite3


def check(conn: sqlite3.Connection, *, run_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT mr.main_ranking_id, mr.competitor_id, mr.ranking_category, mr.ranking_points AS main_points,
               COALESCE((
                   SELECT SUM(p.ranking_points) FROM players_events_results_master p
                   WHERE p.competitor_id = mr.competitor_id AND p.ranking_category_code = mr.ranking_category
                     AND p.category_code = mr.category_code AND p.active = 1 AND p.best_result_no_sen_you = 1
               ), 0) AS breakdown_points
        FROM main_ranking mr
        WHERE mr.ranking_run_id = ?
        """,
        (run_id,),
    ).fetchall()

    mismatches = [r for r in rows if abs((r["main_points"] or 0) - (r["breakdown_points"] or 0)) > 1e-9]

    if not mismatches:
        return [{
            "check_name": "MainRanking vs BreakDown Validation", "passed": 1,
            "remarks": f"All {len(rows)} main_ranking row(s) reconcile with their points breakdown",
            "table_name": "main_ranking", "competitor_id": None, "event_id": None,
            "total_points": None, "main_ranking_points": None,
        }]

    return [
        {
            "check_name": "MainRanking vs BreakDown Validation", "passed": 0,
            "remarks": f"main_ranking.ranking_points ({r['main_points']}) != breakdown sum ({r['breakdown_points']})",
            "table_name": "main_ranking", "competitor_id": r["competitor_id"], "event_id": None,
            "total_points": r["breakdown_points"], "main_ranking_points": r["main_points"],
        }
        for r in mismatches
    ]
