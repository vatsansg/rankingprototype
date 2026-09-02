"""Verifies Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun blocks a Youth run when no
prior successful Senior run exists for the same period, with zero business-table writes."""

import pytest

from engine.master import sp_Calculate_Ranking_YOU
from engine.step_runner import RankingRunFailed
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv


def test_youth_run_aborts_without_prior_senior_success(conn):
    load_new_events_results(conn, fixture_csv("youth_dependency_failure"))

    with pytest.raises(RankingRunFailed):
        sp_Calculate_Ranking_YOU(2026, 2, 5, triggered_by="pytest", conn=conn)

    run = conn.execute(
        "SELECT * FROM ranking_run WHERE category_code='YOU' AND ranking_year=2026 AND ranking_week=5"
    ).fetchone()
    assert run["status"] == "ABORTED_DEPENDENCY"

    assert conn.execute(
        "SELECT COUNT(*) FROM main_ranking WHERE ranking_run_id=?", (run["ranking_run_id"],)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM players_events_results_master WHERE ranking_run_id_created=?",
        (run["ranking_run_id"],),
    ).fetchone()[0] == 0

    error = conn.execute(
        "SELECT error_type FROM ranking_run_error WHERE ranking_run_id=?", (run["ranking_run_id"],)
    ).fetchone()
    assert error["error_type"] == "DependencyNotMetError"
