"""
Port of dbo_sp_Rules_Set_Weekly_Events_ManualModifications.sql (rule alias
'ManualModifications', RulesId 71=SEN/72=YOU -- confirmed active in dbo_Rules.csv, group 2
order 1, i.e. runs first in ResultsSelection, before expiry/best-results/ZPP).

Applies operator-staged corrections from players_events_results_master_modified onto
players_events_results_master, then marks each modification row as applied so it is never
re-applied by a later run.
"""

import sqlite3

from engine.step_runner import StepCounts


def sp_Rules_Set_Weekly_Events_ManualModifications(
    conn: sqlite3.Connection, *, category_code: str, run_id: int, counts: StepCounts,
) -> None:
    pending = conn.execute(
        "SELECT * FROM players_events_results_master_modified WHERE category_code=? AND applied=0",
        (category_code,),
    ).fetchall()

    updated = 0
    for mod in pending:
        result = conn.execute(
            """
            UPDATE players_events_results_master
            SET result_position = COALESCE(?, result_position),
                ranking_points = COALESCE(?, ranking_points),
                expiry_year = COALESCE(?, expiry_year),
                expiry_month = COALESCE(?, expiry_month),
                expiry_week = COALESCE(?, expiry_week),
                active = COALESCE(?, active)
            WHERE competitor_id = ? AND event_id = ? AND ranking_category_code = ? AND category_code = ?
            """,
            (
                mod["modified_result_position"], mod["modified_ranking_points"],
                mod["modified_expiry_year"], mod["modified_expiry_month"], mod["modified_expiry_week"],
                mod["modified_active"],
                mod["competitor_id"], mod["event_id"], mod["ranking_category_code"], mod["category_code"],
            ),
        ).rowcount
        updated += max(result, 0)

        conn.execute(
            "UPDATE players_events_results_master_modified SET applied=1, applied_in_ranking_run_id=? "
            "WHERE player_modification_id=?",
            (run_id, mod["player_modification_id"]),
        )

    counts.updated += updated
    counts.message = f"applied {len(pending)} manual modification(s), {updated} row(s) updated"
