"""End-to-end test of sp_Calculate_Ranking_YOU against the youth_happy_path fixture,
run after a prior successful Senior run for the same period. Also verifies the
age-category-drift fix for the doubles pair."""

from engine.master import sp_Calculate_Ranking_SEN, sp_Calculate_Ranking_YOU
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv, fixture_setup_sql


def test_youth_happy_path_end_to_end(conn):
    load_new_events_results(conn, fixture_csv("senior_happy_path"))
    sen_run = sp_Calculate_Ranking_SEN(2026, 1, 1, triggered_by="pytest", conn=conn)
    assert conn.execute("SELECT status FROM ranking_run WHERE ranking_run_id=?", (sen_run,)).fetchone()[0] == "SUCCEEDED"

    load_new_events_results(conn, fixture_csv("youth_happy_path"))
    conn.executescript(fixture_setup_sql("youth_happy_path"))

    you_run = sp_Calculate_Ranking_YOU(2026, 1, 1, triggered_by="pytest", conn=conn)

    run = conn.execute("SELECT * FROM ranking_run WHERE ranking_run_id=?", (you_run,)).fetchone()
    assert run["status"] == "SUCCEEDED"

    steps = conn.execute(
        "SELECT status FROM ranking_run_step WHERE ranking_run_id=?", (you_run,)
    ).fetchall()
    assert len(steps) == 11
    assert all(s["status"] == "SUCCEEDED" for s in steps)

    # Doubles pair: age_category_code on the resulting main_ranking row must be the derived
    # U15 (from both individual players), NOT the drifted 'SEN' stored on players_doubles.
    doubles_row = conn.execute(
        "SELECT age_category_code, ranking_points FROM main_ranking WHERE ranking_run_id=? AND competitor_id=91013 AND ranking_category='MD'",
        (you_run,),
    ).fetchone()
    assert doubles_row is not None
    assert doubles_row["age_category_code"] == "U15"
    assert doubles_row["ranking_points"] > 0

    # Age-category positions were assigned.
    age_pos = conn.execute(
        "SELECT ranking_pos_age_category FROM main_ranking WHERE ranking_run_id=? AND ranking_category='MS' "
        "ORDER BY ranking_pos_age_category",
        (you_run,),
    ).fetchall()
    assert [r["ranking_pos_age_category"] for r in age_pos if r["ranking_pos_age_category"] is not None]
