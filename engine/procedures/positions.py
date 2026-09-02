"""
Ports of dbo_sp_Calculate_WTT_Ranking_RankingPositions.sql and
dbo_Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory.sql.

Tiebreak order (per the ITTF/WTT regulations documented in the handover summary and the
legacy SQL's ORDER BY): ranking_points DESC, fewest counted results ASC, youngest (later
DOB) first, then competitor_id ASC as the final deterministic tiebreak.

The legacy sp_Calculate_WTT_Ranking_RankingPositions used a deterministic
CHECKSUM(CompetitorId) as its final tiebreak, but its sibling
Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory used NEWID() -- a genuine
non-determinism bug (documented in the plan). Both prototype functions below share the same
deterministic competitor_id-based final tiebreak, fixing that inconsistency.
"""

import sqlite3
from collections import defaultdict

from engine.step_runner import StepCounts


def _dob_sort_value(dob: str | None) -> int:
    """Smaller = sorts first = favored in a tie. Later DOB (younger) should sort first."""
    if not dob:
        return 99999999
    try:
        return -int(dob.replace("-", ""))
    except ValueError:
        return 99999999


def _counted_results_map(conn: sqlite3.Connection, category_code: str) -> dict:
    rows = conn.execute(
        "SELECT competitor_id, ranking_category_code, COUNT(*) AS n FROM players_events_results_master "
        "WHERE category_code=? AND active=1 AND best_result_no_sen_you=1 "
        "GROUP BY competitor_id, ranking_category_code",
        (category_code,),
    ).fetchall()
    return {(r["competitor_id"], r["ranking_category_code"]): r["n"] for r in rows}


def sp_Calculate_WTT_Ranking_RankingPositions(
    conn: sqlite3.Connection, *, category_code: str, run_id: int, counts: StepCounts,
) -> None:
    conn.execute(
        """
        UPDATE main_ranking SET ranking_points = (
            SELECT COALESCE(SUM(p.ranking_points), 0) FROM players_events_results_master p
            WHERE p.competitor_id = main_ranking.competitor_id
              AND p.ranking_category_code = main_ranking.ranking_category
              AND p.category_code = main_ranking.category_code
              AND p.active = 1 AND p.best_result_no_sen_you = 1
        )
        WHERE ranking_run_id = ?
        """,
        (run_id,),
    )

    rows = conn.execute(
        "SELECT mr.main_ranking_id, mr.competitor_id, mr.ranking_category, mr.ranking_points, c.dob "
        "FROM main_ranking mr JOIN competitors c ON c.competitor_id = mr.competitor_id "
        "WHERE mr.ranking_run_id = ?",
        (run_id,),
    ).fetchall()
    counted_map = _counted_results_map(conn, category_code)

    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r["ranking_category"]].append(r)

    updated = 0
    for cat, group_rows in groups.items():
        ordered = sorted(
            group_rows,
            key=lambda r: (
                -(r["ranking_points"] or 0),
                counted_map.get((r["competitor_id"], cat), 0),
                _dob_sort_value(r["dob"]),
                r["competitor_id"],
            ),
        )
        for pos, r in enumerate(ordered, start=1):
            conn.execute("UPDATE main_ranking SET ranking_pos=? WHERE main_ranking_id=?", (pos, r["main_ranking_id"]))
            updated += 1

    counts.updated += updated
    counts.message = f"assigned positions for {len(rows)} row(s) across {len(groups)} ranking-category group(s)"


def Sp_Calculate_WTT_YOU_UpdateRankingPositionsForAgeCategory(
    conn: sqlite3.Connection, *, run_id: int, counts: StepCounts,
) -> None:
    rows = conn.execute(
        "SELECT mr.main_ranking_id, mr.competitor_id, mr.ranking_category, mr.age_category_code, "
        "mr.ranking_points, c.dob FROM main_ranking mr JOIN competitors c ON c.competitor_id = mr.competitor_id "
        "WHERE mr.ranking_run_id = ? AND mr.category_code = 'YOU'",
        (run_id,),
    ).fetchall()
    counted_map = _counted_results_map(conn, "YOU")

    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["ranking_category"], r["age_category_code"])].append(r)

    updated = 0
    for (cat, _age_cat), group_rows in groups.items():
        ordered = sorted(
            group_rows,
            key=lambda r: (
                -(r["ranking_points"] or 0),
                counted_map.get((r["competitor_id"], cat), 0),
                _dob_sort_value(r["dob"]),
                r["competitor_id"],
            ),
        )
        for pos, r in enumerate(ordered, start=1):
            conn.execute(
                "UPDATE main_ranking SET ranking_pos_age_category=? WHERE main_ranking_id=?",
                (pos, r["main_ranking_id"]),
            )
            updated += 1

    counts.updated += updated
    counts.message = f"assigned age-category positions for {len(rows)} row(s) across {len(groups)} group(s)"
