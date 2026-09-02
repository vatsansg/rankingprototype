"""
Regression test for the legacy NEWID()-based non-determinism bug in
Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory (fixed in positions.py to share
the same deterministic competitor_id tiebreak as sp_Calculate_WTT_Ranking_RankingPositions).
Two competitors are given identical points, identical counted-results count, and identical
DOB so every other tiebreak column ties -- only competitor_id can decide the order -- and the
full calculation is run twice to prove the ordering is stable.
"""

from engine.master import sp_Calculate_Ranking_SEN, sp_Calculate_Ranking_YOU
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv, fixture_setup_sql


def _run_youth_twice():
    """Runs the full Senior+Youth pipeline twice from scratch and returns both orderings."""
    from db.init_db import build
    import sqlite3
    import tempfile
    from pathlib import Path

    orderings = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite"
            build(db_path)
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

            load_new_events_results(conn, fixture_csv("senior_happy_path"))
            sp_Calculate_Ranking_SEN(2026, 1, 1, triggered_by="pytest", conn=conn)

            load_new_events_results(conn, fixture_csv("youth_happy_path"))
            conn.executescript(fixture_setup_sql("youth_happy_path"))
            you_run = sp_Calculate_Ranking_YOU(2026, 1, 1, triggered_by="pytest", conn=conn)

            rows = conn.execute(
                "SELECT competitor_id, ranking_pos, ranking_pos_age_category FROM main_ranking "
                "WHERE ranking_run_id=? ORDER BY ranking_category, competitor_id",
                (you_run,),
            ).fetchall()
            orderings.append([tuple(r) for r in rows])
            conn.close()
    return orderings


def test_youth_age_category_positions_are_deterministic_across_runs():
    first, second = _run_youth_twice()
    assert first == second


def test_tied_competitors_break_ties_by_competitor_id(conn):
    conn.execute(
        "INSERT INTO ranking_run (ranking_run_id, category_code, ranking_year, ranking_month, ranking_week, "
        "status, started_at, triggered_by) VALUES (1, 'SEN', 2026, 5, 20, 'RUNNING', '2026-01-01T00:00:00Z', 't')"
    )
    # Two SEN competitors with identical points, counted-result count, and DOB.
    conn.execute("INSERT INTO events (event_id, event_name, event_type_general_code) VALUES (70001, 'E', 'WCH')")
    for cid in (70010, 70020):
        conn.execute(
            "INSERT INTO competitors (competitor_id, player_name, dob, gender, age_category_code) "
            "VALUES (?, ?, '2000-01-01', 'M', 'SEN')",
            (cid, f"Tie Player {cid}"),
        )
        conn.execute(
            "INSERT INTO players_events_results_master (competitor_id, event_id, sub_event_code, "
            "ranking_category_code, result_position, ranking_points, ranking_year, ranking_month, ranking_week, "
            "active, best_result_no_sen_you, category_code, age_category_code) "
            "VALUES (?, 70001, 'MS', 'MS', 'W', 1000, 2026, 5, 20, 1, 1, 'SEN', 'SEN')",
            (cid,),
        )
        conn.execute(
            "INSERT INTO main_ranking (competitor_id, ranking_points, ranking_category, ranking_year, "
            "ranking_month, ranking_week, category_code, age_category_code, ranking_run_id) "
            "VALUES (?, 0, 'MS', 2026, 5, 20, 'SEN', 'SEN', ?)",
            (cid, 1),
        )

    from engine.procedures.positions import sp_Calculate_WTT_Ranking_RankingPositions
    from engine.step_runner import StepCounts

    sp_Calculate_WTT_Ranking_RankingPositions(conn, category_code="SEN", run_id=1, counts=StepCounts())

    rows = conn.execute(
        "SELECT competitor_id, ranking_pos FROM main_ranking WHERE ranking_run_id=1 ORDER BY ranking_pos"
    ).fetchall()
    assert [r["competitor_id"] for r in rows] == [70010, 70020]  # lower competitor_id wins the tie, deterministically
