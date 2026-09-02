"""Verifies a bad-data calculation failure (unrecognized ranking_category_code) is caught
inside sp_Calculate_Ranking_Step2_DataPreparationforNewRun, marks the run FAILED (not
ABORTED_DEPENDENCY), and that the prior successful step remains visible in the audit trail --
i.e. the run never reports a false successful result."""

import pytest

from engine.exceptions import RankingRunFailed
from engine.master import sp_Calculate_Ranking_SEN
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv


def test_bad_ranking_category_code_fails_the_run_cleanly(conn):
    load_new_events_results(conn, fixture_csv("calculation_failure"))

    with pytest.raises(RankingRunFailed) as excinfo:
        sp_Calculate_Ranking_SEN(2026, 4, 15, triggered_by="pytest", conn=conn)

    assert excinfo.value.step_name == "sp_Calculate_Ranking_Step2_DataPreparationforNewRun"

    cur = conn.cursor()
    cur.execute("SELECT * FROM dbo.ranking_run WHERE category_code='SEN' AND ranking_year=2026 AND ranking_week=15")
    run = cur.fetchone()
    assert run.status == "FAILED"

    cur.execute(
        "SELECT step_seq, step_name, status FROM dbo.ranking_run_step WHERE ranking_run_id=? ORDER BY step_seq",
        run.ranking_run_id,
    )
    steps = cur.fetchall()
    assert steps[0].status == "SUCCEEDED"  # TTU sync stub still ran fine
    assert steps[1].status == "FAILED"

    cur.execute(
        "SELECT result_message FROM dbo.ranking_run_step WHERE ranking_run_id=? AND step_seq=2",
        run.ranking_run_id,
    )
    assert "ZZ" in cur.fetchone()[0]

    # No main_ranking rows were ever published for this failed run.
    cur.execute("SELECT COUNT(*) FROM dbo.main_ranking WHERE ranking_run_id=?", run.ranking_run_id)
    assert cur.fetchone()[0] == 0
