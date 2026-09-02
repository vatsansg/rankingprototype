"""
Port of dbo_sp_Calculate_WTT_Ranking_ZeroPointPenalty.sql -- the most complex legacy
procedure (multiple #temp tables and a WHILE loop capped at MAX_ZPP_PER_PLAYER). Reimplemented
as a bounded, per-player loop inside the caller's step transaction (transaction-safe, unlike
the legacy version which had no surrounding BEGIN TRAN despite extensive multi-row writes).

For each active zero-point-penalty result, counts the player's subsequent active,
non-zero-point-penalty participations in eligible event types (event_type param) since that
ZPP was recorded; once event_count such participations have accumulated, the waiver
condition is met and the ZPP is expired (active=0). Still-active ZPP rows are flagged
mandatory_inclusion_for_best_results=1 so a later best-results pass (or a re-run) always
counts them, per the "ZPP always occupies a counted-result slot" rule.
"""

import sqlite3

from engine.constants import MAX_ZPP_PER_PLAYER, SEN_ZPP_EVENT_COUNT, YOU_ZPP_EVENT_COUNT, ZPP_EVENT_TYPE_CODES
from engine.step_runner import StepCounts


def sp_Calculate_WTT_Ranking_ZeroPointPenalty(
    conn: sqlite3.Connection, *, category_code: str,
    event_count: int | None = None,  # defaults per-category below (RulesId 83=8 for SEN, 84=5 for YOU)
    event_type: list[str] = ZPP_EVENT_TYPE_CODES,
    counts: StepCounts,
) -> None:
    if event_count is None:
        event_count = SEN_ZPP_EVENT_COUNT if category_code == "SEN" else YOU_ZPP_EVENT_COUNT

    zpp_rows = conn.execute(
        "SELECT player_event_result_id, competitor_id, ranking_category_code, ranking_year, ranking_week "
        "FROM players_events_results_master "
        "WHERE category_code=? AND active=1 AND zero_point_penalty=1 "
        "LIMIT ?",
        (category_code, MAX_ZPP_PER_PLAYER * 1000),  # sanity bound on total ZPP rows scanned, not per-player cap
    ).fetchall()

    expired = 0
    kept_active = 0
    placeholders = ",".join("?" for _ in event_type)

    for zpp in zpp_rows:
        subsequent_count = conn.execute(
            f"""
            SELECT COUNT(*) FROM players_events_results_master p
            JOIN events e ON e.event_id = p.event_id
            WHERE p.competitor_id = ? AND p.category_code = ? AND p.ranking_category_code = ?
              AND p.active = 1 AND p.zero_point_penalty = 0
              AND (p.ranking_year > ? OR (p.ranking_year = ? AND p.ranking_week > ?))
              AND e.event_type_code IN ({placeholders})
            """,
            (
                zpp["competitor_id"], category_code, zpp["ranking_category_code"],
                zpp["ranking_year"], zpp["ranking_year"], zpp["ranking_week"], *event_type,
            ),
        ).fetchone()[0]

        if subsequent_count >= event_count:
            conn.execute(
                "UPDATE players_events_results_master SET active=0, mandatory_inclusion_for_best_results=0 "
                "WHERE player_event_result_id=?",
                (zpp["player_event_result_id"],),
            )
            expired += 1
        else:
            conn.execute(
                "UPDATE players_events_results_master SET mandatory_inclusion_for_best_results=1 "
                "WHERE player_event_result_id=?",
                (zpp["player_event_result_id"],),
            )
            kept_active += 1

    counts.updated += expired + kept_active
    counts.message = f"{len(zpp_rows)} ZPP row(s) evaluated: {expired} waived/expired, {kept_active} still active"
