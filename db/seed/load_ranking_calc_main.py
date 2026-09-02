"""
Seeds the ranking_calc_main table (points-per-round lookup, ~366 rows) directly from the
legacy production CSV export, rather than hand-transcribing a large table into SQL.

Source (read-only, never modified): C:\\vatsan\\ranking\\RANKINGS2026\\data\\dbo_RankingCalcMain_New.csv
This is the current/active points table per the reverse-engineering research (RankingCalcMain_New
supersedes the older RankingCalcMain in column layout and is treated as the source of truth here).
"""

import csv
import sqlite3
from pathlib import Path

LEGACY_CSV = Path(r"C:\vatsan\ranking\RANKINGS2026\data\dbo_RankingCalcMain_New.csv")

# Legacy CSV column name -> ranking_calc_main column name (order-preserving where identical).
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

INT_COLUMNS = {"w", "f", "sf", "qf", "r16", "r32", "r64", "r128", "r256",
               "qual", "qer", "qr4", "qr3", "qr2", "qr1", "g4l", "g3l", "g2l", "gl"}


def load(conn: sqlite3.Connection) -> int:
    if not LEGACY_CSV.exists():
        raise FileNotFoundError(f"Legacy reference CSV not found: {LEGACY_CSV}")

    with LEGACY_CSV.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            values = []
            for legacy_col, target_col in COLUMN_MAP:
                raw = row[legacy_col]
                if target_col in INT_COLUMNS:
                    values.append(int(raw) if raw not in (None, "") else 0)
                else:
                    values.append(raw)
            rows.append(values)

    target_cols = ", ".join(c for _, c in COLUMN_MAP)
    placeholders = ", ".join("?" for _ in COLUMN_MAP)
    conn.executemany(
        f"INSERT INTO ranking_calc_main ({target_cols}) VALUES ({placeholders})",
        rows,
    )
    return len(rows)


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "rankingapp.db")
    conn = sqlite3.connect(db_path)
    try:
        n = load(conn)
        conn.commit()
        print(f"Loaded {n} ranking_calc_main rows from {LEGACY_CSV.name} into {db_path}")
    finally:
        conn.close()
