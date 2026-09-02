"""
Ports of dbo_sp_Calculate_WTT_SEN_Ranking_BestResults.sql and
dbo_sp_Calculate_WTT_YOU_Ranking_BestResults.sql: selects each competitor's best-of-X
counted results per ranking category, honoring the max-1-continental-event cap, and treats
any already zero-point-penalized or mandatory-inclusion result as always counted (0 points,
occupies a slot) ahead of point-based selection -- this is how a ZPP entry stays "in the
best-of-X" per the regulations even though it earns no points.

Sets player_best_ranking_result_number (1-based rank among a player's counted results) and
best_result_no_sen_you (1 if counted) on players_events_results_master.
"""

import sqlite3
from collections import defaultdict

from engine.constants import (
    BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS,
    CONTINENTAL_EVENT_TYPE_CODES,
    SEN_BEST_X_RESULTS,
    YOU_BEST_X_RESULTS,
)
from engine.step_runner import StepCounts


def _apply_best_results(
    conn: sqlite3.Connection, *, category_code: str, best_x_results: int,
    continental_event_type_codes: list[str], best_x_results_for_continental_events: int,
    counts: StepCounts,
) -> None:
    rows = conn.execute(
        """
        SELECT p.player_event_result_id, p.competitor_id, p.ranking_category_code, p.ranking_points,
               p.zero_point_penalty, p.mandatory_inclusion_for_best_results, e.event_type_general_code
        FROM players_events_results_master p
        JOIN events e ON e.event_id = p.event_id
        WHERE p.category_code = ? AND p.active = 1
        """,
        (category_code,),
    ).fetchall()

    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["competitor_id"], r["ranking_category_code"])].append(r)

    continental_set = set(continental_event_type_codes)
    reset_ids = []
    selected_ids = []

    for _, group_rows in groups.items():
        mandatory = [r for r in group_rows if r["zero_point_penalty"] or r["mandatory_inclusion_for_best_results"]]
        non_mandatory = sorted(
            (r for r in group_rows if r not in mandatory),
            key=lambda r: r["ranking_points"] or 0,
            reverse=True,
        )

        remaining_slots = max(best_x_results - len(mandatory), 0)
        chosen = []
        continental_count = 0
        for r in non_mandatory:
            if len(chosen) >= remaining_slots:
                break
            is_continental = r["event_type_general_code"] in continental_set
            if is_continental and continental_count >= best_x_results_for_continental_events:
                continue
            chosen.append(r)
            if is_continental:
                continental_count += 1

        all_selected = sorted(mandatory + chosen, key=lambda r: r["ranking_points"] or 0, reverse=True)
        for rank, r in enumerate(all_selected, start=1):
            selected_ids.append((rank, r["player_event_result_id"]))

        not_selected = [r for r in group_rows if r not in all_selected]
        reset_ids.extend(r["player_event_result_id"] for r in not_selected)

    updated = 0
    for rank, result_id in selected_ids:
        conn.execute(
            "UPDATE players_events_results_master SET player_best_ranking_result_number=?, best_result_no_sen_you=1 "
            "WHERE player_event_result_id=?",
            (rank, result_id),
        )
        updated += 1
    for result_id in reset_ids:
        conn.execute(
            "UPDATE players_events_results_master SET player_best_ranking_result_number=0, best_result_no_sen_you=0 "
            "WHERE player_event_result_id=?",
            (result_id,),
        )
        updated += 1

    counts.updated += updated
    counts.message = f"selected {len(selected_ids)} best-of-{best_x_results} result(s) across {len(groups)} player/category group(s)"


def sp_Calculate_WTT_SEN_Ranking_BestResults(
    conn: sqlite3.Connection, *,
    best_x_results: int = SEN_BEST_X_RESULTS,
    continental_event_type_codes: list[str] = CONTINENTAL_EVENT_TYPE_CODES,
    best_x_results_for_continental_events: int = BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS,
    counts: StepCounts,
) -> None:
    _apply_best_results(
        conn, category_code="SEN", best_x_results=best_x_results,
        continental_event_type_codes=continental_event_type_codes,
        best_x_results_for_continental_events=best_x_results_for_continental_events, counts=counts,
    )


def sp_Calculate_WTT_YOU_Ranking_BestResults(
    conn: sqlite3.Connection, *,
    best_x_results: int = YOU_BEST_X_RESULTS,
    continental_event_type_codes: list[str] = CONTINENTAL_EVENT_TYPE_CODES,
    best_x_results_for_continental_events: int = BEST_X_RESULTS_FOR_CONTINENTAL_EVENTS,
    counts: StepCounts,
) -> None:
    _apply_best_results(
        conn, category_code="YOU", best_x_results=best_x_results,
        continental_event_type_codes=continental_event_type_codes,
        best_x_results_for_continental_events=best_x_results_for_continental_events, counts=counts,
    )
