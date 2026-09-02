"""End-to-end test of sp_Calculate_Ranking_SEN against the senior_happy_path fixture:
all steps succeed, best-of-8 trimming and the max-1-continental cap behave correctly, and
the ZPP row stays active/mandatory and contributes 0 points."""

from engine.master import sp_Calculate_Ranking_SEN
from importer.load_new_events_results import load_new_events_results
from tests.conftest import fixture_csv


def test_senior_happy_path_end_to_end(conn):
    result = load_new_events_results(conn, fixture_csv("senior_happy_path"))
    assert result == {"competitors_upserted": 15, "events_upserted": 10, "results_inserted": 150}

    run_id = sp_Calculate_Ranking_SEN(2026, 1, 1, triggered_by="pytest", conn=conn)

    run = conn.execute("SELECT * FROM ranking_run WHERE ranking_run_id=?", (run_id,)).fetchone()
    assert run["status"] == "SUCCEEDED"

    steps = conn.execute(
        "SELECT step_seq, step_name, status FROM ranking_run_step WHERE ranking_run_id=? ORDER BY step_seq",
        (run_id,),
    ).fetchall()
    assert len(steps) == 10
    assert all(s["status"] == "SUCCEEDED" for s in steps)
    assert [s["step_name"] for s in steps] == [
        "SP_Calculate_Ranking_UpdatePlayersInfoFromTTU",
        "sp_Calculate_Ranking_Step2_DataPreparationforNewRun",
        "sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking",
        "sp_Rules_Set_Weekly_Events_ManualModifications",
        "sp_Rules_UpdateEventsResultExpiry",
        "sp_Rules_UpdateOlympicResultExpiry",
        "sp_Calculate_WTT_SEN_Ranking_BestResults",
        "sp_Calculate_WTT_Ranking_ZeroPointPenalty",
        "sp_Calculate_WTT_Ranking_RankingPositions",
        "sp_Calculate_Ranking_FinalizeRun",
    ]

    # Every player has exactly 8 counted results (best-of-8), including the mandatory ZPP row.
    counted = conn.execute(
        "SELECT competitor_id, COUNT(*) AS n FROM players_events_results_master "
        "WHERE category_code='SEN' AND active=1 AND best_result_no_sen_you=1 GROUP BY competitor_id"
    ).fetchall()
    assert len(counted) == 15
    assert all(r["n"] == 8 for r in counted)

    # Player 90001's ZPP row: 0 points, still counted.
    zpp_row = conn.execute(
        "SELECT ranking_points, best_result_no_sen_you, zero_point_penalty, active "
        "FROM players_events_results_master WHERE competitor_id=90001 AND event_id=80005"
    ).fetchone()
    assert zpp_row["zero_point_penalty"] == 1
    assert zpp_row["ranking_points"] == 0
    assert zpp_row["best_result_no_sen_you"] == 1
    assert zpp_row["active"] == 1

    # Each player has at most 1 continental (Con) result counted toward their best-of-8.
    continental_counts = conn.execute(
        """
        SELECT p.competitor_id, COUNT(*) AS n FROM players_events_results_master p
        JOIN events e ON e.event_id = p.event_id
        WHERE p.category_code='SEN' AND p.best_result_no_sen_you=1 AND e.event_type_general_code='Con'
        GROUP BY p.competitor_id
        """
    ).fetchall()
    assert all(r["n"] <= 1 for r in continental_counts)

    # Published ranking output exists and is ordered.
    positions = conn.execute(
        "SELECT ranking_pos FROM vw_RankingResult WHERE ranking_category='MS' ORDER BY ranking_pos"
    ).fetchall()
    assert [r["ranking_pos"] for r in positions] == list(range(1, len(positions) + 1))

    # new_events_results cleared for the category by the finalize step.
    assert conn.execute("SELECT COUNT(*) FROM new_events_results WHERE category_code='SEN'").fetchone()[0] == 0
