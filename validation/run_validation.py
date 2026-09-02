"""
Thin wrapper around dbo.SP_Ranking_DataValidation (db/procedures/validation/SP_Ranking_DataValidation.sql),
which orchestrates the individual check procedures (sp_ValidateNullPoints,
sp_ValidateDuplicateResults, sp_ValidatePointsPositionMismatch), records their findings into
ranking_validation_result, and returns those findings via a trailing SELECT.

Unlike sp_Calculate_Ranking_SEN/YOU, validation is NOT auto-chained into a ranking run --
it is invoked directly by the web UI's Validation page or by tests. Full history is retained
(ranking_validation_result is append-only; each call adds new rows tagged to a run_id).
"""

from __future__ import annotations

import pyodbc


def SP_Ranking_DataValidation(
    conn: pyodbc.Connection, *, category_code: str, run_id: int, validation_category: str,
) -> list[pyodbc.Row]:
    if validation_category not in ("PreRankingValidation", "PostRankingValidation"):
        raise ValueError(
            f"validation_category must be PreRankingValidation or PostRankingValidation, got {validation_category!r}"
        )
    cur = conn.cursor()
    cur.execute(
        "{CALL dbo.SP_Ranking_DataValidation(?, ?, ?)}",
        category_code, run_id, validation_category,
    )
    return cur.fetchall()
