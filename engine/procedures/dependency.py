"""
Port of dbo_Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun.sql: confirms a Senior ranking
run for the same (year, month, week) has completed successfully before a Youth run may
proceed (matches RulesId 38, group 4 PreRequisitesValidation, param
CheckRunforCategoryCode='SEN'). Called explicitly by master.py as step 1 of
sp_Calculate_Ranking_YOU, before any write transaction is opened (see engine/master.py).
"""

import sqlite3

from engine.exceptions import DependencyNotMetError
from engine.step_runner import StepCounts


def Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun(
    conn: sqlite3.Connection, *, year: int, month: int, week: int, counts: StepCounts,
) -> None:
    row = conn.execute(
        "SELECT ranking_run_id FROM ranking_run WHERE category_code='SEN' AND ranking_year=? "
        "AND ranking_month=? AND ranking_week=? AND status='SUCCEEDED' ORDER BY ranking_run_id DESC LIMIT 1",
        (year, month, week),
    ).fetchone()
    if row is None:
        raise DependencyNotMetError(
            f"Senior Category Ranking Run should be completed for {year}-{month:02d} week {week} "
            f"before the Youth run can proceed."
        )
    counts.message = f"Senior run {row['ranking_run_id']} confirmed SUCCEEDED for this period"
