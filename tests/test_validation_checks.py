"""Verifies SP_Ranking_DataValidation catches a deliberately injected duplicate result row,
and that a clean run reports no failing checks."""

from engine.master import sp_Calculate_Ranking_SEN
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv, fixture_setup_sql
from validation.run_validation import SP_Ranking_DataValidation


def test_duplicate_result_detected(conn):
    load_new_events_results(conn, fixture_csv("validation_failure"))
    run_id = sp_Calculate_Ranking_SEN(2026, 3, 10, triggered_by="pytest", conn=conn)
    conn.executescript(fixture_setup_sql("validation_failure"))

    findings = SP_Ranking_DataValidation(
        conn, category_code="SEN", run_id=run_id, validation_category="PostRankingValidation",
    )

    duplicate_findings = [f for f in findings if f["check_name"] == "Duplicated Results Validation"]
    assert any(f["passed"] == 0 for f in duplicate_findings)

    stored = conn.execute(
        "SELECT COUNT(*) FROM ranking_validation_result WHERE ranking_run_id=? AND passed=0", (run_id,)
    ).fetchone()[0]
    assert stored >= 1


def test_clean_senior_run_has_no_failing_checks(conn):
    load_new_events_results(conn, fixture_csv("senior_happy_path"))
    run_id = sp_Calculate_Ranking_SEN(2026, 1, 1, triggered_by="pytest", conn=conn)

    findings = SP_Ranking_DataValidation(
        conn, category_code="SEN", run_id=run_id, validation_category="PostRankingValidation",
    )
    assert all(f["passed"] == 1 for f in findings)
