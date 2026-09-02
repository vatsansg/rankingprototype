"""
Deploys the WTT Ranking Engine schema/views/stored procedures/seed data to an Azure SQL
(or any SQL Server-compatible) target, in the correct dependency order: schema -> views ->
types/functions -> step procedures -> master procedures -> import/validation procedures ->
reference-data seed -> ranking_calc_main seed -> app_user seed.

Usage:
    python db/deploy_db.py                  # deploys using .env / real environment variables
    python db/deploy_db.py --skip-app-users  # skip the SUPERADMIN seed step (e.g. re-deploy)

Each .sql file is split on lines that are exactly "GO" (a sqlcmd/SSMS batch-separator
convention -- not real T-SQL, so pyodbc must split and execute each batch separately).
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from engine.db import get_connection  # noqa: E402

DB_DIR = Path(__file__).resolve().parent

# Dependency order matters: types/functions before anything referencing them; step SPs before
# master SPs (SQL Server's deferred name resolution means CREATE PROCEDURE doesn't need the
# EXEC target to exist yet, but keeping this order makes deploy failures easy to localize).
PROCEDURE_DIRS = ["types", "steps", "master", "import", "validation", "admin"]


def run_sql_file(conn, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    batches = [b.strip() for b in _split_on_go(sql) if b.strip()]
    cur = conn.cursor()
    # XACT_ABORT ON is essential here: without it, a statement-level error inside a
    # multi-statement batch (e.g. an IDENTITY_INSERT violation on one INSERT among several)
    # does NOT stop the rest of the batch from executing -- SQL Server just raises the error
    # for that one statement and keeps going, so later statements can silently succeed while
    # you think the whole batch aborted. Hit exactly this deploying seed_mssql.sql.
    cur.execute("SET XACT_ABORT ON;")
    for batch in batches:
        try:
            cur.execute(batch)
            while cur.nextset():
                pass
        except Exception as exc:
            raise RuntimeError(f"Failed deploying {path.name}:\n{batch[:300]}\n---\n{exc}") from exc
    print(f"  applied {path.relative_to(DB_DIR.parent)}")


def _split_on_go(sql: str) -> list[str]:
    batches, current = [], []
    for line in sql.splitlines():
        if line.strip().upper() == "GO":
            batches.append("\n".join(current))
            current = []
        else:
            current.append(line)
    batches.append("\n".join(current))
    return batches


def deploy(skip_app_users: bool = False) -> None:
    conn = get_connection()
    try:
        print("Schema:")
        run_sql_file(conn, DB_DIR / "schema_mssql.sql")

        print("Views:")
        run_sql_file(conn, DB_DIR / "views_mssql.sql")

        for sub in PROCEDURE_DIRS:
            sub_dir = DB_DIR / "procedures" / sub
            if not sub_dir.exists():
                continue
            print(f"Procedures/{sub}:")
            for f in sorted(sub_dir.glob("*.sql")):
                run_sql_file(conn, f)

        print("Reference-data seed:")
        run_sql_file(conn, DB_DIR / "seed_mssql.sql")
    finally:
        conn.close()

    print("ranking_calc_main seed:")
    subprocess.run([sys.executable, str(DB_DIR / "seed_ranking_calc_main.py")], check=True)

    if not skip_app_users:
        print("App users seed:")
        subprocess.run([sys.executable, str(DB_DIR / "seed_app_users.py")], check=True)

    print("\nDeployment complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-app-users", action="store_true")
    args = parser.parse_args()
    deploy(skip_app_users=args.skip_app_users)
