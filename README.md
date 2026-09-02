# WTT Ranking Engine — Azure SQL Prototype

[![tests](https://github.com/vatsansg/rankingprototype/actions/workflows/tests.yml/badge.svg)](https://github.com/vatsansg/rankingprototype/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-black)
![SQL Server](https://img.shields.io/badge/Azure%20SQL-native%20T--SQL-blue)

A from-scratch, fully auditable reimplementation of the WTT (World Table Tennis) Senior and
Youth ranking calculation, replacing the legacy SQL Server dynamic-SQL rule engine
(`RulesSet`/`RulesGroup`/`Rules`/`RulesAlias` → `sp_Rules_ExecuteRule` builds and executes a
SQL string per rule) with two fixed, explicit, directly-callable native T-SQL master stored
procedures — `dbo.sp_Calculate_Ranking_SEN` and `dbo.sp_Calculate_Ranking_YOU` — running on
Azure SQL Database, with full step-by-step audit logging and a role-based (RBAC) user model.

This started as a SQLite prototype with a Python orchestration layer; every calculation
function has since been ported to a real T-SQL stored procedure, and the schema migrated to
Azure SQL Database. Python's role is now a thin `pyodbc` connection layer, a Flask UI, and
session/RBAC enforcement — no calculation logic lives in Python any more.

The legacy system under `C:\vatsan\ranking\RANKINGS2026` (outside this `prototype/` folder)
was reverse-engineered but never modified. See `..\..\` (the repo root) for the original
documentation, stored-procedure source, and table exports this prototype was built from.

## Why this exists

The legacy system works but is hard to audit: run/step status is free text, no row counts are
captured, several procedures have no error handling at all, at least three call sites silently
swallow child-procedure failures (dead output-variable bindings), one position-tiebreak
procedure uses `NEWID()` (non-reproducible), and the alias-resolution mechanism is invisible to
static analysis — you cannot tell what actually ran without querying live configuration data.
This prototype makes every calculation run fully traceable: a unique run ID, a unique step ID
per procedure call, real start/end timestamps, row counts, persisted errors, and a failed step
that can never masquerade as a successful run.

## Architecture

```
Flask UI (web/app.py)  ──► auth/ (session-based login, @login_required / @role_required)
  │
  ├─ Import Results ──────► importer/load_new_events_results.py ──► dbo.sp_ImportNewEventsResults (TVP)
  ├─ Manual Modifications ► importer/modify_new_events_results.py ──► dbo.sp_SearchNewEventsResults /
  │                                                                    dbo.sp_UpdateNewEventResultPosition
  ├─ Start Calculation ───► engine/master.py::sp_Calculate_Ranking_SEN() / _YOU()  (thin pyodbc EXEC wrappers)
  │                            │
  │                            └─ dbo.sp_Calculate_Ranking_SEN / _YOU  (T-SQL master procedures)
  │                                  ├─ EXECs each step's own T-SQL procedure in a fixed sequence
  │                                  ├─ each step manages its own BEGIN TRAN/COMMIT/ROLLBACK (per-step commit + audit)
  │                                  └─ dbo.sp_RankingRun_Create/Schedule/StartScheduled/Finalize (run lifecycle)
  ├─ Validation ───────────► validation/run_validation.py ──► dbo.SP_Ranking_DataValidation
  ├─ Dashboard ────────────► db/views_mssql.sql (vw_RankingRunSummary, vw_RankingRunProgress, ...)
  ├─ Users (SUPERADMIN) ───► auth/models.py ──► dbo.app_user / dbo.app_role / dbo.app_user_audit_log
  └─ Rankings ─────────────► vw_RankingResult
```

Every legacy stored procedure in the calculation path became exactly one native T-SQL stored
procedure, **named identically to the legacy procedure it replaces** (e.g.
`dbo.sp_Calculate_WTT_SEN_Ranking_BestResults`), living in `db/procedures/steps/`. The master
procedures `EXEC` these **directly, in a fixed, hardcoded sequence** — there is no rules-table
config layer and no dynamic dispatch of any kind. See `docs/legacy_rule_mapping.md` for the
full legacy-SP → prototype-procedure mapping and the verified real execution order (derived
from `data/dbo_Rules.csv`, not guessed).

pyodbc has no built-in `OUTPUT`-parameter readback through `{CALL}` syntax, so every procedure
Python needs a return value from also surfaces it via a trailing `SELECT` — see the comments in
`db/procedures/master/sp_RankingRun_lifecycle.sql` for the pattern used throughout.

## Design decisions worth knowing before reading the code

1. **No rules-config tables.** `RulesSet`/`RulesGroup`/`Rules`/`RulesAlias` are not ported into
   the schema. Changing the calculation sequence means editing the T-SQL master procedures
   (`db/procedures/master/sp_Calculate_Ranking_SEN.sql` / `_YOU.sql`) directly. This was an
   explicit, deliberate choice: total transparency over runtime configurability.

2. **Per-step transactions, not one giant per-run transaction.** Each step procedure in
   `db/procedures/steps/` manages its own `BEGIN TRAN`/`COMMIT`/`ROLLBACK`. A naive "one
   transaction for the whole run" design was considered and rejected: writes inside an open
   transaction are invisible to any other connection until `COMMIT`, so a live progress
   dashboard (a separate Flask request polling the database while a run is `RUNNING`) could
   never see intermediate step completions under a single run-long transaction. The tradeoff:
   **"a failed run never looks successful" is enforced at the query layer**, not via whole-run
   rollback — `vw_RankingResult` only ever surfaces `main_ranking` rows belonging to a run with
   `status='SUCCEEDED'`. A `FAILED` run's earlier, already-committed steps remain in the
   business tables (tagged with that run's `ranking_run_id`) for forensic inspection, but are
   never presented as published ranking output. `dbo.sp__RecordStepFailure` (called from each
   master procedure's `CATCH` block) deliberately runs with no open transaction, so the audit
   row survives the failing step's own rollback.

3. **Scheduling records intent; it does not auto-fire.** The Flask UI's "Schedule" action
   inserts a `ranking_run` row at `status='PENDING'` with `trigger_type='scheduled'` and a
   `scheduled_for` timestamp, visible on the Dashboard. A human clicks **Run Now** to actually
   execute it. There is no background scheduler/cron in this prototype, and no recurring
   weekly schedules — both were explicitly scoped out in favor of the simpler "record + manual
   fire" model.

4. **Synchronous execution.** `sp_Calculate_Ranking_SEN`/`_YOU` run inside the Flask request
   that triggers them — there is no background worker. For the small sample datasets this
   completes in well under a second, so in practice a run is usually already `SUCCEEDED`/`FAILED`
   by the time the browser reaches the Run Detail page. The per-step-commit model means the
   architecture is still correct for a longer-running dataset (a concurrent request would see
   completed steps land in real time) — a background worker (Celery, RQ, or a plain thread) is
   the natural next step for that, not a schema or transaction-model change.

5. **Trimmed schema.** ~25 tables are implemented (the ones actually on the Senior/Youth
   calculation + audit path); the other ~65 legacy tables (TTU raw mirrors, historical/reporting,
   OVR export tables, etc.) are catalogued below but not built. See the full inventory appendix.

## Setup

Requires the system **ODBC Driver 18 for SQL Server** installed (not just `pip install`ed —
see Microsoft's install docs for your OS) and an Azure SQL Database (or any SQL Server 2019+)
to deploy against.

```
cd prototype/rankingapp
pip install -r requirements.txt
cp .env.example .env          # fill in AZURE_SQL_*, SECRET_KEY, ADMIN_SEED_* -- never commit .env
python db/deploy_db.py        # deploys schema, views, stored procedures, and reference-data seed
python sample_data/generate.py  # regenerates the 5 sample fixtures (idempotent, no RNG)
python -m pytest -q           # 16 tests
python web/app.py             # http://127.0.0.1:5000/  -- log in as ADMIN_SEED_USERNAME/ADMIN_SEED_PASSWORD
```

`db/deploy_db.py` is idempotent (`CREATE OR ALTER` throughout) except for the one-time
`db/procedures/types/NewEventsResultTVP.sql` table type and the reference-data/app-user seeds;
pass `--skip-app-users` to redeploy schema/procedures without touching the seeded SUPERADMIN.
To clear all imported/calculated data without touching users, use the Dashboard's **Clear
Database (Demo Reset)** button (`dbo.sp_ResetDemoData`) rather than re-running the full deploy.

## Using it

0. **Log In** — every route requires authentication (see Roles & Access below).
1. **Import Results** — pick a sample fixture (`senior_happy_path`, `youth_happy_path`, etc.)
   and import it via `dbo.sp_ImportNewEventsResults` (a table-valued-parameter bulk insert).
2. **Manual Modifications** — search freshly-imported results by player/country and correct a
   result position before calculation begins; every edit is logged and points are recomputed
   server-side.
3. **Start Calculation** — choose Senior / Youth / Both, a ranking year/month/week, and either
   **Run Now** or **Schedule**. Youth requires a prior successful Senior run for the same period
   (enforced by `Sp_Calculate_WTT_YOU_CheckDependencyForRankingRun`, called explicitly before any
   write transaction opens).
4. **Dashboard** — every run, its status, step counts, and duration; a **Run Now** button on any
   still-`PENDING` scheduled run.
5. **Run Detail** — the full step-by-step trace (`vw_RankingRunStepAudit`), row counts, timing,
   and — on failure — the exact error message and traceback (`vw_RankingRunErrors`). A **Run
   Post-Ranking Validation** button invokes `SP_Ranking_DataValidation`.
6. **Rankings** — the published ranking output (`vw_RankingResult`), filterable by category.
7. **Users** (SUPERADMIN/RANKINGUSER) — manage accounts and roles; every account can change its
   own password from the header link.

## Roles & access (RBAC)

Three fixed roles, seeded in `dbo.app_role`:

| Route area | SUPERADMIN | RANKINGUSER | RANKINGVIEWER |
|---|---|---|---|
| Dashboard, Run Detail, Rankings | ✅ | ✅ | ✅ |
| Reset DB, Import, Modify, Start Calculation, Run Now, Validate | ✅ | ✅ | ❌ 403 |
| Users (view) | ✅ | ✅ read-only | ❌ 403 |
| Users (create/edit/deactivate/reset password) | ✅ | ❌ 403 | ❌ 403 |
| My Password | ✅ | ✅ | ✅ |

The seed script (`db/seed_app_users.py`, run automatically by `db/deploy_db.py`) creates one
SUPERADMIN account from `ADMIN_SEED_USERNAME`/`ADMIN_SEED_PASSWORD` (default `admin`/`Admin@123`
if unset — change it via **My Password** immediately after first login). "Delete" a user is
always deactivation (`is_active=0`, `dbo.app_user`), never a hard delete, and the last active
SUPERADMIN can never be deactivated. Every user-management action and every login
success/failure is logged to `dbo.app_user_audit_log`. Sessions store only the user id — role
changes take effect on that user's very next request, not only after their session expires.

## The two master stored procedures

```python
from engine.master import sp_Calculate_Ranking_SEN, sp_Calculate_Ranking_YOU

run_id = sp_Calculate_Ranking_SEN(2026, 1, 1, triggered_by="you@example.com")
run_id = sp_Calculate_Ranking_YOU(2026, 1, 1, triggered_by="you@example.com")  # requires SEN success first
```

`engine/master.py`'s Python functions are thin wrappers: they `EXEC dbo.sp_Calculate_Ranking_SEN`
/ `_YOU` (real native T-SQL stored procedures, not Python) and translate the procedure's single
returned result row `(ranking_run_id, status, failed_step_seq, failed_step_name, error_message)`
into either a `run_id` (on `SUCCEEDED`) or a `RankingRunFailed` exception (`engine/exceptions.py`)
carrying that same context, on `FAILED`/`ABORTED_DEPENDENCY`.

Senior sequence (10 steps) / Youth sequence (11 steps) — see `docs/legacy_rule_mapping.md` for
the full table with legacy rule names and the CSV evidence each step order was derived from.

## Audit model

- `ranking_run` — one row per calculation, with `status` (`PENDING`/`RUNNING`/`SUCCEEDED`/
  `FAILED`/`ABORTED_DEPENDENCY`), real `started_at`/`finished_at`, `trigger_type`,
  `scheduled_for`, `input_snapshot_hash` (sha256 of the in-scope `new_events_results` rows, for
  reproducibility), and `current_active`/`superseded_by_run_id` for re-run history.
- `ranking_run_step` — one row per executed prototype procedure: sequence number, group label,
  the exact function name, status, timestamps, duration, and rows inserted/updated/deleted.
- `ranking_run_error` — tied to both the run **and** the specific step, with the Python
  exception type, message, and full traceback.
- `ranking_run_metric` — free-form named metrics per step (available for future use).
- `ranking_validation_result` — post-run data-quality findings, retained as history (the legacy
  equivalent table was wiped and re-populated every run).

## Known limitations (documented, not silently glossed over)

- **Missing alias-resolution UDFs.** The legacy `@#TOKEN#@` string-substitution engine lives in
  SQL Server UDFs (`ufnrule_General_EvaluateAlias`, `ufnGeneral_EvaluateRulesConfig`, etc.) not
  present in the exported `SPS/` folder — only the calling pattern in `sp_Rules_ExecuteRule` was
  visible. Irrelevant to this prototype's architecture (no dynamic dispatch), but means the
  *exact* legacy substitution semantics could not be verified byte-for-byte.
- **Missing import TVF.** `ufnGetEventResultsForRanking_stat`, which derives points/positions
  during the legacy import, is not present in the exported source. `importer/load_new_events_results.py`
  computes points directly from `result_position` + `ranking_calc_main` instead — a reasonable,
  tested reconstruction, not a guaranteed match to the unseen original.
- **13 of ~16 validation sub-checks not ported** — see `validation/README.md`.
- **No live TTU sync** — `SP_Calculate_Ranking_UpdatePlayersInfoFromTTU` is a documented stub.
- **No `Sp_Process_ScheduledtoPublish` equivalent** — the prototype has `PENDING`/`RUNNING`/
  `SUCCEEDED`/`FAILED`/`ABORTED_DEPENDENCY` run states but no separate "Published" workflow
  state; `current_active` tracks the latest successful run per period instead.
- **Reference-data gaps inherited from the legacy export**: e.g. `ranking_calc_main` has no
  Youth-U17 `MD` (mixed doubles) points row — a genuine gap in the source CSV, not a prototype
  bug (see `sample_data/README.md`'s youth fixture notes for how this was worked around).
- **No recurring/weekly auto-scheduling** — see Design decision 3 above.

## Testing

`tests/` (16 tests, `python -m pytest -q`) covers: full Senior and Youth end-to-end runs against
the sample fixtures (best-of-X trimming, the continental-event cap, ZPP handling, the doubles
age-category fix), the Youth dependency guard, a controlled mid-calculation failure, validation
checks, tie-break determinism, the TVP-based import loader, manual modifications, and the
SEN↔YOU cross-award mirroring. Every test runs against a real deployed SQL Server database (the
CI ephemeral container, or whatever `.env` points at locally) and isolates itself via
`dbo.sp_ResetDemoData` before and after — there is no more per-test throwaway SQLite file.

## Project layout

```
rankingapp/
  README.md, docs/legacy_rule_mapping.md
  db/schema_mssql.sql, db/views_mssql.sql, db/seed_mssql.sql, db/deploy_db.py
  db/seed_ranking_calc_main.py, db/seed_app_users.py, db/seed/ranking_calc_main_source.csv
  db/procedures/types/       -- NewEventsResultTVP, fn_ComputeRankingPoints
  db/procedures/steps/       -- one .sql per legacy calculation SP
  db/procedures/master/      -- sp_Calculate_Ranking_SEN/_YOU, sp_RankingRun_* lifecycle
  db/procedures/import/      -- sp_ImportNewEventsResults, sp_SearchNewEventsResults, sp_MirrorCrossCategoryResult
  db/procedures/validation/  -- SP_Ranking_DataValidation and its per-check procedures
  db/procedures/admin/       -- sp_ResetDemoData
  engine/db.py (pyodbc connection), engine/master.py (thin EXEC wrappers), engine/exceptions.py
  auth/models.py, auth/decorators.py, auth/passwords.py -- RBAC (login, roles, audit log)
  importer/load_new_events_results.py, importer/modify_new_events_results.py, importer/cross_award.py
  validation/run_validation.py, validation/README.md
  web/app.py, web/templates/*.html
  sample_data/generate.py, sample_data/README.md, sample_data/<5 fixtures>/
  tests/*.py, .env.example, .github/workflows/tests.yml
```

## Full legacy table inventory (catalogued; ✅ = implemented in this prototype)

Categorized per the reverse-engineering brief. ~25 of ~87 legacy tables are implemented; the
rest are listed here for completeness of the audit trail but were judged out of scope for a
calculation-and-audit-focused prototype (mostly TTU raw-import mirrors and historical/reporting
tables with no bearing on the Senior/Youth calculation itself).

**1. Master / reference data** — `Countries` ✅(as reference within `competitors.country_code`,
no separate table), `Countries_TTU`, `Continents`, `Organization`, `Organization_TTU`,
`Categories` ✅, `Age_Categories` ✅, `RankingCategories` ✅, `EventTypes`, `EventTypeGeneral`,
`EventTypeCategories`, `EventTypeCategories_PointsDrawType`, `EventCoreTypes_TTU`,
`SubEventTypes`, `SubeventsCodes`, `SubeventsCodes_Description`, `EventPenaltyTypes`,
`ModificationType` ✅, `ReasonType` ✅, `ResultPosition` ✅, `RankingCalcMain`,
`RankingCalcMain_New` ✅ (source for `ranking_calc_main`)

**2. Configuration** — `RulesSet`, `RulesGroup`, `Rules`, `RulesAlias` (all catalogued only —
see "No rules-config tables" above), `AvailableRankingRuns` ✅, `AvailableRankingRunsCategories` ✅,
`RankingEngineInfo` ✅, `Schedule` ✅, `EventCategoryCode_Mapping`, `SubEventDependentCategories`

**3. Event data** — `Events` ✅ (trimmed columns), `Events_TTU`, `EventBasics`,
`EventCompetitions_TTU`, `EventAgeCategeory`, `EventAgeCategory_New`,
`EventTournamentAgeCategoriesLinked_TTU`, `EventTournamentCategories_TTU`,
`EventTournamentCategoriesLinked_TTU`, `EventTournamentCategoryGroup_TTU`,
`EventTournamentPrizeMoney_TTU`, `EventTournamentRestrictions_TTU`,
`EventTournamentSubEventAgeCategoriesLinked_TTU`, `SubEvents`, `SubEvents_TTU`, `tournaments`,
`TournamentAgeCategories_TTU`, `TournamentPlayers`, `TournamentPlayersGroup`, `OVRSubEvents`

**4. Player data** — `Individuals`, `Individuals_Translation`, `Individuals_Organization`,
`Individual_Eligibility`, `Individuals_EventPenalties`, `Profiles`, `Competitors` ✅ (trimmed),
`Players_Singles`, `Players_Doubles` ✅ (trimmed), `LuckyLoosers`

**5. Result data** — `NewEventsResults` ✅, `NewEventsResults_Imported`, `matchresults`,
`OVRExportResults`, `OVRResultPositions`, `OVRResultPositions_MAP`,
`PlayersEventsResultsMaster_Modified` ✅, `ResultsImportDiscrepancyLogs`

**6. Ranking calculation (book of record)** — `PlayersEventsResultsMaster` ✅, `SingleGroupRanking`

**7. Intermediate / staging / historical** — `PlayersEventsResultsMaster_Log`,
`PlayerseventsResultsMaster_log_Archives`, `View_Fetcher_Individuals_Ranking`,
`vw_EventRankingCategories`, `vw_GetCountries`

**8. Ranking output** — `MainRanking` ✅

**9. Audit tables** — `RankingRunsLog` → superseded by `ranking_run` ✅,
`RankingRunsStepLog` → superseded by `ranking_run_step` ✅, `LogTable_RankingRunsLog`,
`Ranking_Validation_Summary` → superseded by `ranking_validation_result` ✅,
`RankingCSVGenerationLog`

**10. Error / log tables** — `DB_Errors` → superseded by `ranking_run_error` ✅, `Export_Errors`,
`Export_Summary`
