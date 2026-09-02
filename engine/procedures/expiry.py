"""
Ports of dbo_sp_Rules_UpdateEventsResultExpiry.sql and dbo_sp_Rules_UpdateOlympicResultExpiry.sql.

sp_Rules_UpdateEventsResultExpiry deactivates results whose (expiry_year, expiry_week) has
been reached as of the run's target ranking period (year/week comparison; ranking_month in
this schedule is an auxiliary label, so it is intentionally not part of the comparison).

sp_Rules_UpdateOlympicResultExpiry deactivates results from any Olympic Games event other
than the most recent one -- the legacy procedure has no CategoryCode/OrganizationCode
parameter and applies globally across categories, preserved here.
"""

import sqlite3

from engine.step_runner import StepCounts


def sp_Rules_UpdateEventsResultExpiry(
    conn: sqlite3.Connection, *, category_code: str, year: int, week: int, counts: StepCounts,
) -> None:
    updated = conn.execute(
        """
        UPDATE players_events_results_master
        SET active = 0
        WHERE category_code = ? AND active = 1
          AND expiry_year IS NOT NULL AND expiry_week IS NOT NULL
          AND (expiry_year < ? OR (expiry_year = ? AND expiry_week <= ?))
        """,
        (category_code, year, year, week),
    ).rowcount
    counts.updated += max(updated, 0)
    counts.message = f"expired {updated} result(s)"


def sp_Rules_UpdateOlympicResultExpiry(conn: sqlite3.Connection, *, counts: StepCounts) -> None:
    latest_og = conn.execute(
        "SELECT event_id FROM events WHERE event_type_general_code='OG' "
        "ORDER BY ranking_year DESC, event_id DESC LIMIT 1"
    ).fetchone()
    if latest_og is None:
        counts.message = "no Olympic Games event on file"
        return

    updated = conn.execute(
        """
        UPDATE players_events_results_master
        SET active = 0
        WHERE active = 1
          AND event_id IN (SELECT event_id FROM events WHERE event_type_general_code='OG' AND event_id != ?)
        """,
        (latest_og["event_id"],),
    ).rowcount
    counts.updated += max(updated, 0)
    counts.message = f"kept event {latest_og['event_id']} active, expired {updated} older Olympic result(s)"
