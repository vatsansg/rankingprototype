"""Verifies the step() context manager's bookkeeping: PENDING->RUNNING->SUCCEEDED with real
timestamps/row counts on success, and FAILED + a populated ranking_run_error row on failure,
with the failing step's own writes rolled back while an earlier successful step's writes
remain committed (per-step atomicity, not whole-run atomicity -- see step_runner.py docstring).
"""

from engine.step_runner import RankingRunFailed, step


def _make_run(conn):
    conn.execute(
        "INSERT INTO ranking_run (category_code, ranking_year, ranking_month, ranking_week, status, "
        "started_at, triggered_by) VALUES ('SEN', 2026, 1, 1, 'RUNNING', '2026-01-01T00:00:00Z', 'test')"
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_successful_step_records_timestamps_and_counts(conn):
    run_id = _make_run(conn)

    with step(conn, run_id, seq=1, group="Test", name="dummy_success") as c:
        conn.execute(
            "INSERT INTO events (event_id, event_name, event_type_general_code) VALUES (99999, 'x', 'WCH')"
        )
        c.inserted += 1
        c.message = "ok"

    row = conn.execute("SELECT * FROM ranking_run_step WHERE ranking_run_id=?", (run_id,)).fetchone()
    assert row["status"] == "SUCCEEDED"
    assert row["started_at"] is not None
    assert row["finished_at"] is not None
    assert row["rows_inserted"] == 1
    assert row["result_message"] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_id=99999").fetchone()[0] == 1


def test_failed_step_rolls_back_its_own_writes_and_records_error(conn):
    run_id = _make_run(conn)

    with step(conn, run_id, seq=1, group="Test", name="dummy_ok") as c:
        conn.execute(
            "INSERT INTO events (event_id, event_name, event_type_general_code) VALUES (99998, 'y', 'WCH')"
        )
        c.inserted += 1

    raised = False
    try:
        with step(conn, run_id, seq=2, group="Test", name="dummy_fail") as c:
            conn.execute(
                "INSERT INTO events (event_id, event_name, event_type_general_code) VALUES (99997, 'z', 'WCH')"
            )
            raise ValueError("deliberate failure")
    except RankingRunFailed as exc:
        raised = True
        assert exc.run_id == run_id
        assert exc.step_name == "dummy_fail"

    assert raised
    # step 1's write survives (already committed); step 2's write was rolled back.
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_id=99998").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_id=99997").fetchone()[0] == 0

    step2_row = conn.execute(
        "SELECT * FROM ranking_run_step WHERE ranking_run_id=? AND step_seq=2", (run_id,)
    ).fetchone()
    assert step2_row["status"] == "FAILED"
    assert "deliberate failure" in step2_row["result_message"]

    error_row = conn.execute("SELECT * FROM ranking_run_error WHERE ranking_run_id=?", (run_id,)).fetchone()
    assert error_row is not None
    assert error_row["error_type"] == "ValueError"
    assert "deliberate failure" in error_row["error_message"]
