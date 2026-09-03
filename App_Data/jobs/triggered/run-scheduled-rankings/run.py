"""
Azure App Service triggered WebJob (see settings.job for the CRON schedule). Runs in the same
instance as the web app, so it inherits the same Application Settings (env vars) and the same
ODBC Driver 18 install that startup.sh performs -- no separate configuration needed.

Finds ranking_run rows that were scheduled (via the "Schedule" action on /start) and are now
due, and fires them exactly the way a human clicking "Run Now" on the Dashboard would --
reuses engine/master.py as-is; no calculation logic lives here.

Kudu captures stdout/stderr as this WebJob's execution log, viewable at
https://<app-name>.scm.azurewebsites.net/api/triggeredwebjobs/run-scheduled-rankings/history
"""

import sys
from pathlib import Path

# This file lives at App_Data/jobs/triggered/run-scheduled-rankings/run.py -- WebJobs execute
# with the job's own folder as the working directory, not the site root, so the repo root
# (four levels up) must be added to sys.path explicitly before importing engine/*.
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")  # no-op in Azure, where real Application Settings are already env vars

from engine.db import get_connection  # noqa: E402
from engine.exceptions import RankingRunFailed  # noqa: E402
from engine.master import sp_Calculate_Ranking_SEN, sp_Calculate_Ranking_YOU  # noqa: E402

TRIGGERED_BY = "webjob-scheduler"


def find_due_runs(conn) -> list:
    cur = conn.cursor()
    cur.execute(
        "SELECT ranking_run_id, category_code, ranking_year, ranking_month, ranking_week "
        "FROM dbo.ranking_run "
        "WHERE status = 'PENDING' AND trigger_type = 'scheduled' AND scheduled_for <= SYSUTCDATETIME() "
        "ORDER BY scheduled_for"
    )
    return cur.fetchall()


def fire(row) -> None:
    run_fn = sp_Calculate_Ranking_SEN if row.category_code == "SEN" else sp_Calculate_Ranking_YOU
    try:
        run_fn(row.ranking_year, row.ranking_month, row.ranking_week,
               triggered_by=TRIGGERED_BY, run_id=row.ranking_run_id)
        print(f"run {row.ranking_run_id} ({row.category_code} {row.ranking_year}-{row.ranking_month:02d} "
              f"wk{row.ranking_week}): SUCCEEDED")
    except RankingRunFailed as exc:
        print(f"run {row.ranking_run_id} ({row.category_code} {row.ranking_year}-{row.ranking_month:02d} "
              f"wk{row.ranking_week}): FAILED at step {exc.step_name} -- {exc.original}")


def main() -> None:
    conn = get_connection()
    try:
        due = find_due_runs(conn)
    finally:
        conn.close()

    if not due:
        print("no due scheduled runs")
        return

    print(f"{len(due)} due scheduled run(s) found")
    for row in due:
        fire(row)


if __name__ == "__main__":
    main()
