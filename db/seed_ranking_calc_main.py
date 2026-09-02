"""
Seeds the ranking_calc_main table (points-per-round lookup, ~366 rows) into Azure SQL from
the bundled reference CSV (db/seed/ranking_calc_main_source.csv -- a copy of the legacy
dbo_RankingCalcMain_New.csv, kept inside the repo so this doesn't depend on the original
legacy machine/path). Uses executemany with a plain INSERT (small row count; a TVP isn't
warranted here the way it is for the potentially-large result-import path).
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from engine.db import get_connection  # noqa: E402

SOURCE_CSV = Path(__file__).resolve().parent / "seed" / "ranking_calc_main_source.csv"

COLUMN_MAP = [
    ("OrganizationCode", "organization_code"),
    ("CategoryCode", "category_code"),
    ("AgeCategoryCode", "age_category_code"),
    ("RankingCategoryCode", "ranking_category_code"),
    ("TYPE", "event_type"),
    ("W", "w"), ("F", "f"), ("SF", "sf"), ("QF", "qf"),
    ("R16", "r16"), ("R32", "r32"), ("R64", "r64"), ("R128", "r128"), ("R256", "r256"),
    ("Qual", "qual"), ("QER", "qer"),
    ("QR4", "qr4"), ("QR3", "qr3"), ("QR2", "qr2"), ("QR1", "qr1"),
    ("G4L", "g4l"), ("G3L", "g3l"), ("G2L", "g2l"), ("GL", "gl"),
]
INT_COLUMNS = {c for _, c in COLUMN_MAP[5:]}


def load(conn) -> int:
    if not SOURCE_CSV.exists():
        raise FileNotFoundError(f"Reference CSV not found: {SOURCE_CSV}")

    with SOURCE_CSV.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            values = []
            for legacy_col, target_col in COLUMN_MAP:
                raw = row[legacy_col]
                values.append(int(raw) if target_col in INT_COLUMNS and raw not in (None, "") else (0 if target_col in INT_COLUMNS else raw))
            rows.append(tuple(values))

    target_cols = ", ".join(c for _, c in COLUMN_MAP)
    placeholders = ", ".join("?" for _ in COLUMN_MAP)
    cur = conn.cursor()
    cur.fast_executemany = True
    cur.executemany(f"INSERT INTO dbo.ranking_calc_main ({target_cols}) VALUES ({placeholders})", rows)
    return len(rows)


if __name__ == "__main__":
    conn = get_connection()
    try:
        n = load(conn)
        print(f"Loaded {n} ranking_calc_main rows from {SOURCE_CSV.name}")
    finally:
        conn.close()
