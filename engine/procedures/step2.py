"""
Port of dbo_sp_Calculate_Ranking_Step2_DataPreparationforNewRun.sql: purges stale
placeholder rows for the target week, resets best-result flags on existing results, and
loads new results staged in new_events_results into players_events_results_master.
"""

import sqlite3

from engine.constants import RESULT_VALIDITY_YEARS
from engine.step_runner import StepCounts


def sp_Calculate_Ranking_Step2_DataPreparationforNewRun(
    conn: sqlite3.Connection, *, category_code: str, year: int, month: int, week: int,
    run_id: int, counts: StepCounts,
) -> None:
    # Defensive check the legacy procedure never had (a documented improvement, not a port):
    # reject unrecognized ranking_category_code values before they enter the book of record,
    # so a bad import fails loudly and traceably here rather than corrupting main_ranking later.
    bad_categories = conn.execute(
        "SELECT DISTINCT n.ranking_category_code FROM new_events_results n "
        "WHERE n.category_code = ? AND NOT EXISTS ("
        "  SELECT 1 FROM ranking_categories rc "
        "  WHERE rc.category_code = n.category_code AND rc.ranking_category_code = n.ranking_category_code)",
        (category_code,),
    ).fetchall()
    if bad_categories:
        codes = ", ".join(r[0] for r in bad_categories)
        raise ValueError(
            f"new_events_results contains unrecognized ranking_category_code(s) for category "
            f"{category_code!r}: {codes}. Fix the import data before re-running the calculation."
        )

    deleted = conn.execute(
        "DELETE FROM main_ranking WHERE category_code=? AND ranking_year=? AND ranking_month=? AND ranking_week=?",
        (category_code, year, month, week),
    ).rowcount
    counts.deleted += max(deleted, 0)

    updated = conn.execute(
        "UPDATE players_events_results_master SET player_best_ranking_result_number=0, "
        "best_result_no_sen_you=0, excluded_due_to_zero_point_penalty=0 "
        "WHERE category_code=? AND active=1",
        (category_code,),
    ).rowcount
    counts.updated += max(updated, 0)

    inserted = conn.execute(
        """
        INSERT INTO players_events_results_master
            (competitor_id, event_id, sub_event_code, ranking_category_code, result_position,
             ranking_points, ranking_year, ranking_month, ranking_week, expiry_year, expiry_month,
             expiry_week, active, zero_point_penalty, age_category_code, category_code,
             organization_code, ranking_run_id_created)
        SELECT
            n.competitor_id, n.event_id, n.sub_event_code, n.ranking_category_code, n.result_position,
            COALESCE(n.ranking_points, 0), ?, ?, ?, ? + ?, ?, ?,
            1, n.zero_point_penalty, n.age_category_code, n.category_code, n.organization_code, ?
        FROM new_events_results n
        WHERE n.category_code = ?
          AND NOT EXISTS (
              SELECT 1 FROM players_events_results_master p
              WHERE p.competitor_id = n.competitor_id AND p.event_id = n.event_id
                AND p.ranking_category_code = n.ranking_category_code AND p.category_code = n.category_code
          )
        """,
        (year, month, week, year, RESULT_VALIDITY_YEARS, month, week, run_id, category_code),
    ).rowcount
    counts.inserted += max(inserted, 0)
    counts.message = f"deleted={deleted} reset={updated} inserted={inserted}"
