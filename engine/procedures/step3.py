"""
Port of dbo_sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking.sql: seeds main_ranking
with zero-point placeholder rows for every competitor who has an active result this run.

Fixes the documented legacy bug where Players_Doubles.AgeCategoryCode drifts to 'SEN' for
Youth pairs and silently drops them from MainRanking: instead of trusting the stored
players_doubles.age_category_code column, _effective_age_category() derives the pair's
effective (most restrictive / youngest) age category from both individual players.
"""

import sqlite3

from engine.step_runner import StepCounts

DOUBLES_RANKING_CATEGORIES = {"MD", "WD", "XD", "MDI", "WDI", "XDI"}

# Ordered youngest-to-oldest so "most restrictive" = first match found.
AGE_CATEGORY_RESTRICTIVENESS = ["U11", "U13", "U15", "U17", "U19", "SEN"]


def _effective_age_category(conn: sqlite3.Connection, competitor_id: int, fallback: str) -> str:
    pair = conn.execute(
        "SELECT player1_id, player2_id FROM players_doubles WHERE player1_id=? OR player2_id=?",
        (competitor_id, competitor_id),
    ).fetchone()
    if pair is None:
        return fallback

    codes = []
    for pid in (pair["player1_id"], pair["player2_id"]):
        row = conn.execute("SELECT age_category_code FROM competitors WHERE competitor_id=?", (pid,)).fetchone()
        if row and row["age_category_code"]:
            codes.append(row["age_category_code"])

    for candidate in AGE_CATEGORY_RESTRICTIVENESS:
        if candidate in codes:
            return candidate
    return fallback


def sp_Calculate_Ranking_Step3_InsertRecordsintoMainRanking(
    conn: sqlite3.Connection, *, category_code: str, year: int, month: int, week: int,
    run_id: int, counts: StepCounts,
) -> None:
    candidates = conn.execute(
        """
        SELECT DISTINCT p.competitor_id, p.ranking_category_code, c.age_category_code AS stored_age_category
        FROM players_events_results_master p
        JOIN competitors c ON c.competitor_id = p.competitor_id
        WHERE p.category_code = ? AND p.active = 1
          AND c.is_retired = 0 AND c.wtt_eligibility = 1
        """,
        (category_code,),
    ).fetchall()

    inserted = 0
    for row in candidates:
        age_category = row["stored_age_category"] or category_code
        if row["ranking_category_code"] in DOUBLES_RANKING_CATEGORIES:
            age_category = _effective_age_category(conn, row["competitor_id"], age_category)

        conn.execute(
            "INSERT INTO main_ranking (competitor_id, ranking_pos, ranking_points, ranking_category, "
            "ranking_year, ranking_month, ranking_week, category_code, age_category_code, ranking_run_id) "
            "VALUES (?, NULL, 0, ?, ?, ?, ?, ?, ?, ?)",
            (row["competitor_id"], row["ranking_category_code"], year, month, week, category_code, age_category, run_id),
        )
        inserted += 1

    counts.inserted += inserted
    counts.message = f"seeded {inserted} main_ranking placeholder rows"
