"""Direct unit test of the age-category-drift fix helper in step3.py."""

from engine.procedures.step3 import _effective_age_category


def test_effective_age_category_ignores_drifted_pair_column(conn):
    conn.execute(
        "INSERT INTO competitors (competitor_id, player_name, age_category_code) VALUES (1, 'A', 'U17')"
    )
    conn.execute(
        "INSERT INTO competitors (competitor_id, player_name, age_category_code) VALUES (2, 'B', 'U17')"
    )
    # Drifted stored value: 'SEN', despite both individual players being U17.
    conn.execute(
        "INSERT INTO players_doubles (doubles_id, player1_id, player2_id, sub_event_code, age_category_code) "
        "VALUES (1, 1, 2, 'MD', 'SEN')"
    )

    assert _effective_age_category(conn, 1, fallback="SEN") == "U17"
    assert _effective_age_category(conn, 2, fallback="SEN") == "U17"


def test_effective_age_category_falls_back_when_no_pair_exists(conn):
    conn.execute(
        "INSERT INTO competitors (competitor_id, player_name, age_category_code) VALUES (5, 'Solo', 'SEN')"
    )
    assert _effective_age_category(conn, 5, fallback="SEN") == "SEN"


def test_effective_age_category_picks_most_restrictive(conn):
    conn.execute("INSERT INTO competitors (competitor_id, player_name, age_category_code) VALUES (10, 'A', 'U19')")
    conn.execute("INSERT INTO competitors (competitor_id, player_name, age_category_code) VALUES (11, 'B', 'U13')")
    conn.execute(
        "INSERT INTO players_doubles (doubles_id, player1_id, player2_id, sub_event_code, age_category_code) "
        "VALUES (2, 10, 11, 'XD', 'U19')"
    )
    assert _effective_age_category(conn, 10, fallback="SEN") == "U13"
