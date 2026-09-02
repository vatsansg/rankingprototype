"""
Port of the final cleanup block inside dbo_sp_Calculate_Ranking.sql (not a separately named
legacy SP -- it is inline logic at the end of sp_Calculate_Ranking, extracted here as its
own named, auditable step): purges main_ranking rows that ended the run with 0 points, and
clears new_events_results for the category now that every row has been absorbed into
players_events_results_master. Without this, stale or bad rows accumulate in
new_events_results indefinitely and can permanently block future runs.
"""

import sqlite3

from engine.step_runner import StepCounts


def sp_Calculate_Ranking_FinalizeRun(
    conn: sqlite3.Connection, *, category_code: str, run_id: int, counts: StepCounts,
) -> None:
    deleted_zero = conn.execute(
        "DELETE FROM main_ranking WHERE ranking_run_id = ? AND ranking_points = 0", (run_id,)
    ).rowcount
    deleted_staging = conn.execute(
        "DELETE FROM new_events_results WHERE category_code = ?", (category_code,)
    ).rowcount

    counts.deleted += max(deleted_zero, 0) + max(deleted_staging, 0)
    counts.message = (
        f"purged {deleted_zero} zero-point main_ranking row(s), cleared {deleted_staging} "
        f"consumed new_events_results row(s) for {category_code}"
    )
