"""
Master orchestration: the two per-category "stored procedures" -- sp_Calculate_Ranking_SEN
and sp_Calculate_Ranking_YOU -- plus a thin combined-run convenience wrapper. Every call
inside each function is a direct, identically-named port of a legacy WTT ranking stored
procedure, invoked directly in the fixed order verified against dbo_Rules.csv (see
docs/legacy_rule_mapping.md). No dynamic dispatch, no config-table lookup -- see
engine/step_runner.py for why each step commits independently rather than the whole run.
"""

import sqlite3

from engine.constants import (
    BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS,
    CONTINENTAL_EVENT_TYPE_CODES,
    SEN_BEST_X_RESULTS,
    SEN_ZPP_EVENT_COUNT,
    YOU_BEST_X_RESULTS,
    YOU_ZPP_EVENT_COUNT,
    ZPP_EVENT_TYPE_CODES,
)
from engine.db import get_connection
from engine.exceptions import DependencyNotMetError
from engine.procedures import (
    SP_Calculate_Ranking_UpdatePlayersInfoFromTTU,
    Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun,
    Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory,
    sp_Calculate_Ranking_FinalizeRun,
    sp_Calculate_Ranking_Step2_DataPreparationforNewRun,
    sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking,
    sp_Calculate_WTT_Ranking_RankingPositions,
    sp_Calculate_WTT_Ranking_ZeroPointPenalty,
    sp_Calculate_WTT_SEN_Ranking_BestResults,
    sp_Calculate_WTT_YOU_Ranking_BestResults,
    sp_Rules_Set_Weekly_Events_ManualModifications,
    sp_Rules_UpdateEventsResultExpiry,
    sp_Rules_UpdateOlympicResultExpiry,
)
from engine.run_registry import create_run, finalize_run, schedule_ranking_run, start_scheduled_run  # noqa: F401
from engine.step_runner import RankingRunFailed, step


def sp_Calculate_Ranking_SEN(
    year: int, month: int, week: int, *, triggered_by: str, mode: str = "normal",
    run_id: int | None = None, conn: sqlite3.Connection | None = None,
) -> int:
    """
    Direct, category-split successor of the legacy parameterized sp_Calculate_Ranking.
    run_id=None => on-demand, creates a fresh RUNNING row. run_id=<int> => this is a
    'Run Now' on a previously scheduled PENDING row.
    """
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        if run_id is None:
            run_id = create_run(
                conn, category_code="SEN", ranking_year=year, ranking_month=month,
                ranking_week=week, triggered_by=triggered_by, run_mode=mode,
            )
        else:
            start_scheduled_run(conn, run_id)

        try:
            with step(conn, run_id, seq=1, group="PreRequisitesValidation",
                      name="SP_Calculate_Ranking_UpdatePlayersInfoFromTTU") as c:
                SP_Calculate_Ranking_UpdatePlayersInfoFromTTU(conn, organization_code="WTT", counts=c)

            with step(conn, run_id, seq=2, group="Orchestration",
                      name="sp_Calculate_Ranking_Step2_DataPreparationforNewRun") as c:
                sp_Calculate_Ranking_Step2_DataPreparationforNewRun(
                    conn, category_code="SEN", year=year, month=month, week=week, run_id=run_id, counts=c,
                )

            with step(conn, run_id, seq=3, group="Orchestration",
                      name="sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking") as c:
                sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking(
                    conn, category_code="SEN", year=year, month=month, week=week, run_id=run_id, counts=c,
                )

            with step(conn, run_id, seq=4, group="ResultsSelection",
                      name="sp_Rules_Set_Weekly_Events_ManualModifications") as c:
                sp_Rules_Set_Weekly_Events_ManualModifications(conn, category_code="SEN", run_id=run_id, counts=c)

            with step(conn, run_id, seq=5, group="ResultsSelection",
                      name="sp_Rules_UpdateEventsResultExpiry") as c:
                sp_Rules_UpdateEventsResultExpiry(conn, category_code="SEN", year=year, week=week, counts=c)

            with step(conn, run_id, seq=6, group="ResultsSelection",
                      name="sp_Rules_UpdateOlympicResultExpiry") as c:
                sp_Rules_UpdateOlympicResultExpiry(conn, counts=c)

            with step(conn, run_id, seq=7, group="ResultsSelection",
                      name="sp_Calculate_WTT_SEN_Ranking_BestResults") as c:
                sp_Calculate_WTT_SEN_Ranking_BestResults(
                    conn, best_x_results=SEN_BEST_X_RESULTS,
                    continental_event_type_codes=CONTINENTAL_EVENT_TYPE_CODES,
                    best_x_results_for_continental_events=BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS, counts=c,
                )

            with step(conn, run_id, seq=8, group="ResultsSelection",
                      name="sp_Calculate_WTT_Ranking_ZeroPointPenalty") as c:
                sp_Calculate_WTT_Ranking_ZeroPointPenalty(
                    conn, category_code="SEN", event_count=SEN_ZPP_EVENT_COUNT,
                    event_type=ZPP_EVENT_TYPE_CODES, counts=c,
                )

            with step(conn, run_id, seq=9, group="RankingResultPositions",
                      name="sp_Calculate_WTT_Ranking_RankingPositions") as c:
                sp_Calculate_WTT_Ranking_RankingPositions(conn, category_code="SEN", run_id=run_id, counts=c)

            with step(conn, run_id, seq=10, group="Orchestration",
                      name="sp_Calculate_Ranking_FinalizeRun") as c:
                sp_Calculate_Ranking_FinalizeRun(conn, category_code="SEN", run_id=run_id, counts=c)

        except RankingRunFailed:
            finalize_run(conn, run_id, status="FAILED")
            raise

        finalize_run(conn, run_id, status="SUCCEEDED")
        return run_id
    finally:
        if owns_conn:
            conn.close()


