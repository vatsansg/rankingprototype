"""
Integration test of the age-category-drift fix inside
dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking (see db/procedures/steps/
sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking.sql): the effective age category for a
doubles pair is derived from the CTE's most-restrictive-of-both-players priority table, never
trusted from players_doubles.age_category_code (which drifts to 'SEN' for youth pairs -- the
documented legacy bug). This was previously a standalone unit test of a private Python helper
(_effective_age_category); that helper no longer exists as Python -- the same behavior is now
exercised end to end via Step2 (seeds players_events_results_master from new_events_results)
followed directly by Step3 (derives the age category and seeds main_ranking).
"""

def _seed_pair_and_run_step2_step3(conn, *, category_code, ranking_category_code,
                                    player1_id, player1_age, player2_id, player2_age,
                                    doubles_age_category, run_id):
    cur = conn.cursor()
    cur.execute("INSERT INTO dbo.events (event_id, event_name, event_type_general_code) VALUES (60001, 'E', 'WCH')")
    cur.execute(
        "INSERT INTO dbo.competitors (competitor_id, player_name, age_category_code) VALUES (?, 'A', ?)",
        player1_id, player1_age,
    )
    cur.execute(
        "INSERT INTO dbo.competitors (competitor_id, player_name, age_category_code) VALUES (?, 'B', ?)",
        player2_id, player2_age,
    )
    cur.execute(
        "INSERT INTO dbo.players_doubles (player1_id, player2_id, sub_event_code, age_category_code) "
        "VALUES (?, ?, ?, ?)",
        player1_id, player2_id, ranking_category_code, doubles_age_category,
    )
    cur.execute(
        "INSERT INTO dbo.new_events_results (event_id, competitor_id, sub_event_code, result_position, "
        "ranking_category_code, age_category_code, category_code, ranking_points) "
        "VALUES (60001, ?, ?, 'W', ?, ?, ?, 100)",
        player1_id, ranking_category_code, ranking_category_code, doubles_age_category, category_code,
    )
    cur.execute(
        "{CALL dbo.sp_Calculate_Ranking_Step2_DataPreparationforNewRun(?, ?, ?, ?, ?, ?, ?, ?, ?)}",
        category_code, 2026, 1, 1, run_id, None, None, None, None,
    )
    cur.execute(
        "{CALL dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking(?, ?, ?, ?, ?, ?, ?)}",
        category_code, 2026, 1, 1, run_id, None, None,
    )


def _make_run(conn, week) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO dbo.ranking_run (category_code, ranking_year, ranking_month, ranking_week, "
        "status, started_at, triggered_by) OUTPUT INSERTED.ranking_run_id "
        "VALUES ('YOU', 2026, 1, ?, 'RUNNING', SYSUTCDATETIME(), 't')",
        week,
    )
    return cur.fetchone()[0]


def test_effective_age_category_ignores_drifted_pair_column(conn):
    run_id = _make_run(conn, 1)
    _seed_pair_and_run_step2_step3(
        conn, category_code="YOU", ranking_category_code="MD",
        player1_id=1, player1_age="U17", player2_id=2, player2_age="U17",
        doubles_age_category="SEN", run_id=run_id,  # drifted stored value, despite both players being U17
    )
    cur = conn.cursor()
    cur.execute(
        "SELECT age_category_code FROM dbo.main_ranking WHERE ranking_run_id=? AND competitor_id=1", run_id
    )
    assert cur.fetchone().age_category_code == "U17"


def test_effective_age_category_falls_back_when_no_pair_exists(conn):
    run_id = _make_run(conn, 2)
    cur = conn.cursor()
    cur.execute("INSERT INTO dbo.events (event_id, event_name, event_type_general_code) VALUES (60002, 'E', 'WCH')")
    cur.execute("INSERT INTO dbo.competitors (competitor_id, player_name, age_category_code) VALUES (5, 'Solo', 'U17')")
    cur.execute(
        "INSERT INTO dbo.new_events_results (event_id, competitor_id, sub_event_code, result_position, "
        "ranking_category_code, age_category_code, category_code, ranking_points) "
        "VALUES (60002, 5, 'MS', 'W', 'MS', 'U17', 'YOU', 100)"
    )
    cur.execute(
        "{CALL dbo.sp_Calculate_Ranking_Step2_DataPreparationforNewRun(?, ?, ?, ?, ?, ?, ?, ?, ?)}",
        "YOU", 2026, 1, 2, run_id, None, None, None, None,
    )
    cur.execute(
        "{CALL dbo.sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking(?, ?, ?, ?, ?, ?, ?)}",
        "YOU", 2026, 1, 2, run_id, None, None,
    )
    cur.execute("SELECT age_category_code FROM dbo.main_ranking WHERE ranking_run_id=? AND competitor_id=5", run_id)
    assert cur.fetchone().age_category_code == "U17"  # singles: no doubles pair, falls back to the stored value


def test_effective_age_category_picks_most_restrictive(conn):
    run_id = _make_run(conn, 3)
    _seed_pair_and_run_step2_step3(
        conn, category_code="YOU", ranking_category_code="XD",
        player1_id=10, player1_age="U19", player2_id=11, player2_age="U13",
        doubles_age_category="U19", run_id=run_id,
    )
    cur = conn.cursor()
    cur.execute(
        "SELECT age_category_code FROM dbo.main_ranking WHERE ranking_run_id=? AND competitor_id=10", run_id
    )
    assert cur.fetchone().age_category_code == "U13"  # most restrictive (youngest) of the two players wins
