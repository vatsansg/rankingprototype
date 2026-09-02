"""
Regression test for the legacy NEWID()-based non-determinism bug in
Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory (fixed so it shares the same
deterministic competitor_id tiebreak as sp_Calculate_WTT_Ranking_RankingPositions, both now
pure ROW_NUMBER() window functions -- see db/procedures/steps/sp_Calculate_WTT_Ranking_RankingPositions.sql).
Two competitors are given identical points, identical counted-results count, and identical
DOB so every other tiebreak column ties -- only competitor_id can decide the order -- and the
full calculation is run twice (resetting demo data between runs) to prove the ordering is
stable.
"""

from engine.master import sp_Calculate_Ranking_SEN, sp_Calculate_Ranking_YOU
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv, fixture_setup_sql


def _run_youth_once(conn):
    conn.cursor().execute("{CALL dbo.sp_ResetDemoData}")

    load_new_events_results(conn, fixture_csv("senior_happy_path"))
    sp_Calculate_Ranking_SEN(2026, 1, 1, triggered_by="pytest", conn=conn)

    load_new_events_results(conn, fixture_csv("youth_happy_path"))
    conn.cursor().execute(fixture_setup_sql("youth_happy_path"))
    you_run = sp_Calculate_Ranking_YOU(2026, 1, 1, triggered_by="pytest", conn=conn)

    cur = conn.cursor()
    cur.execute(
        "SELECT competitor_id, ranking_pos, ranking_pos_age_category FROM dbo.main_ranking "
        "WHERE ranking_run_id=? ORDER BY ranking_category, competitor_id",
        you_run,
    )
    return [tuple(r) for r in cur.fetchall()]


def test_youth_age_category_positions_are_deterministic_across_runs(conn):
    first = _run_youth_once(conn)
    second = _run_youth_once(conn)
    assert first == second


def test_tied_competitors_break_ties_by_competitor_id(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO dbo.ranking_run (category_code, ranking_year, ranking_month, ranking_week, "
        "status, started_at, triggered_by) OUTPUT INSERTED.ranking_run_id "
        "VALUES ('SEN', 2026, 5, 20, 'RUNNING', SYSUTCDATETIME(), 't')"
    )
    run_id = cur.fetchone()[0]

    # Two SEN competitors with identical points, counted-result count, and DOB.
    cur.execute("INSERT INTO dbo.events (event_id, event_name, event_type_general_code) VALUES (70001, 'E', 'WCH')")
    for cid in (70010, 70020):
        cur.execute(
            "INSERT INTO dbo.competitors (competitor_id, player_name, dob, gender, age_category_code) "
            "VALUES (?, ?, '2000-01-01', 'M', 'SEN')",
            cid, f"Tie Player {cid}",
        )
        cur.execute(
            "INSERT INTO dbo.players_events_results_master (competitor_id, event_id, sub_event_code, "
            "ranking_category_code, result_position, ranking_points, ranking_year, ranking_month, ranking_week, "
            "active, best_result_no_sen_you, category_code, age_category_code) "
            "VALUES (?, 70001, 'MS', 'MS', 'W', 1000, 2026, 5, 20, 1, 1, 'SEN', 'SEN')",
            cid,
        )
        cur.execute(
            "INSERT INTO dbo.main_ranking (competitor_id, ranking_points, ranking_category, ranking_year, "
            "ranking_month, ranking_week, category_code, age_category_code, ranking_run_id) "
            "VALUES (?, 0, 'MS', 2026, 5, 20, 'SEN', 'SEN', ?)",
            cid, run_id,
        )

    cur.execute(
        "{CALL dbo.sp_Calculate_WTT_Ranking_RankingPositions(?, ?, ?, ?)}",
        "SEN", run_id, None, None,
    )

    cur.execute(
        "SELECT competitor_id, ranking_pos FROM dbo.main_ranking WHERE ranking_run_id=? ORDER BY ranking_pos",
        run_id,
    )
    rows = cur.fetchall()
    assert [r.competitor_id for r in rows] == [70010, 70020]  # lower competitor_id wins the tie, deterministically
