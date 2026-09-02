"""
SEN<->YOU cross-award mirroring, ported from the implicit logic embedded in
sp_Import_Step2_Web_OVRResultsToNewEventResults: Senior events mirror a Youth
new_events_results row at 5x points for competitors younger than SEN age category; Youth
events mirror a Senior row (no multiplier) for competitors in the U19 age category. This was
an undocumented side effect in the legacy import SP -- here it is an explicit, named,
independently testable function.
"""

import sqlite3

from engine.constants import CROSS_AWARD_MULTIPLIER


def mirror_cross_category_result(conn: sqlite3.Connection, source_category_code: str) -> int:
    if source_category_code == "SEN":
        target_category_code = "YOU"
        multiplier = CROSS_AWARD_MULTIPLIER
        age_filter = "c.age_category_code IS NOT NULL AND c.age_category_code != 'SEN'"
    elif source_category_code == "YOU":
        target_category_code = "SEN"
        multiplier = 1
        age_filter = "c.age_category_code = 'U19'"
    else:
        raise ValueError(f"source_category_code must be 'SEN' or 'YOU', got {source_category_code!r}")

    rows = conn.execute(
        f"""
        SELECT n.new_event_result_id, n.event_id, n.competitor_id, n.sub_event_code, n.result_position,
               n.matches_played, n.matches_won, n.matches_lost, n.qualifier, n.result_type,
               n.zero_point_penalty, n.last_phase_win, n.ranking_category_code, n.age_category_code,
               n.organization_code, n.ranking_points
        FROM new_events_results n
        JOIN competitors c ON c.competitor_id = n.competitor_id
        WHERE n.category_code = ?
          AND n.cross_awarded_from_event_id IS NULL
          AND {age_filter}
          AND NOT EXISTS (
              SELECT 1 FROM new_events_results m
              WHERE m.cross_awarded_from_event_id = n.event_id
                AND m.competitor_id = n.competitor_id
                AND m.category_code = ?
          )
        """,
        (source_category_code, target_category_code),
    ).fetchall()

    count = 0
    conn.execute("BEGIN")
    try:
        for r in rows:
            conn.execute(
                "INSERT INTO new_events_results "
                "(event_id, competitor_id, sub_event_code, result_position, matches_played, matches_won, "
                " matches_lost, qualifier, result_type, zero_point_penalty, last_phase_win, "
                " ranking_category_code, age_category_code, category_code, organization_code, "
                " ranking_points, cross_awarded_from_event_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["event_id"], r["competitor_id"], r["sub_event_code"], r["result_position"],
                    r["matches_played"], r["matches_won"], r["matches_lost"], r["qualifier"], r["result_type"],
                    r["zero_point_penalty"], r["last_phase_win"], r["ranking_category_code"],
                    r["age_category_code"], target_category_code, r["organization_code"],
                    (r["ranking_points"] or 0) * multiplier, r["event_id"],
                ),
            )
            count += 1
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

    return count
