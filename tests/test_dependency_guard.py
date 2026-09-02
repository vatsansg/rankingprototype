"""Verifies Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun blocks a Youth run when no
prior successful Senior run exists for the same period, with zero business-table writes."""

import pytest

from engine.exceptions import RankingRunFailed
from engine.master import sp_Calculate_Ranking_YOU
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv


def test_youth_run_aborts_without_prior_senior_success(conn):
    load_new_events_results(conn, fixture_csv("youth_dependency_failure"))

    with pytest.raises(RankingRunFailed):
        sp_Calculate_Ranking_YOU(2026, 2, 5, triggered_by="pytest", conn=conn)

    cur = conn.cursor()
    cur.execute("SELECT * FROM dbo.ranking_run WHERE category_code='YOU' AND ranking_year=2026 AND ranking_week=5")
    run = cur.fetchone()
    assert run.status == "ABORTED_DEPENDENCY"

    cur.execute("SELECT COUNT(*) FROM dbo.main_ranking WHERE ranking_run_id=?", run.ranking_run_id)
    assert cur.fetchone()[0] == 0
    cur.execute(
        "SELECT COUNT(*) FROM dbo.players_events_results_master WHERE ranking_run_id_created=?",
        run.ranking_run_id,
    )
    assert cur.fetchone()[0] == 0

    # error_type now records the T-SQL procedure name that raised (ERROR_PROCEDURE()), not a
    # Python exception class name -- the dependency guard's own sentinel error (THROW 51001) is
    # still distinguishable in ranking_run_error via its message and the 51001 number embedded
    # in the traceback column by sp__RecordStepFailure.
    cur.execute("SELECT error_type, error_message, traceback FROM dbo.ranking_run_error WHERE ranking_run_id=?", run.ranking_run_id)
    error = cur.fetchone()
    assert error.error_type == "dbo.Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun"
    assert "Senior Category Ranking Run should be completed" in error.error_message
    assert "Number 51001" in error.traceback
