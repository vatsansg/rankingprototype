"""
ranking_run lifecycle helpers, used by engine/master.py and web/app.py. Separate from
step_runner.py (which handles per-step bookkeeping) -- this module handles the run
record itself: creation (on-demand or scheduled), starting a previously-scheduled run,
and finalizing (SUCCEEDED / FAILED / ABORTED_DEPENDENCY).
"""

import hashlib
import sqlite3

from engine.step_runner import now_iso


def compute_input_snapshot_hash(conn: sqlite3.Connection, category_code: str) -> str:
    """sha256 over the in-scope new_events_results rows, for run reproducibility."""
    rows = conn.execute(
        "SELECT new_event_result_id, event_id, competitor_id, sub_event_code, result_position, "
        "ranking_points FROM new_events_results WHERE category_code = ? ORDER BY new_event_result_id",
        (category_code,),
    ).fetchall()
    h = hashlib.sha256()
    for row in rows:
        h.update("|".join(str(v) for v in tuple(row)).encode("utf-8"))
    return h.hexdigest()


def create_run(
    conn: sqlite3.Connection,
    *,
    category_code: str,
    ranking_year: int,
    ranking_month: int,
    ranking_week: int,
    triggered_by: str,
    run_mode: str = "normal",
) -> int:
    """Create and immediately start an on-demand run (status=RUNNING, started_at=now)."""
    started_at = now_iso()
    snapshot_hash = compute_input_snapshot_hash(conn, category_code)
    cur = conn.execute(
        "INSERT INTO ranking_run "
        "(category_code, ranking_year, ranking_month, ranking_week, run_mode, trigger_type, "
        " status, started_at, triggered_by, input_snapshot_hash) "
        "VALUES (?, ?, ?, ?, ?, 'on_demand', 'RUNNING', ?, ?, ?)",
        (category_code, ranking_year, ranking_month, ranking_week, run_mode, started_at, triggered_by, snapshot_hash),
    )
    return cur.lastrowid


def schedule_ranking_run(
    conn: sqlite3.Connection,
    *,
    category_code: str,
    ranking_year: int,
    ranking_month: int,
    ranking_week: int,
    scheduled_for: str,
    triggered_by: str,
    run_mode: str = "normal",
) -> int:
    """Record a future run without executing it. Row sits at status=PENDING until Run Now."""
    cur = conn.execute(
        "INSERT INTO ranking_run "
        "(category_code, ranking_year, ranking_month, ranking_week, run_mode, trigger_type, "
        " scheduled_for, status, triggered_by) "
        "VALUES (?, ?, ?, ?, ?, 'scheduled', ?, 'PENDING', ?)",
        (category_code, ranking_year, ranking_month, ranking_week, run_mode, scheduled_for, triggered_by),
    )
    return cur.lastrowid


def start_scheduled_run(conn: sqlite3.Connection, run_id: int) -> None:
    """Transition a PENDING/scheduled row to RUNNING when the user clicks Run Now."""
    row = conn.execute("SELECT status, category_code FROM ranking_run WHERE ranking_run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"ranking_run {run_id} not found")
    if row["status"] != "PENDING":
        raise ValueError(f"ranking_run {run_id} is not PENDING (status={row['status']})")
    snapshot_hash = compute_input_snapshot_hash(conn, row["category_code"])
    conn.execute(
        "UPDATE ranking_run SET status='RUNNING', started_at=?, input_snapshot_hash=? WHERE ranking_run_id=?",
        (now_iso(), snapshot_hash, run_id),
    )


def finalize_run(conn: sqlite3.Connection, run_id: int, *, status: str, notes: str | None = None) -> None:
    finished_at = now_iso()
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE ranking_run SET status=?, finished_at=?, notes=? WHERE ranking_run_id=?",
            (status, finished_at, notes, run_id),
        )
        if status == "SUCCEEDED":
            row = conn.execute(
                "SELECT category_code, ranking_year, ranking_month, ranking_week FROM ranking_run WHERE ranking_run_id=?",
                (run_id,),
            ).fetchone()
            prior = conn.execute(
                "SELECT ranking_run_id FROM ranking_run WHERE category_code=? AND ranking_year=? AND ranking_month=? "
                "AND ranking_week=? AND current_active=1 AND ranking_run_id != ?",
                (row["category_code"], row["ranking_year"], row["ranking_month"], row["ranking_week"], run_id),
            ).fetchall()
            for p in prior:
                conn.execute(
                    "UPDATE ranking_run SET current_active=0, superseded_by_run_id=? WHERE ranking_run_id=?",
                    (run_id, p["ranking_run_id"]),
                )
            conn.execute("UPDATE ranking_run SET current_active=1 WHERE ranking_run_id=?", (run_id,))
            conn.execute(
                "UPDATE ranking_engine_info SET current_ranking_year=?, current_ranking_month=?, current_ranking_week=? "
                "WHERE category_code=?",
                (row["ranking_year"], row["ranking_month"], row["ranking_week"], row["category_code"]),
            )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def get_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ranking_run WHERE ranking_run_id = ?", (run_id,)).fetchone()
