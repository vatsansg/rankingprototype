"""
Flask front door for the WTT Ranking Engine -- backend-driven, per the approved plan:
Login -> Import Results -> Manual Modifications -> Start Calculation (Run Now or Schedule) ->
Dashboard -> Run Detail -> Rankings, plus SUPERADMIN-only user management. Every action calls
straight into engine/master.py, importer/, validation/, or auth/ -- this file contains no
calculation logic and no direct password handling of its own.

Run: python web/app.py  (serves http://127.0.0.1:5000/)

Backend: Azure SQL Server via engine/db.py (pyodbc) and native T-SQL stored procedures
(db/procedures/) -- see docs on the Azure SQL + RBAC migration. No SQLite remains.

Note on "live" progress: sp_Calculate_Ranking_SEN/YOU execute synchronously inside the
request that triggers them (no background worker in this prototype), so for the small sample
datasets a run typically completes within the same request/redirect cycle. The Run Detail
page's polling still works correctly for a longer-running or larger dataset -- each step
commits independently inside the T-SQL master procedure, so a concurrent request already sees
completed steps as they land.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import pyodbc  # noqa: E402
from flask import Flask, g, redirect, render_template, request, session, url_for  # noqa: E402

from auth.decorators import load_logged_in_user, login_required, role_required  # noqa: E402
from auth.models import (  # noqa: E402
    LastSuperadminError,
    ROLES,
    change_own_password,
    create_user,
    get_user_by_id,
    list_users,
    reset_password,
    set_active,
    update_user_role,
    verify_login,
)
from auth.passwords import validate_password  # noqa: E402
from engine.db import get_connection  # noqa: E402
from engine.exceptions import RankingRunFailed  # noqa: E402
from engine.master import (  # noqa: E402
    run_combined,
    schedule_ranking_run,
    sp_Calculate_Ranking_SEN,
    sp_Calculate_Ranking_YOU,
)
from importer.load_new_events_results import load_new_events_results  # noqa: E402
from importer.modify_new_events_results import (  # noqa: E402
    EDITABLE_RESULT_POSITIONS,
    get_new_event_result,
    search_new_events_results,
    update_result_position,
)
from validation.run_validation import SP_Ranking_DataValidation  # noqa: E402

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required (see .env.example). Fail fast rather than run with an insecure default.")

app = Flask(__name__)
app.secret_key = SECRET_KEY

SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"
IMPORTABLE_FIXTURES = ["senior_happy_path", "youth_happy_path", "validation_failure", "calculation_failure"]

app.before_request(load_logged_in_user)


def get_db() -> pyodbc.Connection:
    return get_connection()


@app.context_processor
def inject_current_user():
    return {"current_user": g.get("current_user")}


# ===== Auth =====

@app.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user is not None:
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        try:
            user = verify_login(conn, username, password)
        finally:
            conn.close()
        if user is None:
            error = "Invalid username or password."
        else:
            session.clear()
            session["app_user_id"] = user.app_user_id
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account/password", methods=["GET", "POST"])
@login_required
def account_password():
    error = None
    success = False
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if new_password != confirm_password:
            error = "New password and confirmation do not match."
        else:
            error = validate_password(new_password)
        if error is None:
            conn = get_db()
            try:
                error = change_own_password(
                    conn, app_user_id=g.current_user.app_user_id,
                    current_password=current_password, new_password=new_password,
                )
            finally:
                conn.close()
        success = error is None
    return render_template("account_password.html", error=error, success=success)


# ===== User management (SUPERADMIN: full; RANKINGUSER: view only; RANKINGVIEWER: no access) =====

@app.route("/users")
@role_required("SUPERADMIN", "RANKINGUSER")
def users_list():
    conn = get_db()
    try:
        users = list_users(conn)
    finally:
        conn.close()
    return render_template("users_list.html", users=users, roles=ROLES)


@app.route("/users/new", methods=["GET", "POST"])
@role_required("SUPERADMIN")
def user_new():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role_code = request.form.get("role_code", "")
        if not username:
            error = "Username is required."
        elif role_code not in ROLES:
            error = "Invalid role."
        else:
            error = validate_password(password)
        if error is None:
            conn = get_db()
            try:
                create_user(conn, username=username, password=password, role_code=role_code,
                            created_by=g.current_user.username)
            except pyodbc.IntegrityError:
                error = f"Username {username!r} is already taken."
            finally:
                conn.close()
            if error is None:
                return redirect(url_for("users_list"))
    return render_template("user_new.html", error=error, roles=ROLES)


@app.route("/users/<int:app_user_id>/edit", methods=["GET", "POST"])
@role_required("SUPERADMIN")
def user_edit(app_user_id: int):
    conn = get_db()
    try:
        error = None
        if request.method == "POST":
            action = request.form.get("action")
            try:
                if action == "role":
                    role_code = request.form.get("role_code", "")
                    if role_code not in ROLES:
                        error = "Invalid role."
                    else:
                        update_user_role(conn, app_user_id=app_user_id, role_code=role_code,
                                          performed_by=g.current_user.username)
                elif action == "deactivate":
                    set_active(conn, app_user_id=app_user_id, is_active=False, performed_by=g.current_user.username)
                elif action == "activate":
                    set_active(conn, app_user_id=app_user_id, is_active=True, performed_by=g.current_user.username)
                elif action == "reset_password":
                    new_password = request.form.get("new_password", "")
                    error = validate_password(new_password)
                    if error is None:
                        reset_password(conn, app_user_id=app_user_id, new_password=new_password,
                                        performed_by=g.current_user.username)
            except LastSuperadminError as exc:
                error = str(exc)
            if error is None and action != "reset_password":
                return redirect(url_for("users_list"))

        user = get_user_by_id(conn, app_user_id)
    finally:
        conn.close()

    if user is None:
        return redirect(url_for("users_list"))
    return render_template("user_edit.html", user=user, roles=ROLES, error=error)


# ===== Dashboard / runs / rankings (all authenticated users) =====

@app.route("/")
@login_required
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT TOP 50 * FROM vw_RankingRunSummary ORDER BY ranking_run_id DESC")
        runs = cur.fetchall()
    finally:
        conn.close()
    return render_template("dashboard.html", runs=runs, just_reset=request.args.get("reset") == "1")


@app.route("/reset-db", methods=["POST"])
@role_required("SUPERADMIN", "RANKINGUSER")
def reset_db():
    # Clears every import, run, and manual modification via dbo.sp_ResetDemoData; reference
    # data and RBAC (app_user/app_role) are left untouched. Intended for resetting between
    # demos; confirmed client-side (see dashboard.html) before this request is ever sent.
    conn = get_db()
    try:
        conn.cursor().execute("{CALL dbo.sp_ResetDemoData}")
    finally:
        conn.close()
    return redirect(url_for("dashboard", reset="1"))


@app.route("/import", methods=["GET", "POST"])
@role_required("SUPERADMIN", "RANKINGUSER")
def import_results():
    message = None
    imported = False
    if request.method == "POST":
        fixture = request.form.get("fixture")
        csv_path = SAMPLE_DATA_DIR / fixture / "result_file.csv"
        conn = get_db()
        try:
            result = load_new_events_results(conn, csv_path, imported_by=g.current_user.username)
            setup_sql_path = SAMPLE_DATA_DIR / fixture / "setup.sql"
            if setup_sql_path.exists():
                conn.cursor().execute(setup_sql_path.read_text(encoding="utf-8"))
            message = f"Imported {fixture}: {result}"
            imported = True
        finally:
            conn.close()
    return render_template("import.html", fixtures=IMPORTABLE_FIXTURES, message=message, imported=imported)


@app.route("/modify")
@role_required("SUPERADMIN", "RANKINGUSER")
def modify_list():
    category_code = request.args.get("category_code") or None
    player_name = request.args.get("player_name") or None
    country_code = request.args.get("country_code") or None

    conn = get_db()
    try:
        results = search_new_events_results(
            conn, category_code=category_code, player_name=player_name, country_code=country_code,
        )
        cur = conn.cursor()
        cur.execute("SELECT TOP 20 * FROM vw_NewEventsResultsModificationLog ORDER BY modified_at DESC")
        recent_log = cur.fetchall()
    finally:
        conn.close()
    return render_template(
        "modify_list.html", results=results, recent_log=recent_log,
        category_code=category_code or "", player_name=player_name or "", country_code=country_code or "",
    )


@app.route("/modify/<int:new_event_result_id>/edit", methods=["GET", "POST"])
@role_required("SUPERADMIN", "RANKINGUSER")
def modify_edit(new_event_result_id: int):
    conn = get_db()
    try:
        if request.method == "POST":
            if request.form.get("action") == "save":
                update_result_position(
                    conn, new_event_result_id=new_event_result_id,
                    new_result_position=request.form["result_position"],
                    modified_by=g.current_user.username,
                )
            return redirect(url_for("modify_list"))

        row = get_new_event_result(conn, new_event_result_id)
    finally:
        conn.close()

    if row is None:
        return redirect(url_for("modify_list"))
    return render_template("modify_edit.html", row=row, positions=EDITABLE_RESULT_POSITIONS)


@app.route("/start", methods=["GET", "POST"])
@role_required("SUPERADMIN", "RANKINGUSER")
def start_calculation():
    error = None
    if request.method == "POST":
        category = request.form["category"]
        year = int(request.form["year"])
        month = int(request.form["month"])
        week = int(request.form["week"])
        action = request.form["action"]
        triggered_by = g.current_user.username
        conn = None
        try:
            if action == "schedule":
                scheduled_for = request.form["scheduled_for"]
                conn = get_db()
                run_id = schedule_ranking_run(
                    conn, category_code=category, ranking_year=year, ranking_month=month,
                    ranking_week=week, scheduled_for=scheduled_for, triggered_by=triggered_by,
                )
                conn.close()
                conn = None
                return redirect(url_for("run_detail", run_id=run_id))

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
            if conn is not None:
                conn.close()

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP 5 ranking_year, ranking_month, ranking_week FROM dbo.ranking_run "
            "WHERE category_code='SEN' AND status='SUCCEEDED' ORDER BY ranking_run_id DESC"
        )
        sen_runs = cur.fetchall()
    finally:
        conn.close()
    return render_template("start_calculation.html", error=error, recent_senior_runs=sen_runs)


@app.route("/run/<int:run_id>/run-now", methods=["POST"])
@role_required("SUPERADMIN", "RANKINGUSER")
def run_now(run_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_code, ranking_year, ranking_month, ranking_week FROM dbo.ranking_run WHERE ranking_run_id=?",
            run_id,
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return redirect(url_for("dashboard"))

    triggered_by = g.current_user.username
    try:
        if row.category_code == "SEN":
            sp_Calculate_Ranking_SEN(row.ranking_year, row.ranking_month, row.ranking_week,
                                      triggered_by=triggered_by, run_id=run_id)
        else:
            sp_Calculate_Ranking_YOU(row.ranking_year, row.ranking_month, row.ranking_week,
                                      triggered_by=triggered_by, run_id=run_id)
    except RankingRunFailed:
        pass  # status already recorded on the run; detail page will show it
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/run/<int:run_id>")
@login_required
def run_detail(run_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM vw_RankingRunSummary WHERE ranking_run_id=?", run_id)
        run = cur.fetchone()
        cur.execute("SELECT * FROM vw_RankingRunStepAudit WHERE ranking_run_id=? ORDER BY step_seq", run_id)
        steps = cur.fetchall()
        cur.execute("SELECT * FROM vw_RankingRunErrors WHERE ranking_run_id=? ORDER BY occurred_at", run_id)
        errors = cur.fetchall()
        cur.execute(
            "SELECT * FROM dbo.ranking_validation_result WHERE ranking_run_id=? "
            "ORDER BY created_at DESC, ranking_validation_result_id DESC",
            run_id,
        )
        validations = cur.fetchall()
    finally:
        conn.close()
    return render_template("run_detail.html", run=run, steps=steps, errors=errors, validations=validations)


@app.route("/run/<int:run_id>/validate", methods=["POST"])
@role_required("SUPERADMIN", "RANKINGUSER")
def run_validate(run_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT category_code FROM dbo.ranking_run WHERE ranking_run_id=?", run_id)
        run = cur.fetchone()
        if run is not None:
            SP_Ranking_DataValidation(
                conn, category_code=run.category_code, run_id=run_id, validation_category="PostRankingValidation",
            )
    finally:
        conn.close()
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/rankings")
@login_required
def rankings():
    category = request.args.get("category", "SEN")
    ranking_category = request.args.get("ranking_category", "MS")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP 100 * FROM vw_RankingResult WHERE category_code=? AND ranking_category=? ORDER BY ranking_pos",
            category, ranking_category,
        )
        results = cur.fetchall()
    finally:
        conn.close()
    return render_template("rankings.html", results=results, category=category, ranking_category=ranking_category)


@app.errorhandler(403)
def forbidden(_exc):
    return render_template("403.html"), 403


if __name__ == "__main__":
    app.run(debug=True)
