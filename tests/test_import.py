"""Tests for importer/load_new_events_results.py and importer/cross_award.py."""

from importer.cross_award import mirror_cross_category_result
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv


def test_zpp_rows_always_import_at_zero_points(conn):
    load_new_events_results(conn, fixture_csv("senior_happy_path"))
    cur = conn.cursor()
    cur.execute(
        "SELECT ranking_points, zero_point_penalty FROM dbo.new_events_results "
        "WHERE competitor_id=90001 AND event_id=80005"
    )
    row = cur.fetchone()
    assert row.zero_point_penalty == 1
    assert row.ranking_points == 0


def test_cross_award_mirrors_senior_result_to_youth_at_5x(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO dbo.events (event_id, event_name, event_type_general_code) VALUES (1, 'E', 'WCH')")
    cur.execute(
        "INSERT INTO dbo.competitors (competitor_id, player_name, age_category_code) VALUES (1, 'Young Senior', 'U17')"
    )
    cur.execute(
        "INSERT INTO dbo.new_events_results (event_id, competitor_id, sub_event_code, result_position, "
        "ranking_category_code, age_category_code, category_code, ranking_points) "
        "VALUES (1, 1, 'MS', 'W', 'MS', 'U17', 'SEN', 100)"
    )

    mirrored = mirror_cross_category_result(conn, "SEN")
    assert mirrored == 1

    cur.execute(
        "SELECT ranking_points, cross_awarded_from_event_id FROM dbo.new_events_results WHERE category_code='YOU'"
    )
    row = cur.fetchone()
    assert row.ranking_points == 500  # 5x multiplier
    assert row.cross_awarded_from_event_id == 1

    # Idempotent: running again does not duplicate the mirror.
    assert mirror_cross_category_result(conn, "SEN") == 0
