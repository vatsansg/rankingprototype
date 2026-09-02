"""
Port of dbo_SP_Calculate_Ranking_UpdatePlayersInfoFromTTU.sql. Legacy syncs player/pair
master data from a linked-server connection to the separate TTU (Table Tennis Universe)
database. The prototype has no live TTU feed; this is a documented stub that reports the
current competitors table size and does no writes -- Simplified, not Migrated, per the
procedure mapping table in the plan.
"""

import sqlite3

from engine.step_runner import StepCounts


def SP_Calculate_Ranking_UpdatePlayersInfoFromTTU(
    conn: sqlite3.Connection, *, organization_code: str = "WTT", counts: StepCounts,
) -> None:
    count = conn.execute("SELECT COUNT(*) FROM competitors").fetchone()[0]
    counts.message = f"stub: no live TTU feed in prototype; {count} competitor(s) already on file"
