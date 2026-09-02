"""
SEN<->YOU cross-award mirroring -- thin wrapper around dbo.sp_MirrorCrossCategoryResult
(db/procedures/import/sp_MirrorCrossCategoryResult.sql), a direct T-SQL port of the mirroring
logic previously implemented here in Python. Preserved as tested-but-dormant, matching the
prototype: NOT wired into sp_ImportNewEventsResults or any live web/app.py route.
"""

from __future__ import annotations

import pyodbc


def mirror_cross_category_result(conn: pyodbc.Connection, source_category_code: str) -> int:
    cur = conn.cursor()
    cur.execute(
        "{CALL dbo.sp_MirrorCrossCategoryResult(?, ?)}",
        source_category_code, None,
    )
    return cur.fetchone().rows_inserted
