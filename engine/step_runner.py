"""
Step-execution framework shared by every prototype "stored procedure" call in
engine/master.py. Each step is its OWN atomic SQLite transaction (BEGIN...COMMIT on
success, BEGIN...ROLLBACK on failure) rather than one giant transaction for the whole
run. This is a deliberate adjustment from a naive "one transaction per run" design:
SQLite writes inside an open transaction are invisible to any other connection until
COMMIT, so a live progress dashboard (a separate Flask request/connection polling
vw_RankingRunProgress while a run is RUNNING) could never see intermediate step
completions under a single run-long transaction. Per-step commits give:
  - live, durable step-by-step audit trail (ranking_run_step, ranking_run_error)
  - each step's business writes are atomic (all-or-nothing per step)
  - "a failed run never looks successful": enforced at the query layer instead of via
    whole-run rollback -- vw_RankingResult only ever surfaces main_ranking rows whose
    ranking_run_id belongs to a run with status='SUCCEEDED' (see db/views.sql), so a
    FAILED run's partial writes (if any earlier steps in that run committed) are never
    visible as published ranking output, even though they physically remain in the
    business tables tagged with that run's id for forensic inspection.
See README.md "Design decisions" for the full rationale.
"""

import datetime
import time
import traceback
from contextlib import contextmanager


class RankingRunFailed(Exception):
    """Raised by step() on any exception inside the wrapped block; carries run/step context."""

    def __init__(self, run_id: int, step_id: int, step_name: str, original: Exception):
        super().__init__(f"Run {run_id} failed at step {step_id} ({step_name}): {original}")
        self.run_id = run_id
        self.step_id = step_id
        self.step_name = step_name
        self.original = original


class StepCounts:
    """Mutable holder a procedure function fills in during its work: counts.inserted += n, etc."""

    def __init__(self):
        self.inserted = 0
        self.updated = 0
        self.deleted = 0
        self.message = None


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def step(conn, run_id: int, *, seq: int, group: str, name: str):
    """
    Wraps one prototype stored-procedure call. Usage:

        with step(conn, run_id, seq=7, group="ResultsSelection",
                   name="sp_Calculate_WTT_SEN_Ranking_BestResults") as c:
            sp_Calculate_WTT_SEN_Ranking_BestResults(conn, best_x_results=8, ..., counts=c)

    On success, commits the step's business writes together with its SUCCEEDED status
    and row counts in one transaction. On failure, rolls back the step's business writes,
    then separately (autocommit) records FAILED status and a ranking_run_error row, and
    raises RankingRunFailed for the caller (master.py) to catch and finalize the run.
    """
    started_at = now_iso()
    cur = conn.execute(
        "INSERT INTO ranking_run_step (ranking_run_id, step_seq, step_group, step_name, status, started_at) "
        "VALUES (?, ?, ?, ?, 'RUNNING', ?)",
        (run_id, seq, group, name, started_at),
    )
    step_id = cur.lastrowid
    t0 = time.monotonic()

    counts = StepCounts()
    conn.execute("BEGIN")
    try:
        yield counts
    except Exception as exc:
        conn.execute("ROLLBACK")
        duration_ms = int((time.monotonic() - t0) * 1000)
        finished_at = now_iso()
        conn.execute(
            "UPDATE ranking_run_step SET status='FAILED', finished_at=?, duration_ms=?, result_message=? "
            "WHERE ranking_run_step_id=?",
            (finished_at, duration_ms, str(exc), step_id),
        )
        conn.execute(
            "INSERT INTO ranking_run_error "
            "(ranking_run_id, ranking_run_step_id, error_type, error_message, traceback, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, step_id, type(exc).__name__, str(exc), traceback.format_exc(), finished_at),
        )
        raise RankingRunFailed(run_id, step_id, name, exc) from exc
    else:
        duration_ms = int((time.monotonic() - t0) * 1000)
        finished_at = now_iso()
        conn.execute(
            "UPDATE ranking_run_step SET status='SUCCEEDED', finished_at=?, duration_ms=?, "
            "rows_inserted=?, rows_updated=?, rows_deleted=?, result_message=? WHERE ranking_run_step_id=?",
            (finished_at, duration_ms, counts.inserted, counts.updated, counts.deleted, counts.message, step_id),
        )
        conn.execute("COMMIT")
