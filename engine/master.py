"""
Master orchestration -- thin Python wrappers around the two per-category T-SQL master
stored procedures (db/procedures/master/sp_Calculate_Ranking_SEN.sql /
sp_Calculate_Ranking_YOU.sql). All step sequencing, audit logging, and error handling now
lives in T-SQL; Python's job is just to EXEC the master procedure and translate its single
returned result row into either a run_id (success) or a RankingRunFailed exception (failure),
preserving the exact same call signatures and exception-based control flow that web/app.py
and the test suite already depend on.
"""

from __future__ import annotations

from engine.db import get_connection
from engine.exceptions import DependencyNotMetError, RankingRunFailed


def _exec_master_procedure(proc_name: str, year: int, month: int, week: int, *,
                            triggered_by: str, mode: str = "normal", run_id: int | None = None,
                            conn=None) -> int:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"{{CALL {proc_name}(?, ?, ?, ?, ?, ?)}}",
            year, month, week, triggered_by, mode, run_id,
        )
        row = cur.fetchone()
        result_run_id = row.ranking_run_id
        status = row.status
        failed_step_seq = row.failed_step_seq
        failed_step_name = row.failed_step_name
        error_message = row.error_message

        if status == "SUCCEEDED":
            return result_run_id

        original: Exception
        if status == "ABORTED_DEPENDENCY":
            original = DependencyNotMetError(error_message)
        else:
            original = RuntimeError(error_message)
        raise RankingRunFailed(result_run_id, failed_step_seq, failed_step_name, original)
    finally:
        if owns_conn:
            conn.close()


def sp_Calculate_Ranking_SEN(
    year: int, month: int, week: int, *, triggered_by: str, mode: str = "normal",
    run_id: int | None = None, conn=None,
) -> int:
    """
    Direct, category-split successor of the legacy parameterized sp_Calculate_Ranking.
    run_id=None => on-demand (the T-SQL procedure creates a fresh RUNNING row).
    run_id=<int> => this is a 'Run Now' on a previously scheduled PENDING row.
    """
    return _exec_master_procedure(
        "dbo.sp_Calculate_Ranking_SEN", year, month, week,
        triggered_by=triggered_by, mode=mode, run_id=run_id, conn=conn,
    )


def sp_Calculate_Ranking_YOU(
    year: int, month: int, week: int, *, triggered_by: str, mode: str = "normal",
    run_id: int | None = None, conn=None,
) -> int:
    return _exec_master_procedure(
        "dbo.sp_Calculate_Ranking_YOU", year, month, week,
        triggered_by=triggered_by, mode=mode, run_id=run_id, conn=conn,
    )


def run_combined(year: int, month: int, week: int, *, triggered_by: str, mode: str = "normal") -> tuple[int, int]:
    """Convenience wrapper for the 'Senior + Youth' UI option; not itself a ported legacy SP."""
    sen_id = sp_Calculate_Ranking_SEN(year, month, week, triggered_by=triggered_by, mode=mode)
    you_id = sp_Calculate_Ranking_YOU(year, month, week, triggered_by=triggered_by, mode=mode)
    return sen_id, you_id


def schedule_ranking_run(
    conn, *, category_code: str, ranking_year: int, ranking_month: int, ranking_week: int,
    scheduled_for: str, triggered_by: str, run_mode: str = "normal",
) -> int:
    """Records a future run without executing it -- EXECs dbo.sp_RankingRun_Schedule and reads
    the new run_id back from its trailing SELECT (see sp_RankingRun_lifecycle.sql notes on why
    OUTPUT parameters aren't used for the Python-facing return value)."""
    cur = conn.cursor()
    cur.execute(
        "{CALL dbo.sp_RankingRun_Schedule(?, ?, ?, ?, ?, ?, ?, ?)}",
        category_code, ranking_year, ranking_month, ranking_week, scheduled_for, triggered_by, run_mode,
        None,
    )
    return cur.fetchone().run_id
