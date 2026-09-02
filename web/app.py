"""
Flask front door for the WTT Ranking Engine prototype -- backend-driven, per the approved
plan: Import Results -> Start Calculation (Run Now or Schedule) -> Dashboard -> Run Detail
-> Rankings. Every action calls straight into engine/master.py, importer/, or validation/ --
this file contains no calculation logic of its own.

Run: python web/app.py  (serves http://127.0.0.1:5000/)

Note on "live" progress: sp_Calculate_Ranking_SEN/YOU execute synchronously inside the
request that triggers them (no background worker in this prototype), so for the small
sample datasets a run typically completes within the same request/redirect cycle. The Run
Detail page's polling still works correctly for a longer-running or larger dataset -- each
step commits independently (see engine/step_runner.py), so a concurrent request already
sees completed steps as they land.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, redirect, render_template, request, url_for  # noqa: E402

from db.init_db import build as build_database  # noqa: E402
from engine.db import DB_PATH  # noqa: E402
from engine.master import (  # noqa: E402
    run_combined,
    schedule_ranking_run,
    sp_Calculate_Ranking_SEN,
    sp_Calculate_Ranking_YOU,
)
from engine.step_runner import RankingRunFailed  # noqa: E402
from importer.load_new_events_results import load_new_events_results  # noqa: E402
from importer.modify_new_events_results import (  # noqa: E402
    EDITABLE_RESULT_POSITIONS,
    get_new_event_result,
    search_new_events_results,
    update_result_position,
)
from validation.run_validation import SP_Ranking_DataValidation  # noqa: E402

app = Flask(__name__)

SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"
IMPORTABLE_FIXTURES = ["senior_happy_path", "youth_happy_path", "validation_failure", "calculation_failure"]


def get_db() -> sqlite3.Connection:
    # isolation_level=None matches engine/db.py: every engine/importer/validation function
    # manages its own explicit BEGIN/COMMIT and otherwise relies on bare execute() statements
    # autocommitting immediately (e.g. run_registry.create_run/schedule_ranking_run). Python's
    # default isolation_level implicitly opens a transaction before writes and silently rolls
    # it back on close() without an explicit commit() -- easy to lose a write that way.
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    runs = conn.execute("SELECT * FROM vw_RankingRunSummary LIMIT 50").fetchall()
    conn.close()
    return render_template("dashboard.html", runs=runs, just_reset=request.args.get("reset") == "1")


@app.route("/reset-db", methods=["POST"])
def reset_db():
    # Rebuilds the whole database from schema.sql + views.sql + reference-data seed --
    # wipes every import, run, and manual modification. Intended for resetting between
    # demos; confirmed client-side (see dashboard.html) before this request is ever sent.
    build_database(DB_PATH)
    return redirect(url_for("dashboard", reset="1"))


@app.route("/import", methods=["GET", "POST"])
def import_results():
    message = None
    imported = False
    if request.method == "POST":
        fixture = request.form.get("fixture")
        csv_path = SAMPLE_DATA_DIR / fixture / "result_file.csv"
        conn = get_db()
        try:
            result = load_new_events_results(conn, csv_path)
            setup_sql_path = SAMPLE_DATA_DIR / fixture / "setup.sql"
            if setup_sql_path.exists():
                conn.executescript(setup_sql_path.read_text(encoding="utf-8"))
            message = f"Imported {fixture}: {result}"
            imported = True
        finally:
            conn.close()
    return render_template("import.html", fixtures=IMPORTABLE_FIXTURES, message=message, imported=imported)


@app.route("/modify")
def modify_list():
    category_code = request.args.get("category_code") or None
    player_name = request.args.get("player_name") or None
    country_code = request.args.get("country_code") or None

    conn = get_db()
    results = search_new_events_results(
        conn, category_code=category_code, player_name=player_name, country_code=country_code,
    )
    recent_log = conn.execute("SELECT * FROM vw_NewEventsResultsModificationLog LIMIT 20").fetchall()
    conn.close()
    return render_template(
        "modify_list.html", results=results, recent_log=recent_log,
        category_code=category_code or "", player_name=player_name or "", country_code=country_code or "",
    )


@app.route("/modify/<int:new_event_result_id>/edit", methods=["GET", "POST"])
def modify_edit(new_event_result_id: int):
    conn = get_db()
    try:
        if request.method == "POST":
            if request.form.get("action") == "save":
                update_result_position(
                    conn, new_event_result_id=new_event_result_id,
                    new_result_position=request.form["result_position"],
                    modified_by=request.form.get("modified_by") or "web-ui",
                )
            return redirect(url_for("modify_list"))

        row = get_new_event_result(conn, new_event_result_id)
    finally:
        conn.close()

    if row is None:
        return redirect(url_for("modify_list"))
    return render_template("modify_edit.html", row=row, positions=EDITABLE_RESULT_POSITIONS)


@app.route("/start", methods=["GET", "POST"])
def start_calculation():
    error = None
    if request.method == "POST":
        category = request.form["category"]
        year = int(request.form["year"])
        month = int(request.form["month"])
        week = int(request.form["week"])
        action = request.form["action"]
        triggered_by = request.form.get("triggered_by") or "web-ui"

        conn = get_db()
        try:
            if action == "schedule":
                scheduled_for = request.form["scheduled_for"]
                run_id = schedule_ranking_run(
                    conn, category_code=category, ranking_year=year, ranking_month=month,
                    ranking_week=week, scheduled_for=scheduled_for, triggered_by=triggered_by,
                )
                conn.close()
                return redirect(url_for("run_detail", run_id=run_id))

            conn.close()
            if category == "SEN":
                run_id = sp_Calculate_Ranking_SEN(year, month, week, triggered_by=triggered_by)
            elif category == "YOU":
                run_id = sp_Calculate_Ranking_YOU(year, month, week, triggered_by=triggered_by)
            else:
                sen_id, you_id = run_combined(year, month, week, triggered_by=triggered_by)
                return redirect(url_for("run_detail", run_id=you_id))
            return redirect(url_for("run_detail", run_id=run_id))
        except RankingRunFailed as exc:
            return redirect(url_for("run_detail", run_id=exc.run_id))
        except Exception as exc:  # dependency guard, validation errors, etc.
            error = str(exc)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    conn = get_db()
    sen_runs = conn.execute(
        "SELECT ranking_year, ranking_month, ranking_week FROM ranking_run "
        "WHERE category_code='SEN' AND status='SUCCEEDED' ORDER BY ranking_run_id DESC LIMIT 5"
    ).fetchall()
    conn.close()
    return render_template("start_calculation.html", error=error, recent_senior_runs=sen_runs)


@app.route("/run/<int:run_id>/run-now", methods=["POST"])
def run_now(run_id: int):
    conn = get_db()
    row = conn.execute("SELECT category_code, ranking_year, ranking_month, ranking_week FROM ranking_run WHERE ranking_run_id=?", (run_id,)).fetchone()
    conn.close()
    if row is None:
        return redirect(url_for("dashboard"))

    try:
        if row["category_code"] == "SEN":
            sp_Calculate_Ranking_SEN(
                row["ranking_year"], row["ranking_month"], row["ranking_week"],
                triggered_by="web-ui", run_id=run_id,
            )
        else:
            sp_Calculate_Ranking_YOU(
                row["ranking_year"], row["ranking_month"], row["ranking_week"],
                triggered_by="web-ui", run_id=run_id,
            )
    except RankingRunFailed:
        pass  # status already recorded on the run; detail page will show it
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/run/<int:run_id>")
def run_detail(run_id: int):
    conn = get_db()
    run = conn.execute("SELECT * FROM vw_RankingRunSummary WHERE ranking_run_id=?", (run_id,)).fetchone()
    steps = conn.execute(
        "SELECT * FROM vw_RankingRunStepAudit WHERE ranking_run_id=? ORDER BY step_seq", (run_id,)
    ).fetchall()
    errors = conn.execute(
        "SELECT * FROM vw_RankingRunErrors WHERE ranking_run_id=? ORDER BY occurred_at", (run_id,)
    ).fetchall()
    validations = conn.execute(
        "SELECT * FROM ranking_validation_result WHERE ranking_run_id=? ORDER BY created_at DESC, ranking_validation_result_id DESC",
        (run_id,),
    ).fetchall()
    conn.close()
    return render_template("run_detail.html", run=run, steps=steps, errors=errors, validations=validations)


@app.route("/run/<int:run_id>/validate", methods=["POST"])
def run_validate(run_id: int):
    conn = get_db()
    run = conn.execute("SELECT category_code FROM ranking_run WHERE ranking_run_id=?", (run_id,)).fetchone()
    if run is not None:
        SP_Ranking_DataValidation(
            conn, category_code=run["category_code"], run_id=run_id, validation_category="PostRankingValidation",
        )
    conn.close()
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/rankings")
def rankings():
    category = request.args.get("category", "SEN")
    ranking_category = request.args.get("ranking_category", "MS")
    conn = get_db()
    results = conn.execute(
        "SELECT * FROM vw_RankingResult WHERE category_code=? AND ranking_category=? ORDER BY ranking_pos LIMIT 100",
        (category, ranking_category),
    ).fetchall()
    conn.close()
    return render_template("rankings.html", results=results, category=category, ranking_category=ranking_category)


if __name__ == "__main__":
    app.run(debug=True)