def sp_Calculate_Ranking_YOU(
    year: int, month: int, week: int, *, triggered_by: str, mode: str = "normal",
    run_id: int | None = None, conn: sqlite3.Connection | None = None,
) -> int:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        if run_id is None:
            run_id = create_run(
                conn, category_code="YOU", ranking_year=year, ranking_month=month,
                ranking_week=week, triggered_by=triggered_by, run_mode=mode,
            )
        else:
            start_scheduled_run(conn, run_id)

        # Dependency guard: explicit step 1, checked before any further writes.
        try:
            with step(conn, run_id, seq=1, group="PreRequisitesValidation",
                      name="Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun") as c:
                Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun(conn, year=year, month=month, week=week, counts=c)
        except RankingRunFailed as fail:
            if isinstance(fail.original, DependencyNotMetError):
                finalize_run(conn, run_id, status="ABORTED_DEPENDENCY", notes=str(fail.original))
            else:
                finalize_run(conn, run_id, status="FAILED", notes=str(fail.original))
            raise

        try:
            with step(conn, run_id, seq=2, group="Orchestration",
                      name="sp_Calculate_Ranking_Step2_DataPreparationforNewRun") as c:
                sp_Calculate_Ranking_Step2_DataPreparationforNewRun(
                    conn, category_code="YOU", year=year, month=month, week=week, run_id=run_id, counts=c,
                )

            with step(conn, run_id, seq=3, group="Orchestration",
                      name="sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking") as c:
                sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking(
                    conn, category_code="YOU", year=year, month=month, week=week, run_id=run_id, counts=c,
                )

            with step(conn, run_id, seq=4, group="ResultsSelection",
                      name="sp_Rules_Set_Weekly_Events_ManualModifications") as c:
                sp_Rules_Set_Weekly_Events_ManualModifications(conn, category_code="YOU", run_id=run_id, counts=c)

            with step(conn, run_id, seq=5, group="ResultsSelection",
                      name="sp_Rules_UpdateEventsResultExpiry") as c:
                sp_Rules_UpdateEventsResultExpiry(conn, category_code="YOU", year=year, week=week, counts=c)

            with step(conn, run_id, seq=6, group="ResultsSelection",
                      name="sp_Rules_UpdateOlympicResultExpiry") as c:
                sp_Rules_UpdateOlympicResultExpiry(conn, counts=c)

            with step(conn, run_id, seq=7, group="ResultsSelection",
                      name="sp_Calculate_WTT_YOU_Ranking_BestResults") as c:
                sp_Calculate_WTT_YOU_Ranking_BestResults(
                    conn, best_x_results=YOU_BEST_X_RESULTS,
                    continental_event_type_codes=CONTINENTAL_EVENT_TYPE_CODES,
                    best_x_results_for_continental_events=BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS, counts=c,
                )

            with step(conn, run_id, seq=8, group="ResultsSelection",
                      name="sp_Calculate_WTT_Ranking_ZeroPointPenalty") as c:
                sp_Calculate_WTT_Ranking_ZeroPointPenalty(
                    conn, category_code="YOU", event_count=YOU_ZPP_EVENT_COUNT,
                    event_type=ZPP_EVENT_TYPE_CODES, counts=c,
                )

            with step(conn, run_id, seq=9, group="RankingResultPositions",
                      name="sp_Calculate_WTT_Ranking_RankingPositions") as c:
                sp_Calculate_WTT_Ranking_RankingPositions(conn, category_code="YOU", run_id=run_id, counts=c)

            with step(conn, run_id, seq=10, group="RankingResultPositions",
                      name="Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory") as c:
                Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory(conn, run_id=run_id, counts=c)

            with step(conn, run_id, seq=11, group="Orchestration",
                      name="sp_Calculate_Ranking_FinalizeRun") as c:
                sp_Calculate_Ranking_FinalizeRun(conn, category_code="YOU", run_id=run_id, counts=c)

        except RankingRunFailed:
            finalize_run(conn, run_id, status="FAILED")
            raise

        finalize_run(conn, run_id, status="SUCCEEDED")
        return run_id
    finally:
        if owns_conn:
            conn.close()


def run_combined(year: int, month: int, week: int, *, triggered_by: str, mode: str = "normal") -> tuple[int, int]:
    """Convenience wrapper for the 'Senior + Youth' UI option; not itself a ported legacy SP."""
    sen_id = sp_Calculate_Ranking_SEN(year, month, week, triggered_by=triggered_by, mode=mode)
    you_id = sp_Calculate_Ranking_YOU(year, month, week, triggered_by=triggered_by, mode=mode)
    return sen_id, you_id
