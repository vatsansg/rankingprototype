"""
Port of dbo_SP_Ranking_DataValidation.sql. Unlike sp_Calculate_Ranking, validation is NOT
auto-chained into a ranking run (matching the legacy system, where validation runs as a
separate, explicit step after calculation) -- it is invoked directly by the web UI's
Validation page or by tests. Only the checks inferable from the real
dbo_Ranking_Validation_Summary.csv sample data are ported; the ~13 other named validation
sub-procedures documented in the plan are not (see validation/README.md).

Unlike the legacy table (wiped and re-populated every run), ranking_validation_result
retains full history -- each call appends new rows tagged to a specific ranking_run_id.
"""

import sqlite3

from engine.step_runner import StepCounts, now_iso
from validation.checks import duplicate_results, null_points, points_position_mismatch


def SP_Ranking_DataValidation(
    conn: sqlite3.Connection, *, category_code: str, run_id: int,
    validation_category: str, counts: StepCounts | None = None,
) -> list[dict]:
    if validation_category not in ("PreRankingValidation", "PostRankingValidation"):
        raise ValueError(f"validation_category must be PreRankingValidation or PostRankingValidation, got {validation_category!r}")

    findings: list[dict] = []
    if validation_category == "PreRankingValidation":
        findings += null_points.check(conn, category_code=category_code)
        findings += duplicate_results.check(conn, category_code=category_code)
    else:
        findings += duplicate_results.check(conn, category_code=category_code)
        findings += points_position_mismatch.check(conn, run_id=run_id)

    created_at = now_iso()
    conn.execute("BEGIN")
    try:
        for f in findings:
            conn.execute(
                "INSERT INTO ranking_validation_result "
                "(ranking_run_id, validation_category, check_name, passed, remarks, table_name, "
                " competitor_id, event_id, total_points, main_ranking_points, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, validation_category, f["check_name"], f["passed"], f["remarks"], f["table_name"],
                    f["competitor_id"], f["event_id"], f["total_points"], f["main_ranking_points"], created_at,
                ),
            )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

    if counts is not None:
        failing = sum(1 for f in findings if not f["passed"])
        counts.inserted += len(findings)
        counts.message = f"{len(findings)} finding(s) recorded, {failing} failing"

    return findings
