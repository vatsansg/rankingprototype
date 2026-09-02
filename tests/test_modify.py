"""Tests for the manual-modification stage on freshly-imported results."""

from importer.load_new_events_results import load_new_events_results
from importer.modify_new_events_results import search_new_events_results, update_result_position
from tests.conftest import fixture_csv


def test_search_by_player_name_and_country(conn):
    load_new_events_results(conn, fixture_csv("senior_happy_path"))

    by_name = search_new_events_results(conn, player_name="SEN Player 1")
    assert len(by_name) > 0
    assert all("SEN Player 1" in r.player_name for r in by_name)

    by_country = search_new_events_results(conn, country_code="CHN")
    assert all(r.country_code == "CHN" for r in by_country)


def test_update_result_position_recomputes_points_and_logs_change(conn):
    load_new_events_results(conn, fixture_csv("senior_happy_path"))
    row = search_new_events_results(conn, player_name="SEN Player 1")[0]
    assert row.result_position != "F"

    result = update_result_position(
        conn, new_event_result_id=row.new_event_result_id, new_result_position="F", modified_by="pytest",
    )
    assert result["new_result_position"] == "F"
    assert result["new_ranking_points"] == 700.0  # WCH F = 700 per ranking_calc_main

    cur = conn.cursor()
    cur.execute(
        "SELECT result_position, ranking_points FROM dbo.new_events_results WHERE new_event_result_id=?",
        row.new_event_result_id,
    )
    updated = cur.fetchone()
    assert updated.result_position == "F"
    assert updated.ranking_points == 700.0

    cur.execute(
        "SELECT * FROM dbo.new_events_results_modification_log WHERE new_event_result_id=?",
        row.new_event_result_id,
    )
    log = cur.fetchone()
    assert log is not None
    assert log.new_result_position == "F"
    assert log.modified_by == "pytest"


def test_zpp_row_stays_zero_points_even_if_position_changed(conn):
    load_new_events_results(conn, fixture_csv("senior_happy_path"))
    cur = conn.cursor()
    cur.execute(
        "SELECT new_event_result_id FROM dbo.new_events_results WHERE competitor_id=90001 AND event_id=80005"
    )
    zpp_row = cur.fetchone()

    result = update_result_position(
        conn, new_event_result_id=zpp_row.new_event_result_id, new_result_position="W", modified_by="pytest",
    )
    assert result["new_ranking_points"] == 0.0  # ZPP overrides the round-points lookup
