"""
Builds the WTT Ranking Engine prototype SQLite database from scratch:
schema.sql -> views.sql -> seed/reference_data.sql -> seed/load_ranking_calc_main.py.

Usage: python db/init_db.py [path/to/rankingapp.db]
Re-running drops and recreates every table/view in place, then reseeds -- deliberately does
NOT delete the underlying file. On Windows, unlinking a file that any process (even briefly,
e.g. the web app's last request) still holds open raises PermissionError; dropping objects
within an open connection has no such requirement and works reliably even while the Flask
dev server is running against the same file.
"""

import sqlite3
import sys
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DB_DIR))
from seed import load_ranking_calc_main  # noqa: E402


def _drop_all_objects(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    existing = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for obj_type, name in existing:
        conn.execute(f'DROP {obj_type.upper()} IF EXISTS "{name}"')
    conn.commit()


def build(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        _drop_all_objects(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        schema_sql = (DB_DIR / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        views_sql = (DB_DIR / "views.sql").read_text(encoding="utf-8")
        conn.executescript(views_sql)

        reference_sql = (DB_DIR / "seed" / "reference_data.sql").read_text(encoding="utf-8")
        conn.executescript(reference_sql)

        n = load_ranking_calc_main.load(conn)
        conn.commit()
        print(f"Loaded {n} ranking_calc_main rows.")

        _print_row_counts(conn)
    finally:
        conn.close()


def _print_row_counts(conn: sqlite3.Connection) -> None:
    tables = [
        "categories", "age_categories", "ranking_categories", "result_position",
        "ranking_calc_main", "modification_type", "reason_type",
        "available_ranking_runs", "available_ranking_runs_categories", "ranking_engine_info",
    ]
    print("\nReference table row counts:")
    for t in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {count}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_DIR.parent / "rankingapp.db"
    build(target)
    print(f"\nDatabase built at {target}")
